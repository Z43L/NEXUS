/**
 * memory-types.js — Tipología de memoria y perfiles de scoring para CHL.
 *
 * Define los tipos de memoria que CHL distingue (usuario, IA, conocimiento,
 * episodio, corto/medio/largo plazo), sus tiers temporales y los pesos de
 * scoring adaptativos para cada tipo.
 */

const { clamp } = require("./utils");

const MemoryType = {
  EPHEMERAL: "ephemeral",       // corto plazo volátil (contexto inmediato de sesión)
  SHORT_TERM: "short_term",     // últimas horas/días, auto-history de conversación
  MEDIUM_TERM: "medium_term",   // hechos, decisiones, preferencias recientes
  LONG_TERM: "long_term",       // identidad, reglas consolidadas, conocimiento base
  USER_PROFILE: "user_profile", // preferencias, identidad y estilo del usuario
  SELF_PROFILE: "self_profile", // personalidad, estilo y valores de la IA
  KNOWLEDGE: "knowledge",       // documentos, código, datos ingeridos
  EPISODIC: "episodic",         // historial de conversaciones
};

// Tier temporal: TTL, half-life de decaimiento y si persiste en disco.
const MemoryTier = {
  ephemeral: { ttlMs: 60 * 60 * 1000,       halfLifeMs: 15 * 60 * 1000,  persist: true },
  short:     { ttlMs: 24 * 60 * 60 * 1000,   halfLifeMs: 2 * 60 * 60 * 1000,  persist: true },
  medium:    { ttlMs: 30 * 24 * 60 * 60 * 1000, halfLifeMs: 7 * 24 * 60 * 60 * 1000, persist: true },
  long:      { ttlMs: Infinity,              halfLifeMs: Infinity, persist: true },
};

// Mapeo tipo → tier por defecto.
const TYPE_TO_TIER = {
  [MemoryType.EPHEMERAL]: MemoryTier.ephemeral,
  [MemoryType.SHORT_TERM]: MemoryTier.short,
  [MemoryType.EPISODIC]: MemoryTier.short,
  [MemoryType.MEDIUM_TERM]: MemoryTier.medium,
  [MemoryType.USER_PROFILE]: MemoryTier.medium,
  [MemoryType.SELF_PROFILE]: MemoryTier.long,
  [MemoryType.KNOWLEDGE]: MemoryTier.long,
  [MemoryType.LONG_TERM]: MemoryTier.long,
};

// Prioridad de evicción: memorias de menor valor/contexto se expulsan primero.
// Valor más alto = más difícil de expulsar.
const TIER_EVICTION_PRIORITY = {
  ephemeral: 0.2,
  short: 0.5,
  medium: 1.0,
  long: 2.0,
};

const TYPE_EVICTION_PRIORITY = {
  [MemoryType.EPHEMERAL]: TIER_EVICTION_PRIORITY.ephemeral,
  [MemoryType.SHORT_TERM]: TIER_EVICTION_PRIORITY.short,
  [MemoryType.EPISODIC]: TIER_EVICTION_PRIORITY.short,
  [MemoryType.MEDIUM_TERM]: TIER_EVICTION_PRIORITY.medium,
  [MemoryType.USER_PROFILE]: TIER_EVICTION_PRIORITY.medium,
  [MemoryType.SELF_PROFILE]: TIER_EVICTION_PRIORITY.long,
  [MemoryType.KNOWLEDGE]: TIER_EVICTION_PRIORITY.long,
  [MemoryType.LONG_TERM]: TIER_EVICTION_PRIORITY.long,
};

// Pesos por defecto (profile generalista, igual al fallback actual).
const DEFAULT_WEIGHTS = {
  hash: 0.22,
  hypervector: 0.18,
  concept: 0.16,
  prototype: 0.18,
  intent: 0.12,
  recency: 0.08,
  quality: 0.04,
  negation: 0.02,
};

// Perfiles de scoring por tipo de memoria.
// Cada perfil indica qué dimensiones son más importantes para ese tipo.
const TYPE_SCORING_PROFILES = {
  [MemoryType.USER_PROFILE]: {
    hash: 0.10,
    hypervector: 0.20,
    concept: 0.30,
    prototype: 0.05,
    intent: 0.05,
    recency: 0.15,
    quality: 0.10,
    negation: 0.05,
  },
  [MemoryType.SELF_PROFILE]: {
    hash: 0.08,
    hypervector: 0.18,
    concept: 0.25,
    prototype: 0.05,
    intent: 0.15,
    recency: 0.05,
    quality: 0.20,
    negation: 0.04,
  },
  [MemoryType.KNOWLEDGE]: {
    hash: 0.20,
    hypervector: 0.30,
    concept: 0.20,
    prototype: 0.10,
    intent: 0.05,
    recency: 0.05,
    quality: 0.07,
    negation: 0.03,
  },
  [MemoryType.EPISODIC]: {
    hash: 0.15,
    hypervector: 0.20,
    concept: 0.15,
    prototype: 0.05,
    intent: 0.10,
    recency: 0.30,
    quality: 0.05,
    negation: 0.00,
  },
  [MemoryType.SHORT_TERM]: {
    hash: 0.18,
    hypervector: 0.22,
    concept: 0.18,
    prototype: 0.08,
    intent: 0.06,
    recency: 0.22,
    quality: 0.04,
    negation: 0.02,
  },
  [MemoryType.MEDIUM_TERM]: {
    hash: 0.20,
    hypervector: 0.20,
    concept: 0.22,
    prototype: 0.10,
    intent: 0.08,
    recency: 0.12,
    quality: 0.06,
    negation: 0.02,
  },
  [MemoryType.LONG_TERM]: {
    hash: 0.18,
    hypervector: 0.20,
    concept: 0.25,
    prototype: 0.12,
    intent: 0.10,
    recency: 0.02,
    quality: 0.10,
    negation: 0.03,
  },
  [MemoryType.EPHEMERAL]: {
    hash: 0.15,
    hypervector: 0.15,
    concept: 0.12,
    prototype: 0.05,
    intent: 0.08,
    recency: 0.40,
    quality: 0.03,
    negation: 0.02,
  },
};

const VALID_MEMORY_TYPES = new Set(Object.values(MemoryType));

function normalizeMemoryType(type) {
  if (!type) return MemoryType.SHORT_TERM;
  const normalized = String(type).toLowerCase().trim();
  if (VALID_MEMORY_TYPES.has(normalized)) return normalized;
  return MemoryType.SHORT_TERM;
}

function getTierForType(type) {
  return TYPE_TO_TIER[normalizeMemoryType(type)] ?? MemoryTier.short;
}

function getDefaultExpiry(type) {
  const tier = getTierForType(type);
  if (tier.ttlMs === Infinity) return Infinity;
  return Date.now() + tier.ttlMs;
}

function getEvictionPriority(type) {
  return TYPE_EVICTION_PRIORITY[normalizeMemoryType(type)] ?? 1.0;
}

function getScoringProfile(type) {
  return TYPE_SCORING_PROFILES[normalizeMemoryType(type)] ?? DEFAULT_WEIGHTS;
}

function temporalScore(entry, now = Date.now()) {
  const tier = getTierForType(entry.memoryType);
  if (tier.halfLifeMs === Infinity) return 1;
  const age = Math.max(0, now - (entry.lastAccessAt || entry.createdAt || now));
  return Math.exp(-age / tier.halfLifeMs);
}

function isExpired(entry, now = Date.now()) {
  const expiresAt = typeof entry === "number" ? entry : entry?.expiresAt;
  if (!expiresAt || expiresAt === Infinity) return false;
  return expiresAt < now;
}

module.exports = {
  MemoryType,
  MemoryTier,
  TYPE_SCORING_PROFILES,
  DEFAULT_WEIGHTS,
  TYPE_TO_TIER,
  TIER_EVICTION_PRIORITY,
  TYPE_EVICTION_PRIORITY,
  normalizeMemoryType,
  getTierForType,
  getDefaultExpiry,
  getEvictionPriority,
  getScoringProfile,
  temporalScore,
  isExpired,
};
