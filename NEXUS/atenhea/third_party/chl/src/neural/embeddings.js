/**
 * Embeddings densos sin dependencias de tensores.
 * 
 * Técnica: TF-IDF ponderado sobre tokens + character n-gramas (3 y 4).
 * Vocabulario congelado tras fase de build para consistencia query-entry.
 * Soporta canonicalización por léxico (concept pairs, phrase pairs).
 * Penalización por mismatch de negación.
 * 
 * Sin dependencias externas. Sin tensores. Sin GPUs.
 */

const { tokenize, charNgrams, normalizeText } = require("../utils");
const { HyperAttentionContext } = require("../hyperattention");
const { LexiconTrainer } = require("../lexiconLearner");

const NEGATION_TOKENS = new Set(["no", "sin", "nunca", "jamas", "tampoco", "nadie", "nada", "ningun", "ninguno", "ninguna"]);
const PRESERVE_TOKENS = NEGATION_TOKENS;

class Vocabulary {
  constructor() {
    this._tokenFreq = new Map();
    this._ngram3Freq = new Map();
    this._ngram4Freq = new Map();
    this._docCount = 0;
    this._idfCache = new Map();
    this._dirty = true;
    this._frozen = false;
  }

  addDocument(text) {
    if (this._frozen) return;
    const norm = normalizeText(String(text ?? ""));
    const rawTokens = tokenize(norm);
    const tokens = new Set(rawTokens.filter((t) => t.length >= 3 || PRESERVE_TOKENS.has(t)));
    const ngrams3 = new Set(charNgrams(norm, 3));
    const ngrams4 = new Set(charNgrams(norm, 4));

    for (const t of tokens) this._tokenFreq.set(t, (this._tokenFreq.get(t) ?? 0) + 1);
    for (const g of ngrams3) this._ngram3Freq.set(g, (this._ngram3Freq.get(g) ?? 0) + 1);
    for (const g of ngrams4) this._ngram4Freq.set(g, (this._ngram4Freq.get(g) ?? 0) + 1);

    this._docCount += 1;
    this._dirty = true;
  }

  freeze() {
    this._rebuildIdf();
    this._frozen = true;
  }

  _rebuildIdf() {
    if (!this._dirty) return;
    this._idfCache.clear();
    const N = Math.max(1, this._docCount);
    for (const [token, df] of this._tokenFreq) {
      this._idfCache.set("t:" + token, Math.log((N + 1) / (df + 1)) + 1);
    }
    for (const [gram, df] of this._ngram3Freq) {
      this._idfCache.set("g3:" + gram, Math.log((N + 1) / (df + 1)) + 1);
    }
    for (const [gram, df] of this._ngram4Freq) {
      this._idfCache.set("g4:" + gram, Math.log((N + 1) / (df + 1)) + 1);
    }
    this._dirty = false;
  }

  idf(featureKey) {
    this._rebuildIdf();
    return this._idfCache.get(featureKey) ?? 1.0;
  }

  get docCount() { return this._docCount; }
  get frozen() { return this._frozen; }
}

function canonicalize(text, conceptMap, phraseMap) {
  let result = normalizeText(String(text ?? ""));
  if (phraseMap && phraseMap.size > 0) {
    for (const [from, to] of phraseMap) {
      const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      result = result.replace(new RegExp("\\b" + escaped + "\\b", "g"), to);
    }
  }
  if (conceptMap && conceptMap.size > 0) {
    const tokens = tokenize(result);
    const expanded = [];
    for (const t of tokens) {
      expanded.push(t);
      const canonical = conceptMap.get(t);
      if (canonical && canonical !== t) expanded.push(canonical);
    }
    result = expanded.join(" ");
  }
  return result;
}

function isNegated(text) {
  return tokenize(normalizeText(String(text ?? ""))).some((t) => NEGATION_TOKENS.has(t));
}

class DocumentVectorizer {
  constructor(vocabulary, options = {}) {
    this.vocab = vocabulary;
    this.conceptMap = options.conceptMap ?? null;
    this.phraseMap = options.phraseMap ?? null;
  }

  vectorize(text) {
    const raw = String(text ?? "");
    const norm = canonicalize(raw, this.conceptMap, this.phraseMap);
    const rawTokens = tokenize(norm);
    const tokens = rawTokens.filter((t) => t.length >= 3 || PRESERVE_TOKENS.has(t));
    const ngrams3 = charNgrams(norm, 3);
    const ngrams4 = charNgrams(norm, 4);

    const vec = new Map();
    const add = (key, count) => vec.set(key, (vec.get(key) ?? 0) + count);

    for (const t of tokens) {
      add("t:" + t, this.vocab.idf("t:" + t));
    }

    if (rawTokens.some((t) => t === "no")) add("t:no", 2.0);
    if (rawTokens.some((t) => t === "sin")) add("t:sin", 2.0);

    for (const g of ngrams3) add("g3:" + g, 0.6 * this.vocab.idf("g3:" + g));
    for (const g of ngrams4) add("g4:" + g, 0.4 * this.vocab.idf("g4:" + g));

    return {
      features: vec,
      featureCount: vec.size,
      negated: isNegated(raw),
    };
  }

  updateLexicon(conceptMap, phraseMap) {
    this.conceptMap = conceptMap;
    this.phraseMap = phraseMap;
  }
}

function dotProduct(vecA, vecB) {
  let dot = 0;
  const [small, large] = vecA.size <= vecB.size ? [vecA, vecB] : [vecB, vecA];
  for (const [key, weightA] of small) {
    const weightB = large.get(key);
    if (weightB !== undefined) dot += weightA * weightB;
  }
  return dot;
}

class EmbeddingIndex {
  constructor(options = {}) {
    this.vocab = new Vocabulary();
    this.conceptMap = options.conceptMap ?? null;
    this.phraseMap = options.phraseMap ?? null;
    this.vectorizer = new DocumentVectorizer(this.vocab, {
      conceptMap: this.conceptMap,
      phraseMap: this.phraseMap,
    });
    this.entries = new Map();
    this.maxEntries = options.maxEntries ?? 20000;
    this.negationMismatchPenalty = options.negationMismatchPenalty ?? 0.5;
    this._built = false;
    // HyperAttention opcional
    this.attention = options.attention ?? null;
    // LexiconTrainer opcional
    this.lexiconTrainer = options.lexiconTrainer ?? null;
  }

  async index(text, payload = null, metadata = {}) {
    // Si no está built, acumular en vocab
    if (!this._built) {
      this.vocab.addDocument(text);
    }

    const vecResult = this.vectorizer.vectorize(text);
    const id = metadata.id ?? `idx-${this.entries.size}-${Date.now().toString(36)}`;

    const entry = {
      id, text, payload,
      metadata: { ...metadata, quality: metadata.quality ?? 5 },
      sparseVec: vecResult.features,
      negated: vecResult.negated,
      accessCount: 0,
      lastAccessAt: Date.now(),
    };

    this.entries.set(id, entry);

    while (this.entries.size > this.maxEntries) {
      const first = this.entries.keys().next().value;
      this.entries.delete(first);
    }

    return entry;
  }

  /**
   * Congela el vocabulario y re-vectoriza todas las entries.
   * Debe llamarse después de indexar todos los documentos base.
   * Después de build(), nuevos index() usan el vocabulario congelado.
   */
  build() {
    this.vocab.freeze();
    this._built = true;
    // Re-vectorizar entries con vocabulario congelado
    for (const [, entry] of this.entries) {
      const vr = this.vectorizer.vectorize(entry.text);
      entry.sparseVec = vr.features;
      entry.negated = vr.negated;
    }
  }

  async query(text, options = {}) {
    const topK = options.topK ?? 5;
    const vecResult = this.vectorizer.vectorize(text);
    const queryNegated = vecResult.negated;

    // Pre-computar hypervector de query para scoring extendido
    const { prototypeVectorFromText } = require("../hypervector");
    const queryHV = this.lexiconTrainer || this.attention
      ? prototypeVectorFromText(text, this.hyperDim ?? 256, 0)
      : null;
    
    const scored = [];
    for (const [id, entry] of this.entries) {
      let sim = dotProduct(vecResult.features, entry.sparseVec);
      if (queryNegated !== entry.negated) {
        sim *= this.negationMismatchPenalty;
      }
      const ageMs = Math.max(0, Date.now() - (entry.lastAccessAt ?? 0));
      const recency = Math.exp(-ageMs / (30 * 60 * 1000));
      const quality = Math.max(0, Math.min(1, (entry.metadata.quality ?? 5) / 10));
      
      let score = sim + 0.0001 * recency + 0.00005 * quality;
      
      // Scoring extendido con LexiconTrainer
      if (this.lexiconTrainer && queryHV) {
        const conceptId = this.lexiconTrainer.resolveConcept(entry.text ?? "");
        if (conceptId) {
          const protoSim = this.lexiconTrainer.prototypeSimilarity(queryHV, conceptId);
          const intentSim = this.lexiconTrainer.intentSimilarity(entry.text ?? "", conceptId);
          score += 0.08 * protoSim + 0.06 * intentSim;
        }
      }
      
      scored.push({ entry, similarity: sim, score });
    }

    scored.sort((a, b) => b.score - a.score);
    scored.splice(topK);

    if (scored[0]) {
      scored[0].entry.accessCount += 1;
      scored[0].entry.lastAccessAt = Date.now();
    }

    const confidence = scored.length > 0
      ? (scored.length === 1
          ? Math.min(1, scored[0].similarity / 10)
          : Math.max(0, Math.min(1, scored[0].similarity / Math.max(0.001, scored[0].similarity + (scored[1]?.similarity ?? 0)))))
      : 0;

    return { queryVec: vecResult.features, candidates: scored, confidence, topK };
  }

  updateLexicon(conceptMap, phraseMap) {
    this.conceptMap = conceptMap;
    this.phraseMap = phraseMap;
    this.vectorizer.updateLexicon(conceptMap, phraseMap);
  }

  snapshot() {
    return {
      type: "neural-embeddings",
      vocabSize: this.vocab._tokenFreq.size,
      entryCount: this.entries.size,
      maxEntries: this.maxEntries,
      built: this._built,
    };
  }

  clear() {
    this.vocab = new Vocabulary();
    this.vectorizer = new DocumentVectorizer(this.vocab);
    this.entries.clear();
    this._built = false;
  }

  get size() { return this.entries.size; }
}

module.exports = {
  Vocabulary, DocumentVectorizer, EmbeddingIndex,
  dotProduct, canonicalize, isNegated, PRESERVE_TOKENS, NEGATION_TOKENS,
};
