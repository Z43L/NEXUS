const fs = require("node:fs");
const zlib = require("node:zlib");

const MAGIC = Buffer.from("CHLB");
const VERSION = 1;
const CODEC_DEFLATE = 1;

function encodeMemoryArchive(archive) {
  const json = Buffer.from(JSON.stringify(archive), "utf8");
  const compressed = zlib.deflateSync(json, { level: 9 });
  const header = Buffer.alloc(12);
  MAGIC.copy(header, 0);
  header.writeUInt8(VERSION, 4);
  header.writeUInt8(CODEC_DEFLATE, 5);
  header.writeUInt16LE(0, 6);
  header.writeUInt32LE(compressed.length, 8);
  return Buffer.concat([header, compressed]);
}

function decodeMemoryArchive(buffer) {
  const input = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer);
  if (input.length < 12) {
    throw new Error("Invalid CHL binary backup");
  }
  if (input.slice(0, 4).compare(MAGIC) !== 0) {
    throw new Error("Invalid CHL binary magic");
  }
  const version = input.readUInt8(4);
  const codec = input.readUInt8(5);
  const payloadLength = input.readUInt32LE(8);
  if (version !== VERSION) {
    throw new Error(`Unsupported CHL backup version: ${version}`);
  }
  if (codec !== CODEC_DEFLATE) {
    throw new Error(`Unsupported CHL backup codec: ${codec}`);
  }
  const compressed = input.subarray(12, 12 + payloadLength);
  if (compressed.length !== payloadLength) {
    throw new Error("Truncated CHL binary backup");
  }
  const json = zlib.inflateSync(compressed).toString("utf8");
  return JSON.parse(json);
}

function writeMemoryArchive(filePath, archive) {
  fs.writeFileSync(filePath, encodeMemoryArchive(archive));
}

function readMemoryArchive(filePath) {
  return decodeMemoryArchive(fs.readFileSync(filePath));
}

module.exports = {
  decodeMemoryArchive,
  encodeMemoryArchive,
  readMemoryArchive,
  writeMemoryArchive,
};
