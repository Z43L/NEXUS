const { resolveMemoryProfile } = require("./profiles");
const { serializePairList } = require("./concepts");
const { processFile, scanDirectory, scanDirectoryStats } = require("./ingester");
const { evaluateInteraction, buildMemoryEntry, buildMemoryPayload, buildMemoryMetadata } = require("./auto-memory");
const {
  MemoryType,
  normalizeMemoryType,
  getDefaultExpiry,
  isExpired,
} = require("./memory-types");
const { classifyMemory } = require("./memory-classifier");
const {
  QueryIntent,
  detectQueryIntent,
  intentToMemoryTypes,
  getTypeBoostForIntent,
  getScoringProfileForIntent,
  buildQueryOptions,
} = require("./query-intent");

const SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];

function createMcpContext(options = {}) {
  const frontierMode = process.env.CHL_FRONTIER === "true" || options.frontier === true;
  
  const memoryOptions = resolveMemoryProfile({
    ...(options.memory ?? {}),
    profile: options.profile ?? (options.memory ?? {}).profile ?? (frontierMode ? "large" : undefined),
    persistPath:
      (options.memory ?? {}).persistPath ??
      process.env.CHL_PERSIST_PATH ??
      null,
  });
  const deferMemoryInit = options.deferMemoryInit === true;
  
  const createMemory = () => {
    if (frontierMode) {
      // Frontier mode: usar JSCHL con componentes de aprendizaje
      const { CHL: JSCHL } = require("./chl");
      const { initFrontier } = require("./mcp-frontier");
      const frontier = initFrontier({ 
        artifactsDir: options.artifactsDir ?? undefined,
        seed: memoryOptions.seed ?? 42,
      });
      const engine = new JSCHL({
        ...memoryOptions,
        lexiconTrainer: frontier.trainer,
        attention: frontier.attention,
      });
      // Adjuntar frontier al engine para acceso desde herramientas
      engine._frontier = frontier;
      return engine;
    }
    const { NativeCHL } = require("./native");
    return new NativeCHL(memoryOptions);
  };

  const autoRememberMode = process.env.CHL_AUTO_REMEMBER || "smart";

  const ctx = {
    memory: deferMemoryInit ? null : createMemory(),
    _createMemory: createMemory,
    serverInfo: {
      name: frontierMode ? "chl-memory-frontier" : "chl-memory",
      version: frontierMode ? "0.3.0" : "0.2.0",
    },
    autoRemember: {
      enabled: autoRememberMode !== "off" && autoRememberMode !== "false",
      mode: autoRememberMode === "all" ? "all" : "smart",
    },
    _frontierMode: frontierMode,
  };
  
  return ctx;
}

async function ensureMemoryReady(context) {
  if (context && !context.memory && typeof context._createMemory === "function") {
    context.memory = context._createMemory();
  }
  if (context?.memory && typeof context.memory.whenReady === "function") {
    await context.memory.whenReady();
  }
}

function toolDefinitions() {
  return [
    // ─── Core memory tools ────────────────────────────────
    {
      name: "chl_init",
      description: "Inicializa o reinicia la memoria CHL completamente. Carga el estado de bootstrap del lexicón y restablece todos los índices. Úsalo al inicio de una sesión o cuando necesites limpiar y empezar de cero.",
      inputSchema: {
        type: "object",
        properties: {
          profile: { type: "string", description: "Perfil de memoria: small, medium, large (default: large en frontier)" },
          seed: { type: "number", description: "Semilla para vectores (default: 42)" },
          reset: { type: "boolean", description: "Si true, hace clear() completo antes de reinicializar (default: true)" },
        },
        additionalProperties: false,
      },
    },
    {
      name: "chl_remember",
      description: "Store a memory entry in CHL. Accepts optional memoryType metadata (ephemeral, short_term, medium_term, long_term, user_profile, self_profile, knowledge, episodic). If omitted the entry is automatically classified.",
      inputSchema: {
        type: "object",
        properties: {
          input: {},
          payload: {},
          metadata: {
            type: "object",
            properties: {
              memoryType: { type: "string", description: "Explicit memory type." },
              source: { type: "string", description: "Origin tag (e.g. user, ingest, consolidation)." },
              quality: { type: "number", description: "Entry quality 0-1 (default 1)." },
              expiresAt: { type: "number", description: "Epoch ms when the entry becomes stale." },
            },
            additionalProperties: true,
          },
        },
        required: ["input"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_remember_typed",
      description: "Store a memory entry with an explicit memory type and optional TTL. Useful for user profiles, AI self-personality, knowledge bases or time-bounded facts.",
      inputSchema: {
        type: "object",
        properties: {
          input: {},
          payload: {},
          memoryType: { type: "string", description: "Memory type: ephemeral, short_term, medium_term, long_term, user_profile, self_profile, knowledge, episodic." },
          source: { type: "string", description: "Origin tag (e.g. user, ai, ingest)." },
          ttlSeconds: { type: "number", minimum: 1, description: "Time-to-live in seconds. Sets expiresAt if not provided." },
          quality: { type: "number", description: "Entry quality 0-1 (default 1)." },
          metadata: { type: "object", additionalProperties: true },
        },
        required: ["input", "memoryType"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_recall",
      description: "Query CHL for the nearest matching memories. Supports adaptive intent detection, type filtering and type-specific scoring profiles.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          topK: { type: "number", minimum: 1 },
          memoryType: { type: "string", description: "Restrict results to a single memory type." },
          excludeTypes: { type: "array", items: { type: "string" }, description: "Memory types to exclude." },
          timeWindowMs: { type: "number", description: "Only return entries newer than this many ms." },
          minQuality: { type: "number", minimum: 0, maximum: 1, description: "Minimum entry quality." },
          source: { type: "string", description: "Filter by source tag." },
          intent: { type: "string", description: "Query intent override: self_reflection, user_recall, personal_preference, fact_lookup, procedural, general_chat." },
          boostProfile: { type: "string", description: "Scoring profile override: default, user-centric, ai-centric, fact-centric, episodic, long-term, short-term." },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_recall_by_type",
      description: "Retrieve memories filtered by one or more memory types, optionally applying intent-aware boosts.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          memoryType: { type: "string", description: "Primary memory type to include." },
          includeTypes: { type: "array", items: { type: "string" }, description: "List of memory types to include (overrides memoryType)." },
          excludeTypes: { type: "array", items: { type: "string" }, description: "Memory types to exclude." },
          topK: { type: "number", minimum: 1 },
          timeWindowMs: { type: "number" },
          minQuality: { type: "number", minimum: 0, maximum: 1 },
          source: { type: "string" },
          intent: { type: "string" },
          boostProfile: { type: "string" },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_recall_personalized",
      description: "Recall memories prioritizing user profile and AI self-profile entries. Intent is auto-detected from the query, but can be overridden.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          topK: { type: "number", minimum: 1 },
          intent: { type: "string", description: "Override auto-detected intent." },
          timeWindowMs: { type: "number" },
          minQuality: { type: "number", minimum: 0, maximum: 1 },
          includeProfiles: { type: "boolean", description: "Always include profile entries even if the query is generic (default true)." },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_infer",
      description: "Infer the best answer from the nearest matching memories.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          topK: { type: "number", minimum: 1 },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_think",
      description: "Build a structured thought trace from memory, graph and hypotheses.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          topK: { type: "number", minimum: 1 },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_ask",
      description: "Choose between answering, clarifying or planning from the current memory state.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          topK: { type: "number", minimum: 1 },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_plan",
      description: "Build a structured plan from the current thought trace.",
      inputSchema: {
        type: "object",
        properties: {
          query: {},
          topK: { type: "number", minimum: 1 },
        },
        required: ["query"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_verify",
      description: "Verify a plan or query against memory and the concept graph.",
      inputSchema: {
        type: "object",
        properties: {
          plan: {},
          query: {},
          topK: { type: "number", minimum: 1 },
        },
        additionalProperties: false,
      },
    },
    {
      name: "chl_learn_from_verification",
      description: "Update memory feedback using a verification result.",
      inputSchema: {
        type: "object",
        properties: {
          verification: {},
          plan: {},
          query: {},
          extraSignals: { type: "array" },
        },
        additionalProperties: false,
      },
    },
    {
      name: "chl_consolidate",
      description: "Consolidate repeated decision episodes into semantic rules.",
      inputSchema: {
        type: "object",
        properties: {
          startIndex: { type: "number", minimum: 0 },
          minSupport: { type: "number", minimum: 1 },
        },
        additionalProperties: false,
      },
    },
    {
      name: "chl_learn",
      description: "Apply feedback to a memory or query string.",
      inputSchema: {
        type: "object",
        properties: {
          input: {},
          reward: { type: "number" },
        },
        required: ["input"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_backup_memory",
      description: "Export the full CHL memory backup to a .memory file path.",
      inputSchema: {
        type: "object",
        properties: {
          backupPath: { type: "string" },
        },
        required: ["backupPath"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_lexicon",
      description: "Inspect the learned concept and phrase lexicon.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_lexicon_export",
      description: "Export the lexicon as a TSV string for storage or training.",
      inputSchema: {
        type: "object",
        properties: {
          conceptsPath: { type: "string" },
          phrasesPath: { type: "string" },
        },
        additionalProperties: false,
      },
    },
    {
      name: "chl_restore_memory",
      description: "Import a memory backup from a .memory file path.",
      inputSchema: {
        type: "object",
        properties: {
          backupPath: { type: "string" },
        },
        required: ["backupPath"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_snapshot",
      description: "Return a lightweight snapshot of the current memory state.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_profile",
      description: "Return the active CHL profile configuration.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_state",
      description: "Return a full internal state dump for debugging.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_graph",
      description: "Return the current concept graph.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_entries",
      description: "Return every stored memory entry.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_journal",
      description: "Return the mutation journal.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_episodes",
      description: "Return recorded decision episodes.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_bucket_stats",
      description: "Return bucket-level statistics for debugging retrieval.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_clear",
      description: "Clear all memory entries. Requires explicit confirmation.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },

    // ─── Ingestion tools ──────────────────────────────────
    {
      name: "chl_ingest_file",
      description: "Ingest a single file into CHL memory. Supports PDF, Markdown, code, text, DOCX. The file is chunked intelligently and each chunk is stored as a separate memory entry with source metadata.",
      inputSchema: {
        type: "object",
        properties: {
          filePath: { type: "string", description: "Absolute path to the file to ingest." },
          maxChars: { type: "number", description: "Maximum characters per chunk (default 1200)." },
          overlapChars: { type: "number", description: "Overlap characters between chunks (default 200)." },
        },
        required: ["filePath"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_ingest_directory",
      description: "Scan and ingest all supported files from a directory recursively into CHL memory. Skips node_modules, .git, and other common ignore directories.",
      inputSchema: {
        type: "object",
        properties: {
          dirPath: { type: "string", description: "Absolute path to the directory to ingest." },
          maxFiles: { type: "number", description: "Maximum number of files to ingest (default 500)." },
          maxFileBytes: { type: "number", description: "Maximum bytes per file (default 3MB)." },
          maxChars: { type: "number", description: "Maximum characters per chunk (default 1200)." },
          includeHidden: { type: "boolean", description: "Include hidden directories (default false)." },
        },
        required: ["dirPath"],
        additionalProperties: false,
      },
    },
    {
      name: "chl_ingest_stats",
      description: "Scan a directory and return statistics about what would be ingested, without actually ingesting anything.",
      inputSchema: {
        type: "object",
        properties: {
          dirPath: { type: "string", description: "Absolute path to the directory to scan." },
        },
        required: ["dirPath"],
        additionalProperties: false,
      },
    },

    // ─── Auto-memory tools ────────────────────────────────
    {
      name: "chl_auto_remember_status",
      description: "Check whether automatic memory logging is enabled and its current mode.",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
    {
      name: "chl_auto_remember_config",
      description: "Configure automatic memory logging mode.",
      inputSchema: {
        type: "object",
        properties: {
          mode: { type: "string", description: "One of: 'all' (log everything), 'smart' (only valuable interactions), 'off' (disable)." },
        },
        required: ["mode"],
        additionalProperties: false,
      },
    },
  ];
}

function buildRecallOptions(args) {
  const options = {
    topK: args.topK ?? 5,
  };
  if (args.memoryType) options.memoryType = normalizeMemoryType(args.memoryType);
  if (Array.isArray(args.excludeTypes) && args.excludeTypes.length > 0) {
    options.excludeTypes = args.excludeTypes.map(normalizeMemoryType).filter(Boolean);
  }
  if (typeof args.timeWindowMs === "number") options.timeWindowMs = args.timeWindowMs;
  if (typeof args.minQuality === "number") options.minQuality = args.minQuality;
  if (args.source) options.source = String(args.source);
  if (args.intent) options.intent = String(args.intent).toLowerCase();
  if (args.boostProfile) options.boostProfile = String(args.boostProfile);
  return options;
}

function formatRecallResult(recall) {
  return {
    confidence: recall.confidence,
    candidates: (recall.candidates ?? []).map((c) => ({
      id: c.id ?? c.entry?.id ?? "",
      text: c.text ?? c.entry?.text ?? "",
      score: c.score ?? 0,
      memoryType: c.metadata?.memoryType ?? c.entry?.memoryType ?? null,
      source: c.metadata?.source ?? c.entry?.source ?? null,
      quality: c.quality ?? c.metadata?.quality ?? null,
      expiresAt: c.metadata?.expiresAt ?? c.entry?.expiresAt ?? null,
      payload: c.payload ?? c.entry?.payload ?? null,
    })),
  };
}

async function callTool(context, name, args) {
  await ensureMemoryReady(context);
  const mem = context.memory;
  if (!mem) throw new Error("CHL memory not ready");

  // Frontier tools — delegar al handler especializado
  if (context._frontierMode && mem._frontier) {
    const { handleFrontierTool, frontierToolDefinitions } = require("./mcp-frontier");
    const frontierTools = new Set(frontierToolDefinitions().map(t => t.name));
    if (frontierTools.has(name)) {
      const ctx = { _engine: mem, _frontier: mem._frontier };
      const frontierResult = await handleFrontierTool(name, args, ctx);
      return { content: [{ type: "text", text: JSON.stringify(frontierResult) }] };
    }
  }

  let result = null;

  switch (name) {
    // ─── Core ─────────────────────────────────────────────
    case "chl_init": {
      const shouldReset = args.reset !== false;
      if (shouldReset && typeof mem.clear === "function") {
        mem.clear();
      }
      // Reinicializar con nuevo perfil si se especifica
      if (args.profile || args.seed) {
        const { CHL: JSCHL } = require("./chl");
        const { initFrontier } = require("./mcp-frontier");
        const { resolveMemoryProfile } = require("./profiles");
        const newProfile = args.profile ?? "large";
        const newOpts = resolveMemoryProfile({ profile: newProfile, seed: args.seed ?? 42 });
        if (context._frontierMode) {
          const frontier = initFrontier({
            artifactsDir: undefined,
            seed: args.seed ?? 42,
          });
          const newEngine = new JSCHL({
            ...newOpts,
            lexiconTrainer: frontier.trainer,
            attention: frontier.attention,
          });
          newEngine._frontier = frontier;
          context.memory = newEngine;
        } else {
          const { NativeCHL } = require("./native");
          context.memory = new NativeCHL(newOpts);
        }
      }
      // Cargar estado del lexicón desde bootstrap
      if (context._frontierMode && context.memory._frontier) {
        const { trainer } = context.memory._frontier;
        if (trainer && typeof trainer.load === "function") {
          trainer.load();
        }
      }
      result = {
        ok: true,
        action: "initialized",
        profile: context.memory.profile?.(),
        entries: context.memory.entries?.()?.length ?? 0,
        frontier: context._frontierMode,
      };
      break;
    }
    case "chl_remember": {
      const entry = mem.remember(args.input, args.payload, args.metadata);
      result = {
        ok: true,
        action: "remembered",
        memoryType: entry?.memoryType ?? entry?.metadata?.memoryType ?? args.metadata?.memoryType ?? null,
      };
      break;
    }
    case "chl_remember_typed": {
      const now = Date.now();
      const explicitType = normalizeMemoryType(args.memoryType);
      const metadata = {
        ...(args.metadata || {}),
        memoryType: explicitType,
        source: args.source ?? args.metadata?.source ?? "",
        quality: args.quality ?? args.metadata?.quality ?? 1,
        createdAt: args.metadata?.createdAt ?? now,
        expiresAt: args.metadata?.expiresAt ?? (args.ttlSeconds ? now + args.ttlSeconds * 1000 : getDefaultExpiry(explicitType)),
      };
      const entry = mem.remember(args.input, args.payload, metadata);
      result = {
        ok: true,
        action: "remembered_typed",
        memoryType: explicitType,
        expiresAt: metadata.expiresAt,
        entryId: entry?.id ?? null,
      };
      break;
    }
    case "chl_recall": {
      const recall = mem.recall(args.query, buildRecallOptions(args));
      result = formatRecallResult(recall);
      break;
    }
    case "chl_recall_by_type": {
      const options = buildRecallOptions(args);
      if (Array.isArray(args.includeTypes) && args.includeTypes.length > 0) {
        const types = args.includeTypes.map(normalizeMemoryType).filter(Boolean);
        options.includeTypes = types;
        options.memoryTypes = types;
      }
      const recall = mem.recall(args.query, options);
      result = formatRecallResult(recall);
      break;
    }
    case "chl_recall_personalized": {
      const intent = args.intent ? String(args.intent).toLowerCase() : detectQueryIntent(args.query);
      const targetTypes = intentToMemoryTypes(intent);
      const profileTypes = [MemoryType.USER_PROFILE, MemoryType.SELF_PROFILE];
      const includeProfiles = args.includeProfiles !== false;
      const includeTypes = includeProfiles
        ? Array.from(new Set([...profileTypes, ...targetTypes]))
        : targetTypes;
      const options = {
        ...buildRecallOptions(args),
        includeTypes,
        memoryTypes: includeTypes,
        intent,
        boostProfile: args.boostProfile || "user-centric",
      };
      const recall = mem.recall(args.query, options);
      result = {
        ...formatRecallResult(recall),
        detectedIntent: intent,
        includeTypes,
      };
      break;
    }
    case "chl_infer": {
      const recall = mem.recall(args.query, { topK: args.topK ?? 5 });
      const best = recall.candidates[0] ?? null;
      result = {
        answer: best?.payload ?? best?.text ?? best?.entry?.payload ?? null,
        support: recall.candidates.map(c => c.payload ?? c.entry?.payload).filter(Boolean),
        confidence: recall.confidence,
        candidates: recall.candidates.length,
      };
      break;
    }
    case "chl_think": {
      const recall = mem.recall(args.query, { topK: args.topK ?? 5 });
      result = {
        query: args.query,
        candidates: (recall.candidates ?? []).map(c => ({
          text: c.text ?? c.entry?.text,
          score: c.score,
          payload: c.payload ?? c.entry?.payload,
        })),
        confidence: recall.confidence,
      };
      break;
    }
    case "chl_ask": {
      if (typeof mem.ask === "function") {
        result = mem.ask(args.query ?? "", { topK: args.topK ?? 5 });
      } else {
        const recall = mem.recall(args.query ?? "", { topK: args.topK ?? 5 });
        result = {
          candidates: (recall.candidates ?? []).map(c => ({
            text: c.text ?? c.entry?.text,
            score: c.score,
          })),
          confidence: recall.confidence,
        };
      }
      break;
    }
    case "chl_plan": {
      if (typeof mem.plan === "function") {
        result = mem.plan(args.query ?? "", { topK: args.topK ?? 5 });
      } else {
        result = { error: "plan not available" };
      }
      break;
    }
    case "chl_verify": {
      if (typeof mem.verify === "function") {
        result = mem.verify(args.plan ?? args.query ?? "", { topK: args.topK ?? 5 });
      } else {
        result = { error: "verify not available" };
      }
      break;
    }
    case "chl_learn_from_verification": {
      if (typeof mem.learnFromVerification === "function") {
        result = mem.learnFromVerification(args.verification ?? args);
      } else {
        result = { error: "learnFromVerification not available" };
      }
      break;
    }
    case "chl_consolidate": {
      if (typeof mem.consolidate === "function") {
        const r = mem.consolidate(args.startIndex, args.minSupport);
        result = r;
      } else {
        result = { ok: false, message: "consolidation not available in this profile" };
      }
      break;
    }
    case "chl_learn": {
      mem.learn(args.input, args.reward ?? 0);
      result = { ok: true, action: "learned" };
      break;
    }
    case "chl_backup_memory": {
      if (!args.backupPath) throw new Error("chl_backup_memory requires backupPath");
      if (typeof mem.backupMemory !== "function") throw new Error("backupMemory not available");
      const saveRes = mem.saveMemory(args.backupPath);
      result = typeof saveRes === "object" && saveRes !== null ? saveRes : { ok: true, path: args.backupPath };
      result.backupPath = args.backupPath;
      break;
    }
    case "chl_lexicon": {
      const lex = mem.lexicon?.() ?? { concepts: [], phrases: [] };
      result = {
        ...lex,
        counts: {
          concepts: lex.concepts?.length ?? 0,
          phrases: lex.phrases?.length ?? 0,
        },
        sources: {
          conceptsPath: mem.conceptsPath ?? null,
          phrasesPath: mem.phrasesPath ?? null,
        },
        conceptPairs: lex.concepts?.length ?? 0,
        prototypeCount: lex.prototypeCount ?? 0,
        phraseCount: lex.phrases?.length ?? 0,
        trainer: lex.trainer ?? null,
      };
      break;
    }
    case "chl_lexicon_export": {
      const l = mem.lexicon?.() ?? { concepts: [], phrases: [] };
      result = {
        format: "chl-lexicon-tsv-v1",
        export: {
          conceptsTsv: serializePairList(l.concepts || []),
          phrasesTsv: serializePairList(l.phrases || []),
        },
        trainerSnapshot: l.trainer ?? null,
      };
      break;
    }
    case "chl_restore_memory": {
      if (!args.backupPath) throw new Error("chl_restore_memory requires backupPath");
      if (typeof mem.restoreMemory !== "function") throw new Error("restoreMemory not available");
      mem.loadMemory(args.backupPath, { replace: args.replace ?? true });
      result = { ok: true, restoredFrom: args.backupPath };
      break;
    }
    case "chl_snapshot": {
      result = {
        entryCount: mem.entries?.()?.length ?? 0,
        journalLength: mem.journal?.()?.length ?? 0,
        episodesCount: mem.episodes?.()?.length ?? 0,
        autoRemember: context.autoRemember || { enabled: false, mode: "off" },
      };
      break;
    }
    case "chl_profile": {
      const p = mem.profile?.();
      result = typeof p === "object" && p !== null ? p : { profile: p ?? "default" };
      break;
    }
    case "chl_state": {
      result = {
        entries: mem.entries?.(),
        journal: mem.journal?.(),
        episodes: mem.episodes?.(),
        autoRemember: context.autoRemember || { enabled: false, mode: "off" },
      };
      break;
    }
    case "chl_graph": {
      result = mem.conceptGraph?.() ?? { nodes: [], edges: [] };
      break;
    }
    case "chl_entries": {
      result = mem.entries?.() ?? [];
      break;
    }
    case "chl_journal": {
      result = mem.journal?.() ?? [];
      break;
    }
    case "chl_episodes": {
      result = mem.episodes?.() ?? [];
      break;
    }
    case "chl_bucket_stats": {
      result = mem.bucketStats?.() ?? {};
      break;
    }
    case "chl_clear": {
      mem.clear?.();
      result = { ok: true, action: "cleared" };
      break;
    }

    // ─── Ingestion ────────────────────────────────────────
    case "chl_ingest_file": {
      const chunks = processFile(args.filePath, {
        maxChars: args.maxChars || 1200,
        overlapChars: args.overlapChars || 200,
      });

      if (chunks.length === 0) {
        result = { ok: true, filePath: args.filePath, chunksIngested: 0, message: "No extractable content found." };
        break;
      }

      let ingested = 0;
      for (const chunk of chunks) {
        try {
          mem.remember(chunk.text, { chunkText: chunk.text.slice(0, 500) }, chunk.metadata);
          ingested++;
        } catch { /* skip failed chunks */ }
      }

      result = {
        ok: true,
        filePath: args.filePath,
        chunksIngested: ingested,
        totalChunks: chunks.length,
        fileType: chunks[0]?.metadata?.fileType || "unknown",
      };
      break;
    }

    case "chl_ingest_directory": {
      const maxFiles = args.maxFiles || 500;
      const files = scanDirectory(args.dirPath, {
        maxFiles,
        maxFileBytes: args.maxFileBytes || 3 * 1024 * 1024,
        includeHidden: args.includeHidden || false,
      });

      if (files.length === 0) {
        result = { ok: true, dirPath: args.dirPath, filesFound: 0, filesIngested: 0, chunksIngested: 0 };
        break;
      }

      let filesIngested = 0;
      let totalChunks = 0;
      const errors = [];

      for (const filePath of files) {
        try {
          const chunks = processFile(filePath, {
            maxChars: args.maxChars || 1200,
            overlapChars: args.overlapChars || 200,
          });
          for (const chunk of chunks) {
            mem.remember(chunk.text, { chunkText: chunk.text.slice(0, 500) }, chunk.metadata);
            totalChunks++;
          }
          if (chunks.length > 0) filesIngested++;
        } catch (err) {
          errors.push({ file: filePath, error: err.message });
        }
      }

      result = {
        ok: true,
        dirPath: args.dirPath,
        filesFound: files.length,
        filesIngested,
        chunksIngested: totalChunks,
        errors: errors.slice(0, 10),
      };
      break;
    }

    case "chl_ingest_stats": {
      result = scanDirectoryStats(args.dirPath);
      break;
    }

    // ─── Auto-memory ──────────────────────────────────────
    case "chl_auto_remember_status": {
      result = {
        enabled: context.autoRemember?.enabled ?? false,
        mode: context.autoRemember?.mode ?? "off",
        envValue: process.env.CHL_AUTO_REMEMBER || "not set",
      };
      break;
    }

    case "chl_auto_remember_config": {
      const mode = String(args.mode || "").toLowerCase();
      if (!["all", "smart", "off"].includes(mode)) {
        throw new Error(`Invalid mode: ${mode}. Use 'all', 'smart', or 'off'.`);
      }
      context.autoRemember = {
        enabled: mode !== "off",
        mode,
      };
      result = { ok: true, autoRemember: context.autoRemember };
      break;
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }

  // ─── Auto-memory hook ──────────────────────────────────
  if (context.autoRemember?.enabled && result && !name.startsWith("chl_")) {
    try {
      const evalResult = evaluateInteraction(
        {
          query: name,
          response: JSON.stringify(result).slice(0, 500),
          toolCalls: [{ function: { name, arguments: args } }],
          mode: context.autoRemember.mode,
        },
        context.autoRemember.mode
      );

      if (evalResult.shouldRemember) {
        const entry = buildMemoryEntry({
          query: `[tool:${name}] ${JSON.stringify(args).slice(0, 300)}`,
          response: JSON.stringify(result).slice(0, 400),
          toolCalls: [{ function: { name, arguments: args } }],
        });

        const payload = buildMemoryPayload({
          query: `[tool:${name}]`,
          response: JSON.stringify(result).slice(0, 400),
          toolCalls: [{ function: { name, arguments: args } }],
          stats: {},
        });

        const metadata = buildMemoryMetadata({
          toolCalls: [{ function: { name, arguments: args } }],
          mode: context.autoRemember.mode,
          autoScore: evalResult.score,
        });

        mem.remember(entry, payload, metadata);
      }
    } catch {
      // Auto-memory nunca debe romper el tool call principal
    }
  }

  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
  };
}

function listTools(context) {
  const tools = toolDefinitions();
  if (context?._frontierMode) {
    const { frontierToolDefinitions } = require("./mcp-frontier");
    tools.push(...frontierToolDefinitions());
  }
  return { tools };
}

function listResources(context) {
  return {
    resources: [
      { uri: "chl://memory", mimeType: "application/json", name: "CHL Memory Snapshot" },
      { uri: "chl://profile", mimeType: "application/json", name: "CHL Profile" },
      { uri: "chl://state", mimeType: "application/json", name: "CHL Full State" },
      { uri: "chl://graph", mimeType: "application/json", name: "CHL Concept Graph" },
      { uri: "chl://thought", mimeType: "application/json", name: "CHL Latest Thought" },
      { uri: "chl://plan", mimeType: "application/json", name: "CHL Latest Plan" },
      { uri: "chl://entries", mimeType: "application/json", name: "CHL All Entries" },
      { uri: "chl://journal", mimeType: "application/json", name: "CHL Mutation Journal" },
      { uri: "chl://episodes", mimeType: "application/json", name: "CHL Decision Episodes" },
      { uri: "chl://consolidation", mimeType: "application/json", name: "CHL Consolidation State" },
      { uri: "chl://backup.memory", mimeType: "application/octet-stream", name: "CHL Memory Backup" },
      { uri: "chl://lexicon", mimeType: "application/json", name: "CHL Lexicon" },
      { uri: "chl://lexicon.concepts", mimeType: "text/tab-separated-values", name: "CHL Concepts TSV" },
      { uri: "chl://lexicon.phrases", mimeType: "text/tab-separated-values", name: "CHL Phrases TSV" },
      { uri: "chl://lexicon.tsv", mimeType: "text/tab-separated-values", name: "CHL Lexicon TSV Export" },
    ],
  };
}

async function readResource(context, uri) {
  if (!context.memory) throw new Error("Memory not initialized");
  switch (uri) {
    case "chl://memory":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify({
            entries: context.memory.entries?.() ?? [],
            entryCount: context.memory.entries?.()?.length ?? 0,
            journalLength: context.memory.journal?.()?.length ?? 0,
            episodesCount: context.memory.episodes?.()?.length ?? 0,
            autoRemember: context.autoRemember || { enabled: false, mode: "off" },
          }, null, 2),
        }],
      };
    case "chl://profile": {
      const p = context.memory.profile?.();
      const pObj = typeof p === "object" && p !== null ? p : { profile: p ?? "default" };
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify(pObj, null, 2),
        }],
      };
    }
    case "chl://state":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify({
            entries: context.memory.entries?.(),
            journal: context.memory.journal?.(),
            episodes: context.memory.episodes?.(),
            autoRemember: context.autoRemember || { enabled: false, mode: "off" },
          }, null, 2),
        }],
      };
    case "chl://graph":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify(context.memory.conceptGraph?.() ?? {}, null, 2),
        }],
      };
    case "chl://thought":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify({
            hint: "Use chl_think with a query to generate a full thought trace.",
          }, null, 2),
        }],
      };
    case "chl://plan":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify({
            hint: "Use chl_plan with a query to generate a plan, then chl_verify to validate it.",
          }, null, 2),
        }],
      };
    case "chl://entries":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify(context.memory.entries?.() ?? [], null, 2),
        }],
      };
    case "chl://journal":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify(context.memory.journal?.() ?? [], null, 2),
        }],
      };
    case "chl://episodes":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify(context.memory.episodes?.() ?? [], null, 2),
        }],
      };
    case "chl://consolidation":
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify({
            consolidation: context.memory.consolidationState?.(),
            episodes: context.memory.episodes?.(),
          }, null, 2),
        }],
      };
    case "chl://backup.memory":
      return {
        contents: [{
          uri, mimeType: "application/octet-stream",
          blob: context.memory.backupMemory?.(),
        }],
      };
    case "chl://lexicon": {
      const current = context.memory.lexicon?.() ?? { concepts: [], phrases: [] };
      return {
        contents: [{
          uri, mimeType: "application/json",
          text: JSON.stringify({
            concepts: current.concepts,
            phrases: current.phrases,
            counts: { concepts: current.concepts?.length ?? 0, phrases: current.phrases?.length ?? 0 },
          }, null, 2),
        }],
      };
    }
    case "chl://lexicon.concepts":
      return {
        contents: [{
          uri, mimeType: "text/tab-separated-values",
          text: serializePairList(context.memory.lexicon?.()?.concepts ?? []),
        }],
      };
    case "chl://lexicon.phrases":
      return {
        contents: [{
          uri, mimeType: "text/tab-separated-values",
          text: serializePairList(context.memory.lexicon?.()?.phrases ?? []),
        }],
      };
    case "chl://lexicon.tsv": {
      const current = context.memory.lexicon?.() ?? { concepts: [], phrases: [] };
      return {
        contents: [{
          uri, mimeType: "text/tab-separated-values",
          text: [
            "# concepts",
            serializePairList(current.concepts ?? []),
            "",
            "# phrases",
            serializePairList(current.phrases ?? []),
            "",
          ].join("\n"),
        }],
      };
    }
    default:
      throw new Error(`Unknown resource: ${uri}`);
  }
}

function handleMcpMessage(context, message) {
  if (!message || typeof message !== "object") return null;

  if (message.method === "initialize") {
    const requestedVersion = message.params?.protocolVersion;
    const negotiatedVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
      ? requestedVersion
      : SUPPORTED_PROTOCOL_VERSIONS[0];
    return {
      jsonrpc: "2.0",
      id: message.id,
      result: {
        protocolVersion: negotiatedVersion,
        capabilities: {
          tools: { listChanged: false },
          resources: { listChanged: false, subscribe: false },
        },
        serverInfo: context.serverInfo,
      },
    };
  }

  if (message.method === "notifications/initialized" || message.method === "initialized") {
    return null;
  }

  if (message.method === "shutdown") {
    return {
      jsonrpc: "2.0",
      id: message.id,
      result: {},
    };
  }

  if (message.method === "tools/list") {
    return {
      jsonrpc: "2.0",
      id: message.id,
      result: listTools(context),
    };
  }

  if (message.method === "resources/list") {
    return {
      jsonrpc: "2.0",
      id: message.id,
      result: listResources(context),
    };
  }

  if (message.method === "resources/read") {
    return readResource(context, message.params?.uri).then((result) => ({
      jsonrpc: "2.0",
      id: message.id,
      result,
    }));
  }

  if (message.method === "tools/call") {
    return callTool(context, message.params?.name, message.params?.arguments ?? {}).then((result) => ({
      jsonrpc: "2.0",
      id: message.id,
      result,
    }));
  }

  if (message.method === "ping") {
    return {
      jsonrpc: "2.0",
      id: message.id,
      result: {},
    };
  }

  if (message.id !== undefined && message.id !== null) {
    return {
      jsonrpc: "2.0",
      id: message.id,
      error: {
        code: -32601,
        message: `Method not found: ${message.method}`,
      },
    };
  }

  return null;
}

module.exports = {
  callTool,
  createMcpContext,
  handleMcpMessage,
  listTools,
  listResources,
  readResource,
  ensureMemoryReady,
  toolDefinitions,
};
