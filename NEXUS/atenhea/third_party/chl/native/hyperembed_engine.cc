#include "hyperembed_engine.h"
#include <algorithm>
#include <cstring>
#include <cmath>
#include <random>
#include <sstream>
#include <fstream>
#include <cassert>
#include <thread>
#include <unordered_set>

#if defined(__ARM_NEON) || defined(__ARM_NEON__)
#include <arm_neon.h>
#endif

namespace hyperembed {

// ─── Vector operations ─────────────────────────────────────

static uint32_t splitmix32(uint32_t& x) {
  x += 0x9e3779b9u;
  uint32_t z = x;
  z = (z ^ (z >> 16)) * 0x85ebca6bu;
  z = (z ^ (z >> 13)) * 0xc2b2ae35u;
  return z ^ (z >> 16);
}

static uint32_t fnv1a32(const std::string& s, uint32_t seed) {
  uint32_t h = 0x811c9dc5u ^ seed;
  for (unsigned char c : s) {
    h ^= c;
    h *= 0x01000193u;
  }
  return h;
}

void vec_random(Vector& v, uint32_t seed) {
  uint32_t state = fnv1a32(std::to_string(seed), 0x9e3779b9u);
  for (size_t i = 0; i < VEC_WORDS; ++i) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    v[i] = state;
  }
}

void vec_clone(const Vector& src, Vector& dst) {
  for (size_t i = 0; i < VEC_WORDS; ++i) dst[i] = src[i];
}

void vec_bind(const Vector& a, const Vector& b, Vector& result) {
  for (size_t i = 0; i < VEC_WORDS; ++i) {
    result[i] = a[i] ^ b[i];
  }
}

void vec_bundle(const std::vector<const Vector*>& vecs, Vector& result) {
  if (vecs.empty()) { vec_clear(result); return; }
  
  // Count bits across all vectors
  std::vector<int32_t> counts(DIM, 0);
  for (const auto* vec : vecs) {
    for (size_t w = 0; w < VEC_WORDS; ++w) {
      uint32_t word = (*vec)[w];
      size_t base = w * WORD_SIZE;
      for (size_t b = 0; b < WORD_SIZE; ++b) {
        size_t bit = base + b;
        if (bit >= DIM) break;
        counts[bit] += (word & (1u << b)) ? 1 : -1;
      }
    }
  }
  
  // Threshold at 0 (majority vote)
  vec_clear(result);
  for (size_t b = 0; b < DIM; ++b) {
    if (counts[b] >= 0) {
      result[b / WORD_SIZE] |= (1u << (b % WORD_SIZE));
    }
  }
}

void vec_bundle_weighted(const std::vector<const Vector*>& vecs,
                         const std::vector<double>& weights, Vector& result) {
  if (vecs.empty()) { vec_clear(result); return; }
  
  std::vector<double> counts(DIM, 0.0);
  for (size_t vi = 0; vi < vecs.size(); ++vi) {
    double w = (vi < weights.size()) ? weights[vi] : 1.0;
    const auto& vec = *vecs[vi];
    for (size_t wi = 0; wi < VEC_WORDS; ++wi) {
      uint32_t word = vec[wi];
      size_t base = wi * WORD_SIZE;
      for (size_t b = 0; b < WORD_SIZE; ++b) {
        size_t bit = base + b;
        if (bit >= DIM) break;
        counts[bit] += (word & (1u << b)) ? w : -w;
      }
    }
  }
  
  vec_clear(result);
  for (size_t b = 0; b < DIM; ++b) {
    if (counts[b] >= 0) {
      result[b / WORD_SIZE] |= (1u << (b % WORD_SIZE));
    }
  }
}

void vec_permute(const Vector& src, int shift, Vector& result) {
  int total_bits = VEC_WORDS * WORD_SIZE;
  shift = ((shift % total_bits) + total_bits) % total_bits;
  if (shift == 0) { vec_clone(src, result); return; }
  
  vec_clear(result);
  for (int b = 0; b < total_bits; ++b) {
    int src_bit = (b - shift + total_bits) % total_bits;
    if (src[src_bit / WORD_SIZE] & (1u << (src_bit % WORD_SIZE))) {
      result[b / WORD_SIZE] |= (1u << (b % WORD_SIZE));
    }
  }
}

double vec_similarity(const Vector& a, const Vector& b) {
  uint32_t mismatches = 0;
#if defined(__ARM_NEON) || defined(__ARM_NEON__)
  uint32x4_t mismatch_cnt = vdupq_n_u32(0);
  for (size_t i = 0; i < 312; i += 4) {
    uint32x4_t va = vld1q_u32(&a[i]);
    uint32x4_t vb = vld1q_u32(&b[i]);
    uint32x4_t diff = veorq_u32(va, vb);
    uint8x16_t cnt8 = vcntq_u8(vreinterpretq_u8_u32(diff));
    uint16x8_t cnt16 = vpaddlq_u8(cnt8);
    uint32x4_t cnt32 = vpaddlq_u16(cnt16);
    mismatch_cnt = vaddq_u32(mismatch_cnt, cnt32);
  }
#if defined(__aarch64__)
  mismatches += vaddvq_u32(mismatch_cnt);
#else
  uint32_t lanes[4];
  vst1q_u32(lanes, mismatch_cnt);
  mismatches += lanes[0] + lanes[1] + lanes[2] + lanes[3];
#endif
#else
  const uint64_t* ptr_a = reinterpret_cast<const uint64_t*>(a.data());
  const uint64_t* ptr_b = reinterpret_cast<const uint64_t*>(b.data());
  for (size_t i = 0; i < 156; ++i) {
    mismatches += __builtin_popcountll(ptr_a[i] ^ ptr_b[i]);
  }
#endif

  uint32_t tail_diff = (a[312] ^ b[312]) & LAST_WORD_MASK;
  mismatches += __builtin_popcount(tail_diff);

  return (DIM - 2.0 * mismatches) / DIM;
}

uint32_t vec_popcount(const Vector& v) {
  uint32_t total = 0;
#if defined(__ARM_NEON) || defined(__ARM_NEON__)
  uint32x4_t total_cnt = vdupq_n_u32(0);
  for (size_t i = 0; i < 312; i += 4) {
    uint32x4_t val = vld1q_u32(&v[i]);
    uint8x16_t cnt8 = vcntq_u8(vreinterpretq_u8_u32(val));
    uint16x8_t cnt16 = vpaddlq_u8(cnt8);
    uint32x4_t cnt32 = vpaddlq_u16(cnt16);
    total_cnt = vaddq_u32(total_cnt, cnt32);
  }
#if defined(__aarch64__)
  total += vaddvq_u32(total_cnt);
#else
  uint32_t lanes[4];
  vst1q_u32(lanes, total_cnt);
  total += lanes[0] + lanes[1] + lanes[2] + lanes[3];
#endif
#else
  const uint64_t* ptr_v = reinterpret_cast<const uint64_t*>(v.data());
  for (size_t i = 0; i < 156; ++i) {
    total += __builtin_popcountll(ptr_v[i]);
  }
#endif

  total += __builtin_popcount(v[312] & LAST_WORD_MASK);
  return total;
}

void vec_normalize(Vector& v) {
  uint32_t ones = vec_popcount(v);
  if (ones < DIM * 0.3 || ones > DIM * 0.7) {
    Vector fresh;
    vec_random(fresh, ones);
    vec_bind(v, fresh, v);
  }
}

// ─── Tokenizer ─────────────────────────────────────────────

std::string normalize(const std::string& text) {
  std::string result;
  result.reserve(text.size());
  for (char c : text) {
    if (c >= 'A' && c <= 'Z') result.push_back(c - 'A' + 'a');
    else if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == ' ' || c == '\'') {
      result.push_back(c);
    } else {
      result.push_back(' ');
    }
  }
  return result;
}

std::vector<std::string> tokenize(const std::string& text) {
  std::vector<std::string> tokens;
  std::string norm = normalize(text);
  std::string current;
  tokens.reserve(128);
  for (char c : norm) {
    if (c == ' ') {
      if (!current.empty()) { tokens.push_back(current); current.clear(); }
    } else {
      current.push_back(c);
    }
  }
  if (!current.empty()) tokens.push_back(current);

  const size_t base_size = tokens.size();
  for (size_t i = 0; i < base_size && tokens.size() < 512; ++i) {
    const std::string& t = tokens[i];
    if (t.size() < 3) continue;

    size_t start = 0;
    for (size_t j = 0; j <= t.size(); ++j) {
      if (j == t.size() || t[j] == '_') {
        if (j > start + 2) tokens.push_back(t.substr(start, j - start));
        start = j + 1;
      }
    }

    if (t.size() >= 6) {
      for (size_t j = 0; j + 2 < t.size() && tokens.size() < 512; ++j) {
        tokens.push_back(t.substr(j, 3));
      }
    }
  }
  return tokens;
}

static std::vector<std::string> extract_terms(const std::string& text, size_t cap = 96) {
  std::unordered_set<std::string> seen;
  std::vector<std::string> terms;
  auto toks = tokenize(text);
  terms.reserve(std::min(cap, toks.size()));
  for (const auto& t : toks) {
    if (t.size() <= 2) continue;
    if (seen.insert(t).second) {
      terms.push_back(t);
      if (terms.size() >= cap) break;
    }
  }
  return terms;
}

// ─── Engine implementation ─────────────────────────────────

HyperEmbedEngine::HyperEmbedEngine() : next_seed_(42), rng_(42) {}

HyperEmbedEngine::~HyperEmbedEngine() {
  for (auto& [_, vec] : token_vectors_) {
    delete vec;
  }
}

Vector* HyperEmbedEngine::getOrCreateVector(const std::string& token) {
  auto it = token_vectors_.find(token);
  if (it != token_vectors_.end()) return it->second;
  
  Vector* v = new Vector;
  vec_random(*v, next_seed_++);
  token_vectors_[token] = v;
  vocab_tokens_.push_back(token);
  return v;
}

Vector* HyperEmbedEngine::getVector(const std::string& token) {
  auto it = token_vectors_.find(token);
  return (it != token_vectors_.end()) ? it->second : nullptr;
}

void HyperEmbedEngine::encode(const std::string& text, Vector& out) {
  auto tokens = tokenize(text);
  if (tokens.empty()) { vec_random(out, next_seed_++); return; }
  
  // Get token vectors
  std::vector<Vector*> token_vecs;
  token_vecs.reserve(tokens.size());
  for (const auto& t : tokens) {
    token_vecs.push_back(getOrCreateVector(t));
  }
  
  // Sequence encoding (with position via permutation)
  std::vector<Vector> permuted(token_vecs.size());
  for (size_t i = 0; i < token_vecs.size(); ++i) {
    vec_permute(*token_vecs[i], (int)(i * 7), permuted[i]);
  }
  
  // Collect all component vectors
  std::vector<const Vector*> components;
  
  // Sequence vector
  Vector seq_vec;
  {
    std::vector<const Vector*> perm_ptrs;
    for (auto& p : permuted) perm_ptrs.push_back(&p);
    vec_bundle(perm_ptrs, seq_vec);
    components.push_back(&seq_vec);
  }
  
  // Bigram bindings: bind(t_i, t_{i+1})
  std::vector<Vector> bigrams;
  for (size_t i = 0; i + 1 < tokens.size(); ++i) {
    if (tokens[i].size() > 2 && tokens[i+1].size() > 2) {
      bigrams.emplace_back();
      vec_bind(*token_vecs[i], *token_vecs[i+1], bigrams.back());
      components.push_back(&bigrams.back());
    }
  }
  
  // Trigram bindings: bind(bind(t_i, t_{i+1}), t_{i+2})
  std::vector<Vector> trigrams;
  for (size_t i = 0; i + 2 < tokens.size(); ++i) {
    if (tokens[i].size() > 2 && tokens[i+1].size() > 2 && tokens[i+2].size() > 2) {
      trigrams.emplace_back();
      Vector tmp;
      vec_bind(*token_vecs[i], *token_vecs[i+1], tmp);
      vec_bind(tmp, *token_vecs[i+2], trigrams.back());
      components.push_back(&trigrams.back());
    }
  }
  
  vec_bundle(components, out);
}

void HyperEmbedEngine::learn(const std::string& text) {
  auto tokens = tokenize(text);
  if (tokens.empty()) return;

  for (const auto& t : tokens) {
    if (t.size() <= 2) continue;
    token_freq_[t]++;
    total_token_count_++;
  }
  
  // Filter content tokens (length > 2)
  std::vector<std::string> content;
  content.reserve(tokens.size());
  for (const auto& t : tokens) {
    if (t.size() <= 2) continue;
    auto fit = token_freq_.find(t);
    uint32_t tf = (fit != token_freq_.end()) ? fit->second : 1;
    double freq = static_cast<double>(tf) / static_cast<double>(std::max<uint64_t>(1, total_token_count_));
    double keep_prob = (freq <= SUBSAMPLE_T) ? 1.0 : (std::sqrt(SUBSAMPLE_T / freq) + (SUBSAMPLE_T / freq));
    keep_prob = std::clamp(keep_prob, 0.05, 1.0);
    std::uniform_real_distribution<double> u01(0.0, 1.0);
    if (u01(rng_) <= keep_prob) content.push_back(t);
  }
  if (content.size() < 2) return;
  
  // Update co-occurrence counts
  for (size_t i = 0; i < content.size(); ++i) {
    for (size_t j = i + 1; j < std::min(i + LEARN_WINDOW, content.size()); ++j) {
      if (content[i] == content[j]) continue;
      std::string key = content[i] < content[j] 
        ? content[i] + "|" + content[j]
        : content[j] + "|" + content[i];
      cooc_counts_[key]++;
    }
  }
  
  // Apply learning: move co-occurring token vectors toward each other
  for (size_t i = 0; i < content.size(); ++i) {
    for (size_t j = i + 1; j < std::min(i + UPDATE_WINDOW, content.size()); ++j) {
      if (content[i] == content[j]) continue;
      
      std::string ck = content[i] < content[j]
        ? content[i] + "|" + content[j]
        : content[j] + "|" + content[i];
      auto it = cooc_counts_.find(ck);
      uint32_t count = (it != cooc_counts_.end()) ? it->second : 0;
      size_t distance = j - i;
      double distance_weight = 1.0 / static_cast<double>(distance + 1);
      double strength = std::min(1.0, count / 12.0) * LEARNING_RATE * distance_weight;
      
      Vector* va = getOrCreateVector(content[i]);
      Vector* vb = getOrCreateVector(content[j]);
      
      std::vector<const Vector*> vecs = {va, vb};
      std::vector<double> weights = {1.0 - strength, strength};
      Vector new_va, new_vb;
      vec_bundle_weighted(vecs, weights, new_va);
      weights = {strength, 1.0 - strength};
      vec_bundle_weighted(vecs, weights, new_vb);
      
      vec_clone(new_va, *va);
      vec_clone(new_vb, *vb);
      vec_normalize(*va);
      vec_normalize(*vb);

      if (vocab_tokens_.size() > 3 && NEGATIVE_SAMPLES > 0) {
        std::uniform_int_distribution<size_t> uid(0, vocab_tokens_.size() - 1);
        for (size_t ns = 0; ns < NEGATIVE_SAMPLES; ++ns) {
          std::string neg_token = vocab_tokens_[uid(rng_)];
          for (size_t probe = 0; probe < 5 && i + probe + 1 < content.size(); ++probe) {
            const std::string& cand = content[i + probe + 1];
            if (cand == content[i] || cand == content[j]) continue;
            std::string nk = cand < content[i] ? cand + "|" + content[i] : content[i] + "|" + cand;
            if (cooc_counts_.find(nk) == cooc_counts_.end()) {
              neg_token = cand;
              break;
            }
          }
          if (neg_token == content[i] || neg_token == content[j]) continue;
          Vector* vn = getOrCreateVector(neg_token);
          if (!vn) continue;

          // Repulsión ligera: reducir similitud con negativos frecuentes aleatorios.
          double neg_strength = strength * 0.35;
          std::vector<const Vector*> neg_vecs = {va, vn};
          std::vector<double> neg_weights = {1.0 + neg_strength, -neg_strength};
          Vector pushed_va;
          vec_bundle_weighted(neg_vecs, neg_weights, pushed_va);
          vec_clone(pushed_va, *va);
          vec_normalize(*va);
        }
      }
    }
  }
}

double HyperEmbedEngine::textSimilarity(const std::string& a, const std::string& b) {
  Vector va, vb;
  encode(a, va);
  encode(b, vb);
  return vec_similarity(va, vb);
}

void HyperEmbedEngine::indexDocument(const std::string& id, const std::string& text) {
  // Learn from the text (update token vectors)
  learn(text);
  
  DocVector doc;
  doc.id = id;
  doc.text = text;
  encode(text, doc.vector);
  doc.terms = extract_terms(text);
  doc.payload_vec = nullptr;
  documents_.push_back(doc);
}

void HyperEmbedEngine::indexBatch(const std::vector<std::pair<std::string, std::string>>& docs) {
  documents_.reserve(documents_.size() + docs.size());
  for (const auto& [id, text] : docs) {
    indexDocument(id, text);
  }
}

void HyperEmbedEngine::clearIndex() {
  documents_.clear();
}

std::vector<Candidate> HyperEmbedEngine::query(const std::string& query, size_t top_k) {
  Vector qvec;
  encode(query, qvec);
  const auto qterms = extract_terms(query, 64);
  const std::unordered_set<std::string> qset(qterms.begin(), qterms.end());

  const size_t doc_count = documents_.size();
  std::vector<Candidate> candidates;
  candidates.reserve(doc_count);

  const size_t min_parallel_docs = 2000;
  const unsigned hw = std::max(1u, std::thread::hardware_concurrency());
  const bool can_parallel = doc_count >= min_parallel_docs && hw > 1;

  if (!can_parallel) {
    for (size_t i = 0; i < doc_count; ++i) {
      double sim = vec_similarity(qvec, documents_[i].vector);
      size_t shared = 0;
      for (const auto& t : documents_[i].terms) {
        if (qset.find(t) != qset.end()) shared++;
      }
      double rel = qset.empty() ? 0.0 : static_cast<double>(shared) / static_cast<double>(qset.size());
      double fused = 0.85 * sim + 0.15 * rel;
      candidates.push_back({i, fused, documents_[i].id, documents_[i].text});
    }
  } else {
    const size_t num_threads = std::min(static_cast<size_t>(hw), doc_count);
    std::vector<std::vector<Candidate>> partials(num_threads);
    std::vector<std::thread> workers;
    workers.reserve(num_threads);

    const size_t chunk = (doc_count + num_threads - 1) / num_threads;
    for (size_t t = 0; t < num_threads; ++t) {
      const size_t start = t * chunk;
      const size_t end = std::min(doc_count, start + chunk);
      if (start >= end) continue;
      workers.emplace_back([this, &qvec, &partials, t, start, end]() {
        auto& out = partials[t];
        out.reserve(end - start);
        for (size_t i = start; i < end; ++i) {
          double sim = vec_similarity(qvec, documents_[i].vector);
          out.push_back({i, sim, documents_[i].id, documents_[i].text});
        }
      });
    }
    for (auto& w : workers) w.join();

    for (auto& p : partials) {
      candidates.insert(candidates.end(), p.begin(), p.end());
    }

    if (!qset.empty()) {
      for (auto& c : candidates) {
        size_t shared = 0;
        for (const auto& t : documents_[c.index].terms) {
          if (qset.find(t) != qset.end()) shared++;
        }
        double rel = static_cast<double>(shared) / static_cast<double>(qset.size());
        c.similarity = 0.85 * c.similarity + 0.15 * rel;
      }
    }
  }

  std::partial_sort(candidates.begin(), 
                    candidates.begin() + std::min(top_k, candidates.size()),
                    candidates.end(),
                    [](const Candidate& a, const Candidate& b) {
                      return a.similarity > b.similarity;
                    });
  
  candidates.resize(std::min(top_k, candidates.size()));
  return candidates;
}

std::vector<std::string> HyperEmbedEngine::nearestNeighbors(const Vector& vec, size_t k) {
  std::vector<std::pair<double, std::string>> scored;
  for (const auto& [token, tvec] : token_vectors_) {
    if (token.size() < 3) continue;
    scored.push_back({vec_similarity(vec, *tvec), token});
  }
  
  std::partial_sort(scored.begin(), 
                    scored.begin() + std::min(k, scored.size()),
                    scored.end(),
                    [](const auto& a, const auto& b) { return a.first > b.first; });
  
  std::vector<std::string> result;
  for (size_t i = 0; i < std::min(k, scored.size()); ++i) {
    result.push_back(scored[i].second);
  }
  return result;
}

// ─── Persistence ───────────────────────────────────────────

bool HyperEmbedEngine::save(const std::string& path) {
  std::ofstream out(path, std::ios::binary);
  if (!out) return false;
  
  // Magic number and version
  const char magic[] = "HDCX";
  out.write(magic, 4);
  uint32_t version = 1;
  out.write(reinterpret_cast<const char*>(&version), 4);
  
  // Token vectors
  uint32_t token_count = token_vectors_.size();
  out.write(reinterpret_cast<const char*>(&token_count), 4);
  for (const auto& [token, vec] : token_vectors_) {
    uint32_t token_len = token.size();
    out.write(reinterpret_cast<const char*>(&token_len), 4);
    out.write(token.data(), token_len);
    out.write(reinterpret_cast<const char*>(vec->data()), VEC_WORDS * sizeof(uint32_t));
  }
  
  // Co-occurrence counts
  uint32_t cooc_count = cooc_counts_.size();
  out.write(reinterpret_cast<const char*>(&cooc_count), 4);
  for (const auto& [key, count] : cooc_counts_) {
    uint32_t key_len = key.size();
    out.write(reinterpret_cast<const char*>(&key_len), 4);
    out.write(key.data(), key_len);
    out.write(reinterpret_cast<const char*>(&count), 4);
  }
  
  // Documents
  uint32_t doc_count = documents_.size();
  out.write(reinterpret_cast<const char*>(&doc_count), 4);
  for (const auto& doc : documents_) {
    uint32_t id_len = doc.id.size();
    out.write(reinterpret_cast<const char*>(&id_len), 4);
    out.write(doc.id.data(), id_len);
    uint32_t text_len = doc.text.size();
    out.write(reinterpret_cast<const char*>(&text_len), 4);
    out.write(doc.text.data(), text_len);
    out.write(reinterpret_cast<const char*>(doc.vector.data()), VEC_WORDS * sizeof(uint32_t));
  }
  
  // Seed
  out.write(reinterpret_cast<const char*>(&next_seed_), 4);
  
  return out.good();
}

bool HyperEmbedEngine::load(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  
  // Clear existing state
  for (auto& [_, vec] : token_vectors_) delete vec;
  token_vectors_.clear();
  vocab_tokens_.clear();
  cooc_counts_.clear();
  token_freq_.clear();
  total_token_count_ = 0;
  documents_.clear();
  
  // Magic
  char magic[4];
  in.read(magic, 4);
  if (std::memcmp(magic, "HDCX", 4) != 0) return false;
  
  uint32_t version;
  in.read(reinterpret_cast<char*>(&version), 4);
  
  // Token vectors
  uint32_t token_count;
  in.read(reinterpret_cast<char*>(&token_count), 4);
  for (uint32_t i = 0; i < token_count; ++i) {
    uint32_t token_len;
    in.read(reinterpret_cast<char*>(&token_len), 4);
    std::string token(token_len, '\0');
    in.read(token.data(), token_len);
    
    Vector* vec = new Vector;
    in.read(reinterpret_cast<char*>(vec->data()), VEC_WORDS * sizeof(uint32_t));
    token_vectors_[token] = vec;
    vocab_tokens_.push_back(token);
  }
  
  // Co-occurrence counts
  uint32_t cooc_count;
  in.read(reinterpret_cast<char*>(&cooc_count), 4);
  for (uint32_t i = 0; i < cooc_count; ++i) {
    uint32_t key_len;
    in.read(reinterpret_cast<char*>(&key_len), 4);
    std::string key(key_len, '\0');
    in.read(key.data(), key_len);
    uint32_t count;
    in.read(reinterpret_cast<char*>(&count), 4);
    cooc_counts_[key] = count;
  }
  
  // Documents
  uint32_t doc_count;
  in.read(reinterpret_cast<char*>(&doc_count), 4);
  documents_.reserve(doc_count);
  for (uint32_t i = 0; i < doc_count; ++i) {
    DocVector doc;
    uint32_t id_len;
    in.read(reinterpret_cast<char*>(&id_len), 4);
    doc.id.resize(id_len);
    in.read(doc.id.data(), id_len);
    
    uint32_t text_len;
    in.read(reinterpret_cast<char*>(&text_len), 4);
    doc.text.resize(text_len);
    in.read(doc.text.data(), text_len);
    
    in.read(reinterpret_cast<char*>(doc.vector.data()), VEC_WORDS * sizeof(uint32_t));
    doc.terms = extract_terms(doc.text);
    doc.payload_vec = nullptr;
    documents_.push_back(doc);
  }
  
  // Seed
  in.read(reinterpret_cast<char*>(&next_seed_), 4);
  if (!in) next_seed_ = doc_count + token_count + 42;
  
  return true;
}

} // namespace hyperembed
