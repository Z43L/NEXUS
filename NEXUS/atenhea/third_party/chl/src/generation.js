function summarizePayload(payload) {
  if (payload == null) return "";
  if (typeof payload === "string") return payload.trim();
  if (Array.isArray(payload)) {
    return payload
      .slice(0, 3)
      .map((item) => summarizePayload(item))
      .filter(Boolean)
      .join("; ");
  }
  if (typeof payload === "object") {
    if (typeof payload.fact === "string" && payload.fact.trim()) return payload.fact.trim();
    if (typeof payload.summary === "string" && payload.summary.trim()) return payload.summary.trim();
    if (typeof payload.text === "string" && payload.text.trim()) return payload.text.trim();
    if (typeof payload.label === "string" && payload.label.trim()) return payload.label.trim();
    const keys = Object.keys(payload).filter((key) => payload[key] != null).slice(0, 3);
    if (keys.length > 0) {
      return keys.map((key) => `${key}: ${summarizePayload(payload[key]) || String(payload[key])}`).join("; ");
    }
  }
  return String(payload);
}

function extractClaims({ kind, thought, plan, answer }) {
  const claims = [];
  if (kind === "answer") {
    const summary = summarizePayload(answer);
    if (summary) {
      claims.push({
        type: "answer",
        text: summary,
        support: thought?.best?.evidence?.text ?? null,
        confidence: thought?.best?.score ?? thought?.confidence ?? 0,
      });
    }
  }
  if (kind === "plan") {
    for (const step of plan?.steps ?? []) {
      claims.push({
        type: "plan_step",
        text: step.text,
        support: null,
        confidence: step.confidence ?? 0,
      });
    }
  }
  return claims;
}

function renderDecisionText({ kind, query, thought, plan, verification, answer, reason }) {
  if (kind === "clarify") {
    const hint = thought?.best?.evidence?.concepts?.length
      ? `Estoy viendo evidencia sobre ${thought.best.evidence.concepts.join(", ")}.`
      : "No tengo suficiente evidencia especifica.";
    return `${hint} Necesito mas contexto para responder con seguridad sobre "${query}".`;
  }

  if (kind === "plan") {
    const steps = (plan?.steps ?? [])
      .map((step, index) => `${index + 1}. ${step.text}`)
      .join(" ");
    const status = verification?.verified ? "El plan parece consistente." : "El plan todavia necesita verificacion.";
    return `${status} Puedo proponer este camino: ${steps}`.trim();
  }

  const summary = summarizePayload(answer);
  const confidenceText = typeof thought?.confidence === "number" ? `Confianza ${thought.confidence.toFixed(2)}.` : "";
  return [
    summary ? `La mejor respuesta que encuentro es: ${summary}.` : "La mejor respuesta es la que sigue.",
    confidenceText,
    reason ? `Motivo: ${reason}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function renderDecisionExplanation({ kind, thought, plan, verification, reason }) {
  const parts = [];
  if (thought?.best) {
    parts.push(`hipotesis=${thought.best.id}`);
    parts.push(`score=${thought.best.score.toFixed(2)}`);
  }
  if (plan?.steps?.length) {
    parts.push(`pasos=${plan.steps.length}`);
  }
  if (typeof verification?.verified === "boolean") {
    parts.push(`verificado=${verification.verified ? "si" : "no"}`);
  }
  parts.push(`modo=${kind}`);
  if (reason) parts.push(`razon=${reason}`);
  return parts.join(" | ");
}

function composeDecisionResponse(input) {
  const responseText = renderDecisionText(input);
  const explanation = renderDecisionExplanation(input);
  const claims = extractClaims(input);
  return {
    responseText,
    explanation,
    claims,
    generation: {
      kind: input.kind,
      claimCount: claims.length,
      style: input.style ?? "default",
    },
  };
}

module.exports = {
  composeDecisionResponse,
  extractClaims,
  renderDecisionExplanation,
  renderDecisionText,
  summarizePayload,
};
