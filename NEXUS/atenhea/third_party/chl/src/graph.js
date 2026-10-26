const { analyzeText } = require("./analysis");
const { normalizeText } = require("./utils");

const RELATION_PHRASES = [
  "sincroniza con",
  "permanece en",
  "sigue en",
  "se posa en",
  "entra en",
  "llega a",
  "duerme sobre",
  "corre por",
  "nada en",
  "ilumina",
  "abre",
  "cierra",
  "guarda",
  "carga",
  "cubre",
  "suena en",
  "escribe",
  "compra",
  "riega",
  "calienta",
  "muestra",
  "observa",
  "analiza",
  "procesa",
  "encuentra",
  "rastrea",
  "protege",
  "activa",
  "desactiva",
  "recibe",
  "prioriza",
  "aprende",
  "usa",
  "crea",
  "reduce",
];

const RELATION_LABELS = new Map([
  ["sincroniza con", "sincroniza_con"],
  ["permanece en", "permanece_en"],
  ["sigue en", "sigue_en"],
  ["se posa en", "se_posa_en"],
  ["entra en", "entra_en"],
  ["llega a", "llega_a"],
  ["duerme sobre", "duerme_sobre"],
  ["corre por", "corre_por"],
  ["nada en", "nada_en"],
  ["ilumina", "ilumina"],
  ["abre", "abre"],
  ["cierra", "cierra"],
  ["guarda", "guarda"],
  ["carga", "carga"],
  ["cubre", "cubre"],
  ["suena en", "suena_en"],
  ["escribe", "escribe"],
  ["compra", "compra"],
  ["riega", "riega"],
  ["calienta", "calienta"],
  ["muestra", "muestra"],
  ["observa", "observa"],
  ["analiza", "analiza"],
  ["procesa", "procesa"],
  ["encuentra", "encuentra"],
  ["rastrea", "rastrea"],
  ["protege", "protege"],
  ["activa", "activa"],
  ["desactiva", "desactiva"],
  ["recibe", "recibe"],
  ["prioriza", "prioriza"],
  ["aprende", "aprende"],
  ["usa", "usa"],
  ["crea", "crea"],
  ["reduce", "reduce"],
]);

function unique(values = []) {
  return Array.from(new Set(values));
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function cleanLabel(value) {
  return normalizeText(value).replace(/\s+/g, " ").trim();
}

function splitAroundRelation(text) {
  const canonical = cleanLabel(text);
  let bestIndex = -1;
  let bestPhrase = null;
  for (const phrase of RELATION_PHRASES) {
    const index = canonical.search(new RegExp(`\\b${escapeRegExp(phrase)}\\b`));
    if (index === -1) continue;
    if (bestIndex === -1 || index < bestIndex || (index === bestIndex && phrase.length > bestPhrase.length)) {
      bestIndex = index;
      bestPhrase = phrase;
    }
  }
  if (!bestPhrase) return null;
  return {
    subject: canonical.slice(0, bestIndex).trim(),
    relation: bestPhrase,
    object: canonical.slice(bestIndex + bestPhrase.length).trim(),
  };
}

function nodeKey(type, value) {
  return `${type}:${cleanLabel(value)}`;
}

function createNode(nodes, key, node) {
  if (!key || !node) return;
  const existing = nodes.get(key);
  if (existing) {
    existing.count = (existing.count ?? 1) + (node.count ?? 1);
    existing.evidence = unique([...(existing.evidence ?? []), ...(node.evidence ?? [])]);
    return existing;
  }
  nodes.set(key, {
    ...node,
    count: node.count ?? 1,
    evidence: unique(node.evidence ?? []),
  });
  return nodes.get(key);
}

function createEdge(edges, key, edge) {
  if (!key || !edge) return;
  const existing = edges.get(key);
  if (existing) {
    existing.weight = (existing.weight ?? 1) + (edge.weight ?? 1);
    existing.evidence = unique([...(existing.evidence ?? []), ...(edge.evidence ?? [])]);
    return existing;
  }
  edges.set(key, {
    ...edge,
    weight: edge.weight ?? 1,
    evidence: unique(edge.evidence ?? []),
  });
  return edges.get(key);
}

function addEntryGraph(graph, entry) {
  const analysis = entry.representations ?? analyzeText(entry.text ?? "");
  const entryId = `entry:${entry.id}`;

  createNode(graph.nodes, entryId, {
    id: entryId,
    type: "entry",
    label: entry.text ?? "",
    evidence: [entry.id],
  });

  const concepts = unique([...(analysis.concepts ?? []), ...(analysis.focusTokens ?? [])]);
  for (const concept of concepts) {
    const conceptId = nodeKey("concept", concept);
    createNode(graph.nodes, conceptId, {
      id: conceptId,
      type: "concept",
      label: concept,
      evidence: [entry.id],
    });
    createEdge(graph.edges, `${entryId}->${conceptId}:mentions`, {
      from: entryId,
      to: conceptId,
      label: "mentions",
      type: "mentions",
      evidence: [entry.text ?? ""],
      entryId,
    });
  }

  const relation = splitAroundRelation(analysis.canonicalText ?? analysis.normalizedText ?? entry.text ?? "");
  if (relation && relation.subject && relation.object) {
    const subjectId = nodeKey("entity", relation.subject);
    const objectId = nodeKey("entity", relation.object);
    const relationLabel = RELATION_LABELS.get(relation.relation) ?? relation.relation;

    createNode(graph.nodes, subjectId, {
      id: subjectId,
      type: "entity",
      label: relation.subject,
      evidence: [entry.id],
    });
    createNode(graph.nodes, objectId, {
      id: objectId,
      type: "entity",
      label: relation.object,
      evidence: [entry.id],
    });

    createEdge(graph.edges, `${subjectId}->${objectId}:${relationLabel}`, {
      from: subjectId,
      to: objectId,
      label: relationLabel,
      type: "relation",
      evidence: [entry.text ?? ""],
      entryId,
    });
    createEdge(graph.edges, `${entryId}->${subjectId}:subject`, {
      from: entryId,
      to: subjectId,
      label: "subject",
      type: "role",
      evidence: [entry.text ?? ""],
      entryId,
    });
    createEdge(graph.edges, `${entryId}->${objectId}:object`, {
      from: entryId,
      to: objectId,
      label: "object",
      type: "role",
      evidence: [entry.text ?? ""],
      entryId,
    });
  }

  for (const rel of entry.payload?.relations ?? []) {
    if (!rel || rel.value == null) continue;
    const relationKey = cleanLabel(rel.key ?? "relation") || "relation";
    const objectId = nodeKey("entity", rel.value);
    createNode(graph.nodes, objectId, {
      id: objectId,
      type: "entity",
      label: cleanLabel(rel.value),
      evidence: [entry.id],
    });
    createEdge(graph.edges, `${entryId}->${objectId}:${relationKey}`, {
      from: entryId,
      to: objectId,
      label: relationKey,
      type: "payload_relation",
      evidence: [entry.text ?? ""],
      entryId,
    });
  }
}

function buildConceptGraph(entries = []) {
  const graph = {
    nodes: new Map(),
    edges: new Map(),
  };

  for (const entry of entries ?? []) {
    if (!entry) continue;
    addEntryGraph(graph, entry);
  }

  const nodes = Array.from(graph.nodes.values()).sort((a, b) => {
    const aCount = a.count ?? 1;
    const bCount = b.count ?? 1;
    return bCount - aCount || String(a.label).localeCompare(String(b.label));
  });
  const edges = Array.from(graph.edges.values()).sort((a, b) => {
    const aWeight = a.weight ?? 1;
    const bWeight = b.weight ?? 1;
    return bWeight - aWeight || String(a.label).localeCompare(String(b.label));
  });

  return {
    nodes,
    edges,
    stats: {
      nodeCount: nodes.length,
      edgeCount: edges.length,
      conceptCount: nodes.filter((node) => node.type === "concept").length,
      entityCount: nodes.filter((node) => node.type === "entity").length,
      entryCount: nodes.filter((node) => node.type === "entry").length,
    },
  };
}

module.exports = {
  RELATION_LABELS,
  RELATION_PHRASES,
  buildConceptGraph,
  cleanLabel,
  splitAroundRelation,
};
