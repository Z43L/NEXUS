#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const { CHL } = require("../src");

function parseArgs(argv) {
  const out = {
    dir: "",
    persistPath: process.env.CHL_PERSIST_PATH || path.resolve(__dirname, "..", "artifacts", "chl-memory.log"),
    maxFiles: 20000,
    maxFileBytes: 2 * 1024 * 1024,
    chunkChars: 1400,
    overlapChars: 220,
    minChunkChars: 80,
    quality: 7,
    includeExt: ".txt,.md,.markdown,.rst,.json,.jsonl,.yaml,.yml,.toml,.ini,.cfg,.conf,.xml,.html,.htm,.csv,.tsv,.log,.js,.cjs,.mjs,.ts,.tsx,.jsx,.py,.java,.go,.rs,.c,.h,.cpp,.hpp,.cc,.hh,.cs,.rb,.php,.swift,.kt,.sql,.sh,.bash,.zsh,.tex",
    excludeDirs: ".git,node_modules,.venv,.venv-rwkv,.venv-mlx,build,dist,coverage,.cache,__pycache__",
    followSymlinks: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[i + 1];
    if (!k.startsWith("--")) continue;
    if (k === "--followSymlinks") {
      out.followSymlinks = true;
      continue;
    }
    if (v == null || v.startsWith("--")) continue;
    if (k === "--dir") out.dir = path.resolve(v);
    if (k === "--persistPath") out.persistPath = path.resolve(v);
    if (k === "--maxFiles") out.maxFiles = Number(v);
    if (k === "--maxFileBytes") out.maxFileBytes = Number(v);
    if (k === "--chunkChars") out.chunkChars = Number(v);
    if (k === "--overlapChars") out.overlapChars = Number(v);
    if (k === "--minChunkChars") out.minChunkChars = Number(v);
    if (k === "--quality") out.quality = Number(v);
    if (k === "--includeExt") out.includeExt = v;
    if (k === "--excludeDirs") out.excludeDirs = v;
    i++;
  }
  return out;
}

function looksBinary(buffer) {
  const len = Math.min(buffer.length, 4096);
  if (len === 0) return false;
  let weird = 0;
  for (let i = 0; i < len; i++) {
    const b = buffer[i];
    if (b === 0) return true;
    if (b < 7 || (b > 14 && b < 32)) weird++;
  }
  return weird / len > 0.08;
}

function splitIntoChunks(text, chunkChars, overlapChars, minChunkChars) {
  const out = [];
  const clean = String(text ?? "").replace(/\r\n/g, "\n");
  let start = 0;
  while (start < clean.length) {
    const end = Math.min(clean.length, start + chunkChars);
    let chunk = clean.slice(start, end);
    if (end < clean.length) {
      const lastBoundary = Math.max(
        chunk.lastIndexOf("\n\n"),
        chunk.lastIndexOf(". "),
        chunk.lastIndexOf("\n"),
        chunk.lastIndexOf(" ")
      );
      if (lastBoundary > minChunkChars) {
        chunk = chunk.slice(0, lastBoundary + 1);
      }
    }
    const trimmed = chunk.trim();
    if (trimmed.length >= minChunkChars) out.push(trimmed);
    if (end >= clean.length) break;
    start += Math.max(1, chunk.length - overlapChars);
  }
  return out;
}

function walkFiles(rootDir, options) {
  const includeExt = new Set(
    String(options.includeExt || "")
      .split(",")
      .map((x) => x.trim().toLowerCase())
      .filter(Boolean)
  );
  const excluded = new Set(
    String(options.excludeDirs || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
  );
  const out = [];
  const queue = [rootDir];
  while (queue.length > 0 && out.length < options.maxFiles) {
    const dir = queue.shift();
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const abs = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (excluded.has(entry.name)) continue;
        queue.push(abs);
        continue;
      }
      if (entry.isSymbolicLink() && !options.followSymlinks) continue;
      if (!entry.isFile() && !(entry.isSymbolicLink() && options.followSymlinks)) continue;
      const ext = path.extname(entry.name).toLowerCase();
      if (includeExt.size > 0 && !includeExt.has(ext)) continue;
      out.push(abs);
      if (out.length >= options.maxFiles) break;
    }
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.dir) throw new Error("Missing required --dir /ruta/a/carpeta");
  if (!fs.existsSync(args.dir)) throw new Error(`Directory not found: ${args.dir}`);

  const files = walkFiles(args.dir, args);
  const chl = new CHL({ persistPath: args.persistPath });
  await chl.whenReady?.();

  let indexedFiles = 0;
  let skippedFiles = 0;
  let insertedChunks = 0;
  const errors = [];

  for (const file of files) {
    try {
      const st = fs.statSync(file);
      if (!st.isFile()) {
        skippedFiles += 1;
        continue;
      }
      if (st.size <= 0 || st.size > args.maxFileBytes) {
        skippedFiles += 1;
        continue;
      }
      const raw = fs.readFileSync(file);
      if (looksBinary(raw)) {
        skippedFiles += 1;
        continue;
      }
      const txt = raw.toString("utf8");
      const chunks = splitIntoChunks(txt, args.chunkChars, args.overlapChars, args.minChunkChars);
      if (!chunks.length) {
        skippedFiles += 1;
        continue;
      }
      for (let i = 0; i < chunks.length; i++) {
        const chunk = chunks[i];
        const rel = path.relative(args.dir, file);
        chl.remember(chunk, {
          source: "directory-ingest",
          filePath: file,
          relativePath: rel,
          chunkIndex: i,
          chunkCount: chunks.length,
          bytes: st.size,
        }, {
          quality: args.quality,
          source: "directory-ingest",
        });
        insertedChunks += 1;
      }
      indexedFiles += 1;
    } catch (err) {
      skippedFiles += 1;
      if (errors.length < 20) errors.push({ file, error: err.message });
    }
  }

  console.log(JSON.stringify({
    ok: true,
    dir: args.dir,
    persistPath: args.persistPath,
    discoveredFiles: files.length,
    indexedFiles,
    skippedFiles,
    insertedChunks,
    errors,
  }, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ ok: false, error: err.message }, null, 2));
  process.exit(1);
});
