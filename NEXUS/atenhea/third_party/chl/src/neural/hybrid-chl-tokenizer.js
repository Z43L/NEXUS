const { analyzeText } = require("../analysis");

function cleanUnit(text) {
  return String(text ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function unique(values = []) {
  return Array.from(new Set(values.filter(Boolean)));
}

class HybridCHLTokenizer {
  constructor(spec = {}) {
    this.version = spec.version ?? "chl-hybrid-tokenizer-v1";
    this.minUnitChars = Math.max(3, Number(spec.minUnitChars ?? 4));
    this.maxUnitWords = Math.max(2, Number(spec.maxUnitWords ?? 6));
    this.semanticTokens = Array.isArray(spec.semanticTokens) ? spec.semanticTokens : [];
    this.unitToToken = new Map();
    this.semanticTokenSet = new Set();
    for (const item of this.semanticTokens) {
      const unit = cleanUnit(item?.unit);
      const token = String(item?.token ?? "").trim();
      if (!unit || !token) continue;
      this.unitToToken.set(unit, token);
      this.semanticTokenSet.add(token);
    }
    this._unitsByWordCount = this._buildUnitsByWordCount();
  }

  static buildFromCHL(entries = [], options = {}) {
    const maxSemanticTokens = Math.max(500, Number(options.maxSemanticTokens ?? 12000));
    const minCount = Math.max(2, Number(options.minCount ?? 3));
    const minUnitChars = Math.max(3, Number(options.minUnitChars ?? 4));
    const maxUnitWords = Math.max(2, Number(options.maxUnitWords ?? 6));

    const bag = new Map();
    function inc(unit, w = 1) {
      if (!unit || unit.length < minUnitChars) return;
      bag.set(unit, (bag.get(unit) ?? 0) + w);
    }

    for (const entry of entries) {
      const text = String(entry?.text ?? entry?.input ?? entry?.payload ?? "").trim();
      if (!text) continue;
      const a = analyzeText(text);
      for (const c of unique(a.concepts ?? [])) inc(cleanUnit(c), 2.0);
      for (const bg of unique(a.tokenBigrams ?? [])) inc(cleanUnit(bg), 1.0);
      for (const tg of unique(a.tokenTrigrams ?? [])) inc(cleanUnit(tg), 0.8);
      for (const t of unique(a.focusTokens ?? [])) inc(cleanUnit(t), 0.6);
    }

    const semanticTokens = [...bag.entries()]
      .filter(([, count]) => count >= minCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, maxSemanticTokens)
      .map(([unit, score], idx) => ({
        unit,
        token: `<chl:${idx}>`,
        score: Number(score.toFixed(4)),
      }));

    return new HybridCHLTokenizer({
      version: "chl-hybrid-tokenizer-v1",
      minUnitChars,
      maxUnitWords,
      semanticTokens,
    });
  }

  _buildUnitsByWordCount() {
    const byWords = new Map();
    for (const item of this.semanticTokens) {
      const unit = cleanUnit(item?.unit);
      const words = unit.split(" ").filter(Boolean).length;
      if (!unit || words < 1 || words > this.maxUnitWords) continue;
      if (!byWords.has(words)) byWords.set(words, []);
      byWords.get(words).push(unit);
    }
    for (const [, units] of byWords) {
      units.sort((a, b) => b.length - a.length);
    }
    return byWords;
  }

  encode(text = "", options = {}) {
    const original = String(text ?? "");
    const normalized = original.toLowerCase().replace(/\s+/g, " ").trim();
    if (!normalized) return [];

    const words = normalized.split(" ").filter(Boolean);
    const out = [];
    let i = 0;
    const keepResidualWords = options.keepResidualWords !== false;

    while (i < words.length) {
      let matchedUnit = null;
      let matchedWordLen = 0;
      const maxLen = Math.min(this.maxUnitWords, words.length - i);
      for (let n = maxLen; n >= 1; n--) {
        const cand = words.slice(i, i + n).join(" ");
        const tok = this.unitToToken.get(cand);
        if (tok) {
          matchedUnit = cand;
          matchedWordLen = n;
          break;
        }
      }
      if (matchedUnit) {
        out.push(this.unitToToken.get(matchedUnit));
        i += matchedWordLen;
        continue;
      }
      if (keepResidualWords) out.push(words[i]);
      i += 1;
    }
    return out;
  }

  decode(tokens = []) {
    const reverse = new Map();
    for (const item of this.semanticTokens) reverse.set(item.token, item.unit);
    const out = [];
    for (const t of tokens) {
      const v = reverse.get(t) ?? t;
      out.push(v);
    }
    return out.join(" ");
  }

  getSemanticTokenSet() {
    return new Set(this.semanticTokenSet);
  }

  toJSON() {
    return {
      version: this.version,
      minUnitChars: this.minUnitChars,
      maxUnitWords: this.maxUnitWords,
      semanticTokens: this.semanticTokens,
    };
  }

  static fromJSON(obj = {}) {
    return new HybridCHLTokenizer(obj);
  }
}

module.exports = {
  HybridCHLTokenizer,
};
