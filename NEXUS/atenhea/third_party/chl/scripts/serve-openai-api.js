#!/usr/bin/env node
/**
 * CHL OpenAI-compatible API Server
 * 
 * Exposes a standard OpenAI API (`/v1/chat/completions`) that wraps
 * the local C++ CHL episodic/semantic memory and reasoning layers.
 * 
 * Usage:
 *   PORT=3040 CHL_PROVIDER=openai CHL_MODEL=gpt-4o node scripts/serve-openai-api.js
 */

const http = require("node:http");
const path = require("node:path");
const { createBridge } = require("../src/bridge/bridge");

const port = Number(process.env.PORT || 3040);
const provider = process.env.CHL_PROVIDER || "openai";
const model = process.env.CHL_MODEL || "gpt-4o";
const persistPath = process.env.CHL_PERSIST_PATH || path.resolve(__dirname, "..", "chl-memory-data", "chl-memory.log");

console.log("=========================================");
console.log("  CHL OpenAI-Compatible API Server");
console.log(`  Provider:     ${provider}`);
console.log(`  Model:        ${model}`);
console.log(`  Persist Path: ${persistPath}`);
console.log(`  Port:         ${port}`);
console.log("=========================================\n");

// Initialize bridge instance
const bridge = createBridge({
  provider,
  model,
  persistPath,
});

async function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const body = Buffer.concat(chunks).toString("utf8");
        resolve(body ? JSON.parse(body) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "*",
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  // CORS Preflight
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "*",
      "Access-Control-Allow-Methods": "*",
    });
    res.end();
    return;
  }

  try {
    const url = req.url;

    // v1/models
    if (req.method === "GET" && (url === "/v1/models" || url === "/models")) {
      sendJson(res, 200, {
        object: "list",
        data: [
          {
            id: model,
            object: "model",
            created: Math.floor(Date.now() / 1000),
            owned_by: "chl-memory",
          }
        ]
      });
      return;
    }

    // v1/chat/completions
    if (req.method === "POST" && (url === "/v1/chat/completions" || url === "/chat/completions")) {
      const body = await readBody(req);
      const messages = body.messages || [];
      if (messages.length === 0) {
        sendJson(res, 400, { error: "messages array cannot be empty" });
        return;
      }

      // Extract the last user message
      const lastUserMsg = [...messages].reverse().find(m => m.role === "user");
      const query = lastUserMsg ? lastUserMsg.content : "";

      // Reset bridge session state to load the history dynamically
      bridge.session.reset();

      // Extract system instructions
      const systemMsg = messages.find(m => m.role === "system");
      if (systemMsg) {
        bridge.session.systemPrompt = systemMsg.content;
      }

      // Load previous user-assistant dialog rounds into history
      const historyMsgs = messages.filter(m => m.role !== "system");
      const lastQuery = historyMsgs.pop(); // Get the last query which will be run

      for (let i = 0; i < historyMsgs.length; i += 2) {
        const user = historyMsgs[i];
        const assistant = historyMsgs[i + 1];
        if (user && assistant) {
          bridge.session.history.push({
            query: user.content,
            response: assistant.content,
            memories: [],
            concepts: [],
            graphEdges: [],
            timestamp: Date.now(),
          });
        }
      }

      // Execute reasoning turn with memory retrieval & tooling
      const result = await bridge.turn(lastQuery ? lastQuery.content : query);

      // Return OpenAI compatible response
      sendJson(res, 200, {
        id: `chatcmpl-${Math.random().toString(36).substring(2, 15)}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: model,
        choices: [
          {
            index: 0,
            message: {
              role: "assistant",
              content: result.response,
            },
            finish_reason: "stop",
          }
        ],
        usage: {
          prompt_tokens: result.stats?.promptTokens || 0,
          completion_tokens: result.stats?.completionTokens || 0,
          total_tokens: (result.stats?.promptTokens || 0) + (result.stats?.completionTokens || 0),
        },
        chl_memories_used: result.memoriesUsed,
      });
      return;
    }

    sendJson(res, 404, { error: "Path not found" });
  } catch (err) {
    console.error("Request Error:", err);
    sendJson(res, 500, { error: err.message });
  }
});

// Graceful cleanup on exit
process.on("SIGINT", async () => {
  console.log("\nStopping server and closing CHL bridge...");
  await bridge.close();
  process.exit(0);
});

server.listen(port, "0.0.0.0", () => {
  console.log(`CHL OpenAI API Server running at http://localhost:${port}/v1`);
});
