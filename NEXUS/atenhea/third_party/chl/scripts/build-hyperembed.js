const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const outDir = path.join(root, "build", "Release");
const outFile = path.join(outDir, "hyperembed_addon.node");
const sources = [
  path.join(root, "native", "hyperembed_engine.cc"),
  path.join(root, "native", "hyperembed_addon.cc"),
];
const includeDir =
  process.env.NODE_INCLUDE_DIR ||
  path.resolve(path.dirname(process.execPath), "..", "include", "node");

fs.mkdirSync(outDir, { recursive: true });

if (!fs.existsSync(path.join(includeDir, "node_api.h"))) {
  console.error(`node_api.h not found in: ${includeDir}`);
  process.exit(1);
}

const args = [
  "-std=c++20",
  "-O3",
  "-march=native",
  "-fPIC",
  "-shared",
  ...sources,
  `-I${includeDir}`,
  `-I${path.join(root, "native")}`,
  "-o",
  outFile,
  "-undefined",
  "dynamic_lookup",
];

console.log("Compiling HyperEmbed native addon...");
console.log(`  Sources: ${sources.map(s => path.basename(s)).join(", ")}`);

const result = spawnSync("clang++", args, { stdio: "inherit" });

if (result.status !== 0) {
  console.error("Build failed");
  process.exit(result.status || 1);
}

console.log(`✅ built ${outFile}`);
console.log(`   Size: ${(fs.statSync(outFile).size / 1024).toFixed(1)} KB`);
