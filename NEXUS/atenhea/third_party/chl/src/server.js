const http = require("node:http");
const { NativeCHL } = require("./native");
const { resolveMemoryProfile } = require("./profiles");
const { serializePairList } = require("./concepts");

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const body = Buffer.concat(chunks).toString("utf8");
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function readBodyBuffer(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function sendBinary(res, statusCode, buffer, contentType = "application/octet-stream", filename = null) {
  const headers = {
    "content-type": contentType,
    "content-length": buffer.length,
  };
  if (filename) {
    headers["content-disposition"] = `attachment; filename="${filename}"`;
  }
  res.writeHead(statusCode, headers);
  res.end(buffer);
}

function sendText(res, statusCode, text, contentType = "text/plain; charset=utf-8") {
  const body = String(text ?? "");
  res.writeHead(statusCode, {
    "content-type": contentType,
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function lexiconPayload(memory) {
  const lexicon = memory.lexicon();
  return {
    ...lexicon,
    counts: {
      concepts: lexicon.concepts.length,
      phrases: lexicon.phrases.length,
    },
    sources: {
      conceptsPath: memory.conceptsPath ?? null,
      phrasesPath: memory.phrasesPath ?? null,
    },
  };
}

function createServer(options = {}) {
  const memoryOptions = resolveMemoryProfile({
    ...(options.memory ?? {}),
    profile: options.profile ?? (options.memory ?? {}).profile,
    persistPath:
      (options.memory ?? {}).persistPath ??
      process.env.CHL_PERSIST_PATH ??
      null,
  });
  const memory = new NativeCHL(memoryOptions);
  return http.createServer(async (req, res) => {
    try {
      await memory.whenReady();

      if (req.method === "GET" && req.url === "/health") {
        sendJson(res, 200, { ok: true, snapshot: memory.snapshot() });
        return;
      }

      if (req.method === "GET" && req.url === "/snapshot") {
        sendJson(res, 200, memory.snapshot());
        return;
      }

      if (req.method === "GET" && req.url === "/profile") {
        sendJson(res, 200, { profile: memory.profile() });
        return;
      }

      if (req.method === "GET" && req.url === "/state") {
        sendJson(res, 200, memory.dumpState());
        return;
      }

      if (req.method === "GET" && req.url === "/graph") {
        sendJson(res, 200, memory.conceptGraph());
        return;
      }

      if (req.method === "GET" && req.url === "/entries") {
        sendJson(res, 200, memory.entries());
        return;
      }

      if (req.method === "GET" && req.url === "/journal") {
        sendJson(res, 200, memory.journal());
        return;
      }

      if (req.method === "GET" && req.url === "/episodes") {
        sendJson(res, 200, memory.episodes());
        return;
      }

      if (req.method === "GET" && req.url === "/lexicon") {
        sendJson(res, 200, lexiconPayload(memory));
        return;
      }

      if (req.method === "GET" && req.url === "/lexicon.concepts.tsv") {
        const lexicon = memory.lexicon();
        sendText(res, 200, serializePairList(lexicon.concepts), "text/tab-separated-values; charset=utf-8");
        return;
      }

      if (req.method === "GET" && req.url === "/lexicon.phrases.tsv") {
        const lexicon = memory.lexicon();
        sendText(res, 200, serializePairList(lexicon.phrases), "text/tab-separated-values; charset=utf-8");
        return;
      }

      if (req.method === "GET" && req.url === "/lexicon.tsv") {
        const lexicon = memory.lexicon();
        const sections = [
          "# concepts",
          serializePairList(lexicon.concepts),
          "",
          "# phrases",
          serializePairList(lexicon.phrases),
          "",
        ];
        sendText(res, 200, sections.join("\n"), "text/tab-separated-values; charset=utf-8");
        return;
      }

      if (req.method === "GET" && req.url === "/backup.memory") {
        sendBinary(res, 200, memory.backupMemory(), "application/octet-stream", "backup.memory");
        return;
      }

      if (req.method === "POST" && req.url === "/remember") {
        const body = await readBody(req);
        const entry = memory.remember(body.text ?? "", body.payload ?? null, body.metadata ?? {});
        sendJson(res, 200, entry);
        return;
      }

      if (req.method === "POST" && req.url === "/recall") {
        const body = await readBody(req);
        const result = memory.recall(body.query ?? "", { topK: body.topK ?? 5 });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/infer") {
        const body = await readBody(req);
        const result = memory.infer(body.query ?? "", { topK: body.topK ?? 5 });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/think") {
        const body = await readBody(req);
        const result = memory.think(body.query ?? "", { topK: body.topK ?? 5 });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/ask") {
        const body = await readBody(req);
        const result = memory.ask(body.query ?? "", { topK: body.topK ?? 5 });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/plan") {
        const body = await readBody(req);
        const result = memory.plan(body.query ?? "", { topK: body.topK ?? 5 });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/verify") {
        const body = await readBody(req);
        const result = memory.verify(body.plan ?? body.query ?? "", { topK: body.topK ?? 5 });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/learn-from-verification") {
        const body = await readBody(req);
        const result = memory.learnFromVerification(body.verification ?? body.plan ?? body.query ?? {}, {
          extraSignals: body.extraSignals ?? [],
        });
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/consolidate") {
        const body = await readBody(req);
        const result = memory.consolidateEpisodes(body ?? {});
        sendJson(res, 200, result);
        return;
      }

      if (req.method === "POST" && req.url === "/learn") {
        const body = await readBody(req);
        memory.learn(body.text ?? "", Number(body.reward ?? 0));
        sendJson(res, 200, { ok: true });
        return;
      }

      if (req.method === "POST" && req.url === "/restore.memory") {
        const body = await readBodyBuffer(req);
        const result = memory.restoreMemory(body);
        sendJson(res, 200, result);
        return;
      }

      sendJson(res, 404, { error: "not found" });
    } catch (error) {
      sendJson(res, 500, { error: error.message });
    }
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT ?? 3030);
  const server = createServer();
  server.listen(port, "127.0.0.1", () => {
    console.log(`CHL API listening on http://127.0.0.1:${port}`);
  });
}

module.exports = { createServer };
