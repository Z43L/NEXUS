#!/usr/bin/env node
/**
 * CHL Unified Runner (chat-unified.js)
 * 
 * Unifies the CHL C++ memory database with the local fine-tuned Qwen 3B model.
 * 
 * Usage:
 *   # Interactive chat using local Qwen model and default memory file:
 *   node scripts/chat-unified.js
 * 
 *   # Interactive chat using custom memory file:
 *   node scripts/chat-unified.js --memory my-session.memory
 * 
 *   # Start OpenAI-compatible API Server with custom memory file:
 *   node scripts/chat-unified.js --serve --port 3050 --memory prod.memory
 */

const fs = require("node:fs");
const path = require("node:path");
const net = require("node:net");
const http = require("node:http");
const readline = require("node:readline");
const { spawn, execSync } = require("node:child_process");
const { NativeCHL } = require("../src/native");
const { createBridge } = require("../src/bridge/bridge");

function parseArgs(argv) {
  const out = {
    serve: false,
    port: 3050,
    modelPort: 3040,
    ollamaPort: 11434,
    memory: null,
    provider: "openai-compat",
    model: "Qwen/Qwen2.5-3B-Instruct",
    showMeta: false,
    stream: true,
  };

  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (!k.startsWith("--")) continue;

    if (k === "--serve") { out.serve = true; continue; }
    if (k === "--showMeta") { out.showMeta = true; continue; }
    if (k === "--stream") { out.stream = true; continue; }
    if (k === "--no-stream") { out.stream = false; continue; }
    if (v == null || v.startsWith("--")) continue;

    if (k === "--port") out.port = Number(v);
    if (k === "--model-port") out.modelPort = Number(v);
    if (k === "--ollama-port") out.ollamaPort = Number(v);
    if (k === "--memory") out.memory = v;
    if (k === "--provider") out.provider = v;
    if (k === "--model") out.model = v;
    i++;
  }

  // Normalize memory path and extension to .memory
  let rawPath = out.memory || process.env.CHL_PERSIST_PATH;
  if (!rawPath) {
    rawPath = path.resolve(__dirname, "..", "chl-memory-data", "chl-memory.memory");
  } else {
    rawPath = path.resolve(rawPath);
  }

  try {
    if (fs.existsSync(rawPath) && fs.statSync(rawPath).isDirectory()) {
      out.persistPath = path.join(rawPath, "chl-memory.memory");
    } else {
      out.persistPath = rawPath;
    }
  } catch {
    out.persistPath = rawPath;
  }

  // Ensure it has .memory extension if not already specified
  if (!out.persistPath.endsWith(".memory")) {
    const parsed = path.parse(out.persistPath);
    out.persistPath = path.join(parsed.dir, `${parsed.name}.memory`);
  }

  if (out.provider === "ollama") {
    out.baseURL = `http://localhost:${out.ollamaPort}`;
  } else {
    out.baseURL = `http://localhost:${out.modelPort}/v1`;
  }
  return out;
}

function isPortInUse(port) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(200);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true); // Port is in use
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => {
      socket.destroy();
      resolve(false);
    });
    socket.connect(port, "127.0.0.1");
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function killProcessOnPort(port) {
  try {
    const pid = execSync(`lsof -t -i:${port}`, { encoding: "utf8" }).trim();
    if (pid) {
      console.log(`[CHL] Terminating existing process on port ${port} (PID: ${pid})...`);
      process.kill(Number(pid), "SIGKILL");
    }
  } catch (err) {
    // Port is not in use or lsof failed
  }
}

async function startPythonBackend(port) {
  console.log(`[CHL] Cleaning up any existing process on port ${port}...`);
  killProcessOnPort(port);
  await sleep(1000); // Give the OS a moment to free the port

  console.log(`[CHL] Launching scripts/serve_model.py in background...`);
  const serveScript = path.resolve(__dirname, "serve_model.py");

  const child = spawn("python3", [serveScript, "--serve", "--port", String(port)], {
    detached: true,
    stdio: "ignore",
    env: { ...process.env, CHL_ENABLE_COMPILE: process.env.CHL_ENABLE_COMPILE || "0" },
  });
  child.unref();

  // Poll until ready
  const maxRetries = 45;
  for (let i = 1; i <= maxRetries; i++) {
    process.stdout.write(`\r[CHL] Waiting for model backend to start (attempt ${i}/${maxRetries})...`);
    await sleep(1500);
    const ready = await isPortInUse(port);
    if (ready) {
      console.log(`\n[CHL] Model backend is UP and running on port ${port}!`);
      return child;
    }
  }

  console.log(`\n❌ Error: Model backend failed to start on port ${port} after 60s.`);
  process.exit(1);
}

async function ensureOllamaBackend(port, model) {
  const baseURL = `http://localhost:${port}`;
  try {
    const res = await fetch(`${baseURL}/api/tags`, { method: "GET", signal: AbortSignal.timeout(1000) });
    if (res.ok) {
      console.log(`[CHL] Ollama ya esta corriendo en ${baseURL}`);
      return null;
    }
  } catch {
    // no responde, intentar arrancar
  }

  console.log(`[CHL] Ollama no responde. Intentando arrancar ollama serve en puerto ${port}...`);
  const child = spawn("ollama", ["serve"], {
    detached: true,
    stdio: "ignore",
    env: { ...process.env, OLLAMA_HOST: `0.0.0.0:${port}` },
  });
  child.unref();

  const maxRetries = 30;
  for (let i = 1; i <= maxRetries; i++) {
    process.stdout.write(`\r[CHL] Waiting for Ollama to start (attempt ${i}/${maxRetries})...`);
    await sleep(1000);
    try {
      const res = await fetch(`${baseURL}/api/tags`, { method: "GET", signal: AbortSignal.timeout(800) });
      if (res.ok) {
        console.log(`\n[CHL] Ollama backend is UP on port ${port}!`);
        return child;
      }
    } catch { /* seguir esperando */ }
  }

  console.log(`\n❌ Error: Ollama no pudo arrancar en ${baseURL} después de 30s.`);
  console.log(`   Asegurate de tener Ollama instalado o de que el servidor Ollama este activo.`);
  process.exit(1);
}

async function ensureOllamaModel(baseURL, model) {
  try {
    const res = await fetch(`${baseURL}/api/tags`, { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      const models = data.models || [];
      const found = models.some((m) => (m.name || m.model || "").startsWith(model));
      if (found) {
        console.log(`[CHL] Modelo Ollama '${model}' disponible.`);
        return;
      }
    }
  } catch (e) {
    console.log(`[CHL] No se pudo verificar modelos Ollama: ${e.message}`);
  }

  console.log(`[CHL] Descargando/Pull del modelo Ollama '${model}' (puede tardar)...`);
  try {
    const res = await fetch(`${baseURL}/api/pull`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: model, stream: false }),
      signal: AbortSignal.timeout(300000),
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Ollama pull error ${res.status}: ${err}`);
    }
    console.log(`[CHL] Modelo '${model}' listo.`);
  } catch (e) {
    console.log(`[CHL] No se pudo descargar '${model}': ${e.message}`);
    console.log(`   Puedes instalarlo manualmente con: ollama pull ${model}`);
  }
}

function printBanner(cfg) {
  console.log("=========================================");
  console.log("          CHL RUNNER");
  console.log("=========================================");
  console.log(`  Mode:          ${cfg.serve ? "OpenAI API Server" : "Terminal TUI Chat"}`);
  console.log(`  Memory DB:     ${cfg.persistPath}`);
  console.log(`  LLM Provider:  ${cfg.provider}`);
  console.log(`  Model:         ${cfg.model}`);
  console.log(`  Model Backend: ${cfg.baseURL}`);
  console.log(`  /learn <texto> <recompensa> — Refuerza o penaliza una asociación en la memoria.`);
  console.log("=========================================\n");
}

// Node-based OpenAI compatible API server implementation (embedded)
function startApiServer(port, bridge, modelName) {
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

      if (req.method === "GET" && (url === "/v1/models" || url === "/models")) {
        sendJson(res, 200, {
          object: "list",
          data: [
            {
              id: modelName,
              object: "model",
              created: Math.floor(Date.now() / 1000),
              owned_by: "chl-memory",
            }
          ]
        });
        return;
      }

      if (req.method === "POST" && (url === "/v1/chat/completions" || url === "/chat/completions")) {
        const body = await readBody(req);
        const messages = body.messages || [];
        if (messages.length === 0) {
          sendJson(res, 400, { error: "messages array cannot be empty" });
          return;
        }

        const lastUserMsg = [...messages].reverse().find(m => m.role === "user");
        const query = lastUserMsg ? lastUserMsg.content : "";

        // Reset bridge session state to load history dynamically
        bridge.session.reset();

        const systemMsg = messages.find(m => m.role === "system");
        if (systemMsg) {
          bridge.session.systemPrompt = systemMsg.content;
        }

        const historyMsgs = messages.filter(m => m.role !== "system");
        const lastQuery = historyMsgs.pop();

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

        const result = await bridge.turn(lastQuery ? lastQuery.content : query);

        sendJson(res, 200, {
          id: `chatcmpl-${Math.random().toString(36).substring(2, 15)}`,
          object: "chat.completion",
          created: Math.floor(Date.now() / 1000),
          model: modelName,
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

  server.listen(port, "0.0.0.0", () => {
    console.log(`🚀 CHL Gateway API Server running at http://localhost:${port}/v1`);
  });

  return server;
}

async function main() {
  const cfg = parseArgs(process.argv);
  printBanner(cfg);

  // 1. Start backend if local compat server is chosen
  let pyChild = null;
  let ollamaChild = null;
  if (cfg.provider === "openai-compat" && cfg.baseURL.includes("localhost")) {
    pyChild = await startPythonBackend(cfg.modelPort);
  } else if (cfg.provider === "ollama") {
    ollamaChild = await ensureOllamaBackend(cfg.ollamaPort, cfg.model);
    await ensureOllamaModel(cfg.baseURL, cfg.model);
  }

  // 2. Initialize the Native CHL Memory Bridge
  const bridge = createBridge({
    provider: cfg.provider,
    model: cfg.model,
    baseURL: cfg.baseURL,
    persistPath: cfg.persistPath,
  });

  // Esperar a que CHL hidrate su memoria persistente, pero con timeout para no bloquear
  // Si el archivo .memory es muy grande, la hidratacion puede tardar minutos en el addon C++.
  const memoryReady = bridge.chl.whenReady();
  const memoryTimeout = new Promise((resolve) => setTimeout(resolve, 5000, "timeout"));
  const readyResult = await Promise.race([memoryReady, memoryTimeout]);
  if (readyResult === "timeout") {
    console.log(`[CHL] La memoria persistente sigue cargando en segundo plano. Puedes empezar a chatear.`);
  } else {
    const entryCount = bridge.chl.entries().length;
    console.log(`[CHL] Memoria persistente lista: ${entryCount} entradas.`);
  }

  // Graceful cleanup logic
  let isCleaningUp = false;
  async function cleanup() {
    if (isCleaningUp) return;
    isCleaningUp = true;
    console.log("\n[CHL] Saving memory and cleaning up...");
    try {
      bridge.chl.saveLexicon?.();
    } catch {}
    await bridge.close();
    if (pyChild) {
      console.log("[CHL] Terminating background Python model process...");
      try {
        process.kill(-pyChild.pid); // Kill process group
      } catch {
        try { pyChild.kill(); } catch { }
      }
    }
    if (ollamaChild) {
      console.log("[CHL] Terminating background Ollama process...");
      try {
        process.kill(-ollamaChild.pid);
      } catch {
        try { ollamaChild.kill(); } catch { }
      }
    }
    console.log("[CHL] Done. Bye!");
    process.exit(0);
  }


  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);

  // 3. Start requested interface mode
  if (cfg.serve) {
    startApiServer(cfg.port, bridge, cfg.model);
  } else {
    // Run CLI Chat Mode (TUI)
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stderr, // use stderr to avoid blocking stdout writes
      prompt: "tú> ",
    });

    console.log("Comandos disponibles:");
    console.log("  /remember <hecho>   — Guarda un hecho directamente en la base de datos.");
    console.log("  /recall <consulta>  — Busca hechos similares en la memoria.");
    console.log("  /state              — Muestra el estado actual y estadísticas de la memoria.");
    console.log("  /clear              — Limpia el contexto de la conversación actual.");
    console.log("  /exit               — Guarda y sale.");
    console.log("");

    rl.prompt();

    rl.on("line", async (line) => {
      line = line.trim();
      if (!line) { rl.prompt(); return; }

      if (line === "/exit" || line === "/quit") {
        console.log("[CHL] Salida solicitada por el usuario.");
        rl.close();
        return;
      }

      if (line === "/help") {
        console.log("Comandos: /remember <hecho>, /recall <consulta>, /state, /clear, /exit");
        rl.prompt();
        return;
      }

      if (line.startsWith("/remember ")) {
        const fact = line.slice(10).trim();
        bridge.chl.remember(fact, fact, { source: "unified-cli" });
        // Fuerza guardado sincrono del lexicon y persistencia
        try {
          bridge.chl.saveLexicon?.();
        } catch {}
        console.log("✓ Guardado en memoria persistente (.memory)");
        rl.prompt();
        return;
      }

      if (line.startsWith("/recall ")) {
        const q = line.slice(8).trim();
        const res = bridge.chl.recall(q, { topK: 5 });
        const cands = res.candidates || [];
        if (cands.length === 0) {
          console.log("(sin resultados)");
        } else {
          cands.forEach((c, idx) => {
            const entry = c.entry || c;
            console.log(`  [${idx + 1}] [Score: ${(c.score || 0).toFixed(3)}] ${entry.text || entry.input || ""}`);
          });
        }
        rl.prompt();
        return;
      }

      if (line === "/state") {
        const snap = bridge.snapshot();
        console.log(JSON.stringify({
          provider: snap.provider,
          model: snap.model,
          entryCount: bridge.chl.entries().length,
          journalCount: bridge.chl.journal().length,
          persistPath: cfg.persistPath,
        }, null, 2));
        rl.prompt();
        return;
      }

      if (line === "/clear") {
        bridge.session.reset();
        console.log("✓ Contexto de conversación limpiado.");
        rl.prompt();
        return;
      }

      // Normal Chat turn
      if (cfg.stream) {
        process.stdout.write("pensando...\r");
        const start = Date.now();
        try {
          let firstChunk = true;
          let lastSave = start;
          await bridge.turnStream(line, (chunk) => {
            if (firstChunk) {
              process.stdout.write("            \r"); // Clear "pensando..."
              firstChunk = false;
            }
            process.stdout.write(chunk);
            // Persistir memoria CHL periodicamente durante la respuesta para no perder nada
            const now = Date.now();
            if (now - lastSave > 5000) {
              bridge.chl.saveLexicon?.();
              lastSave = now;
            }
          });
          process.stdout.write("\n");
          const elapsed = Date.now() - start;
          console.log(`  (${elapsed}ms)`);
        } catch (err) {
          console.log(`❌ Error: ${err.message}`);
        }
      } else {
        // process.stdout.write("pensando...\r"); // removed to keep prompt responsive
        const start = Date.now();
        try {
          const turnResult = await bridge.turn(line);
          const fullResponse = turnResult.response;
          // Mostrar respuesta directamente sin delay artificial
          process.stdout.write(fullResponse);
          process.stdout.write("\n");
          const elapsed = Date.now() - start;
          console.log(`  (${elapsed}ms)`);
          if (cfg.showMeta) {
            console.log(JSON.stringify({
              memoriesUsed: turnResult.memoriesUsed,
              stats: turnResult.stats,
            }, null, 2));
          }
        } catch (err) {
          console.log(`❌ Error: ${err.message}`);
        }
      }

      rl.prompt();
    });

    rl.on("close", cleanup);
  }
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
