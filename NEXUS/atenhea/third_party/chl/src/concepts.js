const fs = require("node:fs");
const { normalizeText, tokenize } = require("./utils");

const STOPWORDS = new Set([
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

const DEFAULT_CONCEPT_PAIRS = [
  ["felino", "gato"],
  ["can", "perro"],
  ["automovil", "coche"],
  ["medico", "doctor"],
  ["cocinera", "chef"],
  ["alumna", "estudiante"],
  ["libreta", "cuaderno"],
  ["desbloquea", "abre"],
  ["abre", "abre"],
  ["cierra", "cierra"],
  ["bloquea", "cierra"],
  ["recarga", "carga"],
  ["carga", "carga"],
  ["desciende", "cae"],
  ["cae", "cae"],
  ["conserva", "guarda"],
  ["guarda", "guarda"],
  ["descansa", "duerme"],
  ["duerme", "duerme"],
  ["anota", "escribe"],
  ["escribe", "escribe"],
  ["templa", "calienta"],
  ["calienta", "calienta"],
  ["enseña", "muestra"],
  ["muestra", "muestra"],
  ["resuena", "suena"],
  ["suena", "suena"],
  ["adquiere", "compra"],
  ["compra", "compra"],
  ["moja", "riega"],
  ["riega", "riega"],
  ["apoya", "posa"],
  ["posa", "posa"],
  ["llega", "entra"],
  ["entra", "entra"],
  ["correr", "corre"],
  ["corre", "corre"],
  ["va", "circula"],
  ["circula", "circula"],
  ["vigila", "observa"],
  ["observa", "observa"],
  ["examina", "analiza"],
  ["analiza", "analiza"],
  ["coordina", "sincroniza"],
  ["sincroniza", "sincroniza"],
  ["maneja", "procesa"],
  ["procesa", "procesa"],
  ["localiza", "encuentra"],
  ["encuentra", "encuentra"],
  ["sigue", "rastrea"],
  ["rastrea", "rastrea"],
  ["resguarda", "protege"],
  ["protege", "protege"],
  ["enciende", "activa"],
  ["activa", "activa"],
  ["apaga", "desactiva"],
  ["desactiva", "desactiva"],
  ["obtiene", "recibe"],
  ["recibe", "recibe"],
  ["favorece", "prioriza"],
  ["prioriza", "prioriza"],
  ["absorbe", "aprende"],
  ["aprende", "aprende"],
  ["mira", "observa"],
  ["usa", "utiliza"],
  ["utiliza", "usa"],
  ["crea", "genera"],
  ["genera", "crea"],
  ["reduce", "disminuye"],
  ["disminuye", "reduce"],
];

const DEFAULT_PHRASE_PAIRS = [
  ["da luz a", "ilumina"],
  ["desprende humo", "humea"],
  ["se mueve por", "corre por"],
  ["se desplaza en", "nada en"],
  ["se posa en", "posa en"],
  ["arriba a", "llega a"],
  ["llega a", "entra en"],
  ["permanece en", "esta en"],
  ["sigue en", "esta en"],
  ["coordina con", "sincroniza con"],
  ["aprende de", "absorbe de"],
];

const conceptMapCache = new Map();
const phraseMapCache = new Map();

function pairsToMap(pairs) {
  const map = new Map();
  for (const [from, to] of pairs ?? []) {
    if (!from || !to) continue;
    map.set(normalizeText(from), normalizeText(to));
  }
  return map;
}

function mergeConceptMaps(...maps) {
  const merged = new Map();
  for (const map of maps) {
    if (!map) continue;
    for (const [from, to] of map.entries()) merged.set(from, to);
  }
  return merged;
}

function loadConceptPairsFromFile(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return [];
  const content = fs.readFileSync(filePath, "utf8");
  const pairs = [];
  for (const line of content.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const [from, to] = line.split("\t");
    if (from && to) pairs.push([from, to]);
  }
  return pairs;
}

function loadPhrasePairsFromFile(filePath) {
  return loadConceptPairsFromFile(filePath);
}

function getConceptMap(options = {}) {
  const filePath = options.filePath ?? process.env.CHL_CONCEPTS_PATH ?? null;
  const cacheKey = `${filePath ?? ""}|${JSON.stringify(options.extraPairs ?? [])}`;
  if (conceptMapCache.has(cacheKey)) return conceptMapCache.get(cacheKey);
  const learnedPairs = loadConceptPairsFromFile(filePath);
  const learnedMap = pairsToMap(learnedPairs);
  const map = mergeConceptMaps(pairsToMap(DEFAULT_CONCEPT_PAIRS), learnedMap, options.extraPairs ? pairsToMap(options.extraPairs) : null);
  conceptMapCache.set(cacheKey, map);
  return map;
}

function getPhraseMap(options = {}) {
  const filePath = options.filePath ?? process.env.CHL_PHRASES_PATH ?? null;
  const cacheKey = `${filePath ?? ""}|${JSON.stringify(options.extraPairs ?? [])}`;
  if (phraseMapCache.has(cacheKey)) return phraseMapCache.get(cacheKey);
  const learnedPairs = loadPhrasePairsFromFile(filePath);
  const map = mergeConceptMaps(pairsToMap(DEFAULT_PHRASE_PAIRS), pairsToMap(learnedPairs), options.extraPairs ? pairsToMap(options.extraPairs) : null);
  phraseMapCache.set(cacheKey, map);
  return map;
}

function canonicalizeText(text, options = {}) {
  let canonical = normalizeText(text);
  const phraseMap = options.phraseMap ?? getPhraseMap(options);
  for (const [from, to] of phraseMap.entries()) {
    const pattern = new RegExp(`\\b${from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g");
    canonical = canonical.replace(pattern, to);
  }
  return canonical;
}

function conceptualizeTokens(text, options = {}) {
  const conceptMap = options.conceptMap ?? getConceptMap(options);
  const canonical = canonicalizeText(text, options);
  const concepts = [];
  for (const token of tokenize(canonical)) {
    if (STOPWORDS.has(token)) continue;
    concepts.push(conceptMap.get(token) ?? token);
  }
  return concepts;
}

function learnConceptPairsFromExamples(examples = []) {
  const counts = new Map();
  const addPair = (from, to) => {
    if (!from || !to || from === to) return;
    if (from.length < 3 || to.length < 3) return;
    const key = `${from}\t${to}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  };

  for (const example of examples) {
    const source = Array.isArray(example) ? example[0] : example?.source;
    const target = Array.isArray(example) ? example[1] : example?.target;
    if (!source || !target) continue;
    const srcTokens = tokenize(normalizeText(source));
    const tgtTokens = tokenize(normalizeText(target));
    const maxPrefix = Math.min(srcTokens.length, tgtTokens.length);
    let prefix = 0;
    while (prefix < maxPrefix && srcTokens[prefix] === tgtTokens[prefix]) prefix += 1;
    let suffix = 0;
    while (
      suffix < Math.min(srcTokens.length - prefix, tgtTokens.length - prefix) &&
      srcTokens[srcTokens.length - 1 - suffix] === tgtTokens[tgtTokens.length - 1 - suffix]
    ) {
      suffix += 1;
    }
    const srcMid = srcTokens.slice(prefix, srcTokens.length - suffix).filter((token) => !STOPWORDS.has(token));
    const tgtMid = tgtTokens.slice(prefix, tgtTokens.length - suffix).filter((token) => !STOPWORDS.has(token));
    const len = Math.min(srcMid.length, tgtMid.length);
    for (let i = 0; i < len; i += 1) {
      addPair(srcMid[i], tgtMid[i]);
      addPair(tgtMid[i], srcMid[i]);
    }
  }

  const learned = new Map();
  for (const [key, count] of counts.entries()) {
    if (count < 2) continue;
    const [from, to] = key.split("\t");
    if (!from || !to) continue;
    learned.set(from, to);
  }
  return learned;
}

function learnPhrasePairsFromExamples(examples = []) {
  const counts = new Map();
  const addPair = (from, to) => {
    if (!from || !to || from === to) return;
    const key = `${from}\t${to}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  };
  for (const example of examples) {
    const source = Array.isArray(example) ? example[0] : example?.source;
    const target = Array.isArray(example) ? example[1] : example?.target;
    if (!source || !target) continue;
    const srcTokens = tokenize(normalizeText(source));
    const tgtTokens = tokenize(normalizeText(target));
    const maxPrefix = Math.min(srcTokens.length, tgtTokens.length);
    let prefix = 0;
    while (prefix < maxPrefix && srcTokens[prefix] === tgtTokens[prefix]) prefix += 1;
    let suffix = 0;
    while (
      suffix < Math.min(srcTokens.length - prefix, tgtTokens.length - prefix) &&
      srcTokens[srcTokens.length - 1 - suffix] === tgtTokens[tgtTokens.length - 1 - suffix]
    ) {
      suffix += 1;
    }
    const srcMid = srcTokens.slice(prefix, srcTokens.length - suffix).join(" ").trim();
    const tgtMid = tgtTokens.slice(prefix, tgtTokens.length - suffix).join(" ").trim();
    if (!srcMid || !tgtMid) continue;
    if (srcMid.split(" ").length > 3 || tgtMid.split(" ").length > 3) continue;
    addPair(srcMid, tgtMid);
    addPair(tgtMid, srcMid);
  }
  const learned = new Map();
  for (const [key, count] of counts.entries()) {
    if (count < 2) continue;
    const [from, to] = key.split("\t");
    if (!from || !to) continue;
    learned.set(from, to);
  }
  return learned;
}

function serializeConceptMap(map) {
  const lines = [];
  for (const [from, to] of map.entries()) {
    lines.push(`${from}\t${to}`);
  }
  return lines.join("\n");
}

function serializePairList(pairs = []) {
  const lines = [];
  for (const pair of pairs) {
    const from = Array.isArray(pair) ? pair[0] : pair?.from;
    const to = Array.isArray(pair) ? pair[1] : pair?.to;
    if (!from || !to) continue;
    lines.push(`${normalizeText(from)}\t${normalizeText(to)}`);
  }
  return lines.join("\n");
}

function loadLexiconState({ conceptsPath = null, phrasesPath = null, prototypesPath = null } = {}) {
  const result = {
    concepts: loadConceptPairsFromFile(conceptsPath),
    phrases: loadPhrasePairsFromFile(phrasesPath),
  };
  if (prototypesPath && fs.existsSync(prototypesPath)) {
    try {
      const raw = JSON.parse(fs.readFileSync(prototypesPath, "utf8"));
      result.prototypes = raw ?? null;
    } catch (_) { /* ignore malformed prototypes */ }
  }
  return result;
}

function saveLexiconState(state = {}, { conceptsPath = null, phrasesPath = null, prototypesPath = null } = {}) {
  const concepts = Array.isArray(state.concepts) ? state.concepts : [];
  const phrases = Array.isArray(state.phrases) ? state.phrases : [];
  if (conceptsPath) {
    fs.mkdirSync(require("node:path").dirname(conceptsPath), { recursive: true });
    fs.writeFileSync(conceptsPath, serializePairList(concepts));
  }
  if (phrasesPath) {
    fs.mkdirSync(require("node:path").dirname(phrasesPath), { recursive: true });
    fs.writeFileSync(phrasesPath, serializePairList(phrases));
  }
  if (prototypesPath && state.prototypes) {
    fs.mkdirSync(require("node:path").dirname(prototypesPath), { recursive: true });
    fs.writeFileSync(prototypesPath, JSON.stringify(state.prototypes, null, 2));
  }
  return {
    conceptsPath,
    phrasesPath,
    prototypesPath: prototypesPath ?? null,
    concepts: concepts.length,
    phrases: phrases.length,
    prototypes: state.prototypes ? true : false,
  };
}

module.exports = {
  DEFAULT_CONCEPT_PAIRS,
  DEFAULT_PHRASE_PAIRS,
  STOPWORDS,
  canonicalizeText,
  conceptualizeTokens,
  getConceptMap,
  getPhraseMap,
  learnConceptPairsFromExamples,
  learnPhrasePairsFromExamples,
  loadConceptPairsFromFile,
  loadPhrasePairsFromFile,
  loadLexiconState,
  mergeConceptMaps,
  pairsToMap,
  saveLexiconState,
  serializePairList,
  serializeConceptMap,
};
