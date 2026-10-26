#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const { CHL } = require("../src");

function parseArgs(argv) {
  const out = {
    file: path.resolve(__dirname, "..", "artifacts", "mlx-programming-data", "train.jsonl"),
    maxRows: 5000,
    minChars: 20,
    quality: 6,
    persistPath: process.env.CHL_PERSIST_PATH || path.resolve(__dirname, "..", "artifacts", "chl-memory.log"),
    maxEntries: Number(process.env.CHL_MAX_ENTRIES || 600000),
  };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (!k.startsWith("--")) continue;
    if (v == null || v.startsWith("--")) continue;
    if (k === "--file") out.file = path.resolve(v);
    if (k === "--maxRows") out.maxRows = Number(v);
    if (k === "--minChars") out.minChars = Number(v);
    if (k === "--quality") out.quality = Number(v);
    if (k === "--persistPath") out.persistPath = path.resolve(v);
    if (k === "--maxEntries") out.maxEntries = Number(v);
    i++;
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv);
  if (!fs.existsSync(args.file)) {
    throw new Error(`JSONL not found: ${args.file}`);
  }

  const chl = new CHL({ persistPath: args.persistPath });
  chl.options.maxEntries = Math.max(4096, Number(args.maxEntries) || 600000);
  if (chl.memory) chl.memory.maxEntries = Math.max(4096, Number(args.maxEntries) || 600000);
  await chl.whenReady?.();

  let inserted = 0;
  let inspected = 0;

  const stream = fs.createReadStream(args.file, { encoding: "utf8" });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  for await (const ln of rl) {
    if (inspected >= args.maxRows) break;
    if (!ln || !ln.trim()) continue;
    inspected += 1;
    let obj;
    try {
      obj = JSON.parse(ln);
    } catch {
      continue;
    }
    const t = String(obj.text ?? obj.prompt ?? obj.question ?? "").trim();
    const a = String(obj.completion ?? obj.answer ?? obj.response ?? "").trim();
    const merged = a ? `${t}\n${a}`.trim() : t;
    if (!merged || merged.length < args.minChars) continue;
    chl.remember(merged, { source: "bootstrap-jsonl" }, { quality: args.quality });
    inserted += 1;
  }
  rl.close();
  stream.destroy();

  console.log(JSON.stringify({
    ok: true,
    file: args.file,
    persistPath: args.persistPath,
    inspected,
    inserted,
  }, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ ok: false, error: err.message }, null, 2));
  process.exit(1);
});
