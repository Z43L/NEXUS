/**
 * ViterbiGen — Generación fluida por decodificación de máxima probabilidad
 * 
 * Encuentra la secuencia de palabras más probable dado el modelo de bigramas
 * y restringida a un vocabulario permitido (extraído de la evidencia).
 * 
 * Implementación ligera: arrays en lugar de Maps para evitar overhead.
 */

const { tokenize, normalizeText } = require("../utils");

class ViterbiGenerator {
  constructor(options = {}) {
    this._bigramCounts = new Map();   // "w1|w2" → count
    this._unigramCounts = new Map();  // "w" → count
    this._totalBigrams = 0;
    this._totalUnigrams = 0;
    this.smoothing = options.smoothing ?? 0.01;
    this.beamWidth = options.beamWidth ?? 5;
    this.maxLength = options.maxLength ?? 12;
  }

  train(text) {
    const tokens = ["<s>", ...tokenize(normalizeText(String(text ?? ""))), "</s>"];
    for (const t of tokens) {
      this._unigramCounts.set(t, (this._unigramCounts.get(t) ?? 0) + 1);
      this._totalUnigrams++;
    }
    for (let i = 0; i < tokens.length - 1; i++) {
      const key = tokens[i] + "|" + tokens[i + 1];
      this._bigramCounts.set(key, (this._bigramCounts.get(key) ?? 0) + 1);
      this._totalBigrams++;
    }
  }

  _bigramProb(w1, w2) {
    const count = this._bigramCounts.get(w1 + "|" + w2) ?? 0;
    const ctxCount = this._unigramCounts.get(w1) ?? 0;
    const V = this._unigramCounts.size || 1;
    return (count + this.smoothing) / (ctxCount + this.smoothing * V);
  }

  /**
   * Viterbi con beam pruning.
   * 
   * @param {string[]} vocab - lista de palabras permitidas
   * @param {string|null} startWord - palabra inicial preferida
   * @returns {string}
   */
  decode(vocab, startWord = null) {
    if (vocab.length === 0) return "";
    
    // Cada entrada del beam guarda: word, prob, prev (índice), used (Set de palabras usadas)
    let beam = [];
    
    if (startWord && vocab.includes(startWord)) {
      const used = new Set([startWord]);
      beam.push({ word: startWord, prob: 1.0, prev: -1, used });
    } else {
      for (const w of vocab) {
        const p = this._bigramProb("<s>", w);
        if (p > 0) {
          const used = new Set([w]);
          beam.push({ word: w, prob: p, prev: -1, used });
        }
      }
    }
    
    beam.sort((a, b) => b.prob - a.prob);
    beam = beam.slice(0, this.beamWidth);
    
    let allBeams = [beam];
    
    for (let t = 1; t < this.maxLength && beam.length > 0; t++) {
      const nextBeam = [];
      
      for (let bi = 0; bi < beam.length; bi++) {
        const prev = beam[bi];
        
        for (const nextWord of vocab) {
          // No repetir palabra ya usada en este camino
          if (prev.used.has(nextWord)) continue;
          
          const transP = this._bigramProb(prev.word, nextWord);
          if (transP <= 0) continue;
          
          const candidateProb = prev.prob * transP;
          
          const existing = nextBeam.find((b) => b.word === nextWord);
          if (existing) {
            if (candidateProb > existing.prob) {
              existing.prob = candidateProb;
              existing.prev = bi;
              // Unir los used sets (el nuevo camino hereda las palabras usadas)
              existing.used = new Set([...prev.used, nextWord]);
            }
          } else {
            const used = new Set([...prev.used, nextWord]);
            nextBeam.push({ word: nextWord, prob: candidateProb, prev: bi, used });
          }
        }
      }
      
      if (nextBeam.length === 0) break;
      
      nextBeam.sort((a, b) => b.prob - a.prob);
      beam = nextBeam.slice(0, this.beamWidth);
      allBeams.push(beam);
    }
    
    if (allBeams.length === 0 || allBeams[0].length === 0) return vocab.join(" ");
    
    const lastBeam = allBeams[allBeams.length - 1];
    let bestEnd = lastBeam[0];
    for (const b of lastBeam) {
      if (b.prob > bestEnd.prob) bestEnd = b;
    }
    
    // Backtrack
    const sequence = [];
    let current = bestEnd;
    for (let t = allBeams.length - 1; t >= 0 && current; t--) {
      sequence.unshift(current.word);
      if (current.prev >= 0 && t > 0) {
        current = allBeams[t - 1][current.prev];
      } else {
        break;
      }
    }
    
    return sequence.join(" ") || vocab.join(" ");
  }

  generate(evidenceText, queryText = "") {
    const stopwords = new Set([
      "el", "la", "los", "las", "un", "una", "de", "del", "en", "a",
      "y", "o", "que", "se", "su", "sus", "es", "por", "para", "con",
      "lo", "le", "me", "te", "nos", "al", "mas", "como", "entre",
      "donde", "cuando", "como", "que", "cual", "quien", "cuanto",
    ]);
    
    const evTokens = tokenize(normalizeText(String(evidenceText ?? "")));
    const vocab = [...new Set(evTokens.filter((t) => t.length > 1 && !stopwords.has(t)))];
    
    const qTokens = tokenize(normalizeText(String(queryText ?? "")));
    const startWord = qTokens.find((t) => t.length > 1 && !stopwords.has(t) && vocab.includes(t)) ?? null;
    
    return this.decode(vocab, startWord);
  }

  generateVariants(evidenceText, queryText = "", count = 5) {
    const stopwords = new Set([
      "el", "la", "los", "las", "un", "una", "de", "del", "en", "a",
      "y", "o", "que", "se", "su", "sus", "es", "por", "para", "con",
    ]);
    
    const evTokens = tokenize(normalizeText(String(evidenceText ?? "")));
    const vocab = [...new Set(evTokens.filter((t) => t.length > 1 && !stopwords.has(t)))];
    
    const variants = [];
    for (const sw of vocab.slice(0, count)) {
      const dec = this.decode(vocab, sw);
      if (dec && dec.length > 3 && !variants.includes(dec)) {
        variants.push(dec);
      }
    }
    return variants;
  }

  snapshot() {
    return {
      type: "viterbi-gen",
      bigrams: this._bigramCounts.size,
      unigrams: this._unigramCounts.size,
      beamWidth: this.beamWidth,
    };
  }
}

module.exports = { ViterbiGenerator };
