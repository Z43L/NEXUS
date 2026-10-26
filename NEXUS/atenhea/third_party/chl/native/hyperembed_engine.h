#ifndef HYPEREMBED_ENGINE_H
#define HYPEREMBED_ENGINE_H

#include <cstdint>
#include <string>
#include <vector>
#include <array>
#include <unordered_map>
#include <fstream>
#include <random>
#include <thread>

namespace hyperembed {

constexpr size_t DIM = 10000;
constexpr size_t WORD_SIZE = 32;
constexpr size_t VEC_WORDS = 320; // Padded to 320 words for 64-byte alignment
constexpr size_t TAIL_BITS = DIM % WORD_SIZE; // 16
constexpr uint32_t LAST_WORD_MASK = TAIL_BITS == 0 ? 0xFFFFFFFFu : ((1u << TAIL_BITS) - 1u);
constexpr double LEARNING_RATE = 0.05;
constexpr size_t BUNDLE_THRESHOLD = 0;
constexpr size_t LEARN_WINDOW = 8;
constexpr size_t UPDATE_WINDOW = 6;
constexpr size_t NEGATIVE_SAMPLES = 2;
constexpr double SUBSAMPLE_T = 1e-4;

struct alignas(64) Vector {
  std::array<uint32_t, VEC_WORDS> arr;

  inline uint32_t& operator[](size_t idx) { return arr[idx]; }
  inline const uint32_t& operator[](size_t idx) const { return arr[idx]; }
  inline uint32_t* data() { return arr.data(); }
  inline const uint32_t* data() const { return arr.data(); }
  inline size_t size() const { return VEC_WORDS; }
};

// ─── Vector operations ─────────────────────────────────────

inline void vec_clear(Vector& v) {
  for (size_t i = 0; i < VEC_WORDS; ++i) v[i] = 0;
}

void vec_random(Vector& v, uint32_t seed);
void vec_clone(const Vector& src, Vector& dst);
void vec_bind(const Vector& a, const Vector& b, Vector& result);
void vec_bundle(const std::vector<const Vector*>& vecs, Vector& result);
void vec_bundle_weighted(const std::vector<const Vector*>& vecs, 
                         const std::vector<double>& weights, Vector& result);
void vec_permute(const Vector& src, int shift, Vector& result);
double vec_similarity(const Vector& a, const Vector& b);
void vec_normalize(Vector& v);
uint32_t vec_popcount(const Vector& v);

// ─── Tokenizer ─────────────────────────────────────────────

std::vector<std::string> tokenize(const std::string& text);
std::string normalize(const std::string& text);

// ─── Engine ────────────────────────────────────────────────

struct DocVector {
  std::string id;
  std::string text;
  Vector vector;
  std::vector<std::string> terms;
  Vector* payload_vec; // owned by engine
};

struct Candidate {
  size_t index;
  double similarity;
  std::string id;
  std::string text;
};

class HyperEmbedEngine {
public:
  HyperEmbedEngine();
  ~HyperEmbedEngine();

  // Core API
  void learn(const std::string& text);
  void encode(const std::string& text, Vector& out);
  double textSimilarity(const std::string& a, const std::string& b);
  
  // Batch operations
  void indexDocument(const std::string& id, const std::string& text);
  void indexBatch(const std::vector<std::pair<std::string, std::string>>& docs);
  void clearIndex();
  std::vector<Candidate> query(const std::string& query, size_t top_k = 5);
  std::vector<std::string> nearestNeighbors(const Vector& vec, size_t k = 10);

  // Persistence
  bool save(const std::string& path);
  bool load(const std::string& path);

  // Stats
  size_t vocabSize() const { return token_vectors_.size(); }
  size_t docCount() const { return documents_.size(); }
  size_t coocPairs() const { return cooc_counts_.size(); }

private:
  // Token vectors: token → Vector (owned)
  std::unordered_map<std::string, Vector*> token_vectors_;
  
  // Co-occurrence counts: "a|b" → count
  std::unordered_map<std::string, uint32_t> cooc_counts_;
  std::unordered_map<std::string, uint32_t> token_freq_;
  uint64_t total_token_count_ = 0;
  std::vector<std::string> vocab_tokens_;
  
  // Indexed documents
  std::vector<DocVector> documents_;
  
  // Seed for random vector generation
  uint32_t next_seed_ = 42;
  std::mt19937 rng_{42};
  
  // Helper
  Vector* getOrCreateVector(const std::string& token);
  Vector* getVector(const std::string& token);
};

} // namespace hyperembed

#endif
