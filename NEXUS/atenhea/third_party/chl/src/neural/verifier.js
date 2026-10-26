/**
 * NeuralVerifier — Capa 7 neuronal (Verificación)
 * 
 * Verifica claims generadas contra la memoria y el grafo de conceptos.
 * Sin modelos externos: usa el propio grafo + embeddings para detectar
 * contradicciones, falta de soporte y consistencia interna.
 * 
 * Métodos de verificación:
 * 1. Claim grounding: cada claim debe tener soporte en entries recuperadas
 * 2. Contradiction detection: claims que contradicen entries existentes
 * 3. Graph consistency: claims consistentes con el grafo de conceptos
 * 4. Confidence calibration: ajusta confianza según calidad del soporte
 */

const { EmbeddingIndex, dotProduct } = require("./embeddings");
const { analyzeText } = require("../analysis");
const { buildConceptGraph } = require("../graph");
const { tokenize, normalizeText } = require("../utils");

class NeuralVerifier {
  constructor(options = {}) {
    this.minClaimSupport = options.minClaimSupport ?? 0.2;
    this.contradictionThreshold = options.contradictionThreshold ?? 0.1;
    this.maxClaimsToVerify = options.maxClaimsToVerify ?? 5;
  }

  /**
   * Extrae claims atómicas de un texto generado.
   * Una claim es una frase con sujeto + verbo + (opcional) objeto.
   */
  extractClaims(text) {
    const claims = [];
    const norm = normalizeText(String(text ?? ""));
    
    // Dividir por puntuación y conectores
    const segments = norm.split(/[.,;:!?]+/g).filter((s) => s.trim().length > 10);

    for (const segment of segments) {
      const tokens = tokenize(segment);
      if (tokens.length < 3) continue;

      // Buscar patrón sujeto-verbo-objeto simple
      const verbs = tokens.filter((t, i) => i > 0 && i < tokens.length - 1 && t.length > 2);
      
      for (const verb of verbs) {
        const verbIdx = tokens.indexOf(verb);
        if (verbIdx < 1 || verbIdx >= tokens.length - 1) continue;

        const subject = tokens.slice(Math.max(0, verbIdx - 2), verbIdx).join(" ");
        const object = tokens.slice(verbIdx + 1, Math.min(tokens.length, verbIdx + 4)).join(" ");

        if (subject && object) {
          claims.push({
            text: `${subject} ${verb} ${object}`,
            subject,
            verb,
            object,
            sourceSegment: segment,
          });
        }
      }

      // Si no se encontraron claims estructuradas, usar el segmento entero
      if (claims.length === 0 || claims.every((c) => c.sourceSegment !== segment)) {
        claims.push({
          text: segment.trim(),
          subject: tokens[0],
          verb: tokens[1] ?? "",
          object: tokens.slice(2).join(" "),
          sourceSegment: segment,
        });
      }
    }

    return claims.slice(0, this.maxClaimsToVerify);
  }

  /**
   * Verifica una claim contra la evidencia.
   * 
   * @param {Object} claim - La claim a verificar
   * @param {string} evidenceText - Texto de evidencia
   * @param {Map} evidenceVec - Vector de la evidencia (sparse)
   * @param {Array} allEntries - Todas las entries para detección de contradicciones
   */
  verifyClaim(claim, evidenceText, evidenceVec, allEntries = []) {
    const claimTokens = tokenize(normalizeText(claim.text));
    const evidenceTokens = tokenize(normalizeText(evidenceText));

    // 1. Grounding: ¿cuántos tokens de la claim están en la evidencia?
    const overlap = claimTokens.filter((t) => evidenceTokens.includes(t));
    const groundingScore = claimTokens.length > 0
      ? overlap.length / claimTokens.length
      : 0;

    // 2. Contradiction: ¿hay entries que contradigan esta claim?
    let contradictionScore = 0;
    let contradictingEntry = null;

    for (const entry of allEntries) {
      if (!entry || entry.text === evidenceText) continue;
      const entryTokens = tokenize(normalizeText(entry.text ?? ""));
      
      // Detectar negación opuesta
      const claimNegated = claimTokens.includes("no") || claimTokens.includes("sin");
      const entryNegated = entryTokens.includes("no") || entryTokens.includes("sin");

      // Si la entry es semánticamente similar pero con negación opuesta
      const contentOverlap = claimTokens.filter((t) => 
        t.length > 3 && entryTokens.includes(t) && t !== "no" && t !== "sin"
      );

      if (contentOverlap.length >= 3 && claimNegated !== entryNegated) {
        contradictionScore = Math.max(contradictionScore, contentOverlap.length / claimTokens.length);
        contradictingEntry = entry.text;
      }
    }

    // 3. Verdict
    const supported = groundingScore >= this.minClaimSupport && contradictionScore < this.contradictionThreshold;
    const contradicted = contradictionScore >= this.contradictionThreshold;

    let verdict;
    if (contradicted) verdict = "contradicted";
    else if (supported) verdict = "supported";
    else verdict = "unsupported";

    return {
      claim: claim.text,
      groundingScore,
      contradictionScore,
      verdict,
      confidence: supported ? groundingScore * (1 - contradictionScore) : 0,
      contradictingEvidence: contradictingEntry,
      evidenceTokens: overlap.slice(0, 5),
    };
  }

  /**
   * Verifica todas las claims de una respuesta contra la evidencia.
   */
  verifyResponse(generatedText, evidence, allEntries = []) {
    const claims = this.extractClaims(generatedText);
    const evidenceText = typeof evidence === "string" ? evidence : evidence?.text ?? "";

    const checks = [];
    for (const claim of claims) {
      const check = this.verifyClaim(claim, evidenceText, null, allEntries);
      checks.push(check);
    }

    const supported = checks.filter((c) => c.verdict === "supported").length;
    const contradicted = checks.filter((c) => c.verdict === "contradicted").length;
    const unsupported = checks.filter((c) => c.verdict === "unsupported").length;

    const allSupported = contradicted === 0 && unsupported === 0 && checks.length > 0;
    const avgConfidence = checks.length > 0
      ? checks.reduce((sum, c) => sum + c.confidence, 0) / checks.length
      : 0;

    return {
      verified: allSupported,
      checks,
      confidence: avgConfidence,
      summary: {
        total: checks.length,
        supported,
        contradicted,
        unsupported,
      },
    };
  }

  /**
   * Verifica consistencia contra el grafo de conceptos.
   */
  verifyGraphConsistency(claims, conceptGraph) {
    if (!conceptGraph || !conceptGraph.nodes || conceptGraph.nodes.length === 0) {
      return { consistent: true, checks: [], confidence: 0.5 };
    }

    const checks = [];
    const entityLabels = new Set(
      conceptGraph.nodes
        .filter((n) => n.type === "entity")
        .map((n) => n.label)
    );

    for (const claim of claims) {
      const tokens = tokenize(normalizeText(claim.text));
      const entities = tokens.filter((t) => entityLabels.has(t) || 
        [...entityLabels].some((label) => label.includes(t))
      );

      // Verificar si las entidades de la claim existen en el grafo
      const knownEntities = entities.length;
      const totalEntities = tokens.filter((t) => t.length > 3).length;
      const entityRatio = totalEntities > 0 ? knownEntities / totalEntities : 0;

      checks.push({
        claim: claim.text,
        knownEntities,
        totalEntities,
        entityRatio,
        consistent: entityRatio >= 0.3 || totalEntities === 0,
      });
    }

    const consistent = checks.every((c) => c.consistent);
    const confidence = checks.length > 0
      ? checks.reduce((sum, c) => sum + (c.entityRatio ?? 0), 0) / checks.length
      : 0.5;

    return { consistent, checks, confidence };
  }
}

module.exports = { NeuralVerifier };
