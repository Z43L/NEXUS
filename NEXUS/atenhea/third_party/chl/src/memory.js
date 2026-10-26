const { hammingDistance, semanticHashFromText } = require("./simhash");
const { conceptualizeTokens: conceptTokens, getPhraseMap } = require("./concepts");
const { analyzeText } = require("./analysis");
const {
  bindVectors,
  bundleVectors,
  cloneVector,
  prototypeVectorFromText,
  similarity,
  vectorFromSeed,
} = require("./hypervector");
const { HyperAttentionContext } = require("./hyperattention");
const { LexiconTrainer } = require("./lexiconLearner");
const {
  clamp,
  charNgrams,
  normalizeText,
  tokenize,
  wordsToHex,
} = require("./utils");
const {
  MemoryType,
  getDefaultExpiry,
  getEvictionPriority,
  getScoringProfile,
  getTierForType,
  isExpired,
  normalizeMemoryType,
  temporalScore,
} = require("./memory-types");
const { classifyMemory } = require("./memory-classifier");
const { buildQueryOptions, getTypeBoostForIntent } = require("./query-intent");
const crypto = require("crypto");

function makeBandKey(words, bandIndex, wordsPerBand) {
  const start = bandIndex * wordsPerBand;
  const slice = words.slice(start, start + wordsPerBand);
  return wordsToHex(slice);
}

function createBands(bitCount, bandBits = 32) {
  if (bitCount % bandBits !== 0) {
    throw new Error(`bitCount ${bitCount} must be divisible by bandBits ${bandBits}`);
  }
  const bands = bitCount / bandBits;
  const wordsPerBand = bandBits / 32;
  return { bands, wordsPerBand };
}

const PHRASE_CANONICALS = [
  ["da luz a", "ilumina"],
  ["desprende humo", "humea"],
  ["se mueve por", "corre por"],
  ["se desplaza en", "nada en"],
  ["se posa en", "posa en"],
  ["arriba a", "llega a"],
  ["llega a", "entra en"],
  ["desbloquea", "abre"],
  ["conserva", "guarda"],
  ["recarga", "carga"],
  ["permanece en", "esta en"],
  ["sigue en", "esta en"],
  ["tapiza", "cubre"],
  ["resuena", "suena"],
  ["anota", "escribe"],
  ["adquiere", "compra"],
  ["moja", "riega"],
  ["templa", "calienta"],
  ["enseña", "muestra"],
  ["vigila", "observa"],
  ["examina", "analiza"],
  ["coordina con", "sincroniza con"],
  ["maneja", "procesa"],
  ["localiza", "encuentra"],
  ["sigue", "rastrea"],
  ["resguarda", "protege"],
  ["enciende", "activa"],
  ["apaga", "desactiva"],
  ["obtiene", "recibe"],
  ["favorece", "prioriza"],
  ["absorbe", "aprende"],
];

function normalizedTokens(text) {
  return tokenize(text);
}

function canonicalizeText(text) {
  let canonical = normalizeText(text);
  for (const [from, to] of PHRASE_CANONICALS) {
    const pattern = new RegExp(`\\b${from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g");
    canonical = canonical.replace(pattern, to);
  }
  const learnedPhraseMap = getPhraseMap();
  for (const [from, to] of learnedPhraseMap.entries()) {
    const pattern = new RegExp(`\\b${from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g");
    canonical = canonical.replace(pattern, to);
  }
  return canonical;
}

function conceptualizeTokens(text) {
  return conceptTokens(text);
}

function setJaccard(a, b) {
  const setA = new Set(a);
  const setB = new Set(b);
  if (setA.size === 0 && setB.size === 0) return 0;
  let inter = 0;
  for (const item of setA) {
    if (setB.has(item)) inter += 1;
  }
  const union = new Set([...setA, ...setB]).size;
  return union ? inter / union : 0;
}

function buildRepresentations(text) {
  return analyzeText(text, {
    canonicalizeText,
    conceptualizeTokens,
  });
}

function stringifyPayload(payload) {
  if (payload == null) return "";
  if (typeof payload === "string") return payload;
  try {
    return JSON.stringify(payload);
  } catch {
    return String(payload);
  }
}

function representationSimilarity(queryReps, entryReps) {
  const tokenScore = setJaccard(queryReps.tokens, entryReps.tokens);
  const sequenceScore = tokenSequenceSimilarity(queryReps.focusTokens, entryReps.focusTokens);
  const ngram3Score = setJaccard(queryReps.ngrams3, entryReps.ngrams3);
  const ngram4Score = setJaccard(queryReps.ngrams4, entryReps.ngrams4);
  const lexical = 0.22 * tokenScore + 0.18 * sequenceScore + 0.30 * ngram3Score + 0.30 * ngram4Score;
  const concept = setJaccard(queryReps.concepts, entryReps.concepts);
  return { lexical, concept, negationMatch: queryReps.negated === entryReps.negated ? 1 : 0, sequenceScore };
}

function tokenSequenceSimilarity(a, b) {
  const left = a ?? [];
  const right = b ?? [];
  if (left.length === 0 || right.length === 0) return 0;
  const dp = Array.from({ length: left.length + 1 }, () => new Uint16Array(right.length + 1));
  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      dp[i][j] = left[i - 1] === right[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return dp[left.length][right.length] / Math.max(left.length, right.length);
}

// ─── Nuevas señales de scoring ───────────────────────────────

function phraseOverlapScore(queryReps, entryReps) {
  const left = queryReps.tokenTrigrams ?? [];
  const right = entryReps.tokenTrigrams ?? [];
  if (left.length === 0 || right.length === 0) return 0;
  const setA = new Set(left);
  const setB = new Set(right);
  let inter = 0;
  for (const item of setA) {
    if (setB.has(item)) inter += 1;
  }
  return inter / Math.max(setA.size, setB.size);
}

function wordOrderScore(queryReps, entryReps) {
  const left = queryReps.focusTokens ?? [];
  const right = entryReps.focusTokens ?? [];
  if (left.length === 0 || right.length === 0) return 0;
  const dp = Array.from({ length: left.length + 1 }, () => new Uint16Array(right.length + 1));
  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      dp[i][j] = left[i - 1] === right[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return dp[left.length][right.length] / Math.max(left.length, right.length);
}

function entityMatchScore(queryReps, entryReps) {
  const qConcepts = queryReps.concepts ?? [];
  const eConcepts = entryReps.concepts ?? [];
  if (qConcepts.length === 0 || eConcepts.length === 0) return 0;
  const setE = new Set(eConcepts);
  let hits = 0;
  for (const concept of qConcepts) {
    if (setE.has(concept)) hits += 1;
  }
  return hits / qConcepts.length;
}

function zNormalize(values) {
  if (values.length === 0) return values;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, b) => a + b * b, 0) / values.length - mean * mean;
  const std = Math.sqrt(Math.max(0, variance)) || 1;
  return values.map((v) => (v - mean) / std);
}

function mergeMemoryType(a, b) {
  // Jerarquía de importancia: perfiles y conocimiento estable ganan sobre corto plazo.
  const rank = {
    [MemoryType.SELF_PROFILE]: 7,
    [MemoryType.USER_PROFILE]: 6,
    [MemoryType.LONG_TERM]: 5,
    [MemoryType.KNOWLEDGE]: 4,
    [MemoryType.MEDIUM_TERM]: 3,
    [MemoryType.EPISODIC]: 2,
    [MemoryType.SHORT_TERM]: 1,
    [MemoryType.EPHEMERAL]: 0,
  };
  const rankA = rank[a] ?? 1;
  const rankB = rank[b] ?? 1;
  return rankA >= rankB ? a : b;
}

class AssociativeMemory {
  constructor(options = {}) {
    this.bitCount = options.bitCount ?? 128;
    this.bandBits = options.bandBits ?? 32;
    this.hyperDim = options.hyperDim ?? 256;
    this.maxEntries = options.maxEntries ?? 4096;
    this.maxCandidates = options.maxCandidates ?? 64;
    this.profile = options.profile ?? "default";
    this.largeProfile = options.largeProfile ?? this.profile === "large";
    this.minMergeSimilarity = options.minMergeSimilarity ?? 0.9;
    this.seed = options.seed ?? 0;
    this.recentHalfLifeMs = options.recentHalfLifeMs ?? 30 * 60 * 1000;
    this.bitBias = new Float64Array(this.bitCount);
    // HyperAttention opcional
    this.attention = options.attention ?? null;
    // LexiconTrainer opcional
    this.lexiconTrainer = options.lexiconTrainer ?? null;
    this.conceptIndex = new Map();  // conceptId → Set<entryId>
    this.entries = new Map();
    this._evictionHeap = [];
    this._evictionVersion = 0;
    this.bandMaps = [];
    this.textMap = new Map();
    this.canonicalTextMap = new Map();
    this.tokenMaps = [new Map(), new Map(), new Map(), new Map(), new Map(), new Map()];
    this.payloadTokenMaps = [new Map(), new Map(), new Map(), new Map(), new Map(), new Map()];
    // Índice por tipo de memoria y por fuente
    this.typeIndex = new Map();   // memoryType → Set<entryId>
    this.sourceMap = new Map();   // source → Set<entryId>
    const { bands, wordsPerBand } = createBands(this.bitCount, this.bandBits);
    this.bandCount = bands;
    this.wordsPerBand = wordsPerBand;
    for (let i = 0; i < this.bandCount; i += 1) {
      this.bandMaps.push(new Map());
    }
  }

  encodeText(text) {
    return semanticHashFromText(text, {
      bitCount: this.bitCount,
      seed: this.seed,
      bitBias: this.bitBias,
    });
  }

  /**
   * Canonicaliza texto usando un mapa específico (conservador).
   * Solo reemplaza tokens, no usa phraseIndex.
   */
  _canonicalizeWithMap(text, map) {
    let result = text;
    const tokens = result.toLowerCase().split(/[^a-z0-9]+/g).filter(Boolean);
    for (const token of tokens) {
      const canonical = map.get(token);
      if (canonical && canonical !== token) {
        result = result.replace(new RegExp('\\b' + token + '\\b', 'g'), canonical);
      }
    }
    return result;
  }

  makeEntry(input, payload = null, metadata = {}) {
    const text = typeof input === "string" ? input : JSON.stringify(input);
    const memoryType = normalizeMemoryType(
      metadata.memoryType ?? classifyMemory(input, payload, metadata)
    );
    const source = metadata.source ?? "manual";
    const tier = metadata.tier ?? getTierForType(memoryType);
    const expiresAt =
      metadata.expiresAt ??
      (metadata.ttlMs ? Date.now() + metadata.ttlMs : getDefaultExpiry(memoryType));

    const representations = buildRepresentations(text);
    const payloadText = stringifyPayload(payload);
    const payloadRepresentations = payloadText ? buildRepresentations(payloadText) : null;
    const hash = this.encodeText(text);
    const hypervector = prototypeVectorFromText(text, this.hyperDim, this.seed);
    const now = Date.now();

    // Quality por defecto ligeramente mayor para perfiles y conocimiento estable.
    let quality = metadata.quality ?? 5;
    if (metadata.quality === undefined) {
      if (memoryType === MemoryType.SELF_PROFILE || memoryType === MemoryType.USER_PROFILE) {
        quality = 7;
      } else if (memoryType === MemoryType.LONG_TERM || memoryType === MemoryType.KNOWLEDGE) {
        quality = 6;
      }
    }

    return {
      id: metadata.id || crypto.randomUUID(),
      text,
      memoryType,
      tier,
      expiresAt,
      source,
      representations,
      payloadRepresentations,
      hash,
      hypervector,
      payload: payload ?? input,
      metadata: { ...metadata, memoryType, source },
      quality: clamp(quality, 0, 10),
      createdAt: now,
      updatedAt: now,
      lastAccessAt: now,
      accessCount: 0,
      prototypeCount: 1,
    };
  }

  indexEntry(entry) {
    this._indexText(this.textMap, entry.representations?.normalizedText ?? "", entry.id);
    this._indexText(this.canonicalTextMap, entry.representations?.canonicalText ?? "", entry.id);
    this._indexText(this.textMap, entry.payloadRepresentations?.normalizedText ?? "", entry.id);
    this._indexText(this.canonicalTextMap, entry.payloadRepresentations?.canonicalText ?? "", entry.id);
    // Indexar por concepto si hay trainer
    if (this.lexiconTrainer) {
      const conceptId = this.lexiconTrainer.resolveConcept(entry.text ?? "");
      if (conceptId) {
        if (!this.conceptIndex.has(conceptId)) {
          this.conceptIndex.set(conceptId, new Set());
        }
        this.conceptIndex.get(conceptId).add(entry.id);
      }
    }
    // Indexar por tipo de memoria y por fuente
    if (entry.memoryType) {
      if (!this.typeIndex.has(entry.memoryType)) {
        this.typeIndex.set(entry.memoryType, new Set());
      }
      this.typeIndex.get(entry.memoryType).add(entry.id);
    }
    if (entry.source) {
      if (!this.sourceMap.has(entry.source)) {
        this.sourceMap.set(entry.source, new Set());
      }
      this.sourceMap.get(entry.source).add(entry.id);
    }
    for (let bandIndex = 0; bandIndex < this.bandCount; bandIndex += 1) {
      const key = makeBandKey(entry.hash, bandIndex, this.wordsPerBand);
      let bucket = this.bandMaps[bandIndex].get(key);
      if (!bucket) {
        bucket = new Set();
        this.bandMaps[bandIndex].set(key, bucket);
      }
      bucket.add(entry.id);
    }
    this._indexTerms(this.tokenMaps[0], entry.representations?.tokens ?? [], entry.id);
    this._indexTerms(this.tokenMaps[1], entry.representations?.ngrams3 ?? [], entry.id);
    this._indexTerms(this.tokenMaps[2], entry.representations?.ngrams4 ?? [], entry.id);
    this._indexTerms(this.tokenMaps[3], entry.representations?.concepts ?? [], entry.id);
    this._indexTerms(this.tokenMaps[4], entry.representations?.focusTokens ?? [], entry.id);
    this._indexTerms(this.tokenMaps[5], entry.representations?.tokenBigrams ?? [], entry.id);
    this._indexTerms(this.payloadTokenMaps[0], entry.payloadRepresentations?.tokens ?? [], entry.id);
    this._indexTerms(this.payloadTokenMaps[1], entry.payloadRepresentations?.ngrams3 ?? [], entry.id);
    this._indexTerms(this.payloadTokenMaps[2], entry.payloadRepresentations?.ngrams4 ?? [], entry.id);
    this._indexTerms(this.payloadTokenMaps[3], entry.payloadRepresentations?.concepts ?? [], entry.id);
    this._indexTerms(this.payloadTokenMaps[4], entry.payloadRepresentations?.focusTokens ?? [], entry.id);
    this._indexTerms(this.payloadTokenMaps[5], entry.payloadRepresentations?.tokenBigrams ?? [], entry.id);
  }

  unindexEntry(entry) {
    this._unindexText(this.textMap, entry.representations?.normalizedText ?? "", entry.id);
    this._unindexText(this.canonicalTextMap, entry.representations?.canonicalText ?? "", entry.id);
    this._unindexText(this.textMap, entry.payloadRepresentations?.normalizedText ?? "", entry.id);
    this._unindexText(this.canonicalTextMap, entry.payloadRepresentations?.canonicalText ?? "", entry.id);
    // Desindexar concepto
    if (this.lexiconTrainer) {
      const conceptId = this.lexiconTrainer.resolveConcept(entry.text ?? "");
      if (conceptId && this.conceptIndex.has(conceptId)) {
        this.conceptIndex.get(conceptId).delete(entry.id);
        if (this.conceptIndex.get(conceptId).size === 0) {
          this.conceptIndex.delete(conceptId);
        }
      }
    }
    // Desindexar por tipo y fuente
    if (entry.memoryType && this.typeIndex.has(entry.memoryType)) {
      this.typeIndex.get(entry.memoryType).delete(entry.id);
      if (this.typeIndex.get(entry.memoryType).size === 0) {
        this.typeIndex.delete(entry.memoryType);
      }
    }
    if (entry.source && this.sourceMap.has(entry.source)) {
      this.sourceMap.get(entry.source).delete(entry.id);
      if (this.sourceMap.get(entry.source).size === 0) {
        this.sourceMap.delete(entry.source);
      }
    }
    for (let bandIndex = 0; bandIndex < this.bandCount; bandIndex += 1) {
      const key = makeBandKey(entry.hash, bandIndex, this.wordsPerBand);
      const bucket = this.bandMaps[bandIndex].get(key);
      if (!bucket) continue;
      bucket.delete(entry.id);
      if (bucket.size === 0) this.bandMaps[bandIndex].delete(key);
    }
    this._unindexTerms(this.tokenMaps[0], entry.representations?.tokens ?? [], entry.id);
    this._unindexTerms(this.tokenMaps[1], entry.representations?.ngrams3 ?? [], entry.id);
    this._unindexTerms(this.tokenMaps[2], entry.representations?.ngrams4 ?? [], entry.id);
    this._unindexTerms(this.tokenMaps[3], entry.representations?.concepts ?? [], entry.id);
    this._unindexTerms(this.tokenMaps[4], entry.representations?.focusTokens ?? [], entry.id);
    this._unindexTerms(this.tokenMaps[5], entry.representations?.tokenBigrams ?? [], entry.id);
    this._unindexTerms(this.payloadTokenMaps[0], entry.payloadRepresentations?.tokens ?? [], entry.id);
    this._unindexTerms(this.payloadTokenMaps[1], entry.payloadRepresentations?.ngrams3 ?? [], entry.id);
    this._unindexTerms(this.payloadTokenMaps[2], entry.payloadRepresentations?.ngrams4 ?? [], entry.id);
    this._unindexTerms(this.payloadTokenMaps[3], entry.payloadRepresentations?.concepts ?? [], entry.id);
    this._unindexTerms(this.payloadTokenMaps[4], entry.payloadRepresentations?.focusTokens ?? [], entry.id);
    this._unindexTerms(this.payloadTokenMaps[5], entry.payloadRepresentations?.tokenBigrams ?? [], entry.id);
  }

  _indexText(map, text, id) {
    if (!text) return;
    let bucket = map.get(text);
    if (!bucket) {
      bucket = new Set();
      map.set(text, bucket);
    }
    bucket.add(id);
  }

  _unindexText(map, text, id) {
    if (!text) return;
    const bucket = map.get(text);
    if (!bucket) return;
    bucket.delete(id);
    if (bucket.size === 0) map.delete(text);
  }

  _indexTerms(map, terms, id) {
    for (const term of terms) {
      if (!term) continue;
      let bucket = map.get(term);
      if (!bucket) {
        bucket = new Set();
        map.set(term, bucket);
      }
      bucket.add(id);
    }
  }

  _unindexTerms(map, terms, id) {
    for (const term of terms) {
      if (!term) continue;
      const bucket = map.get(term);
      if (!bucket) continue;
      bucket.delete(id);
      if (bucket.size === 0) map.delete(term);
    }
  }

  insert(input, payload = null, metadata = {}) {
    const entry = this.makeEntry(input, payload, metadata);
    const candidates = this._candidateEntries(entry.representations, entry.hash);
    const merged = candidates.find((candidate) => {
      const sim = 1 - hammingDistance(candidate.hash, entry.hash) / this.bitCount;
      return sim >= this.minMergeSimilarity;
    });

    if (merged) {
      this.unindexEntry(merged);
      merged.hash = cloneVector(bundleVectors([merged.hash, entry.hash], this.bitCount));
      merged.hypervector = cloneVector(bundleVectors([merged.hypervector, entry.hypervector], this.hyperDim));
      merged.representations = this._mergeRepresentations(merged.representations, entry.representations);
      merged.payloadRepresentations = this._mergePayloadRepresentations(
        merged.payloadRepresentations,
        entry.payloadRepresentations
      );
      merged.payload = this._mergePayloads(merged.payload, entry.payload);
      merged.memoryType = mergeMemoryType(merged.memoryType, entry.memoryType);
      merged.tier = getTierForType(merged.memoryType);
      merged.expiresAt = Math.max(
        merged.expiresAt || 0,
        entry.expiresAt || 0,
        getDefaultExpiry(merged.memoryType)
      );
      merged.quality = clamp((merged.quality + entry.quality) / 2, 0, 10);
      merged.updatedAt = Date.now();
      merged.prototypeCount += 1;
      this.indexEntry(merged);
      this.entries.set(merged.id, merged);
      this._touchEviction(merged);
      return merged;
    }

    this.entries.set(entry.id, entry);
    this.indexEntry(entry);
    this._touchEviction(entry);
    this._enforceCapacity();
    return entry;
  }

  insertBatch(batch = []) {
    const inserted = [];
    for (const item of batch) {
      if (!item) continue;
      const input = item.input ?? item.text ?? "";
      const payload = item.payload ?? null;
      const metadata = item.metadata ?? {};
      const entry = this.insert(input, payload, metadata);
      if (entry) inserted.push(entry);
    }
    return inserted;
  }

  _mergePayloads(previous, next) {
    if (previous == null) return next;
    if (next == null) return previous;
    if (Array.isArray(previous) && Array.isArray(next)) return previous.concat(next);
    if (typeof previous === "object" && typeof next === "object") {
      return { ...previous, ...next };
    }
    if (previous === next) return previous;
    return [previous, next];
  }

  _mergeRepresentations(previous, next) {
    if (!previous) return next;
    if (!next) return previous;
    const mergeUnique = (a = [], b = []) => Array.from(new Set([...(a ?? []), ...(b ?? [])]));
    return {
      normalizedText: previous.normalizedText ?? next.normalizedText ?? "",
      canonicalText: previous.canonicalText ?? next.canonicalText ?? "",
      tokens: mergeUnique(previous.tokens, next.tokens),
      tokenBigrams: mergeUnique(previous.tokenBigrams, next.tokenBigrams),
      tokenTrigrams: mergeUnique(previous.tokenTrigrams, next.tokenTrigrams),
      ngrams3: mergeUnique(previous.ngrams3, next.ngrams3),
      ngrams4: mergeUnique(previous.ngrams4, next.ngrams4),
      concepts: mergeUnique(previous.concepts, next.concepts),
      focusTokens: mergeUnique(previous.focusTokens, next.focusTokens),
      negated: Boolean(previous.negated || next.negated),
    };
  }

  _mergePayloadRepresentations(previous, next) {
    if (!previous) return next;
    if (!next) return previous;
    const mergeUnique = (a = [], b = []) => Array.from(new Set([...(a ?? []), ...(b ?? [])]));
    return {
      normalizedText: previous.normalizedText ?? next.normalizedText ?? "",
      canonicalText: previous.canonicalText ?? next.canonicalText ?? "",
      tokens: mergeUnique(previous.tokens, next.tokens),
      tokenBigrams: mergeUnique(previous.tokenBigrams, next.tokenBigrams),
      tokenTrigrams: mergeUnique(previous.tokenTrigrams, next.tokenTrigrams),
      ngrams3: mergeUnique(previous.ngrams3, next.ngrams3),
      ngrams4: mergeUnique(previous.ngrams4, next.ngrams4),
      concepts: mergeUnique(previous.concepts, next.concepts),
      focusTokens: mergeUnique(previous.focusTokens, next.focusTokens),
      negated: Boolean(previous.negated || next.negated),
    };
  }

  _candidateEntries(queryReps, queryHash, options = {}) {
    const ids = new Set();
    for (let bandIndex = 0; bandIndex < this.bandCount; bandIndex += 1) {
      const key = makeBandKey(queryHash, bandIndex, this.wordsPerBand);
      const bucket = this.bandMaps[bandIndex].get(key);
      if (!bucket) continue;
      for (const id of bucket) ids.add(id);
    }
    this._collectTextCandidates(ids, this.textMap, queryReps.normalizedText);
    this._collectTextCandidates(ids, this.canonicalTextMap, queryReps.canonicalText);
    this._collectTermCandidates(ids, this.tokenMaps[3], queryReps.concepts, 12);
    this._collectTermCandidates(ids, this.tokenMaps[4], queryReps.focusTokens, 12);

    // Si hay filtros por tipo, ampliar candidatos con el índice de tipo.
    if (options.memoryTypes && options.memoryTypes.length > 0) {
      for (const type of options.memoryTypes) {
        const typeIds = this.typeIndex.get(type);
        if (!typeIds) continue;
        for (const id of typeIds) ids.add(id);
      }
    }

    if (ids.size === 0) {
      for (const id of this.entries.keys()) {
        ids.add(id);
        if (ids.size >= this.maxCandidates) break;
      }
    }

    const now = Date.now();
    return Array.from(ids, (id) => this.entries.get(id))
      .filter(Boolean)
      .filter((entry) => this._candidateFilter(entry, options, now));
  }

  _candidateFilter(entry, options, now) {
    // Descartar expiradas
    if (isExpired(entry, now)) return false;

    // Filtro por tipo de memoria
    if (options.memoryTypes && options.memoryTypes.length > 0) {
      if (!options.memoryTypes.includes(entry.memoryType)) return false;
    }

    // Exclusión por tipo
    if (options.excludeTypes && options.excludeTypes.length > 0) {
      if (options.excludeTypes.includes(entry.memoryType)) return false;
    }

    // Filtro temporal
    if (options.timeWindow && Number.isFinite(options.timeWindow)) {
      const age = now - (entry.createdAt || entry.lastAccessAt || now);
      if (age > options.timeWindow) return false;
    }

    // Calidad mínima
    if (options.minQuality && Number.isFinite(options.minQuality)) {
      if ((entry.quality ?? 0) < options.minQuality) return false;
    }

    // Filtro por fuente
    if (options.sourceFilter) {
      const filters = Array.isArray(options.sourceFilter) ? options.sourceFilter : [options.sourceFilter];
      if (!filters.includes(entry.source)) return false;
    }

    return true;
  }

  _collectTermCandidates(ids, map, terms, limit) {
    let seenTerms = 0;
    for (const term of terms) {
      if (seenTerms >= limit) break;
      seenTerms += 1;
      const bucket = map.get(term);
      if (!bucket) continue;
      for (const id of bucket) ids.add(id);
    }
  }

  _collectTextCandidates(ids, map, text) {
    const bucket = map.get(text);
    if (!bucket) return;
    for (const id of bucket) ids.add(id);
  }

  _computeDimensionScores(queryReps, queryHash, queryHypervector, entry) {
    const hashSim = 1 - hammingDistance(queryHash, entry.hash) / this.bitCount;
    const hvSim = similarity(queryHypervector, entry.hypervector);
    const entryReps = entry.representations ?? buildRepresentations(entry.text ?? "");
    const repSim = representationSimilarity(queryReps, entryReps);

    const now = Date.now();
    const quality = clamp(entry.quality / 10, 0, 1);
    const recency = temporalScore(entry, now);

    // Prototype similarity (from lexicon trainer)
    let protoSim = 0;
    let intentSim = 0;
    if (this.lexiconTrainer) {
      const conceptId = this.lexiconTrainer.resolveConcept(entry.text ?? "");
      if (conceptId) {
        protoSim = this.lexiconTrainer.prototypeSimilarity(queryHypervector, conceptId);
        intentSim = this.lexiconTrainer.intentSimilarity(entry.text ?? "", conceptId);
      }
    }

    return {
      hash: hashSim,
      hypervector: hvSim,
      concept: repSim.concept,
      prototype: protoSim,
      intent: intentSim,
      recency,
      quality,
      negation: repSim.negationMatch,
      phraseOverlap: phraseOverlapScore(queryReps, entryReps),
      wordOrder: wordOrderScore(queryReps, entryReps),
      entityMatch: entityMatchScore(queryReps, entryReps),
    };
  }

  _scoreFromDimScores(dimScores, entry, options = {}) {
    if (options.fastEval) {
      return 0.42 * dimScores.hash + 0.38 * dimScores.hypervector + 0.18 * dimScores.concept + 0.02 * dimScores.negation;
    }

    // Perfil de scoring según tipo de memoria e intent de query.
    const scoringProfile = options.queryIntent
      ? require("./query-intent").getScoringProfileForIntent(options.queryIntent, entry.memoryType)
      : getScoringProfile(entry.memoryType);

    // Si hay HyperAttention, mezclar pesos aprendidos con el perfil de tipo.
    let weightedScore = 0;
    if (this.attention) {
      const attentionWeights = this.attention.computeWeights(options.queryHypervector ?? entry.hypervector);
      for (const [dim, baseWeight] of Object.entries(scoringProfile)) {
        const learnedWeight = attentionWeights.get(dim) ?? baseWeight;
        // 70% perfil de tipo + 30% atención aprendida (más estable que 20/80).
        const weight = 0.7 * baseWeight + 0.3 * learnedWeight;
        weightedScore += (dimScores[dim] ?? 0) * weight;
      }
    } else {
      for (const [dim, weight] of Object.entries(scoringProfile)) {
        weightedScore += (dimScores[dim] ?? 0) * weight;
      }
    }

    // Boost por coincidencia de tipo con el intent de la query.
    if (options.queryIntent) {
      const typeBoost = getTypeBoostForIntent(options.queryIntent, entry.memoryType);
      weightedScore += typeBoost;
    }

    return clamp(weightedScore, 0, 1);
  }

  _scoreCandidate(queryReps, queryHash, queryHypervector, entry, options = {}) {
    const dimScores = options.dimScores
      ? { ...options.dimScores }
      : this._computeDimensionScores(queryReps, queryHash, queryHypervector, entry);
    return this._scoreFromDimScores(dimScores, entry, {
      ...options,
      queryHypervector,
    });
  }

  query(input, options = {}) {
    let text = typeof input === "string" ? input : JSON.stringify(input);
    // Canonicalizar query con trainer para matching mejorado
    if (this.lexiconTrainer) {
      const canonMap = this.lexiconTrainer._canonMap ?? this.lexiconTrainer.conceptMap;
      const canonicalized = this._canonicalizeWithMap(text, canonMap);
      if (canonicalized && canonicalized !== text) {
        text = canonicalized;
      }
    }

    // Detectar intención y tipos objetivo de memoria.
    const mergedOptions = buildQueryOptions(text, options);

    const queryReps = buildRepresentations(text);
    const queryHash = this.encodeText(text);
    const queryHypervector = prototypeVectorFromText(text, this.hyperDim, this.seed);

    const candidates = this._candidateEntries(queryReps, queryHash, mergedOptions);

    // Calcular dimension scores una sola vez por candidato.
    const dimScoresList = candidates.map((entry) => ({
      entry,
      dimScores: this._computeDimensionScores(queryReps, queryHash, queryHypervector, entry),
    }));

    // Normalización z-score por dimensión cuando hay suficientes candidatos.
    const normalize =
      mergedOptions.normalizeDimensions !== false && dimScoresList.length >= 10;
    if (normalize) {
      const dims = ["hash", "hypervector", "concept", "recency", "quality", "phraseOverlap", "wordOrder", "entityMatch"];
      for (const dim of dims) {
        const values = dimScoresList.map((d) => d.dimScores[dim] ?? 0);
        const normalized = zNormalize(values);
        for (let i = 0; i < dimScoresList.length; i += 1) {
          dimScoresList[i].dimScores[dim] = normalized[i];
        }
      }
    }

    let scored = dimScoresList
      .map(({ entry, dimScores }) => ({
        entry,
        hashDistance: hammingDistance(queryHash, entry.hash),
        score: this._scoreFromDimScores(dimScores, entry, {
          ...mergedOptions,
          queryHypervector,
          fastEval: mergedOptions.fastEval,
        }),
      }))
      .sort((a, b) => b.score - a.score);

    // Two-pass retrieval: si top-1 es débil, expandir candidatos por concepto/alias
    const top1Threshold = mergedOptions.secondPassThreshold ?? 0.72;
    const shouldExpand =
      !mergedOptions.disableSecondPass &&
      this.lexiconTrainer &&
      (scored.length === 0 || (scored[0]?.score ?? 0) < top1Threshold);
    if (shouldExpand) {
      const conceptCandidates = new Set();
      const queryConcept = this.lexiconTrainer.resolveConcept(text);
      if (queryConcept && this.conceptIndex.has(queryConcept)) {
        for (const id of this.conceptIndex.get(queryConcept)) conceptCandidates.add(id);
      }
      // Expandir por frases detectadas en query
      const phrases = this.lexiconTrainer.phraseIndex.extractPhrases(text);
      for (const phrase of phrases) {
        const best = this.lexiconTrainer.phraseIndex.bestConcept(phrase);
        if (best?.conceptId && this.conceptIndex.has(best.conceptId)) {
          for (const id of this.conceptIndex.get(best.conceptId)) conceptCandidates.add(id);
        }
      }
      const existingIds = new Set(scored.map((s) => s.entry?.id).filter(Boolean));
      for (const id of conceptCandidates) {
        if (existingIds.has(id)) continue;
        const entry = this.entries.get(id);
        if (!entry || this._candidateFilter(entry, mergedOptions, Date.now())) continue;
        const dimScores = this._computeDimensionScores(queryReps, queryHash, queryHypervector, entry);
        scored.push({
          entry,
          hashDistance: hammingDistance(queryHash, entry.hash),
          score: this._scoreFromDimScores(dimScores, entry, {
            ...mergedOptions,
            queryHypervector,
          }),
        });
      }
      scored.sort((a, b) => b.score - a.score);
    }

    scored.splice(mergedOptions.topK ?? 5);

    if (scored[0]) {
      scored[0].entry.lastAccessAt = Date.now();
      scored[0].entry.accessCount += 1;
      this._touchEviction(scored[0].entry);
    }

    return {
      queryHash,
      queryHypervector,
      queryIntent: mergedOptions.queryIntent,
      candidates: scored,
      confidence: this._confidence(scored),
    };
  }

  _confidence(scored) {
    if (scored.length === 0) return 0;
    if (scored.length === 1) return clamp(scored[0].score, 0, 1);
    const margin = scored[0].score - scored[1].score;
    return clamp(0.5 * scored[0].score + 0.5 * margin, 0, 1);
  }

  learnFromFeedback(input, reward = 0, metadata = {}) {
    const text = typeof input === "string" ? input : JSON.stringify(input);
    const signature = this.encodeText(text);
    const rate = reward >= 0 ? 0.05 : 0.03;
    for (let i = 0; i < this.bitCount; i += 1) {
      const bit = (signature[i >>> 5] >>> (i & 31)) & 1;
      this.bitBias[i] += rate * reward * (bit ? 1 : -1);
      this.bitBias[i] = clamp(this.bitBias[i], -4, 4);
    }
    // Si hay lexiconTrainer y feedback negativo, aplicar contraste
    if (this.lexiconTrainer && reward < 0) {
      const selectedId = metadata.selectedConceptId ?? null;
      const rejectedIds = metadata.rejectedConceptIds ?? [];
      if (selectedId) {
        this.lexiconTrainer.applyOnlineFeedback(text, selectedId, rejectedIds);
      }
    }
  }

  updateEntry(id, patch = {}) {
    const entry = this.entries.get(id);
    if (!entry) return null;
    this.unindexEntry(entry);
    if (patch.payload !== undefined) entry.payload = patch.payload;
    if (patch.metadata) entry.metadata = { ...entry.metadata, ...patch.metadata };
    if (patch.quality !== undefined) entry.quality = clamp(patch.quality, 0, 10);
    if (patch.hash) entry.hash = patch.hash;
    if (patch.hypervector) entry.hypervector = patch.hypervector;
    if (patch.payload !== undefined) {
      const payloadText = stringifyPayload(entry.payload);
      entry.payloadRepresentations = payloadText ? buildRepresentations(payloadText) : null;
    }
    entry.updatedAt = Date.now();
    this.indexEntry(entry);
    this._touchEviction(entry);
    return entry;
  }

  _evictionPriority(entry) {
    if (!entry) return Number.NEGATIVE_INFINITY;
    const quality = Number(entry.quality ?? 0);
    const access = Number(entry.lastAccessAt ?? 0);
    const typePriority = getEvictionPriority(entry.memoryType);
    const expiredPenalty = isExpired(entry) ? -1e15 : 0;
    // Menor prioridad = candidato a expulsión.
    // Memorias expiradas primero, luego tipo de menor prioridad, luego calidad y acceso.
    return expiredPenalty + typePriority * quality * 1e12 + access;
  }

  _heapPush(node) {
    const heap = this._evictionHeap;
    heap.push(node);
    let idx = heap.length - 1;
    while (idx > 0) {
      const parent = Math.floor((idx - 1) / 2);
      if (heap[parent].priority <= heap[idx].priority) break;
      [heap[parent], heap[idx]] = [heap[idx], heap[parent]];
      idx = parent;
    }
  }

  _heapPop() {
    const heap = this._evictionHeap;
    if (heap.length === 0) return null;
    const root = heap[0];
    const last = heap.pop();
    if (heap.length > 0 && last) {
      heap[0] = last;
      let idx = 0;
      while (true) {
        const left = idx * 2 + 1;
        const right = idx * 2 + 2;
        let smallest = idx;
        if (left < heap.length && heap[left].priority < heap[smallest].priority) smallest = left;
        if (right < heap.length && heap[right].priority < heap[smallest].priority) smallest = right;
        if (smallest === idx) break;
        [heap[idx], heap[smallest]] = [heap[smallest], heap[idx]];
        idx = smallest;
      }
    }
    return root;
  }

  _touchEviction(entry) {
    if (!entry?.id) return;
    this._evictionVersion += 1;
    entry._evictionVersion = this._evictionVersion;
    this._heapPush({
      id: entry.id,
      version: entry._evictionVersion,
      priority: this._evictionPriority(entry),
    });
  }

  _enforceCapacity() {
    const now = Date.now();
    // Primero eliminar entradas expiradas, incluso si no estamos al límite.
    const expiredIds = [];
    for (const [id, entry] of this.entries) {
      if (isExpired(entry, now)) expiredIds.push(id);
    }
    for (const id of expiredIds) {
      const victim = this.entries.get(id);
      if (victim) {
        this.unindexEntry(victim);
        this.entries.delete(id);
      }
    }

    while (this.entries.size > this.maxEntries) {
      const node = this._heapPop();
      if (!node) break;
      const victim = this.entries.get(node.id);
      if (!victim) continue;
      if (victim._evictionVersion !== node.version) continue;
      this.unindexEntry(victim);
      this.entries.delete(victim.id);
    }
  }

  snapshot() {
    const typeCounts = {};
    for (const entry of this.entries.values()) {
      typeCounts[entry.memoryType] = (typeCounts[entry.memoryType] ?? 0) + 1;
    }
    return {
      bitCount: this.bitCount,
      bandBits: this.bandBits,
      hyperDim: this.hyperDim,
      profile: this.profile,
      size: this.entries.size,
      typeCounts,
    };
  }

  clear() {
    this.entries.clear();
    this._evictionHeap = [];
    this.conceptIndex.clear();
    this.typeIndex.clear();
    this.sourceMap.clear();
    this.bandMaps.forEach((map) => map.clear());
    this.textMap.clear();
    this.canonicalTextMap.clear();
    this.tokenMaps.forEach((map) => map.clear());
    this.payloadTokenMaps.forEach((map) => map.clear());
  }

  allEntries() {
    return Array.from(this.entries.values());
  }

  bucketStats() {
    const bandSizes = this.bandMaps.map(m => m.size);
    const textMapSize = this.textMap.size;
    const totalEntries = this.entries.size;
    const typeCounts = {};
    for (const entry of this.entries.values()) {
      typeCounts[entry.memoryType] = (typeCounts[entry.memoryType] ?? 0) + 1;
    }
    return {
      totalEntries,
      bands: this.bandMaps.length,
      bandSizes,
      occupiedBuckets: bandSizes.reduce((a, b) => a + b, 0),
      textMapSize,
      conceptIndexSize: this.conceptIndex.size,
      typeIndexSize: this.typeIndex.size,
      sourceMapSize: this.sourceMap.size,
      typeCounts,
    };
  }

  whenReady() {
    return Promise.resolve();
  }
}

module.exports = {
  AssociativeMemory,
  bindVectors,
  bundleVectors,
  cloneVector,
  prototypeVectorFromText,
  vectorFromSeed,
};
