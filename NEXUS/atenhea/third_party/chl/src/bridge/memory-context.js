/**
 * MemoryContext — Formatea memorias CHL como contexto optimizado para LLMs.
 *
 * Toma los candidatos recuperados por CHL (C++ nativo, μs) y
 * los empaqueta en un bloque de sistema token-efficient para
 * cualquier modelo grande (GPT-5, Claude, Gemini, Ollama, etc.).
 *
 * Principios:
 * - Priorizar señales fuertes (score alto, verificado, frecuente)
 * - Deducir entradas redundantes o de baja señal
 * - Presupuesto de tokens configurable
 * - Estructura que el modelo entienda sin instrucciones extra
 */

const { clamp } = require("../utils");

function unique(arr = []) {
  return Array.from(new Set(arr));
}

function estimateTokens(text = "") {
  return Math.max(1, Math.ceil(String(text).length / 4));
}

/**
 * Puntúa una memoria para ordenar por relevancia compuesta.
 */
function scoreMemory(entry, idx, queryTokens = []) {
  let score = 0;
  const text = String(entry.text || entry.input || "").toLowerCase();

  // Score base del motor CHL
  score += (entry.score || entry.similarity || 0.5) * 0.4;

  // Overlap léxico con la query
  if (queryTokens.length > 0) {
    let hits = 0;
    for (const t of queryTokens) {
      if (text.includes(t.toLowerCase())) hits++;
    }
    score += (hits / Math.max(1, queryTokens.length)) * 0.3;
  }

  // Recencia: entradas más recientes pesan más
  if (typeof idx === "number") {
    score += (1 / (idx + 2)) * 0.15;
  }

  // Verificadas pesan más
  if (entry.verified || entry.confidence > 0.7) score += 0.15;

  return score;
}

/**
 * Construye el contexto de sistema para el LLM a partir de memorias CHL.
 *
 * @param {Object} opts
 * @param {Array}  opts.memories      - candidatos de chl_recall / semanticNavigate
 * @param {Array}  opts.concepts      - conceptos del lexicon (opcional)
 * @param {Array}  opts.graphEdges    - relaciones del grafo de conceptos (opcional)
 * @param {string} opts.query         - query original del usuario
 * @param {number} opts.maxTokens     - presupuesto máximo de tokens (default 2000)
 * @param {Object} opts.profile       - perfil del usuario desde CHL
 * @returns {string} bloque de contexto formateado
 */
function buildMemoryContext(opts = {}) {
  const {
    memories = [],
    concepts = [],
    graphEdges = [],
    query = "",
    maxTokens = 2000,
    profile = null,
  } = opts;

  const queryTokens = String(query || "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);

  // Ordenar memorias por score compuesto
  const ranked = memories
    .map((m, i) => ({
      entry: m.entry || m,
      score: scoreMemory(m.entry || m, i, queryTokens),
    }))
    .sort((a, b) => b.score - a.score);

  // Deducir near-duplicados
  const seenTexts = new Set();
  const deduped = [];
  for (const { entry, score } of ranked) {
    const text = String(entry.text || entry.input || "").trim();
    const sig = text.slice(0, 80).toLowerCase();
    if (seenTexts.has(sig)) continue;
    if (!text && !entry.payload) continue;
    seenTexts.add(sig);
    deduped.push({ entry, score });
  }

  // Construir secciones dentro del budget
  let budget = clamp(maxTokens, 200, 8000);
  const sections = [];

  // ─── Perfil de usuario ───
  if (profile && (profile.name || profile.preferences)) {
    const profileBlock = [];
    if (profile.name) profileBlock.push(`Usuario: ${profile.name}`);
    if (profile.preferences) {
      const prefs = typeof profile.preferences === "string"
        ? profile.preferences
        : JSON.stringify(profile.preferences);
      profileBlock.push(`Preferencias: ${prefs}`);
    }
    const profileText = profileBlock.join("\n");
    const profileTokens = estimateTokens(profileText);
    if (profileTokens < budget * 0.2) {
      sections.push({ label: "Perfil", text: profileText, tokens: profileTokens });
      budget -= profileTokens;
    }
  }

  // ─── Conceptos clave ───
  if (concepts.length > 0) {
    const topConcepts = concepts.slice(0, 20);
    const conceptText = "Conceptos: " + topConcepts.map(c =>
      typeof c === "string" ? c : (c.label || c.concept || c.token || "")
    ).filter(Boolean).join(", ");
    const cTokens = estimateTokens(conceptText);
    if (cTokens < budget * 0.15) {
      sections.push({ label: "Conceptos", text: conceptText, tokens: cTokens });
      budget -= cTokens;
    }
  }

  // ─── Relaciones del grafo ───
  if (graphEdges.length > 0) {
    const edgeLines = graphEdges.slice(0, 12).map(e =>
      `${e.source || e.from || "?"} → ${e.target || e.to || "?"}${e.label ? ` (${e.label})` : ""}`
    );
    const edgeText = "Relaciones:\n" + edgeLines.join("\n");
    const eTokens = estimateTokens(edgeText);
    if (eTokens < budget * 0.15) {
      sections.push({ label: "Relaciones", text: edgeText, tokens: eTokens });
      budget -= eTokens;
    }
  }

  // ─── Memorias agrupadas por tipo ───
  const TYPE_LABELS = {
    user_profile: "Perfil del usuario",
    self_profile: "Personalidad de la IA",
    knowledge: "Conocimiento",
    long_term: "Memoria a largo plazo",
    medium_term: "Memoria a medio plazo",
    short_term: "Memoria a corto plazo",
    episodic: "Episodios",
    ephemeral: "Contexto efímero",
  };

  const TYPE_PRIORITY = [
    "user_profile",
    "self_profile",
    "knowledge",
    "long_term",
    "medium_term",
    "episodic",
    "short_term",
    "ephemeral",
  ];

  const grouped = new Map();
  let memTokens = 0;
  const memBudget = budget;

  for (const { entry, score } of deduped) {
    const text = String(entry.text || entry.input || "").trim();
    if (!text) continue;
    const payload = entry.payload
      ? (typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload))
      : null;
    const metadata = entry.metadata
      ? (typeof entry.metadata === "string" ? entry.metadata : JSON.stringify(entry.metadata))
      : null;

    let line = text;
    if (payload && payload !== text && String(payload).length < 200) line += ` [${payload}]`;
    if (metadata && String(metadata).length < 120) line += ` (meta: ${metadata})`;

    const lineTokens = estimateTokens(line);
    if (memTokens + lineTokens > memBudget) break;

    const scoreLabel = score >= 0.95 ? "●" : score >= 0.8 ? "★★★" : score >= 0.6 ? "★★" : score >= 0.4 ? "★" : "·";
    const memoryType = entry.memoryType || "short_term";
    if (!grouped.has(memoryType)) grouped.set(memoryType, []);
    grouped.get(memoryType).push(`${scoreLabel} ${line}`);
    memTokens += lineTokens;
  }

  for (const type of TYPE_PRIORITY) {
    const lines = grouped.get(type);
    if (!lines || lines.length === 0) continue;
    const label = TYPE_LABELS[type] || "Memoria";
    const text = lines.join("\n");
    sections.push({ label, text, tokens: estimateTokens(text) });
  }

  // ─── Ensamblar ───
  const header = query
    ? `[Contexto CHL para: "${query.slice(0, 200)}"]`
    : "[Contexto CHL]";

  const body = sections
    .map(s => `## ${s.label}\n${s.text}`)
    .join("\n\n");

  return `${header}\n\n${body}`;
}

/**
 * Versión compacta para cuando el budget de tokens es muy restrictivo (< 500).
 */
function buildCompactMemoryContext(memories = [], query = "") {
  const queryTokens = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);

  const ranked = memories
    .map((m, i) => {
      const entry = m.entry || m;
      return {
        text: String(entry.text || entry.input || "").trim(),
        score: scoreMemory(entry, i, queryTokens),
      };
    })
    .filter(m => m.text)
    .sort((a, b) => b.score - a.score)
    .slice(0, 8);

  const lines = ranked.map(r => {
    const prefix = r.score >= 0.7 ? "✓" : r.score >= 0.4 ? "~" : "·";
    return `${prefix} ${r.text.slice(0, 200)}`;
  });

  const header = query ? `CHL: "${query.slice(0, 120)}"` : "CHL";
  return `${header}\n${lines.join("\n")}`;
}

module.exports = {
  buildMemoryContext,
  buildCompactMemoryContext,
  scoreMemory,
  estimateTokens,
};
