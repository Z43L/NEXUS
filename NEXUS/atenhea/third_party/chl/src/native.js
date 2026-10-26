const fs = require("node:fs");
const readline = require("node:readline");
const path = require("node:path");
const { analyzeText } = require("./analysis");
const { charNgrams, normalizeText, tokenize } = require("./utils");
const {
  decodeMemoryArchive,
  encodeMemoryArchive,
  readMemoryArchive,
  writeMemoryArchive,
} = require("./backup");
const { loadLexiconState, saveLexiconState } = require("./concepts");
const { classifyMemory } = require("./memory-classifier");
const {
  MemoryType,
  normalizeMemoryType,
  getDefaultExpiry,
  getTypeBoostForIntent,
  getScoringProfileForIntent,
  temporalScore,
  isExpired,
} = require("./memory-types");
const { detectQueryIntent } = require("./query-intent");
const { buildConceptGraph } = require("./graph");
const {
  buildAnswer,
  buildDecisionEpisode,
  buildHypotheses,
  buildPlan,
  explainThought,
  learnFromVerification,
  verifyPlan,
} = require("./thought");
const { buildConsolidation } = require("./consolidation");
const { resolveMemoryProfile } = require("./profiles");
const { clamp } = require("./utils");

function scheduleTask(fn) {
  if (typeof setImmediate === "function") {
    setImmediate(fn);
  } else {
    setTimeout(fn, 0);
  }
}

function loadBinding() {
  const candidates = [
    path.resolve(__dirname, "..", "build", "Release", "chl_addon.node"),
    path.resolve(__dirname, "..", "build", "Debug", "chl_addon.node"),
  ];
  let lastError = null;
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      try {
        return { binding: require(candidate), error: null };
      } catch (error) {
        lastError = error;
      }
    }
  }
  return { binding: null, error: lastError };
}

const bindingState = loadBinding();
const binding = bindingState.binding;

class NativeCHL {
  constructor(options = {}) {
    this.options = resolveMemoryProfile({
      ...options,
      persistPath: options.persistPath ?? null,
      seed: options.seed ?? 0,
    });
    this.persistPath = this._normalizePersistPath(this.options.persistPath);
    this.conceptsPath = this.options.conceptsPath ?? this._deriveSidecarPath(".concepts.tsv");
    this.phrasesPath = this.options.phrasesPath ?? this._deriveSidecarPath(".phrases.tsv");
    this._hydrating = false;
    this._journal = [];
    this._readyError = null;
    this._nativeLoadError = bindingState.error ?? null;
    this.fallback = null;
    this._decisionEpisodes = [];
    this._lastConsolidatedEpisodeIndex = 0;
    this.autoConsolidationEvery = Math.max(0, Math.floor(Number(this.options.autoConsolidationEvery ?? 0) || 0));
    this.autoConsolidationMinConfidence = clamp(Number(this.options.autoConsolidationMinConfidence ?? 0.65) || 0, 0, 1);
    this.autoConsolidationMinSupport = Math.max(1, Math.floor(Number(this.options.autoConsolidationMinSupport ?? 2) || 2));
    this._autoConsolidationPending = false;
    this._shardSizeBytes = Number(this.options.shardSize ?? 1024 * 1024 * 10);
    this._hydratedShardIndex = 0;
    this._lazyLoad = Boolean(this.options.lazyLoad);
    this._maxHydrationEntries = Number.isFinite(this.options.maxHydrationEntries) ? this.options.maxHydrationEntries : Infinity;
    this._autoConsolidationStats = {
      scheduled: 0,
      completed: 0,
      skipped: 0,
      lastRunAt: null,
      lastError: null,
      lastReason: null,
    };
    this._syncLexiconEnv();
    if (binding) {
      this.engine = new binding.CHLEngine(
        this.options.bitCount,
        this.options.bandBits,
        this.options.hyperDim,
        this.options.maxEntries,
        this.options.maxCandidates,
        this.options.seed,
        this.options.largeProfile ? 1 : 0
      );
    } else {
      const { CHL } = require("./chl");
      this.fallback = new CHL(this.options);
    }
    this._ensurePersistDir();
this._ready = this._loadOrCreateIndex()
  .then(async () => {
    if (this.persistPath && this.persistPath.endsWith(".memory")) {
      if (fs.existsSync(this.persistPath)) {
        try {
          console.log(`[CHL] Loading binary memory from ${this.persistPath}...`);
          this.loadMemory(this.persistPath, { replace: true });
        } catch (err) {
          console.error(`[CHL] Failed to load binary memory archive:`, err);
        }
      }
      // Load WAL sidecar if exists
      const walPath = this.persistPath + ".wal";
      if (fs.existsSync(walPath)) {
        console.log(`[CHL] Loading WAL events from ${walPath}...`);
        const originalPath = this.persistPath;
        this.persistPath = walPath;
        try {
          this._shardOffsets = this._calculateShardOffsets();
          this._hydratedShardIndex = 0;
          await this._hydrateFromDiskAsync();
        } finally {
          this.persistPath = originalPath;
          this._shardOffsets = this._calculateShardOffsets();
        }
      }
      return;
    }

    if (this._lazyLoad) {
      return this._hydrateFromDiskAsync(this._maxHydrationEntries);
    } else {
      return this._hydrateFromDiskAsync();
    }
  })
  .catch((error) => {
    this._readyError = error;
  });
  }

  _ensurePersistDir() {
    if (!this.persistPath) return;
    fs.mkdirSync(path.dirname(this.persistPath), { recursive: true });
  }

  _normalizePersistPath(persistPath) {
    if (!persistPath) return null;
    try {
      if (fs.existsSync(persistPath) && fs.statSync(persistPath).isDirectory()) {
        return path.join(persistPath, "chl-memory.log");
      }
    } catch {
      // fall through and keep provided path
    }
    return persistPath;
  }

  _deriveSidecarPath(suffix) {
    if (!this.persistPath) return null;
    const parsed = path.parse(this.persistPath);
    return path.join(parsed.dir, `${parsed.name}${suffix}`);
  }

  async _loadOrCreateIndex() {
    this._shardOffsets = this._calculateShardOffsets();
  }

  _calculateShardOffsets() {
    if (!this.persistPath || !fs.existsSync(this.persistPath)) return [0];
    const stats = fs.statSync(this.persistPath);
    const totalSize = stats.size;
    const shardSize = this._shardSizeBytes;
    const offsets = [0];
    if (totalSize <= shardSize) return offsets;

    const fd = fs.openSync(this.persistPath, "r");
    try {
      let currentPos = shardSize;
      const buffer = Buffer.alloc(1024 * 4);
      while (currentPos < totalSize) {
        const bytesRead = fs.readSync(fd, buffer, 0, buffer.length, currentPos);
        const newlineIdx = buffer.indexOf(10, 0, bytesRead);
        if (newlineIdx !== -1) {
          const offset = currentPos + newlineIdx + 1;
          if (offset < totalSize) {
            offsets.push(offset);
            currentPos = offset + shardSize;
          } else {
            break;
          }
        } else {
          currentPos += buffer.length;
        }
      }
    } finally {
      fs.closeSync(fd);
    }
    return offsets;
  }

  _syncLexiconEnv() {
    if (this.conceptsPath) {
      process.env.CHL_CONCEPTS_PATH = this.conceptsPath;
    }
    if (this.phrasesPath) {
      process.env.CHL_PHRASES_PATH = this.phrasesPath;
    }
  }

  _lexiconState() {
    return loadLexiconState({
      conceptsPath: this.conceptsPath,
      phrasesPath: this.phrasesPath,
    });
  }

  _saveLexiconState(state = this._lexiconState()) {
    return saveLexiconState(state, {
      conceptsPath: this.conceptsPath,
      phrasesPath: this.phrasesPath,
    });
  }

  async _hydrateFromDiskAsync(limit = Infinity) {
    if (!this.persistPath || !fs.existsSync(this.persistPath)) return;
    this._hydrating = true;
    try {
      let totalCount = 0;
      while (this._hydratedShardIndex < this._shardOffsets.length && totalCount < limit) {
        const i = this._hydratedShardIndex;
        const start = this._shardOffsets[i];
        const end = i + 1 < this._shardOffsets.length ? this._shardOffsets[i + 1] - 1 : undefined;
        const stream = fs.createReadStream(this.persistPath, {
          encoding: "utf8",
          start,
          end,
        });
        const reader = readline.createInterface({ input: stream, crlfDelay: Infinity });
        let batch = [];
        const batchSize = 500;
        try {
          for await (const line of reader) {
            if (!line.trim()) continue;
            try {
              const event = JSON.parse(line);
              this._journal.push(event);
              if (event.type === "remember") {
                batch.push(event);
                if (batch.length >= batchSize) {
                  for (const ev of batch) {
                    this.remember(ev.text, ev.payload, ev.metadata);
                  }
                  totalCount += batch.length;
                  batch = [];
                  if (totalCount >= limit) break;
                  await new Promise((r) => setImmediate(r));
                }
              } else if (event.type === "learn") {
                this.learn(event.text, event.reward);
              } else if (event.type === "episode" && event.episode) {
                this._decisionEpisodes.push(event.episode);
              } else if (event.type === "consolidation" && Number.isFinite(event.nextEpisodeIndex)) {
                this._lastConsolidatedEpisodeIndex = Math.max(this._lastConsolidatedEpisodeIndex, event.nextEpisodeIndex);
              }
            } catch (parseErr) {
              // ignore malformed lines
            }
          }
          for (const ev of batch) {
            this.remember(ev.text, ev.payload, ev.metadata);
          }
          totalCount += batch.length;
        } finally {
          reader.close();
          stream.destroy();
        }
        this._hydratedShardIndex++;
      }
      if (totalCount > 0) {
        console.log(`[CHL] Memoria hidratada: ${totalCount} entradas desde ${this.persistPath}`);
      }
    } finally {
      this._hydrating = false;
    }
  }

  async loadRemainingShards() {
    return this._hydrateFromDiskAsync(Infinity);
  }

  whenReady() {
    return this._ready.then(() => {
      if (this._readyError) {
        throw this._readyError;
      }
    });
  }

  _appendEvent(event) {
    this._journal.push(event);
    if (event?.type === "episode" && event.episode) {
      this._decisionEpisodes.push(event.episode);
    }
    if (event?.type === "consolidation" && Number.isFinite(event.nextEpisodeIndex)) {
      this._lastConsolidatedEpisodeIndex = Math.max(this._lastConsolidatedEpisodeIndex, event.nextEpisodeIndex);
    }
    if (!this.persistPath || this._hydrating) return;
    if (this.persistPath.endsWith(".memory")) {
      fs.appendFileSync(this.persistPath + ".wal", `${JSON.stringify(event)}\n`);
      return;
    }
    fs.appendFileSync(this.persistPath, `${JSON.stringify(event)}\n`);
  }

  _replacePersistFile(events) {
    if (!this.persistPath) return;
    if (this.persistPath.endsWith(".memory")) {
      try {
        writeMemoryArchive(this.persistPath, this.backup());
        const walPath = this.persistPath + ".wal";
        if (fs.existsSync(walPath)) {
          fs.unlinkSync(walPath);
        }
      } catch (e) {
        console.error("[CHL] Failed to write binary memory archive:", e);
      }
      return;
    }
    const serialized = events.map((event) => JSON.stringify(event)).join("\n");
    fs.writeFileSync(this.persistPath, serialized ? `${serialized}\n` : "");
  }

  _normalize(input) {
    return normalizeText(typeof input === "string" ? input : JSON.stringify(input));
  }

  remember(input, payload = null, metadata = {}) {
    const inferredType = metadata.memoryType ?? classifyMemory(input, payload, metadata);
    const now = Date.now();
    const enrichedMetadata = {
      ...metadata,
      memoryType: inferredType,
      createdAt: metadata.createdAt ?? now,
      expiresAt: metadata.expiresAt ?? getDefaultExpiry(inferredType),
      source: metadata.source ?? "",
    };

    if (this.fallback) {
      const entry = this.fallback.remember(input, payload, enrichedMetadata);
      this._appendEvent({
        type: "remember",
        text: typeof input === "string" ? input : JSON.stringify(input),
        payload,
        metadata: enrichedMetadata,
      });
      return entry;
    }
    const text = this._normalize(input);
    const payloadJson = JSON.stringify({
      payload,
      metadata: enrichedMetadata,
      sourceText: typeof input === "string" ? input : JSON.stringify(input),
    });
    const quality = metadata.quality ?? 1;
    const rawEntry = JSON.parse(this.engine.remember(text, payloadJson, quality));
    const entry = {
      ...rawEntry,
      memoryType: inferredType,
      source: enrichedMetadata.source,
      createdAt: enrichedMetadata.createdAt,
      expiresAt: enrichedMetadata.expiresAt,
      metadata: enrichedMetadata,
    };
    this._appendEvent({
      type: "remember",
      text: typeof input === "string" ? input : JSON.stringify(input),
      payload,
      metadata: enrichedMetadata,
    });
    return entry;
  }

  recall(query, options = {}) {
    if (this.fallback) {
      return this.fallback.recall(query, options);
    }
    const text = this._normalize(query);
    const topK = Math.max(1, Math.floor(options.topK ?? 5));

    const hasAdaptiveFilters =
      options.memoryType != null ||
      options.includeTypes != null ||
      options.memoryTypes != null ||
      options.excludeTypes != null ||
      options.timeWindowMs != null ||
      options.minQuality != null ||
      options.source != null ||
      options.intent != null ||
      options.boostProfile != null;

    const oversample = hasAdaptiveFilters ? Math.min(topK * 5, 100) : topK;
    const raw = JSON.parse(this.engine.query(text, oversample));
    const now = Date.now();
    const intent = options.intent ? String(options.intent).toLowerCase() : detectQueryIntent(query);

    let allowedTypes = null;
    if (options.memoryType) {
      allowedTypes = [normalizeMemoryType(options.memoryType)].filter(Boolean);
    } else {
      const included = Array.isArray(options.includeTypes)
        ? options.includeTypes
        : Array.isArray(options.memoryTypes)
          ? options.memoryTypes
          : null;
      if (included && included.length > 0) {
        allowedTypes = included.map(normalizeMemoryType).filter(Boolean);
      }
    }
    const excludedTypes = Array.isArray(options.excludeTypes)
      ? options.excludeTypes.map(normalizeMemoryType).filter(Boolean)
      : [];
    const timeWindowMs = Number(options.timeWindowMs) || null;
    const minQuality = typeof options.minQuality === "number" ? options.minQuality : null;
    const sourceFilter = options.source ? String(options.source) : null;

    const scored = [];
    for (const candidate of raw.candidates) {
      const meta = unwrapCandidateMetadata(candidate) || {};
      const memoryType = meta.memoryType || MemoryType.SHORT_TERM;

      if (isExpired(meta.expiresAt, now)) continue;
      if (allowedTypes && !allowedTypes.includes(memoryType)) continue;
      if (excludedTypes.length > 0 && excludedTypes.includes(memoryType)) continue;
      if (timeWindowMs != null && meta.createdAt && now - meta.createdAt > timeWindowMs) continue;
      if (minQuality != null && (candidate.quality ?? 1) < minQuality) continue;
      if (sourceFilter != null && meta.source !== sourceFilter) continue;

      let newScore = candidate.score;
      if (hasAdaptiveFilters) {
        const boost = getTypeBoostForIntent(intent, memoryType);
        const temporal = temporalScore({ memoryType, createdAt: meta.createdAt }, now);
        const quality = candidate.quality ?? meta.quality ?? 1;
        newScore *= 1 + boost;
        newScore *= 0.4 + 0.6 * temporal;
        newScore *= 0.5 + 0.5 * quality;
      }

      scored.push({
        ...candidate,
        score: newScore,
        payload: unwrapCandidatePayload(candidate),
        metadata: meta,
      });
    }

    scored.sort((a, b) => b.score - a.score);
    const selected = scored.slice(0, topK);

    let confidence = 0;
    if (selected.length > 0) {
      const best = selected[0].score;
      if (selected.length === 1) {
        confidence = Math.max(0, Math.min(1, best));
      } else {
        const second = selected[1].score;
        confidence = Math.max(0, Math.min(1, 0.5 * best + 0.5 * (best - second)));
      }
    }

    return {
      confidence,
      queryHash: raw.queryHash,
      candidates: selected,
    };
  }

  infer(query, options = {}) {
    const result = this.recall(query, options);
    const best = result.candidates[0] ?? null;
    const answer = unwrapCandidatePayload(best);
    return {
      answer,
      support: result.candidates.map((candidate) => unwrapCandidatePayload(candidate)),
      confidence: result.confidence ?? 0,
      candidates: result.candidates,
      queryHash: result.queryHash,
    };
  }

  learn(input, reward = 0) {
    if (this.fallback) {
      const result = this.fallback.updateFeedback(input, reward);
      this._appendEvent({
        type: "learn",
        text: typeof input === "string" ? input : JSON.stringify(input),
        reward,
      });
      return result;
    }
    const result = this.engine.learn(this._normalize(input), reward);
    this._appendEvent({
      type: "learn",
      text: typeof input === "string" ? input : JSON.stringify(input),
      reward,
    });
    return result;
  }

  updateFeedback(input, reward = 0) {
    return this.learn(input, reward);
  }

  analyze(input) {
    return analyzeText(input);
  }

  snapshot() {
    if (this.fallback) {
      return this.fallback.memory.snapshot();
    }
    return JSON.parse(this.engine.snapshot());
  }

  profile() {
    return this.snapshot().profile ?? this.options.profile ?? "default";
  }

  bucketStats() {
    if (this.fallback) {
      const buckets = [];
      for (const map of this.fallback.memory.bandMaps) {
        for (const bucket of map.values()) {
          buckets.push(bucket.size);
        }
      }
      const occupiedBuckets = buckets.length;
      const collisionBuckets = buckets.filter((size) => size > 1).length;
      const totalAssignments = buckets.reduce((sum, size) => sum + size, 0);
      const maxBucketSize = buckets.reduce((max, size) => Math.max(max, size), 0);
      return {
        occupiedBuckets,
        collisionBuckets,
        totalAssignments,
        maxBucketSize,
        avgBucketLoad: occupiedBuckets ? totalAssignments / occupiedBuckets : 0,
      };
    }
    if (typeof this.engine.bucketStats === "function") {
      return JSON.parse(this.engine.bucketStats());
    }
    const snapshot = this.snapshot();
    return {
      occupiedBuckets: snapshot.buckets ?? 0,
      collisionBuckets: snapshot.exactCollisions ?? 0,
      totalAssignments: snapshot.size ?? 0,
      maxBucketSize: 0,
      avgBucketLoad: snapshot.buckets ? (snapshot.size ?? 0) / snapshot.buckets : 0,
    };
  }

  entries() {
    if (this.fallback) {
      return Array.from(this.fallback.memory.entries.values()).map((entry) => ({
        id: entry.id,
        text: entry.text,
        representations:
          entry.representations ?? {
            normalizedText: normalizeText(entry.text),
            canonicalText: normalizeText(entry.text),
            tokens: tokenize(entry.text),
            ngrams3: charNgrams(entry.text, 3),
            ngrams4: charNgrams(entry.text, 4),
            concepts: tokenize(entry.text),
            negated: tokenize(entry.text).some((token) => token === "no" || token === "sin" || token === "nunca" || token === "jamas"),
          },
        payloadRepresentations:
          entry.payloadRepresentations ?? {
            normalizedText: entry.payload == null ? "" : normalizeText(typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload)),
            canonicalText: entry.payload == null ? "" : normalizeText(typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload)),
            tokens: entry.payload == null ? [] : tokenize(typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload)),
            ngrams3: entry.payload == null ? [] : charNgrams(typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload), 3),
            ngrams4: entry.payload == null ? [] : charNgrams(typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload), 4),
            concepts: entry.payload == null ? [] : tokenize(typeof entry.payload === "string" ? entry.payload : JSON.stringify(entry.payload)),
            negated: false,
          },
        hash: Array.from(entry.hash ?? []).join?.("") ?? "",
        hyper: Array.from(entry.hypervector ?? []).join?.("") ?? "",
        payloadJson: JSON.stringify(entry.payload),
        quality: entry.quality,
        createdAt: entry.createdAt,
        updatedAt: entry.updatedAt,
        lastAccessAt: entry.lastAccessAt,
        accessCount: entry.accessCount,
        prototypeCount: entry.prototypeCount,
      }));
    }
    if (typeof this.engine.entries === "function") {
      return JSON.parse(this.engine.entries());
    }
    return [];
  }

  dumpState() {
    if (this.fallback) {
      return {
        snapshot: this.fallback.memory.snapshot(),
        bucketStats: this.bucketStats(),
        entries: this.entries(),
        journal: [...this._journal],
        episodes: [...this._decisionEpisodes],
        consolidation: this.consolidationState(),
      };
    }
    if (typeof this.engine.dumpState === "function") {
      const state = JSON.parse(this.engine.dumpState());
      return {
        ...state,
        journal: [...this._journal],
        episodes: [...this._decisionEpisodes],
        consolidation: this.consolidationState(),
      };
    }
    return {
      snapshot: this.snapshot(),
      bucketStats: this.bucketStats(),
      entries: this.entries(),
      journal: [...this._journal],
      episodes: [...this._decisionEpisodes],
      consolidation: this.consolidationState(),
    };
  }

  journal() {
    return [...this._journal];
  }

  episodes() {
    return [...this._decisionEpisodes];
  }

  _episodesFromJournal(journal = []) {
    return journal
      .filter((event) => event && event.type === "episode" && event.episode)
      .map((event) => event.episode);
  }

  confidenceFor(query, options = {}) {
    const result = this.recall(query, options);
    if (result.candidates.length === 0) return 0;
    const best = result.candidates[0].score ?? 0;
    const second = result.candidates[1]?.score ?? 0;
    return Math.max(0, Math.min(1, 0.5 * best + 0.5 * (best - second)));
  }

  buildWorkingState(query, candidates = []) {
    const result = this.recall(query, { topK: candidates.length || 5 });
    const support = candidates.length > 0 ? candidates : result.candidates;
    return {
      queryEncoding: { text: this._normalize(query) },
      state: {
        support,
      },
      supportStrength: this.confidenceFor(query, { topK: support.length || 5 }),
    };
  }

  conceptGraph() {
    return buildConceptGraph(this.entries());
  }

  think(query, options = {}) {
    return buildHypotheses(query, this, options);
  }

  plan(query, options = {}) {
    return buildPlan(query, this, options);
  }

  verify(planOrQuery, options = {}) {
    return verifyPlan(planOrQuery, this, options);
  }

  ask(query, options = {}) {
    const decision = buildAnswer(query, this, options);
    const episode = this.recordDecisionEpisode(decision);
    return {
      ...decision,
      episodeId: episode.id,
    };
  }

  learnFromVerification(verification, options = {}) {
    return learnFromVerification(this, verification, options);
  }

  consolidateEpisodes(options = {}) {
    const startIndex = options.startIndex ?? this._lastConsolidatedEpisodeIndex ?? 0;
    const minConfidence = options.minConfidence ?? null;
    const episodes = this._decisionEpisodes
      .slice(startIndex)
      .filter((episode) => minConfidence == null || Number(episode?.confidence ?? 0) >= minConfidence);
    const consolidation = buildConsolidation(episodes, options);
    for (const rule of consolidation.rules) {
      this.remember(rule.text, rule.payload, rule.metadata);
    }
    this._appendEvent({
      type: "consolidation",
      startIndex,
      nextEpisodeIndex: this._decisionEpisodes.length,
      summary: consolidation.summary,
      ruleCount: consolidation.rules.length,
      conceptPairCount: consolidation.conceptPairs.length,
      phrasePairCount: consolidation.phrasePairs.length,
    });
    this._lastConsolidatedEpisodeIndex = this._decisionEpisodes.length;
    return {
      ok: true,
      ...consolidation.summary,
      rules: consolidation.rules,
      conceptPairs: consolidation.conceptPairs,
      phrasePairs: consolidation.phrasePairs,
      nextEpisodeIndex: this._lastConsolidatedEpisodeIndex,
    };
  }

  consolidationState() {
    return {
      lastEpisodeIndex: this._lastConsolidatedEpisodeIndex ?? 0,
      episodeCount: this._decisionEpisodes.length,
      auto: this.autoConsolidationState(),
    };
  }

  autoConsolidationState() {
    return {
      every: this.autoConsolidationEvery,
      minConfidence: this.autoConsolidationMinConfidence,
      minSupport: this.autoConsolidationMinSupport,
      pending: this._autoConsolidationPending,
      ...this._autoConsolidationStats,
    };
  }

  _maybeScheduleAutoConsolidation(episode) {
    if (this.autoConsolidationEvery <= 0) return;
    if (!episode || Number(episode.confidence ?? 0) < this.autoConsolidationMinConfidence) {
      this._autoConsolidationStats.skipped += 1;
      this._autoConsolidationStats.lastReason = "confidence_below_threshold";
      return;
    }
    const pendingEpisodes = this._decisionEpisodes.length - (this._lastConsolidatedEpisodeIndex ?? 0);
    if (pendingEpisodes < this.autoConsolidationEvery) return;
    if (this._autoConsolidationPending) return;

    this._autoConsolidationPending = true;
    this._autoConsolidationStats.scheduled += 1;
    this._autoConsolidationStats.lastReason = "episode_threshold_reached";
    scheduleTask(() => {
      try {
        this.consolidateEpisodes({
          minSupport: this.autoConsolidationMinSupport,
        });
        this._autoConsolidationStats.completed += 1;
        this._autoConsolidationStats.lastRunAt = new Date().toISOString();
      } catch (error) {
        this._autoConsolidationStats.lastError = error.message;
      } finally {
        this._autoConsolidationPending = false;
      }
    });
  }

  recordDecisionEpisode(decision, extras = {}) {
    const episode = buildDecisionEpisode(decision, extras);
    this._appendEvent({ type: "episode", episode });
    this._maybeScheduleAutoConsolidation(episode);
    return episode;
  }

  explainThought(query, options = {}) {
    return explainThought(this.think(query, options));
  }

  route(query, relationKey, options = {}) {
    const result = this.recall(query, options);
    const routed = [];
    for (const candidate of result.candidates) {
      const payload = unwrapCandidatePayload(candidate);
      if (payload && typeof payload === "object" && Array.isArray(payload.relations)) {
        for (const relation of payload.relations) {
          if (relation && relation.key === relationKey) {
            routed.push({
              from: candidate.id,
              relation: relationKey,
              to: relation.value,
              score: candidate.score,
            });
          }
        }
      }
    }
    return routed;
  }

  clear() {
    if (this.fallback) {
      this.fallback.memory.entries.clear();
      this._journal = [];
      this._decisionEpisodes = [];
      this._lastConsolidatedEpisodeIndex = 0;
      this._autoConsolidationPending = false;
      this._autoConsolidationStats = {
        scheduled: 0,
        completed: 0,
        skipped: 0,
        lastRunAt: null,
        lastError: null,
        lastReason: null,
      };
      if (this.persistPath) fs.writeFileSync(this.persistPath, "");
      return;
    }
    this.engine.clear();
    this._journal = [];
    this._decisionEpisodes = [];
    this._lastConsolidatedEpisodeIndex = 0;
    this._autoConsolidationPending = false;
    this._autoConsolidationStats = {
      scheduled: 0,
      completed: 0,
      skipped: 0,
      lastRunAt: null,
      lastError: null,
      lastReason: null,
    };
    if (this.persistPath) fs.writeFileSync(this.persistPath, "");
  }

  backup() {
    return {
      format: "chl-archive-v1",
      createdAt: new Date().toISOString(),
      options: this.options,
      journal: [...this._journal],
      lexicon: this._lexiconState(),
      state: this.dumpState(),
    };
  }

  backupMemory() {
    return encodeMemoryArchive(this.backup());
  }

  restore(backupInput, options = {}) {
    const backup = this._normalizeBackupInput(backupInput);
    const acceptableFormats = new Set(["chl-archive-v1", "chl-backup-v1"]);
    if (!backup || !acceptableFormats.has(backup.format) || !Array.isArray(backup.journal)) {
      throw new Error("Invalid CHL backup");
    }

    const replace = options.replace ?? true;
    if (replace) {
      this.clear();
    }

    this._hydrating = true;
    try {
      for (const event of backup.journal) {
        if (event && event.type === "remember") {
          this.remember(event.text, event.payload, event.metadata ?? {});
        } else if (event && event.type === "learn") {
          this.learn(event.text, event.reward ?? 0);
        }
      }
    } finally {
      this._hydrating = false;
    }

    this._journal = [...backup.journal];
    this._decisionEpisodes = Array.isArray(backup.episodes) ? [...backup.episodes] : this._episodesFromJournal(backup.journal);
    const backupConsolidation = backup.consolidation ?? backup.state?.consolidation ?? null;
    this._lastConsolidatedEpisodeIndex = Number.isFinite(backupConsolidation?.lastEpisodeIndex)
      ? backupConsolidation.lastEpisodeIndex
      : this._decisionEpisodes.length;
    this._autoConsolidationPending = false;
    this._autoConsolidationStats = {
      scheduled: 0,
      completed: 0,
      skipped: 0,
      lastRunAt: null,
      lastError: null,
      lastReason: null,
    };
    this._replacePersistFile(this._journal);
    if (backup.lexicon) {
      this._saveLexiconState(backup.lexicon);
    }
    return {
      ok: true,
      snapshot: this.snapshot(),
      bucketStats: this.bucketStats(),
    };
  }

  restoreMemory(buffer, options = {}) {
    const backup = decodeMemoryArchive(buffer);
    return this.restore(backup, options);
  }

  saveMemory(filePath) {
    writeMemoryArchive(filePath, this.backup());
    return { ok: true, path: filePath };
  }

  loadMemory(filePath, options = {}) {
    const backup = readMemoryArchive(filePath);
    return this.restore(backup, options);
  }

  async close() {
    if (this.persistPath && this.persistPath.endsWith(".memory")) {
      this._replacePersistFile(this._journal);
    }
  }

  saveLexicon() {
    return this._saveLexiconState();
  }

  lexicon() {
    return this._lexiconState();
  }

  _normalizeBackupInput(backupInput) {
    if (Buffer.isBuffer(backupInput) || backupInput instanceof Uint8Array) {
      return decodeMemoryArchive(backupInput);
    }
    if (typeof backupInput === "string") {
      const trimmed = backupInput.trim();
      if (trimmed.startsWith("{")) {
        return JSON.parse(trimmed);
      }
      if (fs.existsSync(trimmed)) {
        const binary = fs.readFileSync(trimmed);
        return decodeMemoryArchive(binary);
      }
      return JSON.parse(trimmed);
    }
    return backupInput;
  }
}

function safeParse(value) {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function unwrapCandidateMetadata(candidate) {
  if (!candidate || typeof candidate !== "object") return {};
  if (candidate.metadata !== undefined) return candidate.metadata || {};
  if (candidate.entry && candidate.entry.metadata !== undefined) return candidate.entry.metadata || {};

  const payloadJson = candidate.payloadJson !== undefined
    ? candidate.payloadJson
    : candidate.entry?.payloadJson;
  if (payloadJson !== undefined) {
    const parsed = safeParse(payloadJson);
    if (parsed && typeof parsed === "object" && parsed.metadata) return parsed.metadata;
  }

  const payload = candidate.payload !== undefined
    ? candidate.payload
    : candidate.entry?.payload;
  if (payload && typeof payload === "object" && payload.metadata) return payload.metadata;

  return {};
}

function unwrapCandidatePayload(candidate) {
  if (!candidate || typeof candidate !== "object") return null;
  const candidatePayload = candidate.payload !== undefined ? candidate.payload : undefined;
  if (candidatePayload !== undefined) {
    if (
      candidatePayload &&
      typeof candidatePayload === "object" &&
      Object.prototype.hasOwnProperty.call(candidatePayload, "payload") &&
      (Object.prototype.hasOwnProperty.call(candidatePayload, "metadata") ||
        Object.prototype.hasOwnProperty.call(candidatePayload, "sourceText"))
    ) {
      return candidatePayload.payload;
    }
    return candidatePayload;
  }
  if (candidate.payloadJson !== undefined) {
    const parsed = safeParse(candidate.payloadJson);
    if (
      parsed &&
      typeof parsed === "object" &&
      Object.prototype.hasOwnProperty.call(parsed, "payload") &&
      (Object.prototype.hasOwnProperty.call(parsed, "metadata") ||
        Object.prototype.hasOwnProperty.call(parsed, "sourceText"))
    ) {
      return parsed.payload;
    }
    return parsed;
  }
  if (candidate.entry && candidate.entry.payload !== undefined) {
    return candidate.entry.payload;
  }
  if (candidate.entry && candidate.entry.payloadJson !== undefined) {
    const parsed = safeParse(candidate.entry.payloadJson);
    if (
      parsed &&
      typeof parsed === "object" &&
      Object.prototype.hasOwnProperty.call(parsed, "payload") &&
      (Object.prototype.hasOwnProperty.call(parsed, "metadata") ||
        Object.prototype.hasOwnProperty.call(parsed, "sourceText"))
    ) {
      return parsed.payload;
    }
    return parsed;
  }
  return null;
}

module.exports = {
  NativeCHL,
  binding,
  loadBinding,
};
