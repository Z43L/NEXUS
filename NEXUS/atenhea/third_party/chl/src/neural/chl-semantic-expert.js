const { analyzeText } = require("../analysis");

function unique(values = []) {
  return Array.from(new Set(values.filter(Boolean)));
}

function expandQueryVariants(query, options = {}) {
  const text = String(query ?? "").trim();
  const a = analyzeText(text);
  const focus = unique(a.focusTokens ?? []).slice(0, 8);
  const concepts = unique(a.concepts ?? []).slice(0, 8);
  const bigrams = unique(a.tokenBigrams ?? []).slice(0, 6);

  const variants = [
    text,
    focus.join(" "),
    concepts.join(" "),
    [...focus.slice(0, 4), ...concepts.slice(0, 4)].join(" "),
    bigrams.slice(0, 3).join(" "),
  ].map((v) => String(v || "").trim()).filter(Boolean);

  // Variantes de intención de memoria: mejora recuperación en CHL con ruido.
  const intentPrefix = [
    "contexto clave",
    "hechos relevantes",
    "memoria semantica",
  ];
  for (const p of intentPrefix) {
    if (focus.length > 0) variants.push(`${p} ${focus.slice(0, 3).join(" ")}`.trim());
  }

  return unique(variants).slice(0, Math.max(3, Number(options.maxVariants ?? 10)));
}

function normalizeCandidateScore(c = {}) {
  const s1 = Number(c.score ?? 0);
  const s2 = Number(c.similarity ?? 0);
  if (Number.isFinite(s1) && Number.isFinite(s2)) return 0.7 * s1 + 0.3 * s2;
  if (Number.isFinite(s1)) return s1;
  if (Number.isFinite(s2)) return s2;
  return 0;
}

function lexicalOverlapBoost(query, text) {
  const q = analyzeText(query);
  const t = analyzeText(text);
  const qSet = new Set(q.focusTokens ?? []);
  const tSet = new Set(t.focusTokens ?? []);
  if (!qSet.size || !tSet.size) return 0;
  let inter = 0;
  for (const tok of qSet) if (tSet.has(tok)) inter += 1;
  const ratio = inter / Math.max(1, Math.min(qSet.size, tSet.size));
  return 0.12 * ratio;
}

function conceptOverlapBoost(query, text) {
  const q = analyzeText(query);
  const t = analyzeText(text);
  const qSet = new Set(q.concepts ?? []);
  const tSet = new Set(t.concepts ?? []);
  if (!qSet.size || !tSet.size) return 0;
  let inter = 0;
  for (const c of qSet) if (tSet.has(c)) inter += 1;
  const ratio = inter / Math.max(1, Math.min(qSet.size, tSet.size));
  return 0.14 * ratio;
}

function noveltyPenalty(entryText, selectedTexts) {
  if (!selectedTexts.length) return 0;
  const a = new Set(analyzeText(entryText).focusTokens ?? []);
  let maxSim = 0;
  for (const s of selectedTexts) {
    const b = new Set(analyzeText(s).focusTokens ?? []);
    if (!a.size || !b.size) continue;
    let inter = 0;
    for (const tok of a) if (b.has(tok)) inter += 1;
    const sim = inter / Math.max(1, Math.min(a.size, b.size));
    if (sim > maxSim) maxSim = sim;
  }
  // Penaliza candidatos demasiado parecidos para fomentar diversidad contextual.
  return maxSim > 0.8 ? 0.1 : maxSim > 0.65 ? 0.05 : 0;
}

async function navigateSemanticMemory(query, recallFn, options = {}) {
  const variants = expandQueryVariants(query, options);
  const perVariantTopK = Math.max(3, Number(options.perVariantTopK ?? 8));
  const targetTopK = Math.max(3, Number(options.targetTopK ?? 12));

  const merged = new Map();
  const evidence = [];

  for (const v of variants) {
    let result;
    try {
      result = await recallFn(v, { topK: perVariantTopK });
    } catch {
      continue;
    }
    const candidates = result?.candidates ?? [];
    evidence.push({ variant: v, hits: candidates.length });

    for (let rank = 0; rank < candidates.length; rank++) {
      const c = candidates[rank];
      const entry = c?.entry;
      if (!entry?.id) continue;
      const base = normalizeCandidateScore(c);
      const rankBoost = 0.07 * (1 - rank / Math.max(1, perVariantTopK));
      const overlap = lexicalOverlapBoost(query, entry.text ?? "");
      const conceptBoost = conceptOverlapBoost(query, entry.text ?? "");
      const score = base + rankBoost + overlap + conceptBoost;

      const prev = merged.get(entry.id) ?? {
        entry,
        scoreSum: 0,
        votes: 0,
        bestScore: -Infinity,
        firstRank: rank,
      };
      prev.scoreSum += score;
      prev.votes += 1;
      prev.bestScore = Math.max(prev.bestScore, score);
      prev.firstRank = Math.min(prev.firstRank, rank);
      merged.set(entry.id, prev);
    }
  }

  const preRanked = [...merged.values()]
    .map((x) => ({
      entry: x.entry,
      score: x.scoreSum / Math.max(1, x.votes) + 0.06 * x.votes + 0.04 * (1 - x.firstRank / Math.max(1, perVariantTopK)),
      votes: x.votes,
      bestScore: x.bestScore,
    }))
    .sort((a, b) => b.score - a.score);

  // Selección final con diversidad para mejorar el contexto lingüístico.
  const reranked = [];
  const selectedTexts = [];
  for (const item of preRanked) {
    const txt = String(item?.entry?.text ?? "");
    const penalty = noveltyPenalty(txt, selectedTexts);
    const adjusted = item.score - penalty;
    if (adjusted <= 0) continue;
    reranked.push({ ...item, score: adjusted, diversityPenalty: penalty });
    selectedTexts.push(txt);
    if (reranked.length >= targetTopK) break;
  }

  return {
    variants,
    reranked,
    evidence,
  };
}

function extractExpansionTerms(texts = [], maxTerms = 8) {
  const bag = new Map();
  for (const txt of texts) {
    const a = analyzeText(String(txt ?? ""));
    for (const tok of a.focusTokens ?? []) {
      if (!tok || tok.length < 3) continue;
      bag.set(tok, (bag.get(tok) ?? 0) + 1);
    }
    for (const c of a.concepts ?? []) {
      if (!c || c.length < 3) continue;
      bag.set(c, (bag.get(c) ?? 0) + 1.2);
    }
  }
  return [...bag.entries()]
    .sort((x, y) => y[1] - x[1])
    .slice(0, maxTerms)
    .map(([term]) => term);
}

async function chainSemanticMemory(query, recallFn, options = {}) {
  const maxHops = Math.max(1, Number(options.maxHops ?? 3));
  const hopTopK = Math.max(3, Number(options.hopTopK ?? 8));
  const targetTopK = Math.max(4, Number(options.targetTopK ?? 12));
  const merged = new Map();
  const trace = [];

  const base = String(query ?? "").trim();
  let currentQuery = base;
  const visited = new Set();

  for (let hop = 0; hop < maxHops; hop++) {
    if (!currentQuery || visited.has(currentQuery)) break;
    visited.add(currentQuery);
    const nav = await navigateSemanticMemory(currentQuery, recallFn, {
      perVariantTopK: hopTopK,
      targetTopK: hopTopK,
      maxVariants: options.maxVariants ?? 10,
    });

    const top = (nav?.reranked ?? []).slice(0, hopTopK);
    const hopDecay = 1 / (1 + hop * 0.35);
    for (const item of top) {
      const entry = item?.entry;
      if (!entry?.id) continue;
      const score = Number(item?.score ?? 0) * hopDecay;
      const prev = merged.get(entry.id) ?? { entry, score: 0, hops: 0 };
      prev.score += score;
      prev.hops += 1;
      merged.set(entry.id, prev);
    }

    const seedTexts = top
      .map((x) => String(x?.entry?.text ?? "").trim())
      .filter(Boolean)
      .slice(0, 4);
    const expansion = extractExpansionTerms(seedTexts, 8);
    trace.push({
      hop,
      query: currentQuery,
      hits: top.length,
      expansion,
    });
    if (!expansion.length) break;
    currentQuery = `${base} ${expansion.slice(0, 6).join(" ")}`.trim();
  }

  const reranked = [...merged.values()]
    .map((x) => ({
      entry: x.entry,
      score: x.score + 0.05 * x.hops,
      hops: x.hops,
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, targetTopK);

  return {
    mode: "semantic-chain",
    query: base,
    reranked,
    trace,
  };
}

module.exports = {
  expandQueryVariants,
  navigateSemanticMemory,
  chainSemanticMemory,
};
