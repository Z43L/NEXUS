const { analyzeText } = require("./analysis");
const { learnConceptPairsFromExamples, learnPhrasePairsFromExamples } = require("./concepts");
const { stableHash32 } = require("./utils");

function unique(values = []) {
  return Array.from(new Set(values));
}

function toPairMap(pairs = []) {
  const map = new Map();
  for (const pair of pairs) {
    const from = Array.isArray(pair) ? pair[0] : pair?.from;
    const to = Array.isArray(pair) ? pair[1] : pair?.to;
    if (!from || !to) continue;
    const key = `${String(from).trim()}\t${String(to).trim()}`;
    map.set(key, [String(from).trim(), String(to).trim()]);
  }
  return map;
}

function mergePairLists(...lists) {
  const merged = new Map();
  for (const list of lists) {
    for (const [key, pair] of toPairMap(list).entries()) merged.set(key, pair);
  }
  return Array.from(merged.values());
}

function episodePatternKey(episode) {
  const queryAnalysis = analyzeText(episode?.query ?? "");
  const concepts = (queryAnalysis.concepts ?? []).slice(0, 4).sort().join("|");
  const mode = episode?.kind ?? "unknown";
  const verified = episode?.verification?.verified ? "verified" : "unverified";
  const plan = episode?.plan?.goal ? String(episode.plan.goal).slice(0, 32) : "";
  return `${mode}|${verified}|${concepts}|${plan}`;
}

function summarizeConcepts(concepts = []) {
  const items = unique(concepts).filter(Boolean).slice(0, 4);
  return items.length > 0 ? items.join(", ") : "patron general";
}

function summarizeResponseKind(kind) {
  if (kind === "answer") return "responder directamente";
  if (kind === "plan") return "planificar la respuesta";
  if (kind === "clarify") return "pedir aclaracion";
  return "actuar";
}

function normalizeEpisodeExamples(episodes = []) {
  const examples = [];
  for (const episode of episodes) {
    if (!episode || !episode.query) continue;
    const source = String(episode.query).trim();
    const target = String(episode.bestEvidenceText ?? episode.plan?.goal ?? episode.responseText ?? "").trim();
    if (!target) continue;
    examples.push({ source, target, episode });
  }
  return examples;
}

function buildConsolidation(episodes = [], options = {}) {
  const minSupport = options.minSupport ?? 2;
  const groups = new Map();
  const examples = normalizeEpisodeExamples(episodes);
  const conceptPairCounts = new Map();
  
  // LexiconTrainer batch (si está disponible)
  const lexiconTrainer = options.lexiconTrainer ?? null;
  let trainerResult = null;
  if (lexiconTrainer) {
    trainerResult = lexiconTrainer.trainBatch(episodes);
  }

  for (const example of examples) {
    const queryAnalysis = analyzeText(example.source);
    const targetAnalysis = analyzeText(example.target);
    const signature = episodePatternKey(example.episode);
    if (!groups.has(signature)) {
      groups.set(signature, []);
    }
    groups.get(signature).push({ ...example, queryAnalysis, targetAnalysis });

    const sourceConcepts = (queryAnalysis.concepts ?? []).slice(0, 3);
    const targetConcepts = (targetAnalysis.concepts ?? []).slice(0, 3);
    for (const sourceConcept of sourceConcepts) {
      for (const targetConcept of targetConcepts) {
        if (sourceConcept === targetConcept) continue;
        const key = `${sourceConcept}\t${targetConcept}`;
        conceptPairCounts.set(key, (conceptPairCounts.get(key) ?? 0) + 1);
      }
    }
  }

  const phraseExamples = examples.map((example) => ({ source: example.source, target: example.target }));
  const learnedConceptPairs = Array.from(conceptPairCounts.entries())
    .filter(([, count]) => count >= minSupport)
    .map(([key]) => key.split("\t"))
    .filter(([from, to]) => from && to);

  const learnedPhrasePairs = Array.from(learnPhrasePairsFromExamples(phraseExamples).entries()).map(([from, to]) => [from, to]);
  const learnedConceptPairsFromExamplesList = Array.from(learnConceptPairsFromExamples(phraseExamples).entries()).map(([from, to]) => [from, to]);
  const mergedConceptPairs = mergePairLists(learnedConceptPairs, learnedConceptPairsFromExamplesList);

  const rules = [];
  for (const [signature, items] of groups.entries()) {
    if (items.length < minSupport) continue;
    const queryConcepts = unique(items.flatMap((item) => item.queryAnalysis.concepts ?? []));
    const targetConcepts = unique(items.flatMap((item) => item.targetAnalysis.concepts ?? []));
    const kind = items[0]?.episode?.kind ?? "unknown";
    const verified = items.some((item) => item.episode?.verification?.verified);
    const ruleId = `rule:${stableHash32(signature).toString(16)}`;
    const ruleText = `Patron consolidado: cuando una consulta sobre ${summarizeConcepts(queryConcepts)} aparece repetidamente, el sistema tiende a ${summarizeResponseKind(kind)} con apoyo en ${summarizeConcepts(targetConcepts)}.`;
    const evidenceIds = unique(items.map((item) => item.episode?.id).filter(Boolean));
    rules.push({
      id: ruleId,
      text: ruleText,
      payload: {
        type: "episode_rule",
        signature,
        kind,
        verified,
        supportCount: items.length,
        queryConcepts,
        targetConcepts,
        evidenceIds,
        examples: items.map((item) => ({
          query: item.episode.query,
          responseText: item.episode.responseText,
          bestEvidenceText: item.episode.bestEvidenceText,
          reason: item.episode.reason,
        })),
      },
      metadata: {
        id: ruleId,
        quality: Math.min(10, 4 + items.length),
        source: "episode_consolidation",
      },
      supportCount: items.length,
    });
  }

  return {
    processedCount: examples.length,
    patternCount: groups.size,
    conceptPairs: mergedConceptPairs,
    phrasePairs: learnedPhrasePairs,
    rules,
    nextEpisodeIndex: episodes.length,
    trainerResult: trainerResult ?? null,
    summary: {
      processedCount: examples.length,
      patternCount: groups.size,
      ruleCount: rules.length,
      conceptPairCount: mergedConceptPairs.length,
      phrasePairCount: learnedPhrasePairs.length,
      trainerUpdates: trainerResult?.updates ?? 0,
    },
  };
}

module.exports = {
  buildConsolidation,
  mergePairLists,
  normalizeEpisodeExamples,
  episodePatternKey,
};
