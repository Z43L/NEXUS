/**
 * HyperDecoder v2 — Recomposición semántica desde memoria
 *
 * En lugar de intentar generar texto desde cero (que requiere un modelo de lenguaje),
 * el HyperDecoder v2 recombina el mejor candidato recuperado con la terminología
 * de la query, produciendo una respuesta fiel a la memoria pero adaptada al usuario.
 *
 * Flujo:
 *   1. Recibir query + top candidates del recall
 *   2. Seleccionar el mejor candidato (por score + compatibilidad semántica)
 *   3. Extraer entidades del candidato y de la query
 *   4. Mapear entidades de la query a las del candidato vía el trainer
 *   5. Sustituir términos en el texto del candidato para reflejar la query
 *   6. Pasar por ViterbiGenerator para fluidez
 *   7. Si no hay candidatos sólidos, devolver el texto original
 */

const { prototypeVectorFromText, similarity } = require("./hypervector");
const { normalizeText, tokenize } = require("./utils");
const { ViterbiGenerator } = require("./neural/viterbi-gen");

class HyperDecoder {
  /**
   * @param {object} options
   * @param {LexiconTrainer} options.lexiconTrainer
   * @param {number} options.hyperDim
   * @param {number} options.seed
   * @param {number} options.minConfidence - umbral mínimo para recomponer
   */
  constructor(options = {}) {
    this.lexiconTrainer = options.lexiconTrainer ?? null;
    this.hyperDim = options.hyperDim ?? 256;
    this.seed = options.seed ?? 0;
    this.minConfidence = options.minConfidence ?? 0.5;
    this._viterbi = new ViterbiGenerator({ beamWidth: 5, maxLength: 15 });
    this._compositionCount = 0;
  }

  /**
   * Compone una respuesta adaptada a la query usando el mejor candidato.
   *
   * @param {string} queryText
   * @param {Array} candidates - [{entry: {id, text, payload}, score, similarity}]
   * @param {object} options
   * @returns {object} {text, confidence, composed, method}
   */
  compose(queryText, candidates = [], options = {}) {
    if (!candidates || candidates.length === 0) {
      return { text: "", confidence: 0, composed: false, method: "no_candidates" };
    }

    const best = candidates[0];
    const bestText = best?.entry?.text ?? best?.text ?? "";
    const bestScore = best?.score ?? best?.similarity ?? 0;

    if (!bestText || bestScore < this.minConfidence) {
      return { text: bestText, confidence: bestScore, composed: false, method: "low_confidence" };
    }

    // Si el score es muy alto (>0.9) y hay trainer, intentar recomposición
    if (this.lexiconTrainer && bestScore > 0.5) {
      try {
        return this._recompose(queryText, bestText, bestScore, candidates);
      } catch (_) {
        // Fallback to original
      }
    }

    return {
      text: bestText,
      confidence: bestScore,
      composed: false,
      method: "direct_match",
    };
  }

  /**
   * Recompone: sustituye términos de la query en el texto del candidato.
   * "el felino descansa sobre la mesa" + candidato "el gato duerme sobre la mesa"
   * → "el felino descansa sobre la mesa" (el usuario ya dijo la respuesta en sus términos)
   */
  _recompose(queryText, bestText, bestScore, allCandidates) {
    const queryNorm = normalizeText(queryText);
    const bestNorm = normalizeText(bestText);
    const queryTokens = tokenize(queryNorm);
    const bestTokens = tokenize(bestNorm);

    // Si los textos son casi idénticos, no recomponer
    if (queryNorm === bestNorm) {
      return { text: bestText, confidence: bestScore, composed: false, method: "identical" };
    }

    let responseTokens = [...bestTokens];
    const substitutedIndices = new Set();
    let substitutions = 0;

    if (this.lexiconTrainer) {
      const conceptMap = this.lexiconTrainer.conceptMap;
      const collMap = this.lexiconTrainer.collocationMap;
      
      // PASO 1: Sustituir tokens usando el conceptMap, preservando preposiciones
      for (let i = 0; i < bestTokens.length; i++) {
        if (substitutedIndices.has(i)) continue;
        const bestTok = bestTokens[i];
        
        for (const qTok of queryTokens) {
          const canonical = conceptMap.get(qTok);
          if (canonical === bestTok && qTok !== bestTok) {
            // ¡Encontramos una sustitución! Verificar colocación
            responseTokens[i] = qTok;
            substitutedIndices.add(i);
            substitutions++;
            
            // Si este token es un verbo, verificar colocación esperada:
            // cambiar, eliminar o insertar preposición para mantener gramática.
            if (collMap && collMap.size > 0 && i + 1 < bestTokens.length) {
              const nextTok = responseTokens[i + 1];
              const isPrep = ['a','en','de','por','sobre','con','para','sin','entre','tras'].includes(nextTok);
              const expectedPrep = collMap.get(qTok);
              
              if (isPrep) {
                if (expectedPrep !== undefined && expectedPrep !== nextTok) {
                  if (expectedPrep === "") {
                    // El nuevo verbo no lleva preposición: eliminar la preposición
                    responseTokens.splice(i + 1, 1);
                  } else {
                    // Cambiar la preposición
                    responseTokens[i + 1] = expectedPrep;
                    substitutedIndices.add(i + 1);
                    substitutions++;
                  }
                }
                // Si expectedPrep === nextTok o expectedPrep === undefined, no cambiar
              } else if (expectedPrep && expectedPrep.length > 0) {
                // Si no hay preposición y la colocación la espera, insertarla.
                responseTokens.splice(i + 1, 0, expectedPrep);
                substitutedIndices.add(i + 1);
                substitutions++;
              }
            }
            break;
          }
        }
      }

      // PASO 2: Si no hubo sustituciones por mapeo directo, intentar inverso
      if (substitutions === 0) {
        const canonicalValues = new Set(conceptMap.values());
        for (let i = 0; i < responseTokens.length; i++) {
          if (canonicalValues.has(responseTokens[i])) {
            for (const qTok of queryTokens) {
              if (conceptMap.get(qTok) === responseTokens[i]) {
                responseTokens[i] = qTok;
                substitutions++;
                break;
              }
            }
          }
        }
      }
    }

    let responseText = responseTokens.join(" ");

    // Si no hubo sustituciones, devolver el mejor candidato tal cual
    if (substitutions === 0) {
      if (allCandidates.length > 1) {
        const second = allCandidates[1];
        const secondText = second?.entry?.text ?? second?.text ?? "";
        if (secondText) {
          return {
            text: secondText,
            confidence: Math.max(bestScore * 0.9, second.score ?? 0),
            composed: false,
            method: "fallback_second",
          };
        }
      }
      return { text: bestText, confidence: bestScore, composed: false, method: "no_substitutions" };
    }

    // Pulir con ViterbiGenerator solo si hay muchas sustituciones
    if (substitutions >= 3) {
      try {
        this._viterbi.train(queryText);
        this._viterbi.train(bestText);
        const polished = this._viterbi.generate(responseText, queryText);
        if (polished && polished.length > responseText.length * 0.7) {
          responseText = polished;
        }
      } catch (_) {}
    }

    this._compositionCount++;

    return {
      text: responseText,
      confidence: Math.min(1, bestScore + 0.05 * substitutions),
      composed: true,
      method: "recomposed",
      substitutions,
    };
  }

  /**
   * Intenta generar una respuesta desde cero combinando múltiples candidatos.
   * Solo se usa cuando ningún candidato individual tiene score suficiente.
   */
  combine(queryText, candidates = [], options = {}) {
    if (candidates.length < 2) {
      return this.compose(queryText, candidates, options);
    }

    // Tomar fragmentos de los 2-3 mejores candidatos
    const fragments = [];
    for (const cand of candidates.slice(0, 3)) {
      const text = cand?.entry?.text ?? cand?.text ?? "";
      if (text && text.length > 3) {
        const tokens = tokenize(normalizeText(text));
        // Tomar la primera mitad de cada candidato como contexto
        const half = tokens.slice(0, Math.ceil(tokens.length / 2));
        fragments.push(...half);
      }
    }

    if (fragments.length === 0) {
      return this.compose(queryText, candidates, options);
    }

    // Usar ViterbiGenerator con el vocabulario combinado
    try {
      const uniqueFragments = [...new Set(fragments)];
      for (const cand of candidates.slice(0, 3)) {
        const text = cand?.entry?.text ?? cand?.text ?? "";
        if (text) this._viterbi.train(text);
      }
      const combined = this._viterbi.generate(uniqueFragments.join(" "), queryText);
      if (combined && combined.length > 3) {
        return {
          text: combined,
          confidence: Math.max(0.3, candidates[0]?.score ?? 0.3),
          composed: true,
          method: "combined",
        };
      }
    } catch (_) {}

    return this.compose(queryText, candidates, options);
  }

  /**
   * Entrena el ViterbiGenerator con textos de ejemplo.
   */
  trainOnExamples(examples = []) {
    for (const text of examples) {
      if (text && text.length > 3) {
        this._viterbi.train(text);
      }
    }
  }

  snapshot() {
    return {
      compositions: this._compositionCount,
      viterbiState: this._viterbi.snapshot(),
    };
  }

  toJSON() {
    return { compositionCount: this._compositionCount };
  }

  static fromJSON(data, options = {}) {
    const decoder = new HyperDecoder(options);
    decoder._compositionCount = data?.compositionCount ?? 0;
    return decoder;
  }
}

module.exports = { HyperDecoder };
