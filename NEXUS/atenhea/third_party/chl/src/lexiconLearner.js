/**
 * LexiconLearner — Capa de aprendizaje semántico para CHL
 * 
 * Cinco clases que transforman el lexicón de un diccionario estático
 * en una mini-capa entrenable con prototipos semánticos HDC,
 * aprendizaje contrastivo online, índice de alias de frases,
 * clusterización de intención y entrenador batch.
 * 
 * - ConceptPrototype: hypervector prototipo por concepto con actualización incremental
 * - ContrastiveFeedback: pull/push online para aprendizaje por refuerzo
 * - PhraseAliasIndex: mapeo de frases compuestas a conceptos con co-ocurrencia
 * - IntentClusterer: agrupación de queries por concepto ganador
 * - LexiconTrainer: orquestador de carga/guardado y entrenamiento
 */

const {
  bundleVectors,
  cloneVector,
  prototypeVectorFromText,
  similarity,
  vectorFromSeed,
} = require("./hypervector");
const { normalizeText, tokenize } = require("./utils");
const fs = require("node:fs");
const path = require("node:path");

// ─── ConceptPrototype ─────────────────────────────────────

class ConceptPrototype {
  /**
   * @param {string} conceptId - identificador único del concepto
   * @param {object} options
   * @param {number} options.hyperDim - dimensión del hypervector (default 256)
   * @param {number} options.seed - semilla para generación de vectores
   * @param {number} options.alpha - factor de inercia para actualización incremental (default 0.95)
   * @param {string[]} options.aliases - alias del concepto para inicializar prototipo
   */
  constructor(conceptId, options = {}) {
    this.id = conceptId;
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    this.alpha = options.alpha ?? 0.95;
    
    // Prototipo: hypervector que representa el centro semántico del concepto
    this.prototype = null;
    
    // Estadísticas
    this.positiveCount = 0;
    this.negativeCount = 0;
    this.queryCount = 0;
    
    // Aliases y ejemplos
    this.aliases = options.aliases ?? [];
    this.positiveExamples = [];
    this.negativeExamples = [];
    
    // Cluster de intención (centroide de queries que cayeron aquí)
    this.clusterCentroid = null;
    this._clusterVectors = [];
    
    // Confianza derivada
    this._confidence = 0.5;
    this._dirtyConfidence = true;
    
    // Inicializar prototipo desde aliases si existen
    if (this.aliases.length > 0) {
      this._initFromAliases();
    }
  }

  _initFromAliases() {
    const vectors = this.aliases.map((alias) =>
      prototypeVectorFromText(alias, this.hyperDim, this.seed)
    );
    this.prototype = bundleVectors(vectors, this.hyperDim);
    this.positiveCount = this.aliases.length;
  }

  /**
   * Inicializa el prototipo desde un texto (si no tiene aliases).
   */
  initFromText(text) {
    if (this.prototype) return;
    this.prototype = prototypeVectorFromText(text, this.hyperDim, this.seed);
    this.positiveCount = 1;
    this.positiveExamples.push(text);
  }

  /**
   * Actualización incremental del prototipo con un nuevo ejemplo.
   * prototype = bundle([prototype * alpha, newVector * (1 - alpha)])
   */
  addExample(text, isPositive = true) {
    if (!this.prototype) {
      this.initFromText(text);
      return;
    }

    const newVector = prototypeVectorFromText(text, this.hyperDim, this.seed);
    
    if (isPositive) {
      this.positiveExamples.push(text);
      this.positiveCount += 1;
    } else {
      this.negativeExamples.push(text);
      this.negativeCount += 1;
    }

    this._updatePrototype(newVector, isPositive);
    this._dirtyConfidence = true;
  }

  _updatePrototype(newVector, isPositive) {
    // Para ejemplos positivos: acercar el prototipo
    // Para ejemplos negativos: alejar (usando bind con ruido)
    if (isPositive) {
      // prototype = alpha * prototype + (1 - alpha) * newVector
      const alphaVec = this._scaleVectorWeight(this.prototype, this.alpha);
      const betaVec = this._scaleVectorWeight(newVector, 1 - this.alpha);
      this.prototype = bundleVectors([alphaVec, betaVec], this.hyperDim);
    } else {
      // prototype se aleja del ejemplo negativo
      // Usamos bind (XOR) con un vector de ruido para "empujar"
      // y luego bundle ponderado para suavizar
      const repelVector = this._createRepelVector(this.prototype, newVector);
      this.prototype = bundleVectors(
        [this._scaleVectorWeight(this.prototype, 0.98), this._scaleVectorWeight(repelVector, 0.02)],
        this.hyperDim
      );
    }
  }

  /**
   * Simula un vector escalado por un peso (para bundle ponderado).
   * Multiplica la contribución de cada bit según el peso.
   */
  _scaleVectorWeight(vec, weight) {
    // Para bundleVectors, cada vector contribuye ±1 por bit.
    // Escalar el peso significa duplicar el vector weight veces.
    // Simplificación: devolvemos el mismo vector; el bundle ponderado
    // se maneja repitiendo vectores en el array.
    // Para alpha cercano a 1, repetimos prototype muchas veces.
    const count = Math.max(1, Math.round(weight * 100));
    return { vector: vec, count };
  }

  _createRepelVector(prototype, badVector) {
    // Crear un vector que, al hacerle bundle con prototype, lo aleje de badVector
    // Estrategia: XOR entre prototype y badVector da las diferencias;
    // luego invertimos algunos bits para crear dirección de repulsión
    const dimWords = this.hyperDim / 32;
    const repel = new Uint32Array(dimWords);
    for (let i = 0; i < dimWords; i++) {
      // ~(p ^ b) da 1 donde son iguales, 0 donde difieren
      // Queremos mover prototype lejos de badVector: cambiar bits donde coinciden
      const diff = prototype[i] ^ badVector[i];
      // Mantener ~60% de los bits donde coinciden, ~40% aleatorio
      repel[i] = (diff ^ 0x55555555) >>> 0;
    }
    return repel;
  }

  /**
   * Similitud entre un hypervector de query y este prototipo.
   */
  similarityTo(queryVector) {
    if (!this.prototype || !queryVector) return 0;
    return similarity(this.prototype, queryVector);
  }

  /**
   * Confianza del prototipo: derivada del ratio positivo/negativo.
   */
  get confidence() {
    if (!this._dirtyConfidence) return this._confidence;
    const total = this.positiveCount + this.negativeCount;
    if (total === 0) {
      this._confidence = 0.5;
    } else {
      // Laplace smoothing ligero
      const raw = (this.positiveCount + 1) / (total + 2);
      // Escalar por cantidad de ejemplos (poca data = menos confianza)
      const scale = Math.min(1, total / 10);
      this._confidence = 0.5 + scale * (raw - 0.5);
    }
    this._dirtyConfidence = false;
    return this._confidence;
  }

  /**
   * Actualiza el centroide del cluster de intención.
   */
  addQueryVector(queryVector) {
    this._clusterVectors.push(cloneVector(queryVector));
    this.queryCount += 1;
    // Mantener solo los últimos 50 vectores para el centroide
    if (this._clusterVectors.length > 50) {
      this._clusterVectors = this._clusterVectors.slice(-50);
    }
    this.clusterCentroid = bundleVectors(this._clusterVectors, this.hyperDim);
  }

  /**
   * Similitud de intención: query vs centroide del cluster.
   */
  intentSimilarity(queryVector) {
    if (!this.clusterCentroid || !queryVector) return 0;
    return similarity(this.clusterCentroid, queryVector);
  }

  toJSON() {
    return {
      id: this.id,
      aliases: this.aliases,
      prototype: this.prototype ? Array.from(this.prototype) : null,
      positiveCount: this.positiveCount,
      negativeCount: this.negativeCount,
      confidence: this.confidence,
      clusterCentroid: this.clusterCentroid ? Array.from(this.clusterCentroid) : null,
      queryCount: this.queryCount,
    };
  }

  static fromJSON(data, options = {}) {
    const proto = new ConceptPrototype(data.id, {
      ...options,
      aliases: data.aliases ?? [],
    });
    if (data.prototype) {
      proto.prototype = Uint32Array.from(data.prototype);
    }
    proto.positiveCount = data.positiveCount ?? 0;
    proto.negativeCount = data.negativeCount ?? 0;
    proto.queryCount = data.queryCount ?? 0;
    proto._confidence = data.confidence ?? 0.5;
    proto._dirtyConfidence = false;
    if (data.clusterCentroid) {
      proto.clusterCentroid = Uint32Array.from(data.clusterCentroid);
    }
    return proto;
  }
}

// ─── ContrastiveFeedback ──────────────────────────────────

class ContrastiveFeedback {
  /**
   * @param {object} options
   * @param {number} options.hyperDim - dimensión del hypervector
   * @param {number} options.seed - semilla
   * @param {number} options.pullRate - tasa de acercamiento (default 0.01)
   * @param {number} options.pushRate - tasa de alejamiento (default 0.02)
   */
  constructor(options = {}) {
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    this.pullRate = options.pullRate ?? 0.01;
    this.pushRate = options.pushRate ?? 0.02;
    this._feedbackCount = 0;
  }

  /**
   * pull: acerca el prototipo hacia el vector de la query.
   * prototype = bundle([prototype * (1 - rate), queryVector * rate])
   */
  pull(prototype, queryVector) {
    this._feedbackCount += 1;
    const keepWeight = 1 - this.pullRate;
    const pullWeight = this.pullRate;
    
    // Construir array de vectores ponderados para bundle
    const vectors = [];
    const keepCount = Math.max(1, Math.round(keepWeight * 100));
    for (let i = 0; i < keepCount; i++) {
      vectors.push(prototype);
    }
    const pullCount = Math.max(1, Math.round(pullWeight * 100));
    for (let i = 0; i < pullCount; i++) {
      vectors.push(queryVector);
    }
    
    return bundleVectors(vectors, this.hyperDim);
  }

  /**
   * push: aleja el prototipo del vector de la query.
   * prototype = bundle([prototype * (1 - rate), repelVector * rate])
   */
  push(prototype, queryVector) {
    this._feedbackCount += 1;
    const keepWeight = 1 - this.pushRate;
    const pushWeight = this.pushRate;
    
    // Crear vector de repulsión
    const dimWords = this.hyperDim / 32;
    const repel = new Uint32Array(dimWords);
    for (let i = 0; i < dimWords; i++) {
      repel[i] = (~prototype[i] ^ queryVector[i]) >>> 0;
    }
    
    const vectors = [];
    const keepCount = Math.max(1, Math.round(keepWeight * 100));
    for (let i = 0; i < keepCount; i++) {
      vectors.push(prototype);
    }
    const pushCount = Math.max(1, Math.round(pushWeight * 100));
    for (let i = 0; i < pushCount; i++) {
      vectors.push(repel);
    }
    
    return bundleVectors(vectors, this.hyperDim);
  }

  /**
   * Aplica feedback online tras un recall.
   * @param {ConceptPrototype} selectedConcept - concepto seleccionado
   * @param {ConceptPrototype[]} rejectedConcepts - conceptos que NO debían ganar
   * @param {Uint32Array} queryVector - vector de la query
   * @returns {object} resultado con conteo de ajustes
   */
  apply(selectedConcept, rejectedConcepts, queryVector) {
    if (!selectedConcept || !queryVector) return { pulled: 0, pushed: 0 };
    if (!selectedConcept.prototype) {
      selectedConcept.initFromText("");
    }

    // Pull hacia el concepto correcto
    selectedConcept.prototype = this.pull(selectedConcept.prototype, queryVector);
    selectedConcept.positiveCount += 1;
    selectedConcept._dirtyConfidence = true;
    
    let pushed = 0;
    // Push lejos de los conceptos incorrectos
    if (rejectedConcepts && rejectedConcepts.length > 0) {
      for (const rejected of rejectedConcepts) {
        if (!rejected || rejected.id === selectedConcept.id) continue;
        if (!rejected.prototype) continue;
        rejected.prototype = this.push(rejected.prototype, queryVector);
        rejected.negativeCount += 1;
        rejected._dirtyConfidence = true;
        pushed += 1;
      }
    }
    
    return { pulled: 1, pushed };
  }

  get feedbackCount() {
    return this._feedbackCount;
  }

  snapshot() {
    return {
      pullRate: this.pullRate,
      pushRate: this.pushRate,
      feedbackCount: this._feedbackCount,
    };
  }
}

// ─── PhraseAliasIndex ─────────────────────────────────────

class PhraseAliasIndex {
  /**
   * Índice de frases compuestas → conceptos con scoring por co-ocurrencia.
   * A diferencia de los phrase pairs (sustitución token-level),
   * detecta que frases semánticamente equivalentes apuntan al mismo concepto.
   */
  constructor(options = {}) {
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    // phraseKey (normalizada) → { conceptIds: Map<conceptId, count>, totalCount }
    this._index = new Map();
    // Frase → vector hypervector cache
    this._vectorCache = new Map();
  }

  /**
   * Normaliza una frase para usarla como clave.
   */
  _normalizePhrase(phrase) {
    return normalizeText(String(phrase ?? "")).replace(/\s+/g, " ").trim();
  }

  /**
   * Obtiene o crea el hypervector para una frase.
   */
  _getVector(phrase) {
    const key = this._normalizePhrase(phrase);
    if (this._vectorCache.has(key)) return this._vectorCache.get(key);
    const vec = prototypeVectorFromText(key, this.hyperDim, this.seed);
    this._vectorCache.set(key, vec);
    return vec;
  }

  /**
   * Registra que una frase está asociada a un concepto.
   */
  add(phrase, conceptId) {
    const key = this._normalizePhrase(phrase);
    if (!key || key.length < 3) return;
    
    if (!this._index.has(key)) {
      this._index.set(key, { conceptIds: new Map(), totalCount: 0 });
    }
    const entry = this._index.get(key);
    entry.conceptIds.set(conceptId, (entry.conceptIds.get(conceptId) ?? 0) + 1);
    entry.totalCount += 1;
  }

  /**
   * Busca los conceptos asociados a una frase.
   * @returns {Array<{conceptId: string, score: number}>}
   */
  lookup(phrase) {
    const key = this._normalizePhrase(phrase);
    const entry = this._index.get(key);
    if (!entry) return [];
    
    const results = [];
    for (const [conceptId, count] of entry.conceptIds) {
      results.push({
        conceptId,
        score: count / entry.totalCount,
        count,
      });
    }
    results.sort((a, b) => b.score - a.score);
    return results;
  }

  /**
   * Busca el concepto más probable para una frase.
   */
  bestConcept(phrase) {
    const results = this.lookup(phrase);
    return results.length > 0 ? results[0] : null;
  }

  /**
   * Detecta frases candidatas en un texto (n-gramas de 2-4 palabras).
   */
  extractPhrases(text) {
    const tokens = tokenize(normalizeText(String(text ?? "")));
    const phrases = [];
    for (let len = 2; len <= 4; len++) {
      for (let i = 0; i <= tokens.length - len; i++) {
        const phrase = tokens.slice(i, i + len).join(" ");
        if (phrase.length >= 5) {
          phrases.push(phrase);
        }
      }
    }
    return phrases;
  }

  /**
   * Encuentra el concepto ganador para un texto analizando sus frases.
   */
  resolveConcept(text, defaultConceptId = null) {
    const phrases = this.extractPhrases(text);
    const scores = new Map();
    
    for (const phrase of phrases) {
      const results = this.lookup(phrase);
      for (const { conceptId, score } of results) {
        scores.set(conceptId, (scores.get(conceptId) ?? 0) + score);
      }
    }
    
    if (scores.size === 0) return defaultConceptId;
    
    let best = null;
    let bestScore = 0;
    for (const [conceptId, score] of scores) {
      if (score > bestScore) {
        bestScore = score;
        best = conceptId;
      }
    }
    
    return best ?? defaultConceptId;
  }

  get size() {
    return this._index.size;
  }

  toJSON() {
    const entries = [];
    for (const [phrase, data] of this._index) {
      entries.push({
        phrase,
        concepts: Array.from(data.conceptIds.entries()),
        total: data.totalCount,
      });
    }
    return entries;
  }

  static fromJSON(data, options = {}) {
    const index = new PhraseAliasIndex(options);
    for (const entry of data) {
      const conceptIds = new Map(entry.concepts);
      index._index.set(entry.phrase, {
        conceptIds,
        totalCount: entry.total,
      });
    }
    return index;
  }
}

// ─── IntentClusterer ──────────────────────────────────────

class IntentClusterer {
  /**
   * Agrupa queries por concepto ganador, manteniendo centroides.
   */
  constructor(options = {}) {
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    // conceptId → { centroid: Uint32Array, vectors: Uint32Array[], count: number }
    this._clusters = new Map();
    this.maxVectorsPerCluster = options.maxVectorsPerCluster ?? 50;
  }

  /**
   * Añade una query a un cluster de concepto.
   */
  add(queryText, conceptId) {
    if (!queryText || !conceptId) return;
    
    const queryVector = prototypeVectorFromText(queryText, this.hyperDim, this.seed);
    
    if (!this._clusters.has(conceptId)) {
      this._clusters.set(conceptId, {
        centroid: cloneVector(queryVector),
        vectors: [cloneVector(queryVector)],
        count: 1,
      });
      return;
    }
    
    const cluster = this._clusters.get(conceptId);
    cluster.vectors.push(cloneVector(queryVector));
    cluster.count += 1;
    
    // Mantener tamaño máximo del buffer
    if (cluster.vectors.length > this.maxVectorsPerCluster) {
      cluster.vectors = cluster.vectors.slice(-this.maxVectorsPerCluster);
    }
    
    // Recalcular centroide
    cluster.centroid = bundleVectors(cluster.vectors, this.hyperDim);
  }

  /**
   * Similitud entre un vector de query y el centroide de un concepto.
   */
  intentSimilarity(queryVector, conceptId) {
    const cluster = this._clusters.get(conceptId);
    if (!cluster || !queryVector) return 0;
    return similarity(cluster.centroid, queryVector);
  }

  /**
   * Similitud de intención para un texto de query.
   */
  intentSimilarityForText(queryText, conceptId) {
    const queryVector = prototypeVectorFromText(queryText, this.hyperDim, this.seed);
    return this.intentSimilarity(queryVector, conceptId);
  }

  get clusterCount() {
    return this._clusters.size;
  }

  toJSON() {
    const clusters = {};
    for (const [conceptId, cluster] of this._clusters) {
      clusters[conceptId] = {
        centroid: Array.from(cluster.centroid),
        count: cluster.count,
      };
    }
    return clusters;
  }

  static fromJSON(data, options = {}) {
    const clusterer = new IntentClusterer(options);
    for (const [conceptId, clusterData] of Object.entries(data)) {
      clusterer._clusters.set(conceptId, {
        centroid: Uint32Array.from(clusterData.centroid),
        vectors: [],
        count: clusterData.count ?? 0,
      });
    }
    return clusterer;
  }
}

// ─── LexiconTrainer ───────────────────────────────────────

class LexiconTrainer {
  /**
   * Orquestador del aprendizaje del lexicón.
   * @param {object} options
   * @param {number} options.hyperDim
   * @param {number} options.seed
   * @param {string} options.prototypesPath - ruta para concepts-prototypes.json
   * @param {Map} options.conceptMap - mapa de conceptos (from concepts.js)
   */
  constructor(options = {}) {
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    this.prototypesPath = options.prototypesPath ?? null;
    
    // Mapa de conceptos base (from → to) desde concepts.js
    this.conceptMap = options.conceptMap ?? new Map();
    
    // Mapa de colocaciones verbo→preposición (para el HyperDecoder)
    this.collocationMap = options.collocationMap ?? new Map();
    
    // Prototipos por concepto
    this._prototypes = new Map();
    
    // Sub-módulos
    this.feedback = new ContrastiveFeedback({
      hyperDim: this.hyperDim,
      seed: this.seed,
    });
    this.phraseIndex = new PhraseAliasIndex({
      hyperDim: this.hyperDim,
      seed: this.seed,
    });
    this.intentClusterer = new IntentClusterer({
      hyperDim: this.hyperDim,
      seed: this.seed,
    });
    
    // Auto-inicializar desde conceptMap si existe
    this._initFromConceptMap();
  }

  _initFromConceptMap() {
    for (const [from, to] of this.conceptMap.entries()) {
      // Cada concepto canónico tiene como alias el término fuente
      this._ensurePrototype(to, [from, to]);
    }
    // También inicializar con los términos canónicos como auto-conceptos
    const canonicals = new Set(this.conceptMap.values());
    for (const canonical of canonicals) {
      if (!this._prototypes.has(canonical)) {
        this._ensurePrototype(canonical, [canonical]);
      }
    }
  }

  _ensurePrototype(conceptId, aliases = []) {
    if (this._prototypes.has(conceptId)) {
      const existing = this._prototypes.get(conceptId);
      // Añadir aliases nuevos
      for (const alias of aliases) {
        if (!existing.aliases.includes(alias)) {
          existing.aliases.push(alias);
        }
      }
      return existing;
    }
    
    const proto = new ConceptPrototype(conceptId, {
      hyperDim: this.hyperDim,
      seed: this.seed,
      aliases: [...new Set(aliases)],
    });
    this._prototypes.set(conceptId, proto);
    return proto;
  }

  /**
   * Obtiene o crea un prototipo para un concepto.
   */
  getPrototype(conceptId) {
    if (!conceptId) return null;
    return this._prototypes.get(conceptId) ?? this._ensurePrototype(conceptId);
  }

  /**
   * Similitud entre un vector de query y el prototipo de un concepto.
   */
  prototypeSimilarity(queryVector, conceptId) {
    const proto = this._prototypes.get(conceptId);
    if (!proto) return 0;
    return proto.similarityTo(queryVector);
  }

  /**
   * Intenta resolver a qué concepto pertenece un texto.
   * Usa el conceptMap para canonicalización y el phraseIndex para frases.
   */
  resolveConcept(text) {
    // Primero intentar con phraseIndex
    const phraseConcept = this.phraseIndex.resolveConcept(text, null);
    if (phraseConcept) return phraseConcept;
    
    // Buscar en el text por tokens que sean keys O values del conceptMap
    const tokens = tokenize(normalizeText(String(text ?? "")));
    
    // Primero buscar keys (variantes como "felino")
    for (const token of tokens) {
      const canonical = this.conceptMap.get(token);
      if (canonical) return canonical;
    }
    
    // Luego buscar values (canónicas como "gato")
    const canonicalValues = new Set(this.conceptMap.values());
    for (const token of tokens) {
      if (canonicalValues.has(token)) return token;
    }
    
    return null;
  }

  /**
   * Similitud de intención entre un texto y un concepto.
   */
  intentSimilarity(queryText, conceptId) {
    return this.intentClusterer.intentSimilarityForText(queryText, conceptId);
  }

  /**
   * Feedback online: ajusta prototipos tras un recall.
   * @param {string} queryText - texto de la query
   * @param {string} selectedConceptId - concepto que DEBERÍA haber ganado
   * @param {string[]} rejectedConceptIds - conceptos incorrectos rankeados alto
   */
  applyOnlineFeedback(queryText, selectedConceptId, rejectedConceptIds = []) {
    const queryVector = prototypeVectorFromText(queryText, this.hyperDim, this.seed);
    const selectedProto = this.getPrototype(selectedConceptId);
    const rejectedProtos = rejectedConceptIds
      .map((id) => this.getPrototype(id))
      .filter(Boolean);
    
    const result = this.feedback.apply(selectedProto, rejectedProtos, queryVector);
    
    // También registrar la query en el intent clusterer
    this.intentClusterer.add(queryText, selectedConceptId);
    
    return result;
  }

  /**
   * Entrenamiento batch: procesa episodios para mejorar el lexicón.
   */
  trainBatch(episodes = []) {
    let updates = 0;
    
    for (const episode of episodes) {
      if (!episode || !episode.query) continue;
      
      const queryText = String(episode.query);
      const targetText = String(episode.bestEvidenceText ?? episode.responseText ?? "");
      
      if (!targetText) continue;
      
      // Detectar conceptos en query y target
      const queryConcept = this.resolveConcept(queryText);
      const targetConcept = this.resolveConcept(targetText);
      
      // Extraer frases y asociarlas a conceptos
      const queryPhrases = this.phraseIndex.extractPhrases(queryText);
      const targetPhrases = this.phraseIndex.extractPhrases(targetText);
      
      const resolvedConcept = targetConcept || queryConcept;
      
      if (resolvedConcept) {
        // Asociar frases de la query al concepto del target
        for (const phrase of queryPhrases) {
          this.phraseIndex.add(phrase, resolvedConcept);
        }
        
        // Reforzar prototipo con el texto target
        const proto = this.getPrototype(resolvedConcept);
        if (proto && targetText.length > 3) {
          proto.addExample(targetText, true);
        }
        
        // Clusterizar intención
        this.intentClusterer.add(queryText, resolvedConcept);
        
        updates += 1;
      }
      
      // También aprender de conceptPairs si existen
      if (episode.conceptPairs) {
        for (const [from, to] of episode.conceptPairs) {
          this._ensurePrototype(to, [from]);
          updates += 1;
        }
      }
    }
    
    return { updates, episodeCount: episodes.length };
  }

  /**
   * Canonicaliza un texto usando los conceptos y frases aprendidos.
   * "el felino descansa sobre la mesa" → "el gato duerme sobre la mesa"
   */
  canonicalizeText(text) {
    let result = normalizeText(String(text ?? ""));
    
    // Primero, reemplazar frases compuestas (phraseIndex)
    const phrases = this.phraseIndex.extractPhrases(result);
    for (const phrase of phrases.sort((a, b) => b.length - a.length)) {
      const concept = this.phraseIndex.bestConcept(phrase);
      if (concept && concept.score > 0.5) {
        const proto = this._prototypes.get(concept.conceptId);
        if (proto && proto.aliases.length > 0) {
          const replacement = proto.aliases[0];
          result = result.replace(
            new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"),
            replacement
          );
        }
      }
    }
    
    // Luego, reemplazar tokens individuales (conceptMap) — REPLACE, no append
    const tokens = tokenize(result);
    const replaced = [];
    for (const token of tokens) {
      const canonical = this.conceptMap.get(token);
      if (canonical && canonical !== token) {
        replaced.push(canonical);  // Solo la versión canónica
      } else {
        replaced.push(token);
      }
    }
    
    return replaced.join(" ");
  }

  /**
   * Carga el estado desde concepts-prototypes.json.
   */
  load() {
    if (!this.prototypesPath || !fs.existsSync(this.prototypesPath)) return false;
    
    try {
      const raw = JSON.parse(fs.readFileSync(this.prototypesPath, "utf8"));
      if (!raw || raw.version < 1) return false;
      
      // Cargar prototipos
      if (raw.concepts) {
        for (const [conceptId, data] of Object.entries(raw.concepts)) {
          this._prototypes.set(conceptId, ConceptPrototype.fromJSON(data, {
            hyperDim: this.hyperDim,
            seed: this.seed,
          }));
        }
      }
      
      // Cargar índice de frases
      if (raw.phraseIndex) {
        this.phraseIndex = PhraseAliasIndex.fromJSON(raw.phraseIndex, {
          hyperDim: this.hyperDim,
          seed: this.seed,
        });
      }
      
      // Cargar clusters de intención
      if (raw.intentClusters) {
        this.intentClusterer = IntentClusterer.fromJSON(raw.intentClusters, {
          hyperDim: this.hyperDim,
          seed: this.seed,
        });
      }
      
      return true;
    } catch (err) {
      return false;
    }
  }

  /**
   * Guarda el estado a concepts-prototypes.json.
   */
  save() {
    if (!this.prototypesPath) return false;
    
    try {
      const dir = path.dirname(this.prototypesPath);
      if (dir && dir !== ".") {
        fs.mkdirSync(dir, { recursive: true });
      }
      
      const payload = {
        version: 2,
        hyperDim: this.hyperDim,
        concepts: {},
        phraseIndex: this.phraseIndex.toJSON(),
        intentClusters: this.intentClusterer.toJSON(),
        feedback: this.feedback.snapshot(),
      };
      
      for (const [conceptId, proto] of this._prototypes) {
        payload.concepts[conceptId] = proto.toJSON();
      }
      
      fs.writeFileSync(this.prototypesPath, JSON.stringify(payload, null, 2));
      return true;
    } catch (err) {
      return false;
    }
  }

  snapshot() {
    return {
      prototypeCount: this._prototypes.size,
      phraseCount: this.phraseIndex.size,
      clusterCount: this.intentClusterer.clusterCount,
      feedbackCount: this.feedback.feedbackCount,
      conceptPairs: this.conceptMap.size,
      collocations: this.collocationMap.size,
    };
  }
}

module.exports = {
  ConceptPrototype,
  ContrastiveFeedback,
  PhraseAliasIndex,
  IntentClusterer,
  LexiconTrainer,
};
