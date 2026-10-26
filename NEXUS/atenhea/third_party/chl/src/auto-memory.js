/**
 * AutoMemory — Guarda automáticamente cada interacción en CHL.
 *
 * Modos:
 * - "all": guarda TODO (query + respuesta + tool calls + metadatos)
 * - "smart": solo guarda si la interacción parece valiosa (hechos, decisiones, preferencias)
 * - "off": no guarda nada automáticamente
 *
 * Configuración por variables de entorno:
 * - CHL_AUTO_REMEMBER=true|false|all|smart   (default: "smart")
 * - CHL_AUTO_REMEMBER_MIN_LENGTH=20           (mínimo de chars en query para guardar)
 * - CHL_AUTO_REMEMBER_MIN_SCORE=0.3           (score mínimo para modo "smart")
 *
 * Qué guarda:
 * - Query del usuario
 * - Respuesta del agente (resumida si es muy larga)
 * - Timestamp
 * - Tool calls realizadas (nombres + args resumidos)
 * - Session ID
 * - Metadata: duración, modelo usado, tokens, memoryType inferido
 */

const { classifyMemory } = require("./memory-classifier");
const { MemoryType, getDefaultExpiry } = require("./memory-types");

const SIGNAL_PATTERNS = [
  // Preferencias
  /\b(prefiero|me gusta|no me gusta|quiero|no quiero|mejor|peor)\b/i,
  // Decisiones
  /\b(decid[ií]|vamos a|hagamos|usa|usemos|cambia|cambiemos|elige|elijamos)\b/i,
  // Identidad / contexto personal
  /\b(me llamo|mi nombre es|soy|trabajo en|mi proyecto|estoy trabajando|mi equipo)\b/i,
  // Hechos técnicos
  /\b(el error|el bug|la causa|el problema|la solución|el fix)\b/i,
  // Configuración
  /\b(configura|set up|instala|deploy|environment|api key|token)\b/i,
  // Aprendizaje
  /\b(recuerda|apunta|guarda|memoriza|no olvides|ten en cuenta)\b/i,
];

function hasStrongSignal(text = "") {
  return SIGNAL_PATTERNS.some(p => p.test(String(text)));
}

function summarizeResponse(text = "", maxChars = 400) {
  const s = String(text || "").trim();
  if (s.length <= maxChars) return s;
  // Tomar primera parte + última parte
  const first = s.slice(0, Math.floor(maxChars * 0.7));
  const last = s.slice(-Math.floor(maxChars * 0.3));
  return `${first}\n...\n${last}`;
}

function summarizeToolCalls(toolCalls = []) {
  if (!toolCalls || toolCalls.length === 0) return null;
  return toolCalls.map(tc => ({
    tool: tc.function?.name || tc.name || "unknown",
    argsSummary: JSON.stringify(tc.function?.arguments || tc.arguments || {}).slice(0, 150),
  }));
}

/**
 * Decide si una interacción debe guardarse automáticamente.
 *
 * @param {Object} interaction
 * @param {string} interaction.query
 * @param {string} interaction.response
 * @param {Array}  interaction.toolCalls
 * @param {Object} interaction.stats
 * @param {string} mode - "all" | "smart" | "off"
 * @returns {Object} { shouldRemember: boolean, score: number, reason: string }
 */
function evaluateInteraction(interaction, mode = "smart") {
  const query = String(interaction.query || "").trim();
  const response = String(interaction.response || "").trim();
  const minLength = Number(process.env.CHL_AUTO_REMEMBER_MIN_LENGTH) || 20;
  const minScore = Number(process.env.CHL_AUTO_REMEMBER_MIN_SCORE) || 0.3;

  if (mode === "off") return { shouldRemember: false, score: 0, reason: "auto_memory_off" };
  if (!query) return { shouldRemember: false, score: 0, reason: "empty_query" };

  if (mode === "all") {
    return query.length >= minLength
      ? { shouldRemember: true, score: 1, reason: "mode_all" }
      : { shouldRemember: false, score: 0, reason: "query_too_short" };
  }

  // Modo smart
  let score = 0;
  const reasons = [];

  // Señal fuerte en la query
  if (hasStrongSignal(query)) {
    score += 0.5;
    reasons.push("strong_signal");
  }

  // Longitud razonable
  if (query.length >= 30) {
    score += 0.15;
    reasons.push("good_query_length");
  }
  if (response.length >= 50) {
    score += 0.15;
    reasons.push("good_response_length");
  }

  // Tool calls realizadas = interacción productiva
  const toolCalls = interaction.toolCalls || [];
  if (toolCalls.length > 0) {
    score += 0.2;
    reasons.push("tool_calls_present");

    // Si llamó a chl_remember o chl_learn, es explícitamente valioso
    const memoryTools = toolCalls.filter(tc => {
      const name = tc.function?.name || tc.name || "";
      return name === "chl_remember" || name === "chl_learn";
    });
    if (memoryTools.length > 0) {
      score += 0.3;
      reasons.push("explicit_memory_action");
    }
  }

  // Penalización: queries ultra cortas tipo "ok", "si", "vale"
  if (query.length < 8 && /^(ok|si|sí|vale|no|ya|bien|hecho|okay)$/i.test(query)) {
    score -= 0.4;
    reasons.push("trivial_query");
  }

  const shouldRemember = score >= minScore;
  return {
    shouldRemember,
    score: Math.max(0, Math.min(1, score)),
    reason: reasons.join(", ") || "below_threshold",
  };
}

/**
 * Construye el texto de memoria para una interacción.
 */
function buildMemoryEntry(interaction) {
  const query = String(interaction.query || "").trim();
  const response = summarizeResponse(interaction.response || "", 400);
  const toolSummary = summarizeToolCalls(interaction.toolCalls || []);

  const parts = [`[user] ${query}`];

  if (response) {
    parts.push(`[assistant] ${response}`);
  }

  if (toolSummary) {
    parts.push(`[tools] ${JSON.stringify(toolSummary)}`);
  }

  return parts.join("\n");
}

/**
 * Construye el payload estructurado.
 */
function buildMemoryPayload(interaction) {
  return {
    query: String(interaction.query || "").slice(0, 500),
    response: summarizeResponse(interaction.response || "", 600),
    toolCalls: summarizeToolCalls(interaction.toolCalls || []),
    timestamp: new Date().toISOString(),
    sessionId: interaction.sessionId || null,
    stats: interaction.stats || {},
  };
}

function inferMemoryTypeForInteraction(interaction) {
  const query = String(interaction.query || "").trim();
  const response = String(interaction.response || "").trim();
  const text = `${query}\n${response}`.trim();

  // Preferencias / identidad del usuario => user_profile.
  if (/\b(me llamo|mi nombre es|soy |trabajo en|mi proyecto|mi equipo|prefiero|me gusta|no me gusta|quiero que|no quiero)\b/i.test(text)) {
    return MemoryType.USER_PROFILE;
  }
  // Instrucciones sobre la personalidad del asistente => self_profile.
  if (/\b(responde como|act[uú]a como|tu personalidad|tu estilo|tu voz|tu tono|c[oó]mo deber[ií]as)\b/i.test(text)) {
    return MemoryType.SELF_PROFILE;
  }
  // Hechos técnicos duraderos => knowledge, si no medium_term.
  if (/\b(documentaci[oó]n|api|librer[ií]a|framework|arquitectura|patr[oó]n|configuraci[oó]n|deploy|instalaci[oó]n)\b/i.test(text)) {
    return MemoryType.KNOWLEDGE;
  }
  // Decisiones explícitas => long_term.
  if (/\b(decidimos|decisi[oó]n|regla|siempre|nunca|debe ser|deber[ií]amos)\b/i.test(text)) {
    return MemoryType.LONG_TERM;
  }

  // Fallback al clasificador general.
  return classifyMemory(text, null, { source: "auto-memory" });
}

/**
 * Construye metadata ligera con tipo de memoria inferido.
 */
function buildMemoryMetadata(interaction) {
  const toolNames = (interaction.toolCalls || [])
    .map(tc => tc.function?.name || tc.name || "")
    .filter(Boolean);

  const memoryType = inferMemoryTypeForInteraction(interaction);
  const now = Date.now();

  return {
    source: "auto-memory",
    mode: interaction.mode || "smart",
    score: interaction.autoScore || 0,
    toolCount: toolNames.length,
    toolsUsed: toolNames.slice(0, 5),
    durationMs: interaction.stats?.lastTurnMs || 0,
    memoryType,
    createdAt: now,
    expiresAt: getDefaultExpiry(memoryType),
  };
}

module.exports = {
  evaluateInteraction,
  buildMemoryEntry,
  buildMemoryPayload,
  buildMemoryMetadata,
  hasStrongSignal,
  summarizeResponse,
  summarizeToolCalls,
  SIGNAL_PATTERNS,
};
