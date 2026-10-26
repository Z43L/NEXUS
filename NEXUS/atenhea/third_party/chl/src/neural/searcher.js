/**
 * NeuralSearcher — Capa 4 neuronal (Thought Search)
 * 
 * Búsqueda multi-hop sobre el grafo de conceptos para encontrar
 * caminos de razonamiento entre conceptos de la query y posibles respuestas.
 * 
 * Sin modelos externos: beam search sobre el grafo construido desde
 * la memoria, expandiendo por relaciones semánticas y co-ocurrencias.
 */

const { buildConceptGraph } = require("../graph");
const { analyzeText } = require("../analysis");
const { tokenize, normalizeText } = require("../utils");

class NeuralSearcher {
  constructor(options = {}) {
    this.beamWidth = options.beamWidth ?? 3;
    this.maxDepth = options.maxDepth ?? 3;
    this.minPathScore = options.minPathScore ?? 0.1;
  }

  /**
   * Convierte entries de memoria en un grafo navegable.
   */
  buildGraph(entries) {
    const entryList = [];
    for (const [, entry] of entries) {
      entryList.push({
        id: entry.id,
        text: entry.text,
        payload: entry.payload,
      });
    }
    return buildConceptGraph(entryList);
  }

  /**
   * Beam search desde conceptos de la query hacia posibles respuestas.
   * 
   * Cada nodo en el beam es un path: [startConcept, ...intermediateNodes..., currentNode].
   * Se expande siguiendo aristas del grafo de conceptos.
   * 
   * @returns {Array} Paths ordenados por score, con evidencia acumulada.
   */
  search(query, graph, options = {}) {
    const beamWidth = options.beamWidth ?? this.beamWidth;
    const maxDepth = options.maxDepth ?? this.maxDepth;

    const queryAnalysis = analyzeText(query);
    const queryConcepts = new Set(queryAnalysis.concepts ?? []);
    const queryTokens = new Set(queryAnalysis.focusTokens ?? []);

    // Nodos de partida: conceptos de la query que están en el grafo
    const startNodes = graph.nodes.filter((node) => {
      if (node.type === "concept") return queryConcepts.has(node.label);
      if (node.type === "entity") return queryTokens.has(node.label) || 
        [...queryTokens].some((t) => node.label.includes(t));
      return false;
    });

    if (startNodes.length === 0) {
      // Sin nodos de partida: usar nodos conectados a entries relevantes
      return [];
    }

    // Construir índice de aristas: fromNode → [{to, edge}]
    const adjacency = new Map();
    for (const edge of graph.edges) {
      if (!adjacency.has(edge.from)) adjacency.set(edge.from, []);
      adjacency.get(edge.from).push({ to: edge.to, edge });
      // También aristas inversas para navegación bidireccional
      if (!adjacency.has(edge.to)) adjacency.set(edge.to, []);
      adjacency.get(edge.to).push({ to: edge.from, edge: { ...edge, label: "inv_" + edge.label } });
    }

    // Inicializar beam: un path por cada nodo de partida
    let beam = startNodes.map((node) => ({
      path: [node],
      score: 1.0,
      evidence: [node.evidence ?? []].flat(),
      depth: 0,
    }));

    // Ordenar por score inicial
    beam.sort((a, b) => b.score - a.score);
    beam = beam.slice(0, beamWidth);

    const visited = new Set(startNodes.map((n) => n.id));

    // Expandir beam
    for (let depth = 0; depth < maxDepth; depth++) {
      const candidates = [];

      for (const state of beam) {
        const currentNode = state.path[state.path.length - 1];
        const neighbors = adjacency.get(currentNode.id) ?? [];

        for (const { to, edge } of neighbors) {
          if (visited.has(to)) continue;

          const edgeWeight = (edge.weight ?? 1) / 10;
          const noveltyBonus = 1.0; // Podríamos ajustar según tipo de arista

          const newScore = state.score * (0.6 + 0.4 * edgeWeight) * noveltyBonus;

          if (newScore < this.minPathScore) continue;

          const newPath = [...state.path, to];
          const newEvidence = [...state.evidence, ...(edge.evidence ?? [])];

          candidates.push({
            path: newPath,
            score: newScore,
            evidence: newEvidence,
            depth: depth + 1,
          });
        }
      }

      if (candidates.length === 0) break;

      // Podar beam
      candidates.sort((a, b) => b.score - a.score);
      beam = candidates.slice(0, beamWidth);

      // Marcar visitados
      for (const state of beam) {
        const lastNode = state.path[state.path.length - 1];
        visited.add(lastNode.id);
      }
    }

    // Enriquecer paths con entidades destino (posibles respuestas)
    const enrichedPaths = beam.map((state) => {
      const lastNode = state.path[state.path.length - 1];
      
      // Buscar entries conectadas al último nodo
      const connectedEntries = graph.edges
        .filter((e) => e.to === lastNode.id && e.type === "mentions")
        .map((e) => e.entryId);

      const pathDescription = state.path
        .map((node, i) => {
          if (i === 0) return `[${node.type}] ${node.label}`;
          const prevNode = state.path[i - 1];
          const edge = graph.edges.find(
            (e) => e.from === prevNode.id && e.to === node.id
          );
          return ` → ${edge?.label ?? "?"} → [${node.type}] ${node.label}`;
        })
        .join("");

      return {
        ...state,
        pathDescription,
        connectedEntries,
        nodeTypes: state.path.map((n) => n.type),
        isComplete: connectedEntries.length > 0,
      };
    });

    return enrichedPaths.sort((a, b) => b.score - a.score);
  }

  /**
   * Búsqueda guiada por hipótesis: expande desde cada hipótesis
   * para encontrar evidencia de soporte o refutación.
   */
  expandHypotheses(hypotheses, graph, options = {}) {
    const enriched = [];

    for (const hyp of hypotheses) {
      const evidenceText = hyp.evidence?.text ?? "";
      const evidenceConcepts = hyp.evidence?.concepts ?? [];
      
      // Buscar caminos desde conceptos de la evidencia
      const paths = this.search(evidenceText, graph, options);

      enriched.push({
        ...hyp,
        reasoningPaths: paths,
        pathCount: paths.length,
        bestPath: paths[0] ?? null,
        // Boost score si hay caminos de razonamiento
        reasoningBoost: paths.length > 0 ? 0.1 * Math.min(paths.length, 5) : 0,
      });
    }

    return enriched;
  }
}

module.exports = { NeuralSearcher };
