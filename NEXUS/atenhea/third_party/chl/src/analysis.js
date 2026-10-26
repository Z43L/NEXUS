const { charNgrams, normalizeText, tokenize } = require("./utils");
const { conceptualizeTokens } = require("./concepts");

const DEFAULT_STOPWORDS = new Set([
  "el",
  "la",
  "los",
  "las",
  "un",
  "una",
  "unos",
  "unas",
  "de",
  "del",
  "al",
  "en",
  "a",
  "y",
  "o",
  "que",
  "se",
  "su",
  "sus",
  "es",
  "esta",
  "estan",
  "hay",
  "por",
  "para",
  "sobre",
  "con",
]);

function unique(values = []) {
  return Array.from(new Set(values));
}

function tokenWindows(tokens, size) {
  if (!Array.isArray(tokens) || size <= 1 || tokens.length < size) return [];
  const windows = [];
  for (let index = 0; index <= tokens.length - size; index += 1) {
    windows.push(tokens.slice(index, index + size).join(" "));
  }
  return windows;
}

function selectFocusTokens(tokens) {
  const focus = [];
  for (const token of tokens ?? []) {
    if (!token) continue;
    if (DEFAULT_STOPWORDS.has(token)) continue;
    if (token.length < 3) continue;
    focus.push(token);
  }
  return unique(focus);
}

function analyzeText(text, options = {}) {
  const normalizedText = typeof text === "string" ? text : JSON.stringify(text);
  const normalized = normalizeText(normalizedText);
  const canonicalText =
    typeof options.canonicalizeText === "function" ? options.canonicalizeText(normalized) : normalized;
  const tokens = tokenize(canonicalText);
  const focusTokens = selectFocusTokens(tokens);
  const tokenBigrams = tokenWindows(tokens, 2);
  const tokenTrigrams = tokenWindows(tokens, 3);
  const concepts =
    typeof options.conceptualizeTokens === "function"
      ? options.conceptualizeTokens(canonicalText)
      : conceptualizeTokens(canonicalText);
  const ngrams3 = charNgrams(canonicalText, 3);
  const ngrams4 = charNgrams(canonicalText, 4);
  const negated = tokens.some((token) => token === "no" || token === "sin" || token === "nunca" || token === "jamas");
  const uniqueTokenCount = unique(tokens).length;
  const tokenCount = tokens.length;
  const lexicalDensity = tokenCount > 0 ? uniqueTokenCount / tokenCount : 0;

  return {
    normalizedText,
    canonicalText,
    tokens,
    focusTokens,
    tokenBigrams,
    tokenTrigrams,
    ngrams3,
    ngrams4,
    concepts,
    negated,
    tokenCount,
    uniqueTokenCount,
    lexicalDensity,
  };
}

module.exports = {
  analyzeText,
  DEFAULT_STOPWORDS,
  selectFocusTokens,
  tokenWindows,
};
