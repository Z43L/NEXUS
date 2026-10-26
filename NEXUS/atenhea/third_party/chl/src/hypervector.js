const { stableHash32 } = require("./utils");

function emptyVector(dimension) {
  if (dimension % 32 !== 0) {
    throw new Error(`dimension must be a multiple of 32, got ${dimension}`);
  }
  return new Uint32Array(dimension / 32);
}

function vectorFromSeed(seed, dimension = 256) {
  const out = emptyVector(dimension);
  let state = stableHash32(String(seed), 0x9e3779b9);
  for (let i = 0; i < out.length; i += 1) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    out[i] = state >>> 0;
  }
  return out;
}

function cloneVector(vector) {
  return new Uint32Array(vector);
}

function xorVectors(a, b) {
  const out = new Uint32Array(a.length);
  for (let i = 0; i < a.length; i += 1) {
    out[i] = (a[i] ^ b[i]) >>> 0;
  }
  return out;
}

function rotateLeftWords(vector, shiftBits) {
  const wordCount = vector.length;
  const bitCount = wordCount * 32;
  const shift = ((shiftBits % bitCount) + bitCount) % bitCount;
  if (shift === 0) return cloneVector(vector);
  const out = emptyVector(bitCount);
  for (let i = 0; i < bitCount; i += 1) {
    const src = (i - shift + bitCount) % bitCount;
    if ((vector[src >>> 5] & (1 << (src & 31))) !== 0) {
      out[i >>> 5] |= 1 << (i & 31);
    }
  }
  return out;
}

function bundleVectors(vectors, dimension = 256) {
  if (vectors.length === 0) {
    return emptyVector(dimension);
  }
  const bitCount = dimension;
  const counts = new Int16Array(bitCount);
  for (const vector of vectors) {
    for (let i = 0; i < bitCount; i += 1) {
      if ((vector[i >>> 5] & (1 << (i & 31))) !== 0) counts[i] += 1;
      else counts[i] -= 1;
    }
  }
  const out = emptyVector(dimension);
  for (let i = 0; i < bitCount; i += 1) {
    if (counts[i] >= 0) out[i >>> 5] |= 1 << (i & 31);
  }
  return out;
}

function bindVectors(a, b) {
  return xorVectors(a, b);
}

function similarity(a, b) {
  let matches = 0;
  const bits = a.length * 32;
  for (let i = 0; i < a.length; i += 1) {
    const x = ~(a[i] ^ b[i]);
    const v = x - ((x >>> 1) & 0x55555555);
    const y = (v & 0x33333333) + ((v >>> 2) & 0x33333333);
    matches += (((y + (y >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
  }
  return matches / bits;
}

function prototypeVectorFromText(text, dimension = 256, seed = 0) {
  const tokens = String(text ?? "")
    .toLowerCase()
    .split(/[^a-z0-9]+/g)
    .filter(Boolean);
  const vectors = tokens.map((token, index) => {
    const basis = vectorFromSeed(`${seed}:${token}`, dimension);
    return rotateLeftWords(basis, index * 11);
  });
  return bundleVectors(vectors, dimension);
}

module.exports = {
  bindVectors,
  bundleVectors,
  cloneVector,
  emptyVector,
  prototypeVectorFromText,
  rotateLeftWords,
  similarity,
  vectorFromSeed,
};
