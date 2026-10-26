/**
 * NeuralCHL v3 — Capa cognitiva delegada a modelos grandes.
 *
 * Esta versión elimina las capas 5-6-8 locales (planning, generación, consolidación)
 * y las reemplaza con delegación al CHL Memory Bridge, que conecta con
 * modelos grandes (GPT-5, Claude, Ollama, etc.).
 *
 * Lo que se mantiene local (rápido, C++ / JS):
 * - Capa 1-2: Encoding y análisis de texto
 * - Capa 3: EmbeddingIndex (memoria vectorial)
 * - Capa 4: NeuralSearcher (beam search sobre grafo de conceptos)
 * - Capa 7: NeuralVerifier (grounding local)
 * - SemanticNavigation (multi-hop retrieval)
 *
 * Lo delegado al Bridge (modelo grande):
 * - Capa 5-6: Planificación y generación de lenguaje
 * - Capa 8: Consolidación (el modelo decide qué recordar)
 */

const { EmbeddingIndex } = require("./embeddings");
const { NeuralVerifier } = require("./verifier");
const { NeuralSearcher } = require("./searcher");
const { navigateSemanticMemory, chainSemanticMemory } = require("./chl-semantic-expert");
const { analyzeText } = require("../analysis");
const { buildConceptGraph } = require("../graph");

function unique(values = []) {
  return Array.from(new Set(values));
}

class NeuralCHL {
  constructor(options = {}) {
    this.options = {
      maxEntries: options.maxEntries ?? 20000,
      seed: options.seed ?? 0,
      profile: options.profile ?? "neural",
      beamWidth: options.beamWidth ?? 3,
      maxSearchDepth: options.maxSearchDepth ?? 3,
    };

    // Capa 3: Memoria vectorial
    this.memory = new EmbeddingIndex({
      maxEntries: this.options.maxEntries,
      conceptMap: options.conceptMap ?? null,
      phraseMap: options.phraseMap ?? null,
      negationMismatchPenalty: options.negationMismatchPenalty ?? 0.5,
    });

    // Capa 4: Buscador semántico
    this.searcher = new NeuralSearcher({
      beamWidth: this.options.beamWidth,
      maxDepth: this.options.maxSearchDepth,
    });

    // Capa 7: Verificador local
    this.verifier = new NeuralVerifier({
      minClaimSupport: options.minClaimSupport ?? 0.2,
      contradictionThreshold: options.contradictionThreshold ?? 0.1,
    });

    // Bridge opcional (modelo grande)
    this._bridge = options.bridge || null;

    // Sesiones
    this._decisionEpisodes = [];
    this._sessions = new Map();
  }

  /**
   * Conecta un bridge de modelo grande.
   * @param {Object} bridge - instancia del Memory Bridge
   */
  attachBridge(bridge) {
    this._bridge = bridge;
  }

  get hasBridge() {
    return !!this._bridge;
  }

  // ─── API de memoria (local, rápido) ────────────────────

  updateLexicon(conceptMap, phraseMap) {
    this.memory.updateLexicon(conceptMap, phraseMap);
  }

  async remember(input, payload = null, metadata = {}) {
    return this.memory.index(input, payload, metadata);
  }

  async recall(query, options = {}) {
    return this.memory.query(query, options);
  }

  async semanticNavigate(query, options = {}) {
    const recallFn = (q, opts) => this.recall(q, opts);
    if (options?.chained !== false) {
      return chainSemanticMemory(query, recallFn, {
        maxHops: options.maxHops ?? 3,
        hopTopK: options.hopTopK ?? options.perVariantTopK ?? 8,
        targetTopK: options.targetTopK ?? 12,
        maxVariants: options.maxVariants ?? 10,
      });
    }
    return navigateSemanticMemory(query, recallFn, {
      perVariantTopK: options.perVariantTopK ?? 8,
      targetTopK: options.targetTopK ?? 12,
      maxVariants: options.maxVariants ?? 10,
    });
  }

  async infer(query, options = {}) {
    const result = await this.recall(query, options);
    const best = result.candidates[0] ?? null;
    return {
      answer: best?.entry?.payload ?? null,
      support: result.candidates.map((c) => c.entry.payload),
      confidence: result.confidence,
      candidates: result.candidates,
    };
  }

  conceptGraph() {
    const entries = [];
    for (const [, e] of this.memory.entries) {
      entries.push({ id: e.id, text: e.text, payload: e.payload, representations: null });
    }
    return buildConceptGraph(entries);
  }

  // ─── Métodos delegados al Bridge ────────────────────────

  /**
   * think: si hay bridge, delega al modelo grande.
   * Si no, devuelve los candidatos crudos para que el caller los use.
   */
  async think(query, options = {}) {
    const navResult = await this.semanticNavigate(query, {
      chained: options.chained !== false,
      maxHops: options.maxHops ?? 2,
      targetTopK: options.topK ?? 8,
    });

    if (this._bridge) {
      try {
        const { buildMemoryContext } = require("../bridge/memory-context");
        const ctx = buildMemoryContext({
          memories: navResult.candidates || [],
          query,
          maxTokens: options.maxTokens || 2000,
        });

        const result = await this._bridge.turn(
          `[THINK] Analiza y razona sobre esta query usando el contexto de memoria proporcionado:\n\nQuery: ${query}`
        );
        return {
          thought: result.response,
          candidates: navResult.candidates,
          evidence: navResult.evidence,
          bridgeUsed: true,
        };
      } catch (err) {
        // Fallback sin bridge
      }
    }

    // Sin bridge: devolver candidatos para procesamiento externo
    return {
      thought: null,
      candidates: navResult.candidates,
      evidence: navResult.evidence,
      bridgeUsed: false,
      hint: "No bridge configured. Use candidates directly or attach a bridge with attachBridge().",
    };
  }

  /**
   * ask: responde usando el bridge si está disponible.
   */
  async ask(query, options = {}) {
    if (this._bridge) {
      try {
        const result = await this._bridge.turn(query);
        return {
          answer: result.response,
          candidates: [],
          confidence: 0.9,
          bridgeUsed: true,
          memoriesUsed: result.memoriesUsed,
        };
      } catch (err) {
        // Fallback
      }
    }

    // Sin bridge: recall + infer básico
    const inferResult = await this.infer(query, options);
    return {
      answer: inferResult.answer || `No tengo suficiente contexto sobre "${query}".`,
      candidates: inferResult.candidates,
      confidence: inferResult.confidence || 0.3,
      bridgeUsed: false,
    };
  }

  /**
   * plan: construye un plan usando el bridge o templates simples.
   */
  async plan(query, options = {}) {
    if (this._bridge) {
      try {
        const result = await this._bridge.turn(
          `[PLAN] Construye un plan paso a paso para: ${query}`
        );
        return {
          plan: result.response,
          steps: [],
          bridgeUsed: true,
        };
      } catch (err) {
        // Fallback
      }
    }

    // Sin bridge: plan simple basado en candidatos
    const navResult = await this.semanticNavigate(query, {
      targetTopK: options.topK ?? 6,
    });
    const steps = (navResult.candidates || []).map((c, i) => ({
      step: i + 1,
      action: c.entry?.text || c.text || "",
      evidence: c.entry?.payload || null,
    }));

    return {
      plan: steps.map(s => `${s.step}. ${s.action}`).join("\n"),
      steps,
      bridgeUsed: false,
    };
  }

  /**
   * verify: verificación local (siempre disponible, no necesita bridge).
   */
  async verify(planOrQuery, options = {}) {
    return this.verifier.verify(planOrQuery, this.memory, options);
  }

  /**
   * learn: refuerza o suprime asociaciones en memoria.
   */
  async learn(input, reward = 0) {
    return this.memory.adjustWeight?.(input, reward) || { ok: false };
  }

  // ─── Consolidación (delegada al bridge si está disponible) ───

  async consolidate(options = {}) {
    if (this._bridge) {
      try {
        const episodes = this._decisionEpisodes.slice(-20);
        const episodeText = episodes.map(e =>
          `Q: ${e.query}\nA: ${e.decision}\nConfidence: ${e.confidence}`
        ).join("\n\n");

        const result = await this._bridge.turn(
          `[CONSOLIDATE] Analiza estos episodios de decisión y extrae patrones o reglas:\n\n${episodeText}`
        );

        return {
          patterns: result.response,
          episodesAnalyzed: episodes.length,
          bridgeUsed: true,
        };
      } catch (err) {
        // Fallback
      }
    }

    return {
      patterns: null,
      episodesAnalyzed: this._decisionEpisodes.length,
      bridgeUsed: false,
    };
  }
}

module.exports = { NeuralCHL };
