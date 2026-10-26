/**
 * Session — Gestión de sesiones multi-turno con memoria CHL.
 *
 * Cada sesión mantiene:
 * - Historial de mensajes (user/assistant/tool)
 * - Referencia al motor CHL para recuperación previa a cada turno
 * - Presupuesto de tokens adaptable al hardware
 *
 * El ciclo de cada turno es:
 * 1. Recuperar contexto relevante de CHL (rápido, C++)
 * 2. Formatear contexto + historial para el LLM
 * 3. Llamar al LLM
 * 4. Procesar tool calls del LLM contra CHL
 * 5. Re-llamar al LLM con resultados de herramientas
 * 6. Devolver respuesta final
 */

const { buildMemoryContext, buildCompactMemoryContext } = require("./memory-context");
const { chooseAdaptiveConfig } = require("../neural/adaptive-context");

const MAX_HISTORY_MESSAGES = 40;
const MAX_TOOL_ROUNDS = 3;

class Session {
  /**
   * @param {Object} opts
   * @param {Object} opts.chl        - instancia de NativeCHL
   * @param {Object} opts.adapter    - ModelAdapter (OpenAI, Anthropic, etc.)
   * @param {Object} opts.systemPrompt - prompt de sistema base (sin memoria)
   * @param {number} opts.maxHistory - máximo de mensajes en historial
   */
  constructor(opts = {}) {
    this.chl = opts.chl;
    this.adapter = opts.adapter;
    this.baseSystemPrompt = opts.systemPrompt || "";
    this.maxHistory = opts.maxHistory || MAX_HISTORY_MESSAGES;
    this.messages = [];
    this.sessionId = `chl-session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    this.stats = {
      turns: 0,
      totalTokens: 0,
      toolCalls: 0,
      memoriesRecalled: 0,
    };
  }

  /**
   * Procesa un turno completo: query → memoria → LLM → tool calls → respuesta.
   *
   * @param {string} userQuery
   * @returns {Object} { response, toolCalls, memoriesUsed, stats }
   */
  async turn(userQuery) {
    this.stats.turns++;
    const startTime = Date.now();

    // 1. Recuperar contexto de CHL
    const memoryContext = await this._retrieveContext(userQuery);

    // 2. Construir system prompt con memoria inyectada
    const systemMsg = this._buildSystemMessage(memoryContext, userQuery);

    // 3. Inicializar mensajes temporales de este turno para soporte de herramientas
    this.messages = [{ role: "user", content: userQuery }];

    // 4. Llamar al LLM con herramientas CHL (sólo system prompt y el query del turno)
    const fullMessages = [systemMsg, ...this.messages];
    let result = await this.adapter.chat(fullMessages);

    this.stats.totalTokens += (result.usage?.total_tokens || result.usage?.input_tokens || 0) +
      (result.usage?.output_tokens || result.usage?.completion_tokens || 0);

    // 5. Bucle de tool calls
    let toolRounds = 0;
    while (result.toolCalls && result.toolCalls.length > 0 && toolRounds < MAX_TOOL_ROUNDS) {
      toolRounds++;
      this.stats.toolCalls += result.toolCalls.length;

      // Añadir respuesta del assistant al historial
      this.messages.push({
        role: "assistant",
        content: result.content || null,
        tool_calls: result.toolCalls,
      });

      // Ejecutar cada tool call contra CHL
      for (const tc of result.toolCalls) {
        const toolResult = await this._executeChlTool(tc.function.name, tc.function.arguments);
        this.messages.push({
          role: "tool",
          tool_call_id: tc.id,
          content: JSON.stringify(toolResult),
        });
      }

      // Re-llamar al LLM
      result = await this.adapter.chat([systemMsg, ...this.messages]);
      this.stats.totalTokens += (result.usage?.total_tokens || result.usage?.input_tokens || 0) +
        (result.usage?.output_tokens || result.usage?.completion_tokens || 0);
    }

    // 6. Guardar turno completo (pregunta + respuesta) como una sola entrada episodica
    const elapsed = Date.now() - startTime;
    if (this.chl) {
      try {
        const episodeText = `User: ${userQuery}\nAssistant: ${result.content || ""}`;
        this.chl.remember(episodeText, null, { source: "auto-history", turnMs: elapsed });
        // Persistir lexicon/conceptos sidecar sincronicamente
        this.chl.saveLexicon?.();
      } catch (err) {
        console.error("[CHL] Error in auto-remember:", err);
      }
    }
    
    // Liberar contexto de chat
    this.messages = [];

    return {
      response: result.content || "",
      toolCalls: result.toolCalls || [],
      memoriesUsed: memoryContext.memories?.length || 0,
      stats: { ...this.stats, lastTurnMs: elapsed },
    };
  }

  /**
   * Recupera contexto relevante de CHL para la query.
   * Combina:
   *  - Ultimas entradas de conversacion (memoria reciente)
   *  - Entradas semanticamente relacionadas con la query
   */
  async _retrieveContext(query) {
    if (!this.chl) return { memories: [], concepts: [], graphEdges: [] };

    try {
      const { navigateSemanticMemory } = require("../neural/chl-semantic-expert");

      // 1. Recuperar ultimos mensajes de conversacion (memoria reciente)
      const recentEntries = this.chl.entries()
        .filter(e => (e.metadata?.source || e.source) === "auto-history")
        .slice(-10)
        .reverse();
      const recentMemories = recentEntries.map((e, idx) => ({
        entry: {
          id: e.id,
          text: e.text || e.input || "",
          score: 1.0 - idx * 0.05, // recientes con score alto
          payload: e.payload,
          metadata: e.metadata,
        },
        score: 1.0 - idx * 0.05,
      }));

      // Wrapper recall function that returns candidates in the shape expected by navigateSemanticMemory
      const recallFn = async (q, opts = {}) => {
        const result = this.chl.recall(q, { topK: opts.topK || 8 });
        const rawCandidates = result?.candidates || [];
        return {
          candidates: rawCandidates.map(c => ({
            entry: {
              id: c.id,
              text: c.text,
              score: c.score,
              payload: c.payload,
              metadata: c.metadata,
            },
            score: c.score,
          })),
        };
      };

      const navResult = await navigateSemanticMemory(query, recallFn, {
        perVariantTopK: 6,
        targetTopK: 10,
      });

      let semanticMemories = (navResult.reranked || []).map(r => ({
        entry: r.entry,
        score: r.score,
      }));

      // Fallback to simple recall if semantic navigation yields no results
      if (semanticMemories.length === 0) {
        const simple = this.chl.recall(query, { topK: 8 });
        const raw = simple?.candidates || [];
        semanticMemories = raw.map(c => ({
          entry: {
            id: c.id,
            text: c.text,
            score: c.score,
            payload: c.payload,
            metadata: c.metadata,
          },
          score: c.score,
        }));
      }

      // Merge: recientes primero, luego semanticas evitando duplicados
      const seenIds = new Set(recentMemories.map(m => m.entry.id));
      const memories = [...recentMemories];
      for (const m of semanticMemories) {
        if (!seenIds.has(m.entry.id)) {
          memories.push(m);
          seenIds.add(m.entry.id);
        }
      }
      this.stats.memoriesRecalled += memories.length;

      // Extract concepts from lexicon if available
      let concepts = [];
      try {
        const lexicon = this.chl.lexicon?.() || this.chl.getLexicon?.() || {};
        concepts = Object.keys(lexicon || {}).slice(0, 20);
      } catch { /* no lexicon */ }

      // Extract graph edges if available
      let graphEdges = [];
      try {
        const graph = this.chl.conceptGraph?.() || this.chl.getGraph?.() || {};
        graphEdges = graph.edges || [];
      } catch { /* no graph */ }

      return { memories, concepts, graphEdges };
    } catch (err) {
      // Final fallback: ultimas entradas + simple recall
      try {
        const recentEntries = this.chl.entries()
          .filter(e => (e.metadata?.source || e.source) === "auto-history")
          .slice(-5)
          .reverse();
        const result = this.chl.recall(query, { topK: 8 });
        const rawCandidates = result?.candidates || [];
        const seenIds = new Set(recentEntries.map(e => e.id));
        const memories = recentEntries.map((e, idx) => ({
          entry: { id: e.id, text: e.text || e.input || "", score: 1.0 - idx * 0.05, payload: e.payload, metadata: e.metadata },
          score: 1.0 - idx * 0.05,
        }));
        for (const c of rawCandidates) {
          if (!seenIds.has(c.id)) {
            memories.push({ entry: { id: c.id, text: c.text, score: c.score, payload: c.payload, metadata: c.metadata }, score: c.score });
            seenIds.add(c.id);
          }
        }
        this.stats.memoriesRecalled += memories.length;
        return { memories, concepts: [], graphEdges: [] };
      } catch {
        return { memories: [], concepts: [], graphEdges: [] };
      }
    }
  }


  /**
   * Construye el mensaje de sistema con memoria inyectada.
   */
  _buildSystemMessage(memoryContext, query = "") {
    const adaptive = chooseAdaptiveConfig({ lmBackend: "external" });
    const maxTokens = adaptive?.memoryBudget || 2000;

    const memBlock = memoryContext.memories?.length > 0
      ? buildMemoryContext({
          memories: memoryContext.memories,
          concepts: memoryContext.concepts,
          graphEdges: memoryContext.graphEdges,
          query,
          maxTokens,
        })
      : "";

    const systemContent = this.baseSystemPrompt
      ? `${this.baseSystemPrompt}\n\n${memBlock}`
      : memBlock;

    return {
      role: "system",
      content: systemContent || "Eres un asistente con acceso a memoria persistente CHL.",
    };
  }

  /**
   * Ejecuta una herramienta CHL llamada por el LLM.
   */
  async _executeChlTool(name, rawArgs) {
    if (!this.chl) return { error: "CHL engine no disponible" };

    let args;
    try {
      args = typeof rawArgs === "string" ? JSON.parse(rawArgs) : rawArgs;
    } catch {
      return { error: `Argumentos inválidos: ${String(rawArgs).slice(0, 200)}` };
    }

    try {
      switch (name) {
        case "chl_remember": {
          this.chl.remember(args.input, args.payload, args.metadata);
          return { ok: true, action: "remembered" };
        }
        case "chl_recall": {
          const result = this.chl.recall(args.query, { topK: args.topK || 5 });
          const candidates = (result?.candidates || []).slice(0, args.topK || 5);
          return {
            ok: true,
            candidates: candidates.map(c => ({
              text: c.text || c.entry?.text || "",
              score: c.score || 0,
            })),
          };
        }
        case "chl_learn": {
          const reward = Math.max(-1, Math.min(1, args.reward || 0));
          this.chl.learn(args.input, reward);
          return { ok: true, action: reward > 0 ? "reinforced" : reward < 0 ? "suppressed" : "neutral" };
        }
        default:
          return { error: `Herramienta desconocida: ${name}` };
      }
    } catch (e) {
      return { error: e.message };
    }
  }

  /**
   * Recorta el historial para no exceder el límite.
   */
  _trimHistory() {
    while (this.messages.length > this.maxHistory) {
      this.messages.shift();
    }
  }

  /**
   * Limpia la sesión (sin borrar memoria CHL).
   */
  reset() {
    this.messages = [];
    this.stats = {
      turns: 0,
      totalTokens: 0,
      toolCalls: 0,
      memoriesRecalled: 0,
    };
  }

  /**
   * Exporta el estado de la sesión.
   */
  snapshot() {
    return {
      sessionId: this.sessionId,
      messageCount: this.messages.length,
      stats: this.stats,
    };
  }
}

module.exports = { Session };
