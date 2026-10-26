const { stdin, stdout, stderr } = require("node:process");
const fs = require("node:fs");
const { createMcpContext, handleMcpMessage } = require("./mcp");

const DEBUG_LOG_PATH =
  process.env.CHL_MCP_DEBUG_LOG ||
  "/private/tmp/chl-memory-mcp-debug.log";

function debugLog(event, extra = {}) {
  try {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      pid: process.pid,
      event,
      ...extra,
    });
    fs.appendFileSync(DEBUG_LOG_PATH, `${line}\n`);
  } catch {
    // Never break MCP IO because of debug logging.
  }
}

function writeMessage(message, mode = "framed") {
  const payload = Buffer.from(JSON.stringify(message), "utf8");
  if (mode === "json") {
    stdout.write(`${payload.toString("utf8")}\n`);
  } else {
    stdout.write(`Content-Length: ${payload.length}\r\n\r\n`);
    stdout.write(payload);
  }
  debugLog("write", { id: message?.id ?? null, method: message?.method ?? null, mode });
}

function createFramedReader(onMessage, input = stdin) {
  let buffer = Buffer.alloc(0);
  const MAX_DEBUG_PREVIEW = 180;

  function parseAndDispatchJson(raw) {
    try {
      const message = JSON.parse(raw);
      message.__mcpTransportMode = "json";
      debugLog("message_parsed", { id: message?.id ?? null, method: message?.method ?? null, mode: "json" });
      onMessage(message);
      return true;
    } catch (error) {
      debugLog("parse_error", { message: error.message, mode: "json" });
      return false;
    }
  }

  function dispatchJsonLines() {
    while (buffer.length > 0) {
      const newlineIndex = buffer.indexOf(10);
      if (newlineIndex === -1) return;

      const line = buffer.slice(0, newlineIndex).toString("utf8").replace(/\r$/, "");
      buffer = buffer.slice(newlineIndex + 1);
      if (!line.trim()) continue;
      parseAndDispatchJson(line);
    }
  }

  input.on("data", (chunk) => {
    debugLog("stdin_data", {
      bytes: chunk.length,
      preview: chunk.toString("utf8", 0, Math.min(chunk.length, MAX_DEBUG_PREVIEW)),
    });
    buffer = Buffer.concat([buffer, chunk]);

    while (true) {
      if (!/^\s*Content-Length:/i.test(buffer.toString("utf8"))) {
        dispatchJsonLines();

        const asText = buffer.toString("utf8").trim();
        if (asText.startsWith("{") && asText.endsWith("}")) {
          if (parseAndDispatchJson(asText)) {
            buffer = Buffer.alloc(0);
            continue;
          }
        }
      }

      // Accept CRLF, LF-only, and CR-only framed headers to interoperate
      // with clients that normalize line endings differently.
      const candidates = [
        { marker: "\r\n\r\n", length: 4 },
        { marker: "\n\n", length: 2 },
        { marker: "\r\r", length: 2 },
      ];
      let headerEnd = -1;
      let separatorLength = 0;
      for (const candidate of candidates) {
        const idx = buffer.indexOf(candidate.marker);
        if (idx !== -1 && (headerEnd === -1 || idx < headerEnd)) {
          headerEnd = idx;
          separatorLength = candidate.length;
        }
      }
      if (headerEnd === -1) break;

      const headerText = buffer.slice(0, headerEnd).toString("utf8");
      const match = headerText.match(/Content-Length:\s*(\d+)/i);
      if (!match) {
        debugLog("header_missing_content_length", { headerText });
        buffer = buffer.slice(headerEnd + separatorLength);
        continue;
      }

      const contentLength = Number(match[1]);
      const bodyStart = headerEnd + separatorLength;
      const bodyEnd = bodyStart + contentLength;
      if (buffer.length < bodyEnd) break;

      const body = buffer.slice(bodyStart, bodyEnd).toString("utf8");
      buffer = buffer.slice(bodyEnd);

      try {
        const message = JSON.parse(body);
        message.__mcpTransportMode = "framed";
        debugLog("message_parsed", { id: message?.id ?? null, method: message?.method ?? null, mode: "framed" });
        onMessage(message);
      } catch (error) {
        debugLog("parse_error", { message: error.message, mode: "framed" });
        stderr.write(`${error.message}\n`);
      }
    }
  });

  input.on("end", () => {
    debugLog("stdin_end");
  });

  input.on("close", () => {
    debugLog("stdin_close");
  });
}

function start() {
  debugLog("start");
  // Keep MCP startup fast: defer native memory initialization until
  // the first request that actually needs memory state.
  const context = createMcpContext({ deferMemoryInit: true });
  createFramedReader((message) => {
    try {
      const response = handleMcpMessage(context, message);
      if (response && typeof response.then === "function") {
        response
          .then((resolved) => {
            if (resolved && message.id !== undefined && message.id !== null) {
              writeMessage(resolved, message.__mcpTransportMode || "framed");
            } else {
              debugLog("handled_no_response", { id: message?.id ?? null, method: message?.method ?? null });
            }
          })
          .catch((error) => {
            debugLog("handle_error_async", { id: message?.id ?? null, method: message?.method ?? null, message: error.message });
            if (message.id !== undefined && message.id !== null) {
              writeMessage({
                jsonrpc: "2.0",
                id: message.id,
                error: {
                  code: -32603,
                  message: error.message,
                },
              }, message.__mcpTransportMode || "framed");
            } else {
              stderr.write(`${error.message}\n`);
            }
          });
      } else if (response && message.id !== undefined && message.id !== null) {
        // Synchronous methods (including initialize) should respond immediately.
        writeMessage(response, message.__mcpTransportMode || "framed");
      } else {
        debugLog("handled_no_response", { id: message?.id ?? null, method: message?.method ?? null });
      }
    } catch (error) {
      debugLog("handle_error_sync", { id: message?.id ?? null, method: message?.method ?? null, message: error.message });
      if (message.id !== undefined && message.id !== null) {
        writeMessage({
          jsonrpc: "2.0",
          id: message.id,
          error: {
            code: -32603,
            message: error.message,
          },
        }, message.__mcpTransportMode || "framed");
      } else {
        stderr.write(`${error.message}\n`);
      }
    }
  });
}

if (require.main === module) {
  start();
}

module.exports = { start, createFramedReader };
