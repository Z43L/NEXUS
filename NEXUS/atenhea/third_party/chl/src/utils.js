const WORD_RE = /\p{L}[\p{L}\p{N}_'-]*/gu;

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function tokenize(value) {
  const text = normalizeText(value);
  const tokens = [];
  for (const match of text.matchAll(WORD_RE)) {
    const token = match[0];
    if (token.length > 0) tokens.push(token);
  }
  return tokens;
}

function charNgrams(text, n) {
  const cleaned = ` ${normalizeText(text)} `;
  if (cleaned.length < n) return cleaned ? [cleaned] : [];
  const grams = [];
  for (let i = 0; i <= cleaned.length - n; i += 1) {
    grams.push(cleaned.slice(i, i + n));
  }
  return grams;
}

function stableHash32(input, seed = 0) {
  let h = (0x811c9dc5 ^ seed) >>> 0;
  const text = String(input);
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  h ^= h >>> 16;
  h = Math.imul(h, 0x7feb352d) >>> 0;
  h ^= h >>> 15;
  h = Math.imul(h, 0x846ca68b) >>> 0;
  h ^= h >>> 16;
  return h >>> 0;
}

function splitmix32(seed) {
  let x = seed >>> 0;
  return function next() {
    x = (x + 0x9e3779b9) >>> 0;
    let z = x;
    z = Math.imul(z ^ (z >>> 16), 0x85ebca6b) >>> 0;
    z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35) >>> 0;
    return (z ^ (z >>> 16)) >>> 0;
  };
}

function popcount32(value) {
  let v = value >>> 0;
  v = v - ((v >>> 1) & 0x55555555);
  v = (v & 0x33333333) + ((v >>> 2) & 0x33333333);
  return (((v + (v >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
}

function popcountWords(a, b) {
  let total = 0;
  for (let i = 0; i < a.length; i += 1) {
    total += popcount32((a[i] ^ b[i]) >>> 0);
  }
  return total;
}

function wordsToHex(words) {
  return Array.from(words, (w) => (w >>> 0).toString(16).padStart(8, "0")).join("");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

module.exports = {
  charNgrams,
  clamp,
  normalizeText,
  popcount32,
  popcountWords,
  splitmix32,
  stableHash32,
  tokenize,
  wordsToHex,
};
