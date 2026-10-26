/**
 * HyperEmbed — Embeddings dinámicos por Hyperdimensional Computing
 * 
 * Principio matemático:
 * Cada concepto es un vector binario de 10,000 dimensiones.
 * Las operaciones de binding (XOR), bundling (suma umbralizada) y
 * permutation (rotación) forman un álgebra completa que permite
 * representar composición, secuencia y asociación sin entrenamiento.
 * 
 * A diferencia de los transformers:
 * - No hay backpropagation
 * - No hay matrices de pesos
 * - No hay GPUs
 * - Los embeddings evolucionan dinámicamente con cada nuevo dato
 * 
 * Fundamentos:
 * - Binding: A ⊕ B representa la asociación "A con B". Es reversible: (A ⊕ B) ⊕ B = A
 * - Bundling: [A + B + C] representa el conjunto {A, B, C}. Robusto al ruido.
 * - Permutation: ρ(A) representa "siguiente de A". Permite codificar secuencias.
 * 
 * Capacidad: a 10,000 bits, la probabilidad de colisión entre dos vectores
 * aleatorios es 2^(-5000) ≈ 10^(-1500). Esencialmente infinita para uso práctico.
 */

const path = require("node:path");
const fs = require("node:fs");
const { stableHash32, tokenize, normalizeText } = require("../utils");

const DIM = 10000;
const WORD_SIZE = 32;
const VEC_WORDS = 320; // Padded to 320 words to align with native SIMD memory structure
const BUNDLE_THRESHOLD = 0.5; // Para bundling: mayoría simple
const LEARNING_RATE = 0.05;   // Tasa de adaptación de vectores dinámicos

// ─── Operaciones fundamentales HDC ────────────────────────

function emptyVector() {
  return new Uint32Array(VEC_WORDS);
}

function randomVector(seed) {
  const vec = emptyVector();
  let state = stableHash32(String(seed), 0x9e3779b9);
  for (let i = 0; i < VEC_WORDS; i++) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    vec[i] = state >>> 0;
  }
  return vec;
}

function cloneVector(vec) {
  return new Uint32Array(vec);
}

/**
 * Binding: XOR bit a bit.
 * Principal operación de asociación. Reversible: bind(bind(A,B), B) = A.
 */
function bind(a, b) {
  const result = emptyVector();
  for (let i = 0; i < VEC_WORDS; i++) {
    result[i] = (a[i] ^ b[i]) >>> 0;
  }
  return result;
}

/**
 * Bundling: suma con umbral de mayoría.
 * Representa un conjunto de vectores. Robusto: añadir ruido no cambia el resultado.
 */
function bundle(vectors) {
  if (vectors.length === 0) return emptyVector();
  
  // Contar bits en cada posición
  const counts = new Int32Array(DIM);
  for (const vec of vectors) {
    for (let w = 0; w < VEC_WORDS; w++) {
      const word = vec[w];
      const base = w * WORD_SIZE;
      for (let b = 0; b < WORD_SIZE; b++) {
        counts[base + b] += (word & (1 << b)) ? 1 : -1;
      }
    }
  }
  
  // Umbralizar: mayoría simple
  const result = emptyVector();
  for (let b = 0; b < DIM; b++) {
    if (counts[b] >= 0) {
      result[b >>> 5] |= 1 << (b & 31);
    }
  }
  return result;
}

/**
 * Bundle ponderado: cada vector contribuye con su peso.
 */
function bundleWeighted(vectors, weights) {
  if (vectors.length === 0) return emptyVector();
  
  const counts = new Float64Array(DIM);
  for (let vi = 0; vi < vectors.length; vi++) {
    const vec = vectors[vi];
    const weight = weights[vi] ?? 1;
    for (let w = 0; w < VEC_WORDS; w++) {
      const word = vec[w];
      const base = w * WORD_SIZE;
      for (let b = 0; b < WORD_SIZE; b++) {
        counts[base + b] += (word & (1 << b)) ? weight : -weight;
      }
    }
  }
  
  const result = emptyVector();
  for (let b = 0; b < DIM; b++) {
    if (counts[b] >= 0) {
      result[b >>> 5] |= 1 << (b & 31);
    }
  }
  return result;
}

/**
 * Permutation: rotación circular de shiftBits.
 * Representa orden/secuencia. ρ^n(A) = "n-ésima posición de A".
 */
function permute(vec, shiftBits) {
  const totalBits = VEC_WORDS * WORD_SIZE;
  const shift = ((shiftBits % totalBits) + totalBits) % totalBits;
  if (shift === 0) return cloneVector(vec);
  
  const result = emptyVector();
  for (let b = 0; b < totalBits; b++) {
    const srcBit = (b - shift + totalBits) % totalBits;
    if ((vec[srcBit >>> 5] & (1 << (srcBit & 31))) !== 0) {
      result[b >>> 5] |= 1 << (b & 31);
    }
  }
  return result;
}

/**
 * Cosine similarity entre vectores binarios: (DIM - 2*HammingDist) / DIM
 * Normalizado a [-1, 1]: 1 = idénticos, 0 = ortogonales, -1 = opuestos
 */
function similarity(a, b) {
  let matches = 0;
  for (let i = 0; i < VEC_WORDS; i++) {
    const diff = ~(a[i] ^ b[i]);
    // popcount inline
    const v = diff - ((diff >>> 1) & 0x55555555);
    const y = (v & 0x33333333) + ((v >>> 2) & 0x33333333);
    matches += (((y + (y >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
  }
  return (2 * matches - DIM) / DIM;
}

/**
 * Protege un vector contra degradación: renormaliza a ~50% densidad.
 */
function normalize(vec) {
  let ones = 0;
  for (let i = 0; i < VEC_WORDS; i++) {
    const v = vec[i];
    const y = (v & 0x33333333) + ((v >>> 2) & 0x33333333);
    ones += (((y + (y >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
  }
  
  // Si la densidad se desvía mucho de 50%, regenerar
  if (ones < DIM * 0.3 || ones > DIM * 0.7) {
    const fresh = randomVector(Date.now() + ones);
    return bind(vec, fresh); // Mezclar con ruido fresco para restaurar densidad
  }
  return vec;
}

// ─── Codificación de estructuras lingüísticas ─────────────

/**
 * Codifica una secuencia de tokens como un hipervector.
 * Secuencia = bundle(ρ^0(tok1), ρ^1(tok2), ρ^2(tok3), ...)
 * La permutación captura el orden sin perder composicionalidad.
 */
function encodeSequence(tokenVectors) {
  const permuted = tokenVectors.map((v, i) => permute(v, i * 7));
  return bundle(permuted);
}

/**
 * Codifica un par sujeto-verbo-objeto como:
 * bind(bind(subj, verb), obj)
 * Esto permite recuperar cualquier componente:
 * unbind(result, verb) ≈ bind(subj, obj)
 */
function encodeTriple(subjVec, verbVec, objVec) {
  return bind(bind(subjVec, verbVec), objVec);
}

/**
 * Decodifica: dado un encoding de triple y un componente, recupera los otros dos.
 * unbind(tripleEncoding, verbVec) ≈ bind(subjVec, objVec) = "sujeto-objeto"
 */
function unbind(bound, key) {
  return bind(bound, key);
}

// ─── Motor de embeddings dinámicos ────────────────────────

class JSHyperEmbed {
  constructor(options = {}) {
    this.dim = options.dim ?? DIM;
    this.vectors = new Map();     // token → hypervector
    this.coocCounts = new Map();  // "token1|token2" → count
    this.learningRate = options.learningRate ?? LEARNING_RATE;
    this._nextSeed = options.seed ?? 42;
    this._documents = [];
  }

  /**
   * Obtiene o crea el hipervector para un token.
   * Los vectores nuevos son aleatorios. Los existentes evolucionan.
   */
  getVector(token) {
    if (!token) return randomVector(this._nextSeed++);
    
    let vec = this.vectors.get(token);
    if (!vec) {
      vec = randomVector(this._nextSeed++);
      this.vectors.set(token, vec);
    }
    return vec;
  }

  /**
   * Codifica un texto completo en un hipervector.
   * 
   * Estrategia:
   * 1. Cada token → su hipervector
   * 2. Secuencia = encodeSequence(tokenVectors) → captura orden
   * 3. N-gramas de conceptos: bind de pares de tokens consecutivos
   * 4. Bundle final: [secuencia + Σ bind(t_i, t_{i+1})]
   * 
   * Esto captura tanto bag-of-words como relaciones binarias.
   */
  encode(text) {
    const tokens = tokenize(normalizeText(String(text ?? "")));
    if (tokens.length === 0) return randomVector(Date.now());
    
    const tokenVectors = tokens.map((t) => this.getVector(t));
    
    // Secuencia con orden: ρ^i(tok_i)
    const sequenceVec = encodeSequence(tokenVectors);
    
    // Bigramas: bind(t_i, t_{i+1}) captura relaciones adyacentes
    const bigramVectors = [];
    for (let i = 0; i < tokens.length - 1; i++) {
      if (tokens[i].length > 2 && tokens[i + 1].length > 2) {
        bigramVectors.push(bind(tokenVectors[i], tokenVectors[i + 1]));
      }
    }
    
    // Trigramas: bind(bind(t_i, t_{i+1}), t_{i+2}) para sujeto-verbo-objeto
    const trigramVectors = [];
    for (let i = 0; i < tokens.length - 2; i++) {
      if (tokens[i].length > 2 && tokens[i + 1].length > 2 && tokens[i + 2].length > 2) {
        trigramVectors.push(encodeTriple(tokenVectors[i], tokenVectors[i + 1], tokenVectors[i + 2]));
      }
    }
    
    // Bundle final: secuencia + bigramas + trigramas
    const allVectors = [sequenceVec, ...bigramVectors, ...trigramVectors];
    return bundle(allVectors);
  }

  /**
   * Aprendizaje dinámico: actualiza los vectores de tokens que co-ocurren.
   * 
   * Principio: si dos tokens aparecen juntos frecuentemente,
   * sus vectores se vuelven más similares (se "atraen").
   * 
   * Mecanismo: para cada par de tokens en el texto,
   * actualizar token_i ← token_i + learningRate * token_j
   * usando bundling ponderado.
   */
  learn(text) {
    const tokens = tokenize(normalizeText(String(text ?? "")));
    const contentTokens = tokens.filter((t) => t.length > 2);
    
    // Acumular co-ocurrencias
    for (let i = 0; i < contentTokens.length; i++) {
      for (let j = i + 1; j < Math.min(i + 5, contentTokens.length); j++) {
        const a = contentTokens[i];
        const b = contentTokens[j];
        if (a === b) continue;
        
        const key = a < b ? `${a}|${b}` : `${b}|${a}`;
        this.coocCounts.set(key, (this.coocCounts.get(key) ?? 0) + 1);
      }
    }
    
    // Aplicar aprendizaje: mover vectores de tokens co-ocurrentes
    const processed = new Set();
    
    for (let i = 0; i < contentTokens.length; i++) {
      for (let j = i + 1; j < Math.min(i + 3, contentTokens.length); j++) {
        const a = contentTokens[i];
        const b = contentTokens[j];
        if (a === b) continue;
        
        const pairKey = `${a}|${b}`;
        if (processed.has(pairKey)) continue;
        processed.add(pairKey);
        
        const count = this.coocCounts.get(a < b ? `${a}|${b}` : `${b}|${a}`) ?? 0;
        const strength = Math.min(1, count / 10) * this.learningRate;
        
        // Mover a hacia b y b hacia a (atracción mutua)
        const va = this.getVector(a);
        const vb = this.getVector(b);
        
        const newVa = bundleWeighted([va, vb], [1 - strength, strength]);
        const newVb = bundleWeighted([vb, va], [1 - strength, strength]);
        
        this.vectors.set(a, normalize(newVa));
        this.vectors.set(b, normalize(newVb));
      }
    }
  }

  /**
   * Similitud semántica entre dos textos usando sus hipervectores.
   */
  textSimilarity(textA, textB) {
    const vecA = this.encode(textA);
    const vecB = this.encode(textB);
    return similarity(vecA, vecB);
  }

  index(id, text) {
    const docId = String(id ?? "");
    const docText = String(text ?? "");
    this.learn(docText);
    this._documents.push({ id: docId, text: docText, vec: this.encode(docText) });
  }

  indexBatch(items) {
    if (!Array.isArray(items) || items.length === 0) return;
    for (const it of items) this.index(it?.id, it?.text);
  }

  query(queryText, topK = 5) {
    const q = this.encode(String(queryText ?? ""));
    const scored = this._documents.map((d) => ({
      id: d.id,
      text: d.text,
      similarity: similarity(q, d.vec),
    }));
    scored.sort((a, b) => b.similarity - a.similarity);
    return scored.slice(0, Math.max(0, topK | 0));
  }

  clearIndex() {
    this._documents = [];
  }

  save(filePath) {
    const payload = {
      kind: "hyperembed-js",
      dim: this.dim,
      learningRate: this.learningRate,
      nextSeed: this._nextSeed,
      vectors: Array.from(this.vectors.entries()).map(([token, vec]) => [token, Array.from(vec)]),
      coocCounts: Array.from(this.coocCounts.entries()),
      documents: this._documents.map((d) => ({ id: d.id, text: d.text, vec: Array.from(d.vec) })),
    };
    fs.writeFileSync(filePath, JSON.stringify(payload));
    return true;
  }

  load(filePath) {
    const raw = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (!raw || raw.kind !== "hyperembed-js") return false;
    this.dim = raw.dim ?? DIM;
    this.learningRate = raw.learningRate ?? LEARNING_RATE;
    this._nextSeed = raw.nextSeed ?? 42;
    this.vectors = new Map((raw.vectors ?? []).map(([t, vec]) => [t, Uint32Array.from(vec)]));
    this.coocCounts = new Map(raw.coocCounts ?? []);
    this._documents = (raw.documents ?? []).map((d) => ({
      id: String(d.id ?? ""),
      text: String(d.text ?? ""),
      vec: Uint32Array.from(d.vec ?? []),
    }));
    return true;
  }

  /**
   * Recupera los conceptos más similares a un vector dado.
   */
  nearestNeighbors(vector, k = 10) {
    const results = [];
    for (const [token, vec] of this.vectors) {
      if (token.length < 3) continue;
      results.push({ token, sim: similarity(vector, vec) });
    }
    results.sort((a, b) => b.sim - a.sim);
    return results.slice(0, k);
  }

  snapshot() {
    return {
      type: "hyperembed",
      dim: this.dim,
      vocabularySize: this.vectors.size,
      coocPairs: this.coocCounts.size,
      learningRate: this.learningRate,
    };
  }
}

function loadNativeHyperEmbed() {
  try {
    // build/Release/hyperembed_addon.node
    const addonPath = path.resolve(__dirname, "..", "..", "build", "Release", "hyperembed_addon.node");
    const addon = require(addonPath);
    return addon?.NativeHyperEmbed ?? null;
  } catch {
    return null;
  }
}

class NativeHyperEmbed {
  constructor() {
    const NativeCtor = loadNativeHyperEmbed();
    if (!NativeCtor) {
      throw new Error("Native HyperEmbed addon not found. Build with: node scripts/build-hyperembed.js");
    }
    this._native = new NativeCtor();
    this.dim = DIM;
    this.learningRate = LEARNING_RATE;
    this.vectors = { size: 0 };
    this.coocCounts = { size: 0 };
  }

  _syncSnapshot() {
    const snap = this._native.snapshot();
    this.vectors.size = snap?.vocabSize ?? 0;
    this.coocCounts.size = snap?.coocPairs ?? 0;
    return snap;
  }

  learn(text) {
    this._native.learn(String(text ?? ""));
    this._syncSnapshot();
  }

  encode(text) {
    return Uint32Array.from(this._native.encode(String(text ?? "")));
  }

  textSimilarity(textA, textB) {
    return this._native.similarity(String(textA ?? ""), String(textB ?? ""));
  }

  nearestNeighbors(vectorOrText, k = 10) {
    const input = typeof vectorOrText === "string" ? vectorOrText : "";
    return this._native.neighbors(input, k).map((token) => ({ token, sim: NaN }));
  }

  index(id, text) {
    this._native.index(String(id ?? ""), String(text ?? ""));
    this._syncSnapshot();
  }

  indexBatch(items) {
    if (!Array.isArray(items) || items.length === 0) return;
    const prepared = items.map((it) => ({
      id: String(it?.id ?? ""),
      text: String(it?.text ?? ""),
    }));
    if (typeof this._native.indexBatch === "function") {
      this._native.indexBatch(prepared);
      this._syncSnapshot();
      return;
    }
    for (const it of prepared) this._native.index(it.id, it.text);
    this._syncSnapshot();
  }

  query(queryText, topK = 5) {
    return this._native.query(String(queryText ?? ""), topK | 0);
  }

  clearIndex() {
    if (typeof this._native.clearIndex === "function") this._native.clearIndex();
    this._syncSnapshot();
  }

  save(filePath) {
    return this._native.save(String(filePath));
  }

  load(filePath) {
    const ok = this._native.load(String(filePath));
    this._syncSnapshot();
    return ok;
  }

  snapshot() {
    const snap = this._syncSnapshot();
    return {
      type: "hyperembed-native",
      dim: this.dim,
      vocabularySize: snap?.vocabSize ?? 0,
      coocPairs: snap?.coocPairs ?? 0,
      docCount: snap?.docCount ?? 0,
      learningRate: this.learningRate,
    };
  }
}

const HyperEmbed = loadNativeHyperEmbed() ? NativeHyperEmbed : JSHyperEmbed;

module.exports = {
  HyperEmbed,
  bind,
  bundle,
  bundleWeighted,
  permute,
  similarity,
  encodeSequence,
  encodeTriple,
  unbind,
  DIM,
};
