#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");
const readline = require("node:readline");
const { pipeline } = require("node:stream/promises");

function parseArgs(argv) {
  const out = {
    urls: "",
    urlsFile: "",
    out: path.resolve(__dirname, "..", "artifacts", "real-corpus.jsonl"),
    maxDocs: 500000,
    minChars: 40,
    timeoutMs: 120000,
  };
  const setArg = (key, value) => {
    if (value == null) return;
    if (key === "--urls") out.urls = value;
    if (key === "--urlsFile") out.urlsFile = path.resolve(value);
    if (key === "--out") out.out = path.resolve(value);
    if (key === "--maxDocs") out.maxDocs = Number(value);
    if (key === "--minChars") out.minChars = Number(value);
    if (key === "--timeoutMs") out.timeoutMs = Number(value);
  };
  for (let i = 2; i < argv.length; i++) {
    const raw = argv[i];
    if (!raw.startsWith("--")) continue;
    if (raw.includes("=")) {
      const idx = raw.indexOf("=");
      const k = raw.slice(0, idx);
      const v = raw.slice(idx + 1);
      setArg(k, v);
      continue;
    }
    const k = raw;
    const v = argv[i + 1];
    if (!k.startsWith("--")) continue;
    if (v == null || v.startsWith("--")) continue;
    setArg(k, v);
    i++;
  }
  return out;
}

function collectUrls(args) {
  const urls = [];
  if (args.urls) {
    for (const u of args.urls.split(",").map((x) => x.trim()).filter(Boolean)) urls.push(u);
  }
  if (args.urlsFile && fs.existsSync(args.urlsFile)) {
    const content = fs.readFileSync(args.urlsFile, "utf8");
    for (const ln of content.split(/\r?\n/)) {
      const s = ln.trim();
      if (!s || s.startsWith("#")) continue;
      urls.push(s);
    }
  }
  return [...new Set(urls)];
}

function cleanText(text) {
  return String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\u0000/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function downloadToFile(url, outPath, timeoutMs) {
  const ac = new AbortController();
  const timeout = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ac.signal });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const tmp = fs.createWriteStream(outPath);
    await pipeline(res.body, tmp);
  } finally {
    clearTimeout(timeout);
  }
}

async function parseSourceToJsonl(sourcePath, writer, state, minChars) {
  const lower = sourcePath.toLowerCase();
  const gz = lower.endsWith(".gz");
  const txtPath = gz ? sourcePath.slice(0, -3) : sourcePath;

  if (gz) {
    await pipeline(
      fs.createReadStream(sourcePath),
      zlib.createGunzip(),
      fs.createWriteStream(txtPath)
    );
  }

  const stream = fs.createReadStream(txtPath, { encoding: "utf8" });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (state.count >= state.maxDocs) break;
    const t = cleanText(line);
    if (!t || t.length < minChars) continue;
    const row = {
      id: `doc-${state.count}`,
      text: t,
      source: path.basename(sourcePath),
    };
    writer.write(JSON.stringify(row) + "\n");
    state.count += 1;
  }

  rl.close();
  stream.destroy();
}

async function main() {
  const args = parseArgs(process.argv);
  const urls = collectUrls(args);
  if (urls.length === 0) {
    throw new Error("Pasa --urls o --urlsFile con al menos una URL");
  }

  const outDir = path.dirname(args.out);
  fs.mkdirSync(outDir, { recursive: true });
  const tmpDir = path.join(outDir, "downloads-tmp");
  fs.mkdirSync(tmpDir, { recursive: true });
  const writer = fs.createWriteStream(args.out, { flags: "w" });

  const state = { count: 0, maxDocs: args.maxDocs };
  const downloaded = [];
  const failed = [];

  for (let i = 0; i < urls.length; i++) {
    if (state.count >= state.maxDocs) break;
    const url = urls[i];
    const name = `source-${i}${path.extname(new URL(url).pathname) || ".txt"}`;
    const target = path.join(tmpDir, name);
    try {
      await downloadToFile(url, target, args.timeoutMs);
      await parseSourceToJsonl(target, writer, state, args.minChars);
      downloaded.push(url);
    } catch (err) {
      failed.push({ url, error: err.message });
    }
  }

  writer.end();
  console.log(JSON.stringify({
    ok: true,
    out: args.out,
    maxDocs: args.maxDocs,
    downloaded: downloaded.length,
    failed: failed.length,
    rows: state.count,
    failedSources: failed.slice(0, 20),
  }, null, 2));
}

main().catch((err) => {
  console.error(JSON.stringify({ ok: false, error: err.message }, null, 2));
  process.exit(1);
});
