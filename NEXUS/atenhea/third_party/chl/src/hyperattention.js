/**
 * HyperAttention — Pesos de scoring dinámicos como función del contexto.
 *
 * El scoring actual usa pesos fijos:
 *   0.28·hashSim + 0.24·hvSim + 0.18·concept + 0.08·protoSim + 0.06·intent + ...
 *
 * HyperAttention aprende un vector clave (key hypervector) por cada dimensión.
 * La atención se computa comparando el hypervector de la query contra cada key,
 * aplicando softmax para obtener pesos normalizados que dependen del contexto.
 *
 * Durante el feedback, las keys se ajustan para que queries similares
 * activen patrones de atención similares.
 */

const {
  bundleVectors,
  cloneVector,
  prototypeVectorFromText,
  similarity,
  vectorFromSeed,
} = require("./hypervector");
const { clamp } = require("./utils");

// Dimensiones del scoring y sus pesos por defecto
const DEFAULT_SCORING_DIMS = [
  { id: "hash",       key: "hash",       defaultWeight: 0.28 },
  { id: "hypervector", key: "hypervector", defaultWeight: 0.24 },
  { id: "concept",    key: "concept",    defaultWeight: 0.18 },
  { id: "prototype",  key: "prototype",  defaultWeight: 0.08 },
  { id: "intent",     key: "intent",     defaultWeight: 0.06 },
  { id: "recency",    key: "recency",    defaultWeight: 0.10 },
  { id: "quality",    key: "quality",    defaultWeight: 0.04 },
  { id: "negation",   key: "negation",   defaultWeight: 0.02 },
];

/**
 * Softmax numéricamente estable sobre un array.
 */
function softmax(values) {
  const maxVal = Math.max(...values);
  const exps = values.map((v) => Math.exp(v - maxVal));
  const sum = exps.reduce((a, b) => a + b, 0);
  return exps.map((e) => e / sum);
}

class HyperAttentionContext {
  /**
   * @param {object} options
   * @param {number} options.hyperDim - dimensión de hypervectores (default 256)
   * @param {number} options.seed - semilla base
   * @param {number} options.learningRate - tasa de actualización de keys (default 0.01)
   * @param {number} options.temperature - temperatura para softmax (default 1.0)
   * @param {Array} options.dimensions - definición de dimensiones de scoring
   */
  constructor(options = {}) {
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    this.learningRate = options.learningRate ?? 0.01;
    this.temperature = options.temperature ?? 1.0;
    this.dimensions = options.dimensions ?? DEFAULT_SCORING_DIMS;
    
    // Un key vector por cada dimensión de scoring
    this._keys = new Map();
    // Valores por defecto (sin entrenar = pesos fijos)
    this._defaultWeights = new Map();
    
    this._initKeys();
    this._updateCount = 0;
  }

  /**
   * Inicializa los key vectors con semillas deterministas.
   * Cada key empieza con una semilla diferente para que sean
   * ortogonales entre sí al inicio.
   */
  _initKeys() {
    for (let i = 0; i < this.dimensions.length; i++) {
      const dim = this.dimensions[i];
      const keySeed = `${this.seed}:attn:${dim.key}:${i}`;
      this._keys.set(dim.id, vectorFromSeed(keySeed, this.hyperDim));
      this._defaultWeights.set(dim.id, dim.defaultWeight);
    }
  }

  /**
   * Computa los pesos de atención para un vector de query.
   * 
   * raw[i] = similarity(queryVector, key_i) / temperature
   * weights = softmax(raw)
   * 
   * Al inicio (sin entrenar), las keys producen pesos cercanos a los defaults.
   * 
   * @param {Uint32Array} queryVector - hypervector de la query
   * @returns {Map<string, number>} mapa de dimId → peso normalizado
   */
  computeWeights(queryVector) {
    const raw = [];
    const dimIds = [];
    
    for (const dim of this.dimensions) {
      const key = this._keys.get(dim.id);
      if (!key) {
        raw.push(0);
      } else {
        const sim = similarity(queryVector, key);
        raw.push(sim / Math.max(0.1, this.temperature));
      }
      dimIds.push(dim.id);
    }
    
    const weights = softmax(raw);
    
    // Interpolar con los pesos por defecto para estabilidad
    // (20% default + 80% aprendido)
    const result = new Map();
    for (let i = 0; i < dimIds.length; i++) {
      const dimId = dimIds[i];
      const defaultW = this._defaultWeights.get(dimId) ?? 0;
      const learnedW = weights[i];
      result.set(dimId, 0.2 * defaultW + 0.8 * learnedW);
    }
    
    return result;
  }

  /**
   * Computa los pesos para un texto de query (conveniencia).
   */
  computeWeightsForText(queryText) {
    const queryVector = prototypeVectorFromText(queryText, this.hyperDim, this.seed);
    return this.computeWeights(queryVector);
  }

  /**
   * Calcula el score compuesto usando los pesos dinámicos.
   * 
   * @param {Uint32Array} queryVector
   * @param {object} dimensionScores - { hash: number, hypervector: number, ... }
   * @returns {number}
   */
  score(queryVector, dimensionScores) {
    const weights = this.computeWeights(queryVector);
    let total = 0;
    for (const [dimId, weight] of weights) {
      const dimScore = dimensionScores[dimId] ?? 0;
      total += weight * dimScore;
    }
    return total;
  }

  /**
   * Actualiza los key vectors basado en feedback.
   * 
   * Cuando una dimensión debería haber pesado más (o menos) en el scoring,
   * movemos su key vector en la dirección adecuada.
   * 
   * @param {Uint32Array} queryVector - hypervector de la query
   * @param {object} dimensionDeltas - { hash: +0.05, concept: -0.03, ... }
   *        Valores positivos = esta dimensión debería pesar MÁS
   *        Valores negativos = esta dimensión debería pesar MENOS
   */
  updateKeys(queryVector, dimensionDeltas) {
    for (const [dimId, delta] of Object.entries(dimensionDeltas)) {
      const key = this._keys.get(dimId);
      if (!key || delta === 0) continue;
      
      // Mover la key hacia (delta > 0) o lejos de (delta < 0) el queryVector
      const rate = Math.min(0.05, Math.abs(delta)) * this.learningRate;
      
      if (delta > 0) {
        // pull: key se acerca al queryVector
        this._keys.set(dimId, this._pull(key, queryVector, rate));
      } else {
        // push: key se aleja del queryVector
        this._keys.set(dimId, this._push(key, queryVector, rate));
      }
    }
    
    this._updateCount += 1;
  }

  _pull(vec, target, rate) {
    const keepCount = Math.max(1, Math.round((1 - rate) * 100));
    const pullCount = Math.max(1, Math.round(rate * 100));
    const vectors = [];
    for (let i = 0; i < keepCount; i++) vectors.push(vec);
    for (let i = 0; i < pullCount; i++) vectors.push(target);
    return bundleVectors(vectors, this.hyperDim);
  }

  _push(vec, awayFrom, rate) {
    const dimWords = this.hyperDim / 32;
    const repel = new Uint32Array(dimWords);
    for (let i = 0; i < dimWords; i++) {
      repel[i] = (~vec[i] ^ awayFrom[i]) >>> 0;
    }
    const keepCount = Math.max(1, Math.round((1 - rate) * 100));
    const pushCount = Math.max(1, Math.round(rate * 100));
    const vectors = [];
    for (let i = 0; i < keepCount; i++) vectors.push(vec);
    for (let i = 0; i < pushCount; i++) vectors.push(repel);
    return bundleVectors(vectors, this.hyperDim);
  }

  /**
   * Calcula los dimensionDeltas ideales basados en qué entry ganó
   * vs qué entry debería haber ganado.
   * 
   * @param {object} winnerScores - scores de la entry ganadora
   * @param {object} shouldWinScores - scores de la entry que debería ganar
   * @returns {object} dimensionDeltas
   */
  computeDeltas(winnerScores, shouldWinScores) {
    const deltas = {};
    const dims = ["hash", "hypervector", "concept", "prototype", "intent", "recency", "quality", "negation"];
    
    for (const dim of dims) {
      const winnerVal = winnerScores[dim] ?? 0;
      const shouldVal = shouldWinScores[dim] ?? 0;
      // Si la entry correcta tenía mejor score en esta dimensión, 
      // reforzar esta dimensión. Si no, penalizar.
      const diff = shouldVal - winnerVal;
      deltas[dim] = clamp(diff * 0.5, -0.1, 0.1);
    }
    
    return deltas;
  }

  get updateCount() {
    return this._updateCount;
  }

  toJSON() {
    const keys = {};
    for (const [dimId, key] of this._keys) {
      keys[dimId] = Array.from(key);
    }
    return {
      hyperDim: this.hyperDim,
      temperature: this.temperature,
      learningRate: this.learningRate,
      updateCount: this._updateCount,
      keys,
    };
  }

  static fromJSON(data, options = {}) {
    const ctx = new HyperAttentionContext({
      ...options,
      hyperDim: data.hyperDim ?? options.hyperDim,
      temperature: data.temperature ?? options.temperature,
      learningRate: data.learningRate ?? options.learningRate,
    });
    
    if (data.keys) {
      for (const [dimId, keyArr] of Object.entries(data.keys)) {
        ctx._keys.set(dimId, Uint32Array.from(keyArr));
      }
    }
    
    ctx._updateCount = data.updateCount ?? 0;
    return ctx;
  }

  snapshot() {
    return {
      hyperDim: this.hyperDim,
      dimensions: this.dimensions.length,
      updateCount: this._updateCount,
      temperature: this.temperature,
    };
  }
}

module.exports = {
  HyperAttentionContext,
  DEFAULT_SCORING_DIMS,
  softmax,
};
