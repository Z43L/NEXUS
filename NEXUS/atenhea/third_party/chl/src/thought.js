const { analyzeText } = require("./analysis");
const {
  composeDecisionResponse,
  renderDecisionExplanation,
  renderDecisionText,
  summarizePayload,
} = require("./generation");
const { buildConceptGraph, cleanLabel, splitAroundRelation } = require("./graph");
const { clamp } = require("./utils");

function unique(values = []) {
  return Array.from(new Set(values));
}

function getCandidateEntry(candidate) {
  if (!candidate || typeof candidate !== "object") return {};
  if (candidate.entry && typeof candidate.entry === "object") return candidate.entry;
  return candidate;
}

function scoreHypothesis(hypothesis) {
  const weights = {
    direct: 0.42,
    relation: 0.24,
    graph: 0.18,
    support: 0.10,
    contradiction: 0.06,
  };
  return clamp(
    (weights.direct * (hypothesis.directScore ?? 0)) +
      (weights.relation * (hypothesis.relationScore ?? 0)) +
      (weights.graph * (hypothesis.graphScore ?? 0)) +
      (weights.support * (hypothesis.supportScore ?? 0)) +
      (weights.contradiction * (1 - (hypothesis.contradictionScore ?? 0))),
    0,
    1
  );
}

function extractGraphSignals(graph, queryAnalysis) {
  const concepts = new Set(queryAnalysis.concepts ?? []);
  const entityLabels = new Set();
  const relationLabels = new Set();
  for (const node of graph?.nodes ?? []) {
    if (node.type === "entity") entityLabels.add(cleanLabel(node.label));
  }
  for (const edge of graph?.edges ?? []) {
    if (edge.type === "relation" || edge.type === "payload_relation") {
      relationLabels.add(cleanLabel(edge.label));
    }
  }
  return {
    conceptHits: unique([...concepts].filter((concept) => Array.from(entityLabels).some((label) => label.includes(concept)))),
    relationHits: unique(
      Array.from(relationLabels).filter((relation) => queryAnalysis.canonicalText.includes(relation.replace(/_/g, " ")))
    ),
  };
}

function buildHypotheses(query, memory, options = {}) {
  const topK = options.topK ?? 5;
  const queryAnalysis = analyzeText(query, options.analysisOptions ?? {});
  const recall = memory.recall(query, { topK });
  const graph = typeof memory.conceptGraph === "function" ? memory.conceptGraph() : buildConceptGraph(memory.entries?.() ?? []);
  const graphSignals = extractGraphSignals(graph, queryAnalysis);
  const relation = splitAroundRelation(queryAnalysis.canonicalText);

  const candidates = (recall.candidates ?? []).map((candidate, index) => {
    const entry = getCandidateEntry(candidate);
    const payload = entry.payload ?? null;
    const candidateText = entry.text ?? "";
    const entryAnalysis = analyzeText(candidateText, options.analysisOptions ?? {});
    const overlapConcepts = unique((queryAnalysis.concepts ?? []).filter((concept) => (entryAnalysis.concepts ?? []).includes(concept)));
    const overlapFocus = unique((queryAnalysis.focusTokens ?? []).filter((token) => (entryAnalysis.focusTokens ?? []).includes(token)));
    const supportConcepts = overlapConcepts.length > 0 ? overlapConcepts : unique((entryAnalysis.concepts ?? []).slice(0, 2));
    const supportFocus = overlapFocus.length > 0 ? overlapFocus : unique((entryAnalysis.focusTokens ?? []).slice(0, 2));
    const graphMatches = unique(overlapConcepts.filter((concept) => graphSignals.conceptHits.includes(concept)));
    const relationScore = relation
      ? (candidateText.includes(relation.relation) || JSON.stringify(payload ?? "").includes(relation.relation) ? 1 : 0)
      : 0;
    const supportScore = clamp((overlapConcepts.length + overlapFocus.length) / Math.max(1, queryAnalysis.focusTokens.length || 1), 0, 1);
    const contradictionScore = queryAnalysis.negated && entryAnalysis.negated ? 0 : queryAnalysis.negated !== entryAnalysis.negated ? 0.35 : 0;
    const directScore = candidate.score ?? 0;
    const graphScore = clamp((graphMatches.length + (graphSignals.relationHits.length > 0 ? 1 : 0)) / 4, 0, 1);

    return {
      id: entry.id ?? `candidate-${index}`,
      type: "candidate",
      directScore,
      relationScore,
      graphScore,
      supportScore,
      contradictionScore,
      score: 0,
      answer: payload,
      evidence: {
        text: candidateText,
        concepts: supportConcepts,
        focusTokens: supportFocus,
        graphMatches,
      },
    };
  });

  const hypotheses = candidates.map((hypothesis) => ({
    ...hypothesis,
    score: scoreHypothesis(hypothesis),
  }));

  hypotheses.sort((a, b) => b.score - a.score);

  const contradictionNotes = [];
  if (queryAnalysis.negated) {
    for (const hypothesis of hypotheses.slice(0, 3)) {
      if ((hypothesis.contradictionScore ?? 0) > 0) {
        contradictionNotes.push({
          candidateId: hypothesis.id,
          reason: "query_is_negated_but_candidate_is_positive",
          severity: hypothesis.contradictionScore,
        });
      }
    }
  }

  const best = hypotheses[0] ?? null;
  return {
    queryAnalysis,
    recall,
    graph,
    graphSignals,
    relation,
    hypotheses,
    contradictions: contradictionNotes,
    best,
    confidence: best ? clamp(best.score, 0, 1) : 0,
  };
}

function buildPlan(query, memory, options = {}) {
  const thought = options.thought ?? buildHypotheses(query, memory, options);
  const best = thought.best ?? null;
  const queryAnalysis = thought.queryAnalysis ?? analyzeText(query, options.analysisOptions ?? {});
  const steps = [];

  if (!best) {
    steps.push({
      id: "step-1",
      kind: "gather",
      text: "Buscar evidencia relevante en memoria",
      requires: [],
      confidence: 0,
    });
    return {
      query: queryAnalysis.canonicalText,
      thought,
      steps,
      goal: "recuperar evidencia suficiente",
      confidence: 0,
      rationale: "No se encontró una hipótesis fuerte.",
    };
  }

  const concepts = unique(best.evidence?.concepts ?? []);
  const focusTokens = unique(best.evidence?.focusTokens ?? []);
  const graphMatches = unique(best.evidence?.graphMatches ?? []);
  const relation = thought.relation?.relation ?? null;

  steps.push({
    id: "step-1",
    kind: "retrieve",
    text: "Recuperar la evidencia más cercana",
    requires: [],
    confidence: clamp(best.directScore ?? 0, 0, 1),
  });

  if (concepts.length > 0) {
    steps.push({
      id: "step-2",
      kind: "align",
      text: `Alinear conceptos clave: ${concepts.join(", ")}`,
      requires: ["step-1"],
      confidence: clamp((concepts.length + focusTokens.length) / Math.max(1, queryAnalysis.focusTokens.length || 1), 0, 1),
    });
  }

  if (relation || graphMatches.length > 0) {
    steps.push({
      id: "step-3",
      kind: "verify",
      text: relation ? `Verificar la relación ${relation}` : "Verificar consistencia con el grafo",
      requires: steps.map((step) => step.id),
      confidence: clamp((graphMatches.length + (relation ? 1 : 0)) / 2, 0, 1),
    });
  }

  steps.push({
    id: "step-final",
    kind: "answer",
    text: "Construir respuesta con la mejor hipótesis y la evidencia disponible",
    requires: steps.map((step) => step.id),
    confidence: clamp(best.score, 0, 1),
  });

  return {
    query: queryAnalysis.canonicalText,
    thought,
    steps,
    goal: relation ? `resolver la relación ${relation}` : "responder con evidencia relevante",
    confidence: thought.confidence ?? best.score ?? 0,
    rationale: explainThought(thought),
  };
}

function verifyPlan(plan, memory, options = {}) {
  const sourcePlan = typeof plan === "string" ? buildPlan(plan, memory, options) : plan;
  const thought = sourcePlan.thought ?? (sourcePlan.query ? buildHypotheses(sourcePlan.query, memory, options) : null);
  const graph = thought?.graph ?? (typeof memory.conceptGraph === "function" ? memory.conceptGraph() : buildConceptGraph(memory.entries?.() ?? []));
  const queryAnalysis = thought?.queryAnalysis ?? analyzeText(sourcePlan.query ?? "", options.analysisOptions ?? {});
  const checks = [];

  for (const step of sourcePlan.steps ?? []) {
    const text = String(step.text ?? "");
    const stepConcepts = queryAnalysis.concepts.filter((concept) => text.toLowerCase().includes(concept));
    const graphSupport = (thought?.graphSignals?.conceptHits ?? []).filter((concept) => text.toLowerCase().includes(concept));
    const memorySupport = (thought?.hypotheses ?? []).some((hypothesis) => {
      const evidenceText = String(hypothesis.evidence?.text ?? "").toLowerCase();
      return text.toLowerCase().includes(evidenceText.slice(0, 16)) || graphSupport.length > 0 || stepConcepts.length > 0;
    });
    const passed = step.kind === "answer" ? Boolean(thought?.best) : step.kind === "verify" ? graphSupport.length > 0 || memorySupport : memorySupport || stepConcepts.length > 0;
    checks.push({
      stepId: step.id,
      kind: step.kind,
      passed,
      evidence: {
        stepConcepts,
        graphSupport,
        memorySupport,
      },
      confidence: clamp((step.confidence ?? 0) * (passed ? 1 : 0.4), 0, 1),
    });
  }

  const passedCount = checks.filter((check) => check.passed).length;
  const verified = checks.length > 0 ? passedCount === checks.length : false;
  const confidence = checks.length > 0 ? clamp(checks.reduce((sum, check) => sum + check.confidence, 0) / checks.length, 0, 1) : 0;

  return {
    plan: sourcePlan,
    thought,
    graph,
    checks,
    verified,
    confidence,
  };
}

function buildAnswer(query, memory, options = {}) {
  const thought = options.thought ?? buildHypotheses(query, memory, options);
  const plan = options.plan ?? buildPlan(query, memory, { ...options, thought });
  const verification = options.verification ?? verifyPlan(plan, memory, options);
  const queryAnalysis = thought.queryAnalysis ?? analyzeText(query, options.analysisOptions ?? {});
  const best = thought.best ?? null;
  const confidence = clamp(
    0.4 * (thought.confidence ?? 0) + 0.3 * (plan.confidence ?? 0) + 0.3 * (verification.confidence ?? 0),
    0,
    1
  );

  let kind = "answer";
  let response = best?.answer ?? null;
  let reason = "La evidencia y la verificacion son suficientes.";

  if (!best || confidence < 0.28 || !verification.verified) {
    kind = "clarify";
    response = null;
    reason = verification.verified
      ? "La confianza es baja y conviene pedir mas contexto."
      : "La verificacion no es suficiente para responder con seguridad.";
  } else if (confidence < 0.55 || (verification.checks ?? []).some((check) => check.kind === "verify" && !check.passed)) {
    kind = "plan";
    response = plan;
    reason = "Hay evidencia util, pero conviene estructurar la respuesta como plan.";
  }

  const composed = composeDecisionResponse({
    kind,
    query: queryAnalysis.canonicalText,
    thought,
    plan,
    verification,
    answer: response,
    reason,
    style: options.style,
  });

  return {
    query,
    kind,
    response,
    responseText: composed.responseText,
    explanation: composed.explanation,
    reason,
    confidence,
    claims: composed.claims,
    generation: composed.generation,
    thought,
    plan,
    verification,
  };
}

function learnFromVerification(memory, verification, options = {}) {
  const feedbackFn =
    memory && typeof memory.updateFeedback === "function"
      ? memory.updateFeedback.bind(memory)
      : memory && typeof memory.learnFromFeedback === "function"
        ? memory.learnFromFeedback.bind(memory)
        : null;
  if (!feedbackFn) {
    throw new Error("learnFromVerification requires a memory with updateFeedback or learnFromFeedback");
  }
  const source = verification?.plan?.query ?? verification?.thought?.queryAnalysis?.canonicalText ?? verification?.query ?? "";
  const best = verification?.thought?.best ?? null;
  const rewardBase = verification?.verified ? 1 : -1;
  const reward = clamp(
    rewardBase * (0.25 + 0.5 * (verification?.confidence ?? 0)),
    -1,
    1
  );
  feedbackFn(source, reward);
  if (best?.evidence?.text) {
    feedbackFn(best.evidence.text, reward * 0.5);
  }
  if (Array.isArray(options.extraSignals)) {
    for (const signal of options.extraSignals) {
      if (!signal) continue;
      feedbackFn(signal, reward * 0.25);
    }
  }
  return {
    ok: true,
    reward,
    source,
    appliedTo: best?.evidence?.text ?? null,
  };
}

function buildDecisionEpisode(decision, extras = {}) {
  return {
    id: extras.id ?? `episode-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`,
    kind: decision?.kind ?? "unknown",
    query: decision?.query ?? "",
    responseText: decision?.responseText ?? "",
    reason: decision?.reason ?? "",
    confidence: clamp(decision?.confidence ?? 0, 0, 1),
    createdAt: extras.createdAt ?? new Date().toISOString(),
    bestEvidenceText: decision?.thought?.best?.evidence?.text ?? null,
    bestConcepts: Array.isArray(decision?.thought?.best?.evidence?.concepts) ? [...decision.thought.best.evidence.concepts] : [],
    bestFocusTokens: Array.isArray(decision?.thought?.best?.evidence?.focusTokens) ? [...decision.thought.best.evidence.focusTokens] : [],
    bestGraphMatches: Array.isArray(decision?.thought?.best?.evidence?.graphMatches) ? [...decision.thought.best.evidence.graphMatches] : [],
    thought: decision?.thought
      ? {
          confidence: decision.thought.confidence ?? 0,
          bestId: decision.thought.best?.id ?? null,
          bestScore: decision.thought.best?.score ?? null,
        }
      : null,
    plan: decision?.plan
      ? {
          goal: decision.plan.goal ?? null,
          stepCount: Array.isArray(decision.plan.steps) ? decision.plan.steps.length : 0,
        }
      : null,
    verification: decision?.verification
      ? {
          verified: Boolean(decision.verification.verified),
          confidence: decision.verification.confidence ?? 0,
        }
      : null,
  };
}

function explainThought(thought) {
  if (!thought?.best) {
    return "No hay evidencia suficiente para formar una hipótesis.";
  }
  const best = thought.best;
  const parts = [];
  parts.push(`Mejor hipótesis: ${best.id}`);
  parts.push(`confianza ${best.score.toFixed(2)}`);
  if (best.evidence?.concepts?.length) parts.push(`conceptos compartidos: ${best.evidence.concepts.join(", ")}`);
  if (best.evidence?.focusTokens?.length) parts.push(`tokens clave: ${best.evidence.focusTokens.join(", ")}`);
  if (best.evidence?.graphMatches?.length) parts.push(`soporte grafo: ${best.evidence.graphMatches.join(", ")}`);
  return parts.join(" | ");
}

module.exports = {
  buildAnswer,
  buildDecisionEpisode,
  buildHypotheses,
  buildPlan,
  explainThought,
  learnFromVerification,
  verifyPlan,
  renderDecisionExplanation,
  renderDecisionText,
  scoreHypothesis,
  summarizePayload,
};
