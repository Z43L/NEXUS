const os = require("node:os");

function clampInt(v, min, max) {
  const n = Math.floor(Number(v) || 0);
  if (n < min) return min;
  if (n > max) return max;
  return n;
}

function estimateTokenCount(text = "") {
  // Aproximación rápida para presupuesto: ~4 chars/token en promedio mixto.
  return Math.max(1, Math.ceil(String(text).length / 4));
}

function hardwareTier() {
  const totalGb = os.totalmem() / (1024 ** 3);
  const freeGb = os.freemem() / (1024 ** 3);
  const cores = os.cpus()?.length ?? 4;

  let tier = "small";
  if (totalGb >= 48 && cores >= 16) tier = "xlarge";
  else if (totalGb >= 24 && cores >= 10) tier = "large";
  else if (totalGb >= 12 && cores >= 8) tier = "medium";

  return { totalGb, freeGb, cores, tier };
}

function chooseAdaptiveConfig(options = {}) {
  const hw = hardwareTier();
  const backend = String(options.lmBackend ?? "legacy");
  const explicitMax = Number(options.maxTokens);

  const baseByTier = {
    small: backend === "rwkv" ? 96 : 160,
    medium: backend === "rwkv" ? 144 : 256,
    large: backend === "rwkv" ? 192 : 384,
    xlarge: backend === "rwkv" ? 256 : 512,
  };

  const defaultMaxTokens = baseByTier[hw.tier] ?? 128;
  const maxGenerationTokens = Number.isFinite(explicitMax) && explicitMax > 0
    ? clampInt(explicitMax, 32, 4096)
    : defaultMaxTokens;

  // Reservar parte para salida y parte para contexto recuperado.
  const contextTokenBudget = clampInt(Math.floor(maxGenerationTokens * 1.8), 128, 6000);
  const historyBudget = clampInt(Math.floor(contextTokenBudget * 0.20), 40, 1000);
  const evidenceBudget = clampInt(Math.floor(contextTokenBudget * 0.35), 60, 1800);
  const memoryBudget = clampInt(Math.floor(contextTokenBudget * 0.45), 60, 2600);

  let topK = clampInt(Math.floor(memoryBudget / 160), 3, 24);
  if (hw.freeGb < 2.5) topK = Math.max(3, Math.floor(topK * 0.7));
  if (hw.freeGb > 12) topK = Math.min(32, topK + 4);

  return {
    hardware: hw,
    maxGenerationTokens,
    contextTokenBudget,
    historyBudget,
    evidenceBudget,
    memoryBudget,
    memoryTopK: topK,
  };
}

function trimByTokenBudget(text = "", budgetTokens = 120) {
  if (!text) return "";
  const s = String(text).trim();
  const maxChars = Math.max(80, budgetTokens * 4);
  if (s.length <= maxChars) return s;
  return `${s.slice(0, maxChars)}...`;
}

function cleanSnippet(text = "") {
  const s = String(text || "")
    .replace(/\s+/g, " ")
    .replace(/(?:^|\s)(user:|assistant:|context:|q:|a:)/gi, " ")
    .trim();
  return s;
}

function composeSemanticMemory(snippets = [], budgetTokens = 300) {
  const out = [];
  let used = 0;
  const seen = new Set();
  for (const raw of snippets) {
    const s = cleanSnippet(raw);
    if (!s || s.length < 12) continue;
    const key = s.toLowerCase().slice(0, 140);
    if (seen.has(key)) continue;
    seen.add(key);
    const piece = s.length > 260 ? `${s.slice(0, 260)}...` : s;
    const t = estimateTokenCount(piece);
    if (used + t > budgetTokens) break;
    out.push(`- ${piece}`);
    used += t;
  }
  return { text: out.join("\n"), usedTokens: used, count: out.length };
}

async function buildAdaptivePrompt({ model, query, thought, options = {} }) {
  const cfg = chooseAdaptiveConfig(options);
  const best = thought?.best;
  const evidenceText = best?.evidence?.text ?? "";

  const historyRaw = Array.isArray(options.history) ? options.history : [];
  const historyText = historyRaw
    .slice(-8)
    .map((m) => `${m.role ?? "user"}: ${String(m.text ?? "").trim()}`)
    .join("\n");
  const history = trimByTokenBudget(historyText, cfg.historyBudget);

  const evidence = trimByTokenBudget(evidenceText, cfg.evidenceBudget);

  let snippets = [];
  let expertMeta = null;
  if (typeof model.semanticNavigate === "function") {
    try {
      const nav = await model.semanticNavigate(query, {
        perVariantTopK: Math.max(6, Math.min(16, cfg.memoryTopK)),
        targetTopK: cfg.memoryTopK,
        maxVariants: 10,
      });
      snippets = (nav?.reranked ?? []).map((x) => String(x?.entry?.text ?? "").trim()).filter(Boolean);
      expertMeta = {
        variants: nav?.variants?.length ?? 0,
        retrieved: nav?.reranked?.length ?? 0,
      };
    } catch {
      // fallback
    }
  }

  if (snippets.length === 0) {
    const recalled = await model.recall(query, { topK: cfg.memoryTopK });
    snippets = (recalled?.candidates ?? [])
      .map((c) => String(c?.entry?.text ?? "").trim())
      .filter(Boolean);
  }

  const memoryComposed = composeSemanticMemory(snippets, cfg.memoryBudget);
  const memory = memoryComposed.text;

  const prompt = [
    "system: usa la memoria semantica CHL como contexto primario. responde en español con precision y claridad.",
    history ? `history:\n${history}` : "",
    evidence ? `evidence:\n${evidence}` : "",
    memory ? `semantic_memory:\n${memory}` : "",
    `user: ${String(query ?? "")}`,
    "assistant:",
  ].filter(Boolean).join("\n\n");

  return {
    prompt,
    adaptive: {
      ...cfg,
      selectedMemorySnippets: memoryComposed.count,
      selectedMemoryTokens: memoryComposed.usedTokens,
      expertNavigation: expertMeta,
    },
  };
}

module.exports = {
  buildAdaptivePrompt,
  chooseAdaptiveConfig,
};
