const { tokenize, normalizeText } = require("./utils");
const { conceptualizeTokens } = require("./concepts");

function textOfEntry(entry) {
  if (!entry) return "";
  if (typeof entry.text === "string") return entry.text;
  if (typeof entry.input === "string") return entry.input;
  if (typeof entry.payload === "string") return entry.payload;
  try {
    return JSON.stringify(entry.payload ?? entry);
  } catch {
    return String(entry ?? "");
  }
}

function clamp01(v) {
  const x = Number(v);
  if (!Number.isFinite(x)) return 0;
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

function incNested(map, a, b, delta = 1) {
  let row = map.get(a);
  if (!row) {
    row = new Map();
    map.set(a, row);
  }
  row.set(b, (row.get(b) ?? 0) + delta);
}

function buildVocabAndConcepts(entries, options = {}) {
  const minTokenLen = Math.max(2, Number(options.minTokenLen ?? 3));
  const maxTokensPerEntry = Math.max(8, Number(options.maxTokensPerEntry ?? 80));
  const maxConceptsPerEntry = Math.max(4, Number(options.maxConceptsPerEntry ?? 48));

  const tokenFreq = new Map();
  const conceptFreq = new Map();
  const entrySignals = [];

  for (const entry of entries) {
    const raw = textOfEntry(entry);
    const text = normalizeText(raw);
    const tokens = tokenize(text)
      .filter((t) => t.length >= minTokenLen)
      .slice(0, maxTokensPerEntry);
    const concepts = conceptualizeTokens(text).slice(0, maxConceptsPerEntry);

    for (const t of tokens) tokenFreq.set(t, (tokenFreq.get(t) ?? 0) + 1);
    for (const c of concepts) conceptFreq.set(c, (conceptFreq.get(c) ?? 0) + 1);
    entrySignals.push({ text, tokens, concepts, entry });
  }

  const tokenDim = [...tokenFreq.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([t]) => t);
  const conceptDim = [...conceptFreq.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([c]) => c);

  const tokenIndex = new Map(tokenDim.map((t, i) => [t, i]));
  const conceptIndex = new Map(conceptDim.map((c, i) => [c, i]));
  return { tokenDim, conceptDim, tokenIndex, conceptIndex, entrySignals };
}

function buildSemanticTensor(entries = [], episodes = [], options = {}) {
  const hashBits = Math.max(64, Number(options.hashBits ?? 128));
  const maxTriples = Math.max(5000, Number(options.maxTriples ?? 500000));
  const relWeight = Number(options.relationWeight ?? 1.6);
  const epiWeight = Number(options.episodeWeight ?? 1.3);
  const tokenWeight = Number(options.tokenWeight ?? 1.0);
  const conceptWeight = Number(options.conceptWeight ?? 1.2);

  const {
    tokenDim,
    conceptDim,
    tokenIndex,
    conceptIndex,
    entrySignals,
  } = buildVocabAndConcepts(entries, options);

  // Sparse channels:
  // C0 token-token cooccurrence
  // C1 concept-concept cooccurrence
  // C2 token-concept links
  // C3 relation-like sequence links from episodes/assistant outputs
  const c0 = new Map();
  const c1 = new Map();
  const c2 = new Map();
  const c3 = new Map();

  for (const s of entrySignals) {
    const uniqTokens = [...new Set(s.tokens)];
    const uniqConcepts = [...new Set(s.concepts)];

    for (let i = 0; i < uniqTokens.length; i++) {
      const a = tokenIndex.get(uniqTokens[i]);
      if (a == null) continue;
      for (let j = i + 1; j < uniqTokens.length; j++) {
        const b = tokenIndex.get(uniqTokens[j]);
        if (b == null) continue;
        incNested(c0, a, b, tokenWeight);
        incNested(c0, b, a, tokenWeight);
      }
    }

    for (let i = 0; i < uniqConcepts.length; i++) {
      const a = conceptIndex.get(uniqConcepts[i]);
      if (a == null) continue;
      for (let j = i + 1; j < uniqConcepts.length; j++) {
        const b = conceptIndex.get(uniqConcepts[j]);
        if (b == null) continue;
        incNested(c1, a, b, conceptWeight);
        incNested(c1, b, a, conceptWeight);
      }
    }

    for (const t of uniqTokens) {
      const ti = tokenIndex.get(t);
      if (ti == null) continue;
      for (const c of uniqConcepts) {
        const ci = conceptIndex.get(c);
        if (ci == null) continue;
        incNested(c2, ti, ci, Math.sqrt(tokenWeight * conceptWeight));
      }
    }
  }

  // Extract sequence/relational links from episodes (if available)
  for (const ep of episodes ?? []) {
    const text = normalizeText(String(ep?.responseText ?? ep?.generatedText ?? ep?.query ?? ""));
    const toks = tokenize(text).filter((t) => tokenIndex.has(t));
    for (let i = 0; i < toks.length - 1; i++) {
      const a = tokenIndex.get(toks[i]);
      const b = tokenIndex.get(toks[i + 1]);
      incNested(c3, a, b, epiWeight);
    }
    const confidence = clamp01(ep?.confidence ?? 0.5);
    if (toks.length >= 3) {
      const a = tokenIndex.get(toks[0]);
      const b = tokenIndex.get(toks[Math.floor(toks.length / 2)]);
      const c = tokenIndex.get(toks[toks.length - 1]);
      if (a != null && b != null) incNested(c3, a, b, relWeight * (0.5 + confidence));
      if (b != null && c != null) incNested(c3, b, c, relWeight * (0.5 + confidence));
    }
  }

  function toTriples(channelMap, channelId, limit = maxTriples) {
    const out = [];
    for (const [i, row] of channelMap.entries()) {
      for (const [j, value] of row.entries()) {
        out.push([channelId, i, j, Number(value.toFixed(6))]);
      }
    }
    out.sort((a, b) => b[3] - a[3]);
    return out.slice(0, limit);
  }

  const triples = [
    ...toTriples(c0, 0),
    ...toTriples(c1, 1),
    ...toTriples(c2, 2),
    ...toTriples(c3, 3),
  ];

  // Compact "hash-plane" per entry: summarize semantic hashes as dense bit means.
  // This is useful as an auxiliary channel for later training.
  const hashPlane = new Array(hashBits).fill(0);
  let hashCount = 0;
  for (const s of entrySignals) {
    const raw = s.entry?.hash;
    if (!raw || typeof raw.length !== "number") continue;
    for (let bit = 0; bit < hashBits; bit++) {
      const word = raw[bit >>> 5] ?? 0;
      hashPlane[bit] += (word & (1 << (bit & 31))) !== 0 ? 1 : 0;
    }
    hashCount += 1;
  }
  if (hashCount > 0) {
    for (let i = 0; i < hashPlane.length; i++) hashPlane[i] = hashPlane[i] / hashCount;
  }

  return {
    type: "chl-semantic-tensor-v1",
    createdAt: new Date().toISOString(),
    dims: {
      tokens: tokenDim.length,
      concepts: conceptDim.length,
      channels: 4,
      hashBits,
    },
    lexicon: {
      tokens: tokenDim,
      concepts: conceptDim,
    },
    tensor: {
      // Sparse COO-like [channel, i, j, weight]
      triples,
      hashPlane,
    },
    stats: {
      entries: entries.length,
      episodes: (episodes ?? []).length,
      triples: triples.length,
    },
  };
}

function tensorToTrainingJsonl(tensor, options = {}) {
  const maxRows = Math.max(100, Number(options.maxRows ?? 100000));
  const out = [];
  const tokens = tensor?.lexicon?.tokens ?? [];
  const concepts = tensor?.lexicon?.concepts ?? [];
  const triples = tensor?.tensor?.triples ?? [];

  for (const [channel, i, j, w] of triples) {
    if (out.length >= maxRows) break;
    if (channel === 0) {
      const a = tokens[i];
      const b = tokens[j];
      if (!a || !b) continue;
      out.push(JSON.stringify({
        text: `Relacion semantica entre tokens: ${a} <-> ${b}. Peso=${w}.`,
      }));
    } else if (channel === 1) {
      const a = concepts[i];
      const b = concepts[j];
      if (!a || !b) continue;
      out.push(JSON.stringify({
        text: `Relacion conceptual: ${a} se asocia con ${b}. Fuerza=${w}.`,
      }));
    } else if (channel === 2) {
      const t = tokens[i];
      const c = concepts[j];
      if (!t || !c) continue;
      out.push(JSON.stringify({
        text: `Token-concepto: "${t}" aporta al concepto "${c}" con peso ${w}.`,
      }));
    } else if (channel === 3) {
      const a = tokens[i];
      const b = tokens[j];
      if (!a || !b) continue;
      out.push(JSON.stringify({
        text: `Patron secuencial: despues de "${a}" suele aparecer "${b}" (peso ${w}).`,
      }));
    }
  }

  return out;
}

function tensorToSpecializedMemoryJsonl(tensor, options = {}) {
  const maxRows = Math.max(100, Number(options.maxRows ?? 120000));
  const maxPerChannel = Math.max(20, Number(options.maxPerChannel ?? Math.floor(maxRows / 4)));
  const tokens = tensor?.lexicon?.tokens ?? [];
  const concepts = tensor?.lexicon?.concepts ?? [];
  const triples = Array.isArray(tensor?.tensor?.triples) ? tensor.tensor.triples : [];

  const byChannel = [[], [], [], []];
  for (const t of triples) {
    const ch = t[0];
    if (ch >= 0 && ch <= 3) byChannel[ch].push(t);
  }
  for (const arr of byChannel) arr.sort((a, b) => b[3] - a[3]);

  const out = [];
  const pushPair = (prompt, completion) => {
    if (out.length >= maxRows) return;
    out.push(JSON.stringify({ prompt, completion }));
  };

  // C0 token-token: asociación léxica
  for (const [, i, j, w] of byChannel[0].slice(0, maxPerChannel)) {
    const a = tokens[i];
    const b = tokens[j];
    if (!a || !b) continue;
    pushPair(
      `Memoria CHL: ¿Qué término está fuertemente asociado con "${a}"?`,
      `Un término altamente asociado es "${b}" (fuerza ${w}).`
    );
    pushPair(
      `Memoria CHL: completa la asociación "${a}" -> ?`,
      `${b}`
    );
  }

  // C1 concept-concept: relación conceptual
  for (const [, i, j, w] of byChannel[1].slice(0, maxPerChannel)) {
    const a = concepts[i];
    const b = concepts[j];
    if (!a || !b) continue;
    pushPair(
      `Memoria CHL conceptual: describe la relación entre "${a}" y "${b}".`,
      `En CHL, "${a}" y "${b}" aparecen relacionados con fuerza ${w}.`
    );
  }

  // C2 token-concept: grounding token->concepto
  for (const [, i, j, w] of byChannel[2].slice(0, maxPerChannel)) {
    const t = tokens[i];
    const c = concepts[j];
    if (!t || !c) continue;
    pushPair(
      `Grounding CHL: ¿A qué concepto se vincula el token "${t}"?`,
      `El token "${t}" se vincula al concepto "${c}" (peso ${w}).`
    );
    pushPair(
      `CHL semántico: token "${t}", responde solo el concepto principal.`,
      `${c}`
    );
  }

  // C3 secuencia: siguiente elemento probable
  for (const [, i, j, w] of byChannel[3].slice(0, maxPerChannel)) {
    const a = tokens[i];
    const b = tokens[j];
    if (!a || !b) continue;
    pushPair(
      `Memoria secuencial CHL: después de "${a}" ¿qué token suele venir?`,
      `Suele aparecer "${b}" (peso secuencial ${w}).`
    );
  }

  return out.slice(0, maxRows);
}

module.exports = {
  buildSemanticTensor,
  tensorToTrainingJsonl,
  tensorToSpecializedMemoryJsonl,
};
