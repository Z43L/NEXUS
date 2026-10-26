const {
  charNgrams,
  popcountWords,
  splitmix32,
  stableHash32,
  tokenize,
} = require("./utils");
const { conceptualizeTokens } = require("./concepts");

function emptyWords(bitCount) {
  if (bitCount % 32 !== 0) {
    throw new Error(`bitCount must be a multiple of 32, got ${bitCount}`);
  }
  return new Uint32Array(bitCount / 32);
}

function extractFeatures(input, options = {}) {
  const text = String(input ?? "");
  const tokens = tokenize(text);
  const concepts = conceptualizeTokens(text);
  const features = [];
  const tokenWeight = options.tokenWeight ?? 3;
  const gramWeight = options.gramWeight ?? 1;
  const conceptWeight = options.conceptWeight ?? 3;

  for (const token of tokens) {
    features.push({ key: `tok:${token}`, weight: tokenWeight });
  }

  for (const concept of concepts) {
    features.push({ key: `con:${concept}`, weight: conceptWeight });
  }

  for (const gram of charNgrams(text, options.charN ?? 3)) {
    features.push({ key: `chr:${gram}`, weight: gramWeight });
  }

  if (features.length === 0 && text.trim()) {
    features.push({ key: `raw:${text.trim()}`, weight: 1 });
  }

  return features;
}

function semanticHash(features, bitCount = 128, options = {}) {
  const scores = new Float64Array(bitCount);
  const seed = options.seed ?? 0;
  const bitBias = options.bitBias ?? null;
  const wordCount = bitCount / 32;

  for (const feature of features) {
    const featureSeed = stableHash32(feature.key, seed);
    const next = splitmix32(featureSeed);
    const weight = feature.weight ?? 1;
    for (let w = 0; w < wordCount; w += 1) {
      const word = next();
      const base = w * 32;
      for (let bit = 0; bit < 32; bit += 1) {
        scores[base + bit] += (word & (1 << bit)) !== 0 ? weight : -weight;
      }
    }
  }

  if (bitBias) {
    for (let i = 0; i < Math.min(bitBias.length, scores.length); i += 1) {
      scores[i] += bitBias[i];
    }
  }

  const out = emptyWords(bitCount);
  for (let i = 0; i < bitCount; i += 1) {
    if (scores[i] >= 0) {
      out[i >>> 5] |= 1 << (i & 31);
    }
  }
  return out;
}

function semanticHashFromText(text, options = {}) {
  return semanticHash(extractFeatures(text, options), options.bitCount ?? 128, options);
}

function hammingDistance(a, b) {
  return popcountWords(a, b);
}

function hammingSimilarity(a, b) {
  const bits = a.length * 32;
  return 1 - hammingDistance(a, b) / bits;
}

module.exports = {
  emptyWords,
  extractFeatures,
  hammingDistance,
  hammingSimilarity,
  semanticHash,
  semanticHashFromText,
};
