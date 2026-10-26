/**
 * query-intent.js — Detección de intención de query para CHL.
 *
 * Clasifica una query del usuario (autorreflexión, recuerdo de perfil,
 * búsqueda de hechos, procedimiento, etc.) y decide qué tipos de memoria
 * deberían recuperarse y con qué pesos.
 */

const { MemoryType, getScoringProfile } = require("./memory-types");
const { normalizeText, tokenize } = require("./utils");

const QueryIntent = {
  SELF_REFLECTION: "self_reflection",       // "quién eres", "tu personalidad"
  USER_RECALL: "user_recall",             // "qué dije", "mi nombre", "prefiero"
  PERSONAL_PREFERENCE: "personal_preference", // "me gusta", "prefiero"
  FACT_LOOKUP: "fact_lookup",             // "qué es", "cómo funciona"
  PROCEDURAL: "procedural",               // "cómo hago", "pasos para"
  GENERAL_CHAT: "general_chat",           // default
};

const INTENT_PATTERNS = {
  [QueryIntent.SELF_REFLECTION]: [
    /\bqui[eé]n eres\b/i,
    /\bqu[eé] eres\b/i,
    /\btu personalidad\b/i,
    /\btu estilo\b/i,
    /\btu voz\b/i,
    /\btu tono\b/i,
    /\btu rol\b/i,
    /\bc[oó]mo act[uú]as\b/i,
    /\bc[oó]mo deber[ií]as (responder|actuar|hablar)\b/i,
    /\bresponde como\b/i,
    /\bcomportate como\b/i,
    /\bt[uú] eres\b/i,
  ],
  [QueryIntent.USER_RECALL]: [
    /\bqu[eé] (dije|dijimos|hablamos|decid[ií]|decidimos)\b/i,
    /\brecuerdas (que|cu[aá]ndo|lo de)\b/i,
    /\bmi nombre\b/i,
    /\bc[oó]mo me llamo\b/i,
    /\bmi (proyecto|equipo|empresa|rol|trabajo)\b/i,
    /\blo que te dije\b/i,
    /\bhablamos de\b/i,
  ],
  [QueryIntent.PERSONAL_PREFERENCE]: [
    /\bme gusta\b/i,
    /\bno me gusta\b/i,
    /\bprefiero\b/i,
    /\bno prefiero\b/i,
    /\bno quiero\b/i,
    /\bquiero\b/i,
    /\bmi (preferencia|configuraci[oó]n|estilo)\b/i,
  ],
  [QueryIntent.FACT_LOOKUP]: [
    /\bqu[eé] es\b/i,
    /\bc[oó]mo funciona\b/i,
    /\bpara qu[eé] sirve\b/i,
    /\bdefinici[oó]n de\b/i,
    /\bexplica\b/i,
    /\bdime sobre\b/i,
    /\binformaci[oó]n sobre\b/i,
  ],
  [QueryIntent.PROCEDURAL]: [
    /\bc[oó]mo (hago|se hace|puedo|debo)\b/i,
    /\bpasos para\b/i,
    /\bgu[ií]a (de|para)\b/i,
    /\btutorial\b/i,
    /\bc[oó]mo (instalar|configurar|deployar|desplegar|usar|implementar)\b/i,
    /\bpasos? (necesarios|para)\b/i,
  ],
};

const INTENT_PRIORITY_ORDER = [
  QueryIntent.SELF_REFLECTION,
  QueryIntent.USER_RECALL,
  QueryIntent.PERSONAL_PREFERENCE,
  QueryIntent.PROCEDURAL,
  QueryIntent.FACT_LOOKUP,
];

const INTENT_TO_MEMORY_TYPES = {
  [QueryIntent.SELF_REFLECTION]: [MemoryType.SELF_PROFILE, MemoryType.LONG_TERM, MemoryType.SHORT_TERM],
  [QueryIntent.USER_RECALL]: [MemoryType.USER_PROFILE, MemoryType.EPISODIC, MemoryType.MEDIUM_TERM, MemoryType.SHORT_TERM],
  [QueryIntent.PERSONAL_PREFERENCE]: [MemoryType.USER_PROFILE, MemoryType.MEDIUM_TERM, MemoryType.EPISODIC],
  [QueryIntent.FACT_LOOKUP]: [MemoryType.KNOWLEDGE, MemoryType.LONG_TERM, MemoryType.MEDIUM_TERM],
  [QueryIntent.PROCEDURAL]: [MemoryType.KNOWLEDGE, MemoryType.MEDIUM_TERM, MemoryType.LONG_TERM],
  [QueryIntent.GENERAL_CHAT]: [MemoryType.SHORT_TERM, MemoryType.EPISODIC, MemoryType.MEDIUM_TERM],
};

// Pesos de boost para tipos objetivo en cada intent.
// Se aplican como bonus multiplicativo sobre el score cuando un candidato
// pertenece a un tipo objetivo.
const INTENT_TYPE_BOOST = {
  [QueryIntent.SELF_REFLECTION]: {
    [MemoryType.SELF_PROFILE]: 0.25,
    [MemoryType.LONG_TERM]: 0.10,
  },
  [QueryIntent.USER_RECALL]: {
    [MemoryType.USER_PROFILE]: 0.30,
    [MemoryType.EPISODIC]: 0.15,
    [MemoryType.MEDIUM_TERM]: 0.05,
  },
  [QueryIntent.PERSONAL_PREFERENCE]: {
    [MemoryType.USER_PROFILE]: 0.35,
    [MemoryType.MEDIUM_TERM]: 0.10,
  },
  [QueryIntent.FACT_LOOKUP]: {
    [MemoryType.KNOWLEDGE]: 0.25,
    [MemoryType.LONG_TERM]: 0.10,
  },
  [QueryIntent.PROCEDURAL]: {
    [MemoryType.KNOWLEDGE]: 0.20,
    [MemoryType.MEDIUM_TERM]: 0.10,
  },
  [QueryIntent.GENERAL_CHAT]: {
    [MemoryType.SHORT_TERM]: 0.05,
    [MemoryType.EPISODIC]: 0.05,
  },
};

function detectQueryIntent(query) {
  const normalized = normalizeText(query);

  for (const intent of INTENT_PRIORITY_ORDER) {
    const patterns = INTENT_PATTERNS[intent];
    if (patterns && patterns.some((p) => p.test(normalized))) {
      return intent;
    }
  }
  return QueryIntent.GENERAL_CHAT;
}

function intentToMemoryTypes(intent) {
  return INTENT_TO_MEMORY_TYPES[intent] ?? INTENT_TO_MEMORY_TYPES[QueryIntent.GENERAL_CHAT];
}

function getTypeBoostForIntent(intent, memoryType) {
  const boosts = INTENT_TYPE_BOOST[intent] ?? {};
  return boosts[memoryType] ?? 0;
}

function getScoringProfileForIntent(intent, memoryType) {
  // Empieza con el perfil del tipo de memoria y ajusta ligeramente según intent.
  const baseProfile = getScoringProfile(memoryType);
  const intentTypes = intentToMemoryTypes(intent);

  const profile = { ...baseProfile };

  // Si el tipo de la entrada está entre los objetivos del intent, subir recency y quality.
  if (intentTypes.includes(memoryType)) {
    profile.recency = Math.min(0.5, profile.recency + 0.08);
    profile.quality = Math.min(0.25, profile.quality + 0.05);
  }

  return profile;
}

function buildQueryOptions(query, options = {}) {
  const intent = options.intent ? String(options.intent).toLowerCase() : detectQueryIntent(query);
  let targetTypes;
  if (options.memoryTypes) {
    targetTypes = options.memoryTypes;
  } else if (options.includeTypes) {
    targetTypes = options.includeTypes;
  } else if (options.memoryType) {
    targetTypes = [options.memoryType];
  } else {
    targetTypes = intentToMemoryTypes(intent);
  }

  return {
    ...options,
    queryIntent: intent,
    memoryTypes: targetTypes,
    typeBoosts: INTENT_TYPE_BOOST[intent] ?? {},
  };
}

module.exports = {
  QueryIntent,
  INTENT_PATTERNS,
  INTENT_TO_MEMORY_TYPES,
  INTENT_TYPE_BOOST,
  detectQueryIntent,
  intentToMemoryTypes,
  getTypeBoostForIntent,
  getScoringProfileForIntent,
  buildQueryOptions,
};
