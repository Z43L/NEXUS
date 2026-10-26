#!/usr/bin/env node
/**
 * CHL Chat TUI v3 — Terminal chat con Memory Bridge.
 *
 * Modos:
 * - bridge: usa un modelo grande (OpenAI, Anthropic, Ollama) con memoria CHL
 * - local: modo offline usando solo recuperación CHL (sin generación)
 *
 * Uso:
 *   node scripts/chat-tui.js --provider openai
 *   node scripts/chat-tui.js --provider ollama --model llama3
 *   node scripts/chat-tui.js --local
 */

const path = require("node:path");
const readline = require("node:readline");
const { NativeCHL } = require("../src/native");
const { createBridge } = require("../src/bridge/bridge");

function parseArgs(argv) {
  const out = {
    provider: "openai",
    model: null,
    local: false,
    persistPath: process.env.CHL_PERSIST_PATH || path.resolve(__dirname, "..", "chl-memory-data", "chl-memory.log"),
    showMeta: false,
    autoRemember: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (!k.startsWith("--")) continue;
    if (k === "--showMeta") { out.showMeta = true; continue; }
    if (k === "--local") { out.local = true; continue; }
    if (k === "--autoRemember") { out.autoRemember = true; continue; }
    if (v == null || v.startsWith("--")) continue;
    if (k === "--provider") out.provider = v;
    if (k === "--model") out.model = v;
    if (k === "--persistPath") out.persistPath = path.resolve(v);
    i++;
  }
  return out;
}

function printBanner(cfg) {
  console.log("═══ CHL Chat TUI v3 ═══");
  if (cfg.local) {
    console.log("Modo: local (solo recuperación CHL, sin generación)");
  } else {
    console.log(`Modo: bridge (${cfg.provider}${cfg.model ? ` → ${cfg.model}` : ""})`);
  }
  console.log(`Persistencia: ${cfg.persistPath}`);
  console.log("Comandos: /help, /remember <text>, /recall <query>, /state, /clear, /exit");
  console.log("");
}

async function main() {
  const cfg = parseArgs(process.argv);
  printBanner(cfg);

  // Motor CHL (siempre local, C++)
  const chl = new NativeCHL({ persistPath: cfg.persistPath });

  // Bridge (opcional)
  let bridge = null;
  if (!cfg.local) {
    try {
      bridge = createBridge({
        provider: cfg.provider,
        model: cfg.model || undefined,
        persistPath: cfg.persistPath,
      });
      console.log(`Bridge conectado: ${cfg.provider}${cfg.model ? ` (${cfg.model})` : ""}`);
    } catch (err) {
      console.log(`Bridge no disponible (${err.message}). Usando modo local.`);
      cfg.local = true;
    }
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: "tú> ",
  });

  console.log('Escribe tu mensaje. /exit para salir.\n');
  rl.prompt();

  rl.on("line", async (text) => {
    text = text.trim();
    if (!text) { rl.prompt(); return; }

    // Comandos
    if (text === "/help") {
      console.log("/remember <text>  — guarda un hecho en memoria");
      console.log("/recall <query>   — busca en memoria");
      console.log("/state            — snapshot de la sesión");
      console.log("/clear            — limpia sesión (no borra memoria)");
      console.log("/exit             — salir");
      rl.prompt();
      return;
    }

    if (text === "/exit") {
      console.log("bye");
      if (bridge) await bridge.close();
      process.exit(0);
    }

    if (text.startsWith("/remember ")) {
      const mem = text.slice(10).trim();
      chl.remember(mem, mem, { source: "tui" });
      console.log("✓ recordado");
      rl.prompt();
      return;
    }

    if (text.startsWith("/recall ")) {
      const q = text.slice(8).trim();
      const result = chl.recall(q, { topK: 5 });
      const cands = result?.candidates || [];
      if (cands.length === 0) {
        console.log("(sin resultados)");
      } else {
        cands.forEach((c, i) => {
          const entry = c.entry || c;
          console.log(`  ${i + 1}. [${(c.score || 0).toFixed(2)}] ${String(entry.text || entry.input || "").slice(0, 120)}`);
        });
      }
      rl.prompt();
      return;
    }

    if (text === "/state") {
      const snap = bridge ? bridge.snapshot() : { session: { stats: {} } };
      console.log(JSON.stringify(snap, null, 2));
      rl.prompt();
      return;
    }

    if (text === "/clear") {
      if (bridge) bridge.session.reset();
      console.log("✓ sesión limpiada");
      rl.prompt();
      return;
    }

    // Turno normal
    try {
      if (bridge) {
        const result = await bridge.turn(text);
        console.log(`bot> ${result.response}`);
        if (cfg.showMeta) {
          console.log(JSON.stringify({
            memoriesUsed: result.memoriesUsed,
            toolCalls: result.toolCalls?.length || 0,
            stats: result.stats,
          }, null, 2));
        }
      } else {
        // Modo local: solo recall
        const result = chl.recall(text, { topK: 3 });
        const cands = result?.candidates || [];
        if (cands.length === 0) {
          console.log("bot> (sin memorias relevantes — conecta un bridge con --provider openai)");
        } else {
          const top = cands[0].entry || cands[0];
          console.log(`bot> [memoria] ${String(top.text || top.input || "").slice(0, 300)}`);
          if (cands.length > 1) {
            console.log(`     (+${cands.length - 1} resultados más. Usa /recall para ver todos)`);
          }
        }
      }
    } catch (err) {
      console.log(`error: ${err.message}`);
    }

    rl.prompt();
  });

  rl.on("close", async () => {
    if (bridge) await bridge.close();
    process.exit(0);
  });
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
