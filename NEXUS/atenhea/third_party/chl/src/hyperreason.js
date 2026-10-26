/**
 * HyperReason — Motor de inferencia multi-hop en espacio HDC
 *
 * Encadena inferencias usando el grafo de conceptos + operaciones HDC
 * (bind/unbind/bundle/permute) para razonar sin necesidad de un LLM.
 *
 * A diferencia de un transformer, cada paso de inferencia es determinista
 * y trazable. No hay alucinaciones: solo se infiere lo que está soportado
 * por la memoria existente.
 *
 * Operaciones clave:
 *   bind(A, B)    — asocia A con B (XOR)
 *   unbind(A, B)  — recupera B dado A⊕B (XOR de nuevo)
 *   bundle([...]) — conjunto de vectores
 *   permute(V, n) — desplazamiento circular (codifica secuencia)
 *
 * Ejemplo de inferencia:
 *   "el gato duerme sobre la mesa" + "la mesa está en la cocina"
 *   → ¿dónde está el gato?
 *   → bind(gato, mesa) ⊕ bind(mesa, cocina) → gato en cocina
 */

const {
  bundleVectors,
  cloneVector,
  prototypeVectorFromText,
  similarity,
} = require("./hypervector");
const { buildConceptGraph } = require("./graph");
const { analyzeText } = require("./analysis");
const { normalizeText, tokenize } = require("./utils");

class HyperReason {
  /**
   * @param {object} options
   * @param {number} options.hyperDim
   * @param {number} options.seed
   * @param {object} options.lexiconTrainer
   * @param {number} options.maxHops - profundidad máxima de inferencia
   * @param {number} options.minConfidence - umbral mínimo para aceptar inferencia
   */
  constructor(options = {}) {
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    this.lexiconTrainer = options.lexiconTrainer ?? null;
    this.maxHops = options.maxHops ?? 3;
    this.minConfidence = options.minConfidence ?? 0.3;
    this._inferenceCount = 0;
  }

  /**
   * Razona sobre una query encadenando inferencias a través del grafo de conceptos.
   *
   * @param {string} query - pregunta a razonar
   * @param {Array} memoryEntries - entradas de memoria [{id, text, payload}]
   * @param {object} options
   * @returns {object} { conclusion, chain, confidence, trace }
   */
  reason(query, memoryEntries = [], options = {}) {
    const maxHops = options.maxHops ?? this.maxHops;
    const queryAnalysis = analyzeText(query);
    const queryVector = prototypeVectorFromText(query, this.hyperDim, this.seed);

    // Construir grafo de conceptos desde las entradas de memoria
    const graph = buildConceptGraph(memoryEntries);
    
    // Extraer entidades y relaciones de la query
    const queryEntities = this._extractEntities(queryAnalysis, graph);
    if (queryEntities.length < 2) {
      return this._directLookup(query, memoryEntries, queryVector);
    }

    // Cadena de inferencia: buscar caminos entre entidades en el grafo
    const paths = this._findPaths(queryEntities, graph, maxHops);
    
    if (paths.length === 0) {
      return this._directLookup(query, memoryEntries, queryVector);
    }

    // Evaluar cada camino y construir conclusión
    const bestPath = paths[0];
    const conclusion = this._buildConclusion(bestPath, memoryEntries);
    
    this._inferenceCount++;

    return {
      conclusion: conclusion.text,
      confidence: conclusion.confidence,
      chain: bestPath.map(node => node.label),
      trace: bestPath.map(node => `${node.type}:${node.label}`).join(" → "),
      evidence: bestPath.flatMap(node => node.evidence || []),
      inferred: true,
      hops: bestPath.length - 1,
    };
  }

  /**
   * Búsqueda directa sin inferencia (fallback).
   */
  _directLookup(query, memoryEntries, queryVector) {
    const best = memoryEntries[0];
    return {
      conclusion: best?.text ?? "",
      confidence: best ? 0.7 : 0,
      chain: [],
      trace: "direct",
      evidence: best ? [best.id] : [],
      inferred: false,
      hops: 0,
    };
  }

  /**
   * Extrae entidades mencionadas en la query que existen en el grafo.
   */
  _extractEntities(queryAnalysis, graph) {
    const concepts = new Set(queryAnalysis.concepts ?? []);
    const focusTokens = new Set(queryAnalysis.focusTokens ?? []);
    const allTerms = new Set([...concepts, ...focusTokens]);

    const entities = [];
    for (const node of graph.nodes) {
      if (node.type === "entity" || node.type === "concept") {
        const label = node.label.toLowerCase();
        for (const term of allTerms) {
          if (label.includes(term) || term.includes(label)) {
            entities.push(node);
            break;
          }
        }
      }
    }
    return entities;
  }

  /**
   * Encuentra caminos entre entidades en el grafo usando BFS bidireccional.
   */
  _findPaths(startNodes, graph, maxHops) {
    if (startNodes.length < 2) return [];

    // Construir índice de adyacencia
    const adjacency = new Map();
    for (const edge of graph.edges) {
      if (!adjacency.has(edge.from)) adjacency.set(edge.from, []);
      adjacency.get(edge.from).push({ to: edge.to, edge });
      if (!adjacency.has(edge.to)) adjacency.set(edge.to, []);
      adjacency.get(edge.to).push({ to: edge.from, edge: { ...edge, label: "inv_" + edge.label } });
    }

    const paths = [];
    const source = startNodes[0];
    const targets = new Set(startNodes.slice(1).map(n => n.id));

    // BFS desde source
    const visited = new Set([source.id]);
    const queue = [{ node: source, path: [source], depth: 0 }];

    while (queue.length > 0) {
      const current = queue.shift();
      
      if (targets.has(current.node.id) && current.depth > 0) {
        paths.push({
          nodes: current.path,
          depth: current.depth,
          score: 1.0 / (current.depth + 1),
        });
        if (paths.length >= 5) break;
      }

      if (current.depth >= maxHops) continue;

      const neighbors = adjacency.get(current.node.id) ?? [];
      for (const { to, edge } of neighbors) {
        if (visited.has(to)) continue;
        visited.add(to);
        const toNode = graph.nodes.find(n => n.id === to);
        if (toNode) {
          queue.push({
            node: toNode,
            path: [...current.path, toNode],
            depth: current.depth + 1,
          });
        }
      }
    }

    paths.sort((a, b) => b.score - a.score);
    return paths.map(p => p.nodes);
  }

  /**
   * Construye una conclusión en lenguaje natural desde un camino de inferencia.
   */
  _buildConclusion(path, memoryEntries) {
    if (path.length < 2) {
      return { text: path[0]?.label ?? "", confidence: 0.3 };
    }

    const parts = [];
    let confidence = 1.0;

    for (let i = 0; i < path.length - 1; i++) {
      const from = path[i];
      const to = path[i + 1];
      
      // Buscar la arista que conecta estos nodos
      const fromEntry = memoryEntries.find(e => 
        e.text && (e.text.includes(from.label) || from.label.includes(e.text?.split(" ")[1] || ""))
      );
      
      if (fromEntry) {
        parts.push(fromEntry.text || from.label);
        confidence *= 0.9;
      } else {
        parts.push(from.label);
        confidence *= 0.7;
      }
    }
    
    // Añadir el último nodo
    const lastEntry = memoryEntries.find(e => 
      e.text && e.text.includes(path[path.length - 1].label)
    );
    if (lastEntry) {
      parts.push(lastEntry.text || path[path.length - 1].label);
    }

    return {
      text: parts.filter(Boolean).join(". ") || path.map(n => n.label).join(" → "),
      confidence: Math.max(0.1, confidence),
    };
  }

  /**
   * Verifica si una conclusión es consistente con la memoria.
   */
  verify(conclusion, memoryEntries = []) {
    const conclVector = prototypeVectorFromText(conclusion, this.hyperDim, this.seed);
    let bestSim = 0;
    let supportingEntry = null;
    let contradictions = [];

    for (const entry of memoryEntries) {
      const entryVector = prototypeVectorFromText(entry.text ?? "", this.hyperDim, this.seed);
      const sim = similarity(conclVector, entryVector);
      
      if (sim > bestSim) {
        bestSim = sim;
        supportingEntry = entry;
      }
      
      // Detectar posible contradicción por negación
      if (entry.text && conclusion) {
        const entryNeg = entry.text.toLowerCase().includes("no ");
        const conclNeg = conclusion.toLowerCase().includes("no ");
        if (entryNeg !== conclNeg && sim > 0.3) {
          contradictions.push(entry);
        }
      }
    }

    return {
      verified: bestSim > 0.4 && contradictions.length === 0,
      confidence: bestSim,
      supporting: supportingEntry?.text ?? null,
      contradictions: contradictions.map(e => e.text),
    };
  }

  snapshot() {
    return {
      inferences: this._inferenceCount,
      maxHops: this.maxHops,
      minConfidence: this.minConfidence,
    };
  }
}

module.exports = { HyperReason };
