/**
 * SpectralEntities — Extracción de entidades y relaciones por álgebra lineal
 * 
 * Principio matemático:
 * La matriz de co-ocurrencia término-documento contiene toda la información
 * semántica. Usamos descomposición en valores singulares (SVD) parcial
 * mediante Power Iteration para encontrar la estructura latente.
 * 
 * Optimizado para memoria: arrays tipados, sin matrices densas V×V.
 * Complejidad: O(k * E) donde k = componentes, E = pares co-ocurrentes.
 */

const { tokenize, normalizeText } = require("../utils");

class SpectralExtractor {
  constructor(options = {}) {
    this.docs = [];
    this.vocab = new Map();
    this.vocabList = [];
    this.docFreq = new Map();
    this.numDocs = 0;
    this.numComponents = Math.min(options.numComponents ?? 4, 8);
  }

  addDocument(text) {
    const tokens = tokenize(normalizeText(String(text ?? "")));
    const contentTokens = [...new Set(tokens.filter((t) => t.length > 2))];
    
    for (const t of contentTokens) {
      if (!this.vocab.has(t)) {
        this.vocab.set(t, this.vocabList.length);
        this.vocabList.push(t);
      }
      this.docFreq.set(t, (this.docFreq.get(t) ?? 0) + 1);
    }
    
    this.docs.push({ tokens: contentTokens, text });
    this.numDocs++;
  }

  /**
   * Calcula embeddings espectrales para cada token usando
   * Power Iteration sobre la matriz de co-ocurrencia PPMI.
   * 
   * Optimización: en lugar de construir la matriz V×V completa,
   * iteramos sobre los pares co-ocurrentes directamente.
   */
  _spectralEmbed(k = 4) {
    const V = this.vocabList.length;
    if (V < 2) return [];
    
    // Construir índice de co-ocurrencias disperso
    const coocMap = new Map(); // "i|j" → ppmi value
    let maxPPmi = 0;
    
    for (const doc of this.docs) {
      for (let a = 0; a < doc.tokens.length; a++) {
        const i = this.vocab.get(doc.tokens[a]);
        if (i === undefined) continue;
        for (let b = a + 1; b < doc.tokens.length; b++) {
          const j = this.vocab.get(doc.tokens[b]);
          if (j === undefined || i === j) continue;
          const key = i < j ? `${i}|${j}` : `${j}|${i}`;
          coocMap.set(key, (coocMap.get(key) ?? 0) + 1);
        }
      }
    }
    
    // Convertir a PPMI
    const ppmiEntries = [];
    for (const [key, count] of coocMap) {
      const [iStr, jStr] = key.split("|");
      const i = parseInt(iStr), j = parseInt(jStr);
      const dfI = this.docFreq.get(this.vocabList[i]) ?? 1;
      const dfJ = this.docFreq.get(this.vocabList[j]) ?? 1;
      const expected = (dfI * dfJ) / Math.max(1, this.numDocs);
      
      if (count > expected) {
        const ppmi = Math.log(count / Math.max(expected, 0.5));
        ppmiEntries.push({ i, j, ppmi });
        if (ppmi > maxPPmi) maxPPmi = ppmi;
      }
    }
    
    if (ppmiEntries.length === 0) return [];
    
    // Normalizar PPMI
    for (const entry of ppmiEntries) {
      entry.ppmi /= Math.max(1, maxPPmi);
    }
    
    // Power Iteration: matriz dispersa × vector
    const matVecMul = (vec) => {
      const result = new Float64Array(V);
      for (const { i, j, ppmi } of ppmiEntries) {
        result[i] += ppmi * vec[j];
        result[j] += ppmi * vec[i];
      }
      // Añadir identidad para estabilidad numérica
      for (let i = 0; i < V; i++) result[i] += 0.01 * vec[i];
      return result;
    };
    
    const eigenvectors = [];
    
    for (let comp = 0; comp < k; comp++) {
      let vec = new Float64Array(V);
      for (let i = 0; i < V; i++) vec[i] = Math.random() * 2 - 1;
      
      // Normalizar
      let norm = Math.sqrt(vec.reduce((s, v) => s + v * v, 0));
      if (norm < 1e-10) continue;
      for (let i = 0; i < V; i++) vec[i] /= norm;
      
      for (let iter = 0; iter < 50; iter++) {
        let next = matVecMul(vec);
        
        // Deflación
        for (const [evec] of eigenvectors) {
          let dot = 0;
          for (let i = 0; i < V; i++) dot += evec[i] * next[i];
          for (let i = 0; i < V; i++) next[i] -= dot * evec[i];
        }
        
        norm = Math.sqrt(next.reduce((s, v) => s + v * v, 0));
        if (norm < 1e-10) break;
        for (let i = 0; i < V; i++) next[i] /= norm;
        
        let diff = 0;
        for (let i = 0; i < V; i++) diff += Math.abs(next[i] - vec[i]);
        vec = next;
        if (diff < 1e-6) break;
      }
      
      // Rayleigh quotient para eigenvalue
      const Av = matVecMul(vec);
      let evalue = 0;
      for (let i = 0; i < V; i++) evalue += vec[i] * Av[i];
      
      eigenvectors.push([vec, evalue]);
    }
    
    return eigenvectors;
  }

  /**
   * Extrae entidades y relaciones del corpus.
   */
  extract() {
    const V = this.vocabList.length;
    if (V < 2) return { entities: [], relations: [], clusters: [] };
    
    const eigenvectors = this._spectralEmbed(this.numComponents);
    if (eigenvectors.length === 0) return { entities: [], relations: [], clusters: [] };
    
    // Proyectar tokens al espacio espectral
    const projections = [];
    for (let i = 0; i < V; i++) {
      const proj = [];
      for (let c = 0; c < eigenvectors.length; c++) {
        proj.push(eigenvectors[c][0][i]);
      }
      projections.push({ token: this.vocabList[i], vector: proj, index: i });
    }
    
    // Clustering por signo del primer y segundo eigenvector
    const groups = new Map();
    for (const p of projections) {
      const sign1 = p.vector[0] >= 0 ? 1 : 0;
      const sign2 = eigenvectors.length > 1 ? (p.vector[1] >= 0 ? 2 : 0) : 0;
      const key = sign1 | sign2;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(p);
    }
    
    const clusters = [];
    for (const [, members] of groups) {
      if (members.length < 2) continue;
      
      // Cohesión: similitud coseno media intra-cluster
      let cohesion = 0, pairs = 0;
      for (let a = 0; a < members.length; a++) {
        for (let b = a + 1; b < members.length; b++) {
          let dot = 0;
          for (let c = 0; c < eigenvectors.length; c++) {
            dot += members[a].vector[c] * members[b].vector[c];
          }
          cohesion += (dot + 1) / 2; // normalizar a [0,1]
          pairs++;
        }
      }
      cohesion = pairs > 0 ? cohesion / pairs : 0;
      
      clusters.push({
        tokens: members.map((m) => m.token),
        cohesion: Math.max(0, Math.min(1, cohesion)),
      });
    }
    
    clusters.sort((a, b) => b.tokens.length - a.tokens.length);
    
    // Entidades: clústeres cohesivos
    const entities = clusters
      .filter((c) => c.cohesion > 0.2 && c.tokens.length >= 2)
      .map((c) => ({
        name: c.tokens.slice(0, 3).join(" "),
        tokens: c.tokens,
        size: c.tokens.length,
        cohesion: c.cohesion,
      }));
    
    // Relaciones: tokens que aparecen en el mismo documento
    // pero en clústeres diferentes
    const relations = [];
    const clusterMap = new Map();
    for (let ci = 0; ci < clusters.length; ci++) {
      for (const t of clusters[ci].tokens) {
        clusterMap.set(t, ci);
      }
    }
    
    // Co-ocurrencias entre clústeres
    const crossCluster = new Map();
    for (const doc of this.docs) {
      for (let a = 0; a < doc.tokens.length; a++) {
        const ca = clusterMap.get(doc.tokens[a]);
        if (ca === undefined) continue;
        for (let b = a + 1; b < doc.tokens.length; b++) {
          const cb = clusterMap.get(doc.tokens[b]);
          if (cb === undefined || ca === cb) continue;
          const key = `${Math.min(ca, cb)}|${Math.max(ca, cb)}`;
          crossCluster.set(key, (crossCluster.get(key) ?? 0) + 1);
        }
      }
    }
    
    for (const [key, count] of crossCluster) {
      const [ci, cj] = key.split("|").map(Number);
      if (ci < clusters.length && cj < clusters.length) {
        relations.push({
          from: clusters[ci].tokens.slice(0, 3).join(" "),
          to: clusters[cj].tokens.slice(0, 3).join(" "),
          strength: count,
        });
      }
    }
    
    relations.sort((a, b) => b.strength - a.strength);
    
    return {
      entities: entities.slice(0, 15),
      relations: relations.slice(0, 10),
      clusters: clusters.map((c) => ({
        tokens: c.tokens,
        size: c.tokens.length,
        cohesion: c.cohesion,
      })),
      eigenvalues: eigenvectors.map(([, ev]) => ev),
    };
  }

  snapshot() {
    return {
      type: "spectral-entities",
      vocabSize: this.vocabList.length,
      numDocs: this.numDocs,
      numComponents: this.numComponents,
    };
  }
}

module.exports = { SpectralExtractor };
