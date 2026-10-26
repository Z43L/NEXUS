/**
 * memory-classifier.js — Clasificación automática de entradas de memoria CHL.
 *
 * Decide el tipo de memoria (user_profile, self_profile, knowledge, etc.)
 * a partir del texto, payload y metadata. Permite override explícito via
 * metadata.memoryType.
 */

const { MemoryType, normalizeMemoryType } = require("./memory-types");
const { normalizeText, tokenize } = require("./utils");

const USER_PROFILE_PATTERNS = [
  /\bme llamo\b/i,
  /\bmi nombre es\b/i,
  /\bsoy\s+[a-záéíóúñ]+(\s+[a-záéíóúñ]+)?\b/i,
  /\btrabajo en\b/i,
  /\bmi proyecto\b/i,
  /\bmi equipo\b/i,
  /\bmi empresa\b/i,
  /\bmi rol\b/i,
  /\bprefiero\b/i,
  /\bme gusta\b/i,
  /\bno me gusta\b/i,
  /\bno quiero\b/i,
  /\bquiero\s+(que|usar|hacer|configurar)\b/i,
  /\bmi (lenguaje|lenguaje favorito|editor|ide|stack|framework)\b/i,
];

const SELF_PROFILE_PATTERNS = [
  /\btu personalidad\b/i,
  /\btu estilo\b/i,
  /\btu rol\b/i,
  /\btu forma de (responder|actuar|hablar)\b/i,
  /\btu (personalidad|estilo|voz|tono|rol)\s+(debe|debería|es|ser)\b/i,
  /\bresponde\s+(siempre|nunca|ahora|con|de|en)\b/i,
  /\bactúa\s+(como|según|con)\b/i,
  /\bcomportate\s+(como|según|con)\b/i,
  /\b(debes|deberías)\s+(responder|actuar|hablar|ser)\b/i,
  /\bresponde como\b/i,
  /\bcomportate como\b/i,
  /\bcomo deberías\b/i,
  /\btú eres\b/i,
  /\btu nombre es\b/i,
  /\bquién eres\b/i,
  /\btu voz\b/i,
  /\btu tono\b/i,
];

const KNOWLEDGE_PATTERNS = [
  /\b(documentación|docs?|manual|guía|referencia)\b/i,
  /\b(código|función|clase|módulo|api|endpoint|librería)\b/i,
  /\b(archivo|fichero|script|configuración|dockerfile)\b/i,
  /\b(qué es|definición de|cómo funciona|para qué sirve)\b/i,
  /\b(base de datos|motor|servidor|cliente|protocolo|formato|estándar)\b/i,
  /\b(es un|es una|son unos|son unas)\s+\w+\b/i,
];

const LONG_TERM_PATTERNS = [
  /\bregla\b/i,
  /\bsiempre\b/i,
  /\bnunca\b/i,
  /\bconsolida\b/i,
  /\bhecho fundamental\b/i,
  /\bdecidimos\b/i,
  /\bdecisi[oó]n\b/i,
];

const EPHEMERAL_PATTERNS = [
  /\b(contexto actual|ahora mismo|en este turno)\b/i,
];

function matchesAny(text, patterns) {
  return patterns.some((p) => p.test(text));
}

function looksLikeCode(text) {
  const codeIndicators = [
    /\bfunction\s+\w+\s*\(/,
    /\bclass\s+\w+/,
    /\bconst\s+\w+\s*=/,
    /\bimport\s+.*?\s+from\s+/,
    /\bdef\s+\w+\s*\(/,
    /\bpublic\s+static\s+void\b/,
    /\breturn\s+.*?;/,
    /\{[\s\S]*\}/,
  ];
  return codeIndicators.some((r) => r.test(text));
}

function looksLikeUserInstruction(text) {
  const instructions = [/\b(?:configura|ajusta|cambia|haz|pon)\b/i];
  return instructions.some((p) => p.test(text));
}

function classifyMemory(input, payload = null, metadata = {}) {
  // 1. Override explícito siempre gana.
  if (metadata.memoryType) {
    return normalizeMemoryType(metadata.memoryType);
  }

  const text = typeof input === "string" ? input : JSON.stringify(input);
  const normalized = normalizeText(text);
  const source = metadata.source ?? "";

  // 2. Fuente conocida.
  if (source === "auto-history") return MemoryType.EPISODIC;
  if (source === "ingest" || source === "file-chunk" || source.startsWith("ingest-")) return MemoryType.KNOWLEDGE;
  if (source === "consolidation" || source === "rule") return MemoryType.LONG_TERM;
  if (source === "user-profile") return MemoryType.USER_PROFILE;
  if (source === "self-profile") return MemoryType.SELF_PROFILE;

  // 3. Payload tipado.
  if (payload && typeof payload === "object") {
    if (payload.memoryType) return normalizeMemoryType(payload.memoryType);
    if (payload.fileType || payload.sourceFile || payload.chunkIndex !== undefined) {
      return MemoryType.KNOWLEDGE;
    }
    if (payload.factType === "rule" || payload.kind === "rule") return MemoryType.LONG_TERM;
  }

  // 4. Detección por contenido.
  if (matchesAny(normalized, SELF_PROFILE_PATTERNS)) return MemoryType.SELF_PROFILE;
  if (matchesAny(normalized, USER_PROFILE_PATTERNS)) return MemoryType.USER_PROFILE;
  if (matchesAny(normalized, LONG_TERM_PATTERNS)) return MemoryType.LONG_TERM;
  if (matchesAny(normalized, KNOWLEDGE_PATTERNS) || looksLikeCode(normalized)) {
    return MemoryType.KNOWLEDGE;
  }
  if (matchesAny(normalized, EPHEMERAL_PATTERNS)) return MemoryType.EPHEMERAL;

  // 5. Si parece una instrucción directa al asistente sobre sí mismo, self-profile.
  if (looksLikeUserInstruction(normalized) && /\b(ti|tú|tu|tu mismo)\b/i.test(normalized)) {
    return MemoryType.SELF_PROFILE;
  }

  // 6. Hechos técnicos sin más contexto: medium_term.
  if (/\b(error|bug|solución|fix|causa|problema|arquitectura)\b/i.test(normalized)) {
    return MemoryType.MEDIUM_TERM;
  }

  return MemoryType.SHORT_TERM;
}

module.exports = {
  classifyMemory,
  USER_PROFILE_PATTERNS,
  SELF_PROFILE_PATTERNS,
  KNOWLEDGE_PATTERNS,
  LONG_TERM_PATTERNS,
  EPHEMERAL_PATTERNS,
};
