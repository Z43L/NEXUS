const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const outDir = path.join(root, "build", "Release");
const outFile = path.join(outDir, "chl_addon.node");
const source = path.join(root, "native", "chl_addon.cc");
const includeDir =
  process.env.NODE_INCLUDE_DIR ||
  path.resolve(path.dirname(process.execPath), "..", "include", "node");

fs.mkdirSync(outDir, { recursive: true });

const args = [
  "-std=c++20",
  "-O3",
  "-fPIC",
  "-shared",
  source,
  `-I${includeDir}`,
  "-o",
  outFile,
  "-undefined",
  "dynamic_lookup",
];

if (!fs.existsSync(path.join(includeDir, "node_api.h"))) {
  console.error(`node_api.h not found in include directory: ${includeDir}`);
  console.error("Set NODE_INCLUDE_DIR to a valid Node headers path.");
  process.exit(1);
}

const compiler = process.env.CXX || "clang++";
const result = spawnSync(compiler, args, { stdio: "inherit" });

if (result.status !== 0) {
  process.exit(result.status || 1);
}

console.log(`built ${outFile}`);

// Compile llama_chl_bridge.cc if llama.cpp headers exist
const llamaCppDir = path.join(root, "llama.cpp");
if (fs.existsSync(path.join(llamaCppDir, "include", "llama.h"))) {
  console.log("Compiling GGML llama_chl_bridge.cc...");
  const bridgeSource = path.join(root, "native", "llama_chl_bridge.cc");
  const bridgeOut = path.join(outDir, "llama_chl_bridge.o");
  const bridgeArgs = [
    "-std=c++20",
    "-O3",
    "-fPIC",
    "-c",
    bridgeSource,
    `-I${path.join(llamaCppDir, "include")}`,
    `-I${path.join(llamaCppDir, "ggml", "include")}`,
    "-o",
    bridgeOut
  ];
  
  const bridgeResult = spawnSync(compiler, bridgeArgs, { stdio: "inherit" });
  if (bridgeResult.status === 0) {
    console.log(`✅ successfully compiled llama_chl_bridge.cc to ${bridgeOut}`);
    
    // Also build the shared library (dylib on macOS)
    const bridgeSharedLib = path.join(outDir, "libllama_chl.dylib");
    const linkArgs = [
      "-std=c++20",
      "-O3",
      "-fPIC",
      "-shared",
      bridgeSource,
      path.join(root, "native", "hyperembed_engine.cc"),
      `-I${path.join(llamaCppDir, "include")}`,
      `-I${path.join(llamaCppDir, "ggml", "include")}`,
      "-o",
      bridgeSharedLib,
      "-undefined",
      "dynamic_lookup"
    ];
    const linkResult = spawnSync(compiler, linkArgs, { stdio: "inherit" });
    if (linkResult.status === 0) {
      console.log(`✅ successfully linked libllama_chl.dylib to ${bridgeSharedLib}`);
    } else {
      console.warn("⚠️ warning: failed to link libllama_chl.dylib");
    }
  } else {
    console.warn("⚠️ warning: failed to compile llama_chl_bridge.cc");
  }
}

