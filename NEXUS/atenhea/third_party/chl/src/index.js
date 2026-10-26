const { CHL: JSCHL } = require("./chl");
const { AssociativeMemory } = require("./memory");
const {
  bindVectors,
  bundleVectors,
  prototypeVectorFromText,
  similarity,
  vectorFromSeed,
} = require("./hypervector");
const {
  extractFeatures,
  hammingDistance,
  hammingSimilarity,
  semanticHash,
  semanticHashFromText,
} = require("./simhash");
const {
  normalizeText,
  popcount32,
  popcountWords,
  stableHash32,
  tokenize,
} = require("./utils");
const { NativeCHL } = require("./native");
const { analyzeText } = require("./analysis");
const {
  MemoryType,
  MemoryTier,
  TYPE_SCORING_PROFILES,
  TYPE_TO_TIER,
  TYPE_EVICTION_PRIORITY,
  normalizeMemoryType,
  getTierForType,
  getDefaultExpiry,
  getEvictionPriority,
  getScoringProfile,
  temporalScore,
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
const {
  buildConsolidation,
  episodePatternKey,
  mergePairLists,
  normalizeEpisodeExamples,
} = require("./consolidation");
const { buildConceptGraph } = require("./graph");
const {
  buildAnswer,
  buildHypotheses,
  buildPlan,
  explainThought,
  learnFromVerification,
  scoreHypothesis,
  verifyPlan,
} = require("./thought");
const {
  composeDecisionResponse,
  extractClaims,
  renderDecisionExplanation,
  renderDecisionText,
  summarizePayload,
} = require("./generation");
const { createServer } = require("./server");
const { callTool, createMcpContext, handleMcpMessage, listResources, listTools, readResource } = require("./mcp");
const {
  decodeMemoryArchive,
  encodeMemoryArchive,
  readMemoryArchive,
  writeMemoryArchive,
} = require("./backup");
const {
  conceptualizeTokens,
  getConceptMap,
  learnConceptPairsFromExamples,
  loadLexiconState,
  serializeConceptMap,
  saveLexiconState,
  serializePairList,
} = require("./concepts");

// Lexicon learner (capa de aprendizaje semántico)
const {
  ConceptPrototype,
  ContrastiveFeedback,
  PhraseAliasIndex,
  IntentClusterer,
  LexiconTrainer,
} = require("./lexiconLearner");

// HyperAttention (pesos dinámicos)
const { HyperAttentionContext, DEFAULT_SCORING_DIMS } = require("./hyperattention");

// HyperDecoder (composición generativa)
const { HyperDecoder } = require("./hyperdecoder");
const { HyperReason } = require("./hyperreason");

// Neural layer (retrieval, no generation)
const { NeuralCHL } = require("./neural/neural-chl");
const { EmbeddingIndex, dotProduct, Vocabulary, DocumentVectorizer } = require("./neural/embeddings");
const { NeuralVerifier } = require("./neural/verifier");
const { NeuralSearcher } = require("./neural/searcher");
const { HyperEmbed, bind, bundle, permute, similarity: hdcSimilarity } = require("./neural/hyperembed");
const { ViterbiGenerator } = require("./neural/viterbi-gen");
const { SpectralExtractor } = require("./neural/spectral-entities");
const { HybridCHLTokenizer } = require("./neural/hybrid-chl-tokenizer");
const { buildSemanticTensor, tensorToTrainingJsonl } = require("./semantic-tensor");

// Bridge (modelos grandes)
const { createBridge, quickTurn, Session } = require("./bridge/bridge");
const { buildMemoryContext, buildCompactMemoryContext } = require("./bridge/memory-context");
const { createAdapter, CHL_TOOLS_FOR_LLM } = require("./bridge/model-adapter");

module.exports = {
  // Core engine
  CHL: NativeCHL,
  JSCHL,
  NativeCHL,

  // Neural retrieval
  NeuralCHL,
  EmbeddingIndex,
  dotProduct,
  Vocabulary,
  DocumentVectorizer,
  NeuralVerifier,
  NeuralSearcher,
  HyperEmbed,
  bind,
  bundle,
  permute,
  hdcSimilarity,
  ViterbiGenerator,
  SpectralExtractor,
  HybridCHLTokenizer,

  // Memory bridge (modelos grandes)
  createBridge,
  quickTurn,
  Session,
  buildMemoryContext,
  buildCompactMemoryContext,
  createAdapter,
  CHL_TOOLS_FOR_LLM,

  // Memory
  AssociativeMemory,
  bindVectors,
  bundleVectors,
  extractFeatures,
  hammingDistance,
  hammingSimilarity,
  normalizeText,
  popcount32,
  popcountWords,
  analyzeText,
  buildConceptGraph,
  buildConsolidation,
  buildAnswer,
  buildHypotheses,
  buildPlan,
  composeDecisionResponse,
  explainThought,
  extractClaims,
  learnFromVerification,
  episodePatternKey,
  mergePairLists,
  renderDecisionExplanation,
  renderDecisionText,
  scoreHypothesis,
  summarizePayload,
  verifyPlan,
  normalizeEpisodeExamples,
  prototypeVectorFromText,
  semanticHash,
  semanticHashFromText,
  similarity,
  stableHash32,
  createServer,
  callTool,
  createMcpContext,
  handleMcpMessage,
  listResources,
  listTools,
  readResource,
  decodeMemoryArchive,
  encodeMemoryArchive,
  conceptualizeTokens,
  getConceptMap,
  learnConceptPairsFromExamples,
  loadLexiconState,
  readMemoryArchive,
  serializeConceptMap,
  saveLexiconState,
  serializePairList,
  tokenize,
  vectorFromSeed,
  writeMemoryArchive,
  buildSemanticTensor,
  tensorToTrainingJsonl,

  // Lexicon learner
  ConceptPrototype,
  ContrastiveFeedback,
  PhraseAliasIndex,
  IntentClusterer,
  LexiconTrainer,

  // HyperAttention
  HyperAttentionContext,
  DEFAULT_SCORING_DIMS,

  // HyperDecoder
  HyperDecoder,

  // HyperReason
  HyperReason,
};

// ─── Añadidos en v0.2.0 ──────────────────────────────────
const {
  processFile,
  scanDirectory,
  scanDirectoryStats,
  detectFileType,
  isSupportedFile,
  chunkContent,
  chunkByParagraphs,
  chunkMarkdown,
  chunkCode,
  extractPDFText,
  extractDocxText,
  SUPPORTED_EXTENSIONS,
} = require("./ingester");

const {
  evaluateInteraction,
  buildMemoryEntry,
  buildMemoryPayload,
  buildMemoryMetadata,
  hasStrongSignal,
  summarizeResponse,
  summarizeToolCalls,
} = require("./auto-memory");

// Re-export (appended to existing module.exports)
Object.assign(module.exports, {
  processFile,
  scanDirectory,
  scanDirectoryStats,
  detectFileType,
  isSupportedFile,
  chunkContent,
  chunkByParagraphs,
  chunkMarkdown,
  chunkCode,
  extractPDFText,
  extractDocxText,
  SUPPORTED_EXTENSIONS,
  evaluateInteraction,
  buildMemoryEntry: buildMemoryEntry,
  buildMemoryPayload,
  buildMemoryMetadata,
  hasStrongSignal,
  summarizeResponse,
  summarizeToolCalls,

  // Memory types & adaptive scoring
  MemoryType,
  MemoryTier,
  TYPE_SCORING_PROFILES,
  TYPE_TO_TIER,
  TYPE_EVICTION_PRIORITY,
  normalizeMemoryType,
  getTierForType,
  getDefaultExpiry,
  getEvictionPriority,
  getScoringProfile,
  temporalScore,
  isExpired,

  classifyMemory,

  QueryIntent,
  detectQueryIntent,
  intentToMemoryTypes,
  getTypeBoostForIntent,
  getScoringProfileForIntent,
  buildQueryOptions,
});
