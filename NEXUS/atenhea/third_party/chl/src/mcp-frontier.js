/**
 * MCP Frontier Tools — Extensión del MCP server con capacidades frontier.
 * 
 * Añade herramientas para:
 * - chl_frontier_status: estado del trainer, attention, decoder, reasoner
 * - chl_reason: inferencia multi-hop
 * - chl_compose: composición HyperDecoder
 * - chl_feedback: entrenamiento online
 */

const { LexiconTrainer } = require("./lexiconLearner");
const { HyperAttentionContext } = require("./hyperattention");
const { HyperDecoder } = require("./hyperdecoder");
const { HyperReason } = require("./hyperreason");
const fs = require("node:fs");
const path = require("node:path");

/**
 * Inicializa los componentes frontier desde archivos de bootstrap.
 */
function initFrontier(options = {}) {
  const artifactsDir = options.artifactsDir ?? path.resolve(__dirname, "..", "artifacts");
  const seed = options.seed ?? 42;

  // Cargar lexicon bootstrap
  let conceptMap = new Map();
  let collocationMap = new Map();
  
  const bootstrapPath = path.join(artifactsDir, "chl-concepts-bootstrap.tsv");
  if (fs.existsSync(bootstrapPath)) {
    const lines = fs.readFileSync(bootstrapPath, "utf8").split("\n");
    for (const line of lines) {
      const [variant, canonical] = line.split("\t");
      if (variant && canonical) conceptMap.set(variant.trim(), canonical.trim());
    }
  }

  const collocationPath = path.join(artifactsDir, "chl-collocations.json");
  if (fs.existsSync(collocationPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(collocationPath, "utf8"));
      for (const [verb, prep] of data.collocations || []) {
        collocationMap.set(verb, prep);
      }
    } catch (_) {}
  }

  // Inicializar componentes
  const trainer = new LexiconTrainer({
    conceptMap,
    collocationMap,
    seed,
    prototypesPath: path.join(artifactsDir, "concepts-prototypes.json"),
  });
  
  // Cargar estado guardado si existe
  trainer.load();

  const attention = new HyperAttentionContext({ seed });
  const decoder = new HyperDecoder({ lexiconTrainer: trainer, seed });
  const reasoner = new HyperReason({ lexiconTrainer: trainer, seed });

  return { trainer, attention, decoder, reasoner, artifactsDir };
}

/**
 * Definiciones de herramientas adicionales para el MCP.
 */
function frontierToolDefinitions() {
  return [
    {
      name: "chl_frontier_status",
      description: "Estado de los componentes frontier: trainer, attention, decoder, reasoner",
      inputSchema: { type: "object", properties: {}, required: [] },
    },
    {
      name: "chl_reason",
      description: "Inferencia multi-hop sobre la memoria. Encadena hechos para responder preguntas que requieren razonamiento.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Pregunta a razonar" },
          maxHops: { type: "number", description: "Máxima profundidad de inferencia (default 3)" },
          topK: { type: "number", description: "Número de entradas a recuperar para razonar (default 10)" },
        },
        required: ["query"],
      },
    },
    {
      name: "chl_compose",
      description: "Recompone una respuesta usando el vocabulario de la query. Útil para adaptar respuestas recuperadas al lenguaje del usuario.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Query original del usuario" },
          topK: { type: "number", description: "Número de candidatos a usar (default 5)" },
        },
        required: ["query"],
      },
    },
    {
      name: "chl_feedback",
      description: "Entrena el sistema a partir de una corrección. Mejora futuros recalls.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Query que falló" },
          expectedText: { type: "string", description: "El texto/respuesta que DEBERÍA haberse recuperado" },
          rejectedText: { type: "string", description: "El texto/respuesta incorrecta que se recuperó" },
        },
        required: ["query", "expectedText"],
      },
    },
  ];
}

/**
 * Maneja las llamadas a herramientas frontier.
 */
async function handleFrontierTool(toolName, args, context) {
  const frontier = context._frontier;
  if (!frontier) {
    return { error: "Frontier components not initialized. Set CHL_FRONTIER=true" };
  }

  const { trainer, attention, decoder, reasoner } = frontier;

  switch (toolName) {
    case "chl_frontier_status": {
      return {
        trainer: trainer.snapshot(),
        attention: attention.snapshot(),
        decoder: decoder.snapshot(),
        reasoner: reasoner.snapshot(),
      };
    }

    case "chl_reason": {
      const query = args.query;
      const maxHops = args.maxHops ?? 3;
      const topK = args.topK ?? 10;

      // Recuperar entradas relevantes de la memoria
      const engine = context._engine;
      if (!engine) return { error: "No memory engine available" };

      const recallResult = await (engine.recall ? engine.recall(query, { topK }) : engine.query?.(query, { topK }));
      const candidates = recallResult?.candidates ?? [];
      const entries = candidates.map(c => ({
        id: c.entry?.id ?? c.id ?? "",
        text: c.entry?.text ?? c.text ?? "",
        payload: c.entry?.payload ?? c.payload,
      }));

      const result = reasoner.reason(query, entries, { maxHops });
      return result;
    }

    case "chl_compose": {
      const query = args.query;
      const topK = args.topK ?? 5;

      const engine = context._engine;
      if (!engine) return { error: "No memory engine available" };

      const recallResult = await (engine.recall ? engine.recall(query, { topK }) : engine.query?.(query, { topK }));
      const candidates = recallResult?.candidates ?? [];

      const result = decoder.compose(query, candidates);
      return result;
    }

    case "chl_feedback": {
      const { query, expectedText, rejectedText } = args;

      // Resolver conceptos
      const expectedConcept = trainer.resolveConcept(expectedText);
      const rejectedConcept = rejectedText ? trainer.resolveConcept(rejectedText) : null;

      const rejectedIds = rejectedConcept ? [rejectedConcept] : [];
      const fbResult = trainer.applyOnlineFeedback(query, expectedConcept || "unknown", rejectedIds);

      // También actualizar atención
      const { prototypeVectorFromText } = require("./hypervector");
      const qv = prototypeVectorFromText(query, 256, trainer.seed);
      attention.updateKeys(qv, { prototype: 0.05, intent: 0.03 });

      return {
        ok: true,
        feedback: fbResult,
        trainerState: trainer.snapshot(),
      };
    }

    default:
      return { error: `Unknown frontier tool: ${toolName}` };
  }
}

module.exports = {
  initFrontier,
  frontierToolDefinitions,
  handleFrontierTool,
};
