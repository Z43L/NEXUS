#include <node_api.h>

#include <algorithm>
#include <fstream>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <future>
#include <limits>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

struct Candidate {
  size_t index;
  double score;
  uint32_t hash_distance;
};

struct Entry {
  std::string id;
  std::string text;
  std::string canonical_text;
  std::vector<std::string> tokens;
  std::vector<std::string> ngrams3;
  std::vector<std::string> ngrams4;
  std::vector<std::string> concepts;
  bool negated = false;
  std::string payload_canonical_text;
  std::vector<std::string> payload_tokens;
  std::vector<std::string> payload_ngrams3;
  std::vector<std::string> payload_ngrams4;
  std::vector<std::string> payload_concepts;
  bool payload_negated = false;
  std::vector<uint32_t> hash;
  std::vector<uint32_t> hyper;
  std::string payload_json;
  double quality = 1.0;
  int64_t created_at = 0;
  int64_t updated_at = 0;
  int64_t last_access_at = 0;
  uint32_t access_count = 0;
  uint32_t prototype_count = 1;
};

static int64_t now_ms() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

static uint32_t fnv1a32(const std::string& input, uint32_t seed) {
  uint32_t h = 0x811c9dc5u ^ seed;
  for (unsigned char c : input) {
    h ^= c;
    h *= 0x01000193u;
  }
  h ^= h >> 16;
  h *= 0x7feb352du;
  h ^= h >> 15;
  h *= 0x846ca68bu;
  h ^= h >> 16;
  return h;
}

static uint32_t splitmix32(uint32_t& x) {
  x = x + 0x9e3779b9u;
  uint32_t z = x;
  z = (z ^ (z >> 16)) * 0x85ebca6bu;
  z = (z ^ (z >> 13)) * 0xc2b2ae35u;
  return z ^ (z >> 16);
}

static uint32_t popcount32(uint32_t v) {
  return static_cast<uint32_t>(__builtin_popcount(v));
}

static uint32_t hamming_distance(const std::vector<uint32_t>& a, const std::vector<uint32_t>& b) {
  uint32_t total = 0;
  for (size_t i = 0; i < a.size(); ++i) {
    total += popcount32(a[i] ^ b[i]);
  }
  return total;
}

static double hamming_similarity(const std::vector<uint32_t>& a, const std::vector<uint32_t>& b) {
  return 1.0 - static_cast<double>(hamming_distance(a, b)) / static_cast<double>(a.size() * 32u);
}

static std::string to_lower_ascii(std::string text) {
  for (char& ch : text) {
    unsigned char u = static_cast<unsigned char>(ch);
    if (u >= 'A' && u <= 'Z') {
      ch = static_cast<char>(u - 'A' + 'a');
    }
  }
  return text;
}

static std::vector<std::string> tokenize_ascii(const std::string& text) {
  std::vector<std::string> out;
  std::string current;
  for (unsigned char ch : text) {
    bool ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '\'';
    if (ok) {
      current.push_back(static_cast<char>(ch));
    } else if (!current.empty()) {
      out.push_back(current);
      current.clear();
    }
  }
  if (!current.empty()) out.push_back(current);
  return out;
}

static std::vector<std::string> char_ngrams(const std::string& text, size_t n) {
  std::string cleaned = " " + text + " ";
  std::vector<std::string> grams;
  if (cleaned.size() < n) {
    if (!cleaned.empty()) grams.push_back(cleaned);
    return grams;
  }
  for (size_t i = 0; i + n <= cleaned.size(); ++i) {
    grams.push_back(cleaned.substr(i, n));
  }
  return grams;
}

static const std::vector<std::pair<std::string, std::string>>& canonical_phrase_map() {
  static const std::vector<std::pair<std::string, std::string>> kMap = {
      {"da luz a", "ilumina"},
      {"desprende humo", "humea"},
      {"se mueve por", "corre por"},
      {"se desplaza en", "nada en"},
      {"se posa en", "posa en"},
      {"arriba a", "llega a"},
      {"llega a", "entra en"},
      {"desbloquea", "abre"},
      {"conserva", "guarda"},
      {"recarga", "carga"},
      {"permanece en", "esta en"},
      {"sigue en", "esta en"},
      {"tapiza", "cubre"},
      {"resuena", "suena"},
      {"anota", "escribe"},
      {"adquiere", "compra"},
      {"moja", "riega"},
      {"templa", "calienta"},
      {"enseña", "muestra"},
      {"vigila", "observa"},
      {"examina", "analiza"},
      {"coordina con", "sincroniza con"},
      {"maneja", "procesa"},
      {"localiza", "encuentra"},
      {"sigue", "rastrea"},
      {"resguarda", "protege"},
      {"enciende", "activa"},
      {"apaga", "desactiva"},
      {"obtiene", "recibe"},
      {"favorece", "prioriza"},
      {"absorbe", "aprende"},
  };
  return kMap;
}

static const std::vector<std::pair<std::string, std::string>>& extra_phrase_map() {
  static const std::vector<std::pair<std::string, std::string>> kMap = []() {
    std::vector<std::pair<std::string, std::string>> map;
    const char* extra_path = std::getenv("CHL_PHRASES_PATH");
    if (extra_path && *extra_path) {
      std::ifstream in(extra_path);
      if (in.good()) {
        std::string line;
        while (std::getline(in, line)) {
          if (line.empty()) continue;
          const size_t tab = line.find('\t');
          if (tab == std::string::npos) continue;
          std::string from = to_lower_ascii(line.substr(0, tab));
          std::string to = to_lower_ascii(line.substr(tab + 1));
          if (from.empty() || to.empty()) continue;
          map.emplace_back(from, to);
        }
      }
    }
    return map;
  }();
  return kMap;
}

static std::string canonicalize_text(std::string text) {
  text = to_lower_ascii(text);
  for (const auto& pair : canonical_phrase_map()) {
    size_t pos = 0;
    while ((pos = text.find(pair.first, pos)) != std::string::npos) {
      const bool left_ok = pos == 0 || text[pos - 1] == ' ';
      const size_t end = pos + pair.first.size();
      const bool right_ok = end >= text.size() || text[end] == ' ';
      if (left_ok && right_ok) {
        text.replace(pos, pair.first.size(), pair.second);
        pos += pair.second.size();
      } else {
        pos = end;
      }
    }
  }
  for (const auto& pair : extra_phrase_map()) {
    size_t pos = 0;
    while ((pos = text.find(pair.first, pos)) != std::string::npos) {
      const bool left_ok = pos == 0 || text[pos - 1] == ' ';
      const size_t end = pos + pair.first.size();
      const bool right_ok = end >= text.size() || text[end] == ' ';
      if (left_ok && right_ok) {
        text.replace(pos, pair.first.size(), pair.second);
        pos += pair.second.size();
      } else {
        pos = end;
      }
    }
  }
  return text;
}

static const std::unordered_map<std::string, std::string>& concept_map() {
  static const std::unordered_map<std::string, std::string> kBaseMap = {
      {"felino", "gato"},
      {"can", "perro"},
      {"automovil", "coche"},
      {"medico", "doctor"},
      {"cocinera", "chef"},
      {"alumna", "estudiante"},
      {"libreta", "cuaderno"},
      {"desbloquea", "abre"},
      {"abre", "abre"},
      {"cierra", "cierra"},
      {"recarga", "carga"},
      {"carga", "carga"},
      {"desciende", "cae"},
      {"cae", "cae"},
      {"conserva", "guarda"},
      {"guarda", "guarda"},
      {"descansa", "duerme"},
      {"duerme", "duerme"},
      {"anota", "escribe"},
      {"escribe", "escribe"},
      {"templa", "calienta"},
      {"calienta", "calienta"},
      {"enseña", "muestra"},
      {"muestra", "muestra"},
      {"resuena", "suena"},
      {"suena", "suena"},
      {"adquiere", "compra"},
      {"compra", "compra"},
      {"moja", "riega"},
      {"riega", "riega"},
      {"apoya", "posa"},
      {"posa", "posa"},
      {"llega", "entra"},
      {"entra", "entra"},
      {"correr", "corre"},
      {"corre", "corre"},
      {"va", "circula"},
      {"circula", "circula"},
      {"vigila", "observa"},
      {"observa", "observa"},
      {"examina", "analiza"},
      {"analiza", "analiza"},
      {"coordina", "sincroniza"},
      {"sincroniza", "sincroniza"},
      {"maneja", "procesa"},
      {"procesa", "procesa"},
      {"localiza", "encuentra"},
      {"encuentra", "encuentra"},
      {"sigue", "rastrea"},
      {"rastrea", "rastrea"},
      {"resguarda", "protege"},
      {"protege", "protege"},
      {"enciende", "activa"},
      {"activa", "activa"},
      {"apaga", "desactiva"},
      {"desactiva", "desactiva"},
      {"obtiene", "recibe"},
      {"recibe", "recibe"},
      {"favorece", "prioriza"},
      {"prioriza", "prioriza"},
      {"absorbe", "aprende"},
      {"aprende", "aprende"},
  };
  static std::unordered_map<std::string, std::string> kMap = [&]() {
    std::unordered_map<std::string, std::string> map = kBaseMap;
    const char* file = std::getenv("CHL_CONCEPTS_PATH");
    if (file && *file) {
      std::ifstream in(file);
      std::string line;
      while (std::getline(in, line)) {
        if (line.empty()) continue;
        const size_t tab = line.find('\t');
        if (tab == std::string::npos) continue;
        std::string from = to_lower_ascii(line.substr(0, tab));
        std::string to = to_lower_ascii(line.substr(tab + 1));
        if (from.empty() || to.empty()) continue;
        map[from] = to;
      }
    }
    return map;
  }();
  return kMap;
}

static bool is_stopword(const std::string& token) {
  static const std::unordered_set<std::string> kStop = {
      "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "en", "a",
      "y", "o", "que", "se", "su", "sus", "es", "esta", "estan", "hay", "por", "para",
      "sobre", "con",
  };
  return kStop.find(token) != kStop.end();
}

struct Representations {
  std::string normalized_text;
  std::string canonical_text;
  std::vector<std::string> tokens;
  std::vector<std::string> ngrams3;
  std::vector<std::string> ngrams4;
  std::vector<std::string> concepts;
  bool negated = false;
};

static Representations build_representations(const std::string& text) {
  Representations reps;
  reps.normalized_text = to_lower_ascii(text);
  reps.canonical_text = canonicalize_text(reps.normalized_text);
  reps.tokens = tokenize_ascii(reps.canonical_text);
  reps.ngrams3 = char_ngrams(reps.canonical_text, 3);
  reps.ngrams4 = char_ngrams(reps.canonical_text, 4);
  reps.negated = false;
  reps.concepts.reserve(reps.tokens.size());
  for (const auto& token : reps.tokens) {
    if (token == "no" || token == "sin" || token == "nunca" || token == "jamas") {
      reps.negated = true;
      reps.concepts.push_back(token);
      continue;
    }
    if (is_stopword(token)) continue;
    const auto it = concept_map().find(token);
    reps.concepts.push_back(it == concept_map().end() ? token : it->second);
  }
  return reps;
}

static double set_jaccard(const std::vector<std::string>& a, const std::vector<std::string>& b) {
  std::unordered_set<std::string> set_a(a.begin(), a.end());
  std::unordered_set<std::string> set_b(b.begin(), b.end());
  if (set_a.empty() && set_b.empty()) return 0.0;
  size_t inter = 0;
  for (const auto& item : set_a) {
    if (set_b.find(item) != set_b.end()) {
      ++inter;
    }
  }
  const size_t uni = set_a.size() + set_b.size() - inter;
  return uni == 0 ? 0.0 : static_cast<double>(inter) / static_cast<double>(uni);
}

static bool has_payload_text(const std::string& payload_json) {
  return !payload_json.empty() && payload_json != "null";
}

struct RepresentationSimilarity {
  double lexical;
  double semantic;
  double negation_match;
};

static double token_sequence_similarity(const std::vector<std::string>& a, const std::vector<std::string>& b) {
  if (a.empty() || b.empty()) return 0.0;
  std::vector<std::vector<uint16_t>> dp(a.size() + 1, std::vector<uint16_t>(b.size() + 1, 0));
  for (size_t i = 1; i <= a.size(); ++i) {
    for (size_t j = 1; j <= b.size(); ++j) {
      dp[i][j] = a[i - 1] == b[j - 1] ? static_cast<uint16_t>(dp[i - 1][j - 1] + 1) : std::max(dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return static_cast<double>(dp[a.size()][b.size()]) / static_cast<double>(std::max(a.size(), b.size()));
}

static RepresentationSimilarity representation_similarity(const Representations& query, const Representations& entry) {
  const double token_score = set_jaccard(query.tokens, entry.tokens);
  const double gram3_score = set_jaccard(query.ngrams3, entry.ngrams3);
  const double gram4_score = set_jaccard(query.ngrams4, entry.ngrams4);
  const double lexical = 0.3 * token_score + 0.4 * gram3_score + 0.3 * gram4_score;
  const double semantic = set_jaccard(query.concepts, entry.concepts);
  const double negation_match = query.negated == entry.negated ? 1.0 : 0.0;
  return {lexical, semantic, negation_match};
}

static std::vector<std::string> merge_strings(const std::vector<std::string>& a, const std::vector<std::string>& b) {
  std::unordered_set<std::string> seen(a.begin(), a.end());
  std::vector<std::string> out = a;
  for (const auto& value : b) {
    if (seen.insert(value).second) {
      out.push_back(value);
    }
  }
  return out;
}

static void index_text(std::unordered_map<std::string, std::vector<size_t>>& map, const std::string& text, size_t index) {
  if (text.empty()) return;
  map[text].push_back(index);
}

static void unindex_text(std::unordered_map<std::string, std::vector<size_t>>& map, const std::string& text, size_t index) {
  if (text.empty()) return;
  auto it = map.find(text);
  if (it == map.end()) return;
  auto& vec = it->second;
  vec.erase(std::remove(vec.begin(), vec.end(), index), vec.end());
  if (vec.empty()) map.erase(it);
}

static std::vector<std::pair<std::string, double>> extract_features(const std::string& text) {
  std::vector<std::pair<std::string, double>> features;
  const std::string canonical = canonicalize_text(to_lower_ascii(text));
  auto tokens = tokenize_ascii(canonical);
  for (const auto& token : tokens) {
    features.emplace_back("tok:" + token, 3.0);
  }
  for (const auto& token : tokens) {
    if (token == "no" || token == "sin" || token == "nunca" || token == "jamas") {
      features.emplace_back("neg:" + token, 4.0);
      continue;
    }
    if (is_stopword(token)) continue;
    const auto it = concept_map().find(token);
    features.emplace_back("con:" + (it == concept_map().end() ? token : it->second), 3.0);
  }
  auto grams = char_ngrams(text, 3);
  for (const auto& gram : grams) {
    features.emplace_back("chr:" + gram, 1.0);
  }
  if (features.empty() && !text.empty()) {
    features.emplace_back("raw:" + text, 1.0);
  }
  return features;
}

static std::vector<uint32_t> make_zero_words(size_t bit_count) {
  return std::vector<uint32_t>(bit_count / 32u, 0u);
}

static std::vector<uint32_t> semantic_hash(const std::string& text, size_t bit_count, uint32_t seed, const std::vector<double>* bias) {
  std::vector<double> scores(bit_count, 0.0);
  auto features = extract_features(text);
  const size_t word_count = bit_count / 32u;
  for (const auto& feature : features) {
    uint32_t feature_seed = fnv1a32(feature.first, seed);
    uint32_t state = feature_seed;
    for (size_t w = 0; w < word_count; ++w) {
      uint32_t word = splitmix32(state);
      size_t base = w * 32u;
      for (size_t bit = 0; bit < 32u; ++bit) {
        scores[base + bit] += (word & (1u << bit)) ? feature.second : -feature.second;
      }
    }
  }
  if (bias) {
    for (size_t i = 0; i < std::min(bias->size(), scores.size()); ++i) {
      scores[i] += (*bias)[i];
    }
  }
  auto out = make_zero_words(bit_count);
  for (size_t i = 0; i < bit_count; ++i) {
    if (scores[i] >= 0.0) {
      out[i >> 5] |= (1u << (i & 31u));
    }
  }
  return out;
}

static std::vector<uint32_t> prototype_vector(const std::string& text, size_t dimension, uint32_t seed) {
  std::vector<int32_t> counts(dimension, 0);
  auto tokens = tokenize_ascii(text);
  if (tokens.empty()) {
    tokens.push_back(text);
  }
  for (size_t token_index = 0; token_index < tokens.size(); ++token_index) {
    uint32_t s = fnv1a32(tokens[token_index], seed ^ static_cast<uint32_t>(token_index * 0x9e37u));
    for (size_t i = 0; i < dimension; ++i) {
      uint32_t x = s;
      uint32_t bit = splitmix32(x);
      counts[i] += (bit & 1u) ? 1 : -1;
      s ^= (bit + static_cast<uint32_t>(i * 2654435761u));
    }
  }
  auto out = make_zero_words(dimension);
  for (size_t i = 0; i < dimension; ++i) {
    if (counts[i] >= 0) {
      out[i >> 5] |= (1u << (i & 31u));
    }
  }
  return out;
}

static std::string hex_words(const std::vector<uint32_t>& words) {
  std::ostringstream oss;
  for (uint32_t word : words) {
    oss.width(8);
    oss.fill('0');
    oss << std::hex << std::nouppercase << word;
  }
  return oss.str();
}

static std::string json_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (char ch : s) {
    switch (ch) {
      case '\\': out += "\\\\"; break;
      case '"': out += "\\\""; break;
      case '\b': out += "\\b"; break;
      case '\f': out += "\\f"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (static_cast<unsigned char>(ch) < 0x20) {
          constexpr char hex[] = "0123456789abcdef";
          out += "\\u00";
          out += hex[(ch >> 4) & 0xF];
          out += hex[ch & 0xF];
        } else {
          out.push_back(ch);
        }
    }
  }
  return out;
}

static std::string json_array(const std::vector<std::string>& values) {
  std::ostringstream oss;
  oss << "[";
  for (size_t i = 0; i < values.size(); ++i) {
    if (i) oss << ",";
    oss << "\"" << json_escape(values[i]) << "\"";
  }
  oss << "]";
  return oss.str();
}

class CHLEngine {
 public:
  CHLEngine(size_t bit_count, size_t band_bits, size_t hyper_dim, size_t max_entries, size_t max_candidates, uint32_t seed, bool large_profile)
      : bit_count_(bit_count),
        band_bits_(band_bits),
        hyper_dim_(hyper_dim),
        max_entries_(max_entries),
        max_candidates_(max_candidates),
        seed_(seed),
        large_profile_(large_profile),
        bit_bias_(bit_count, 0.0) {
    if (bit_count_ % band_bits_ != 0 || bit_count_ % 32u != 0 || hyper_dim_ % 32u != 0) {
      throw std::runtime_error("invalid dimensions");
    }
    band_count_ = bit_count_ / band_bits_;
    words_per_band_ = band_bits_ / 32u;
    band_maps_.resize(band_count_);
    token_maps_.resize(4);
    payload_token_maps_.resize(4);
  }

  std::string remember(const std::string& raw_text, const std::string& payload_json, double quality) {
    const std::string text = to_lower_ascii(raw_text);
    Entry entry;
    entry.id = generate_id(text);
    entry.text = text;
    const auto reps = build_representations(text);
    entry.canonical_text = reps.canonical_text;
    entry.tokens = reps.tokens;
    entry.ngrams3 = reps.ngrams3;
    entry.ngrams4 = reps.ngrams4;
    entry.concepts = reps.concepts;
    entry.negated = reps.negated;
    if (has_payload_text(payload_json)) {
      const auto payload_reps = build_representations(payload_json);
      entry.payload_canonical_text = payload_reps.canonical_text;
      entry.payload_tokens = payload_reps.tokens;
      entry.payload_ngrams3 = payload_reps.ngrams3;
      entry.payload_ngrams4 = payload_reps.ngrams4;
      entry.payload_concepts = payload_reps.concepts;
      entry.payload_negated = payload_reps.negated;
    }
    entry.hash = semantic_hash(text, bit_count_, seed_, &bit_bias_);
    entry.hyper = prototype_vector(text, hyper_dim_, seed_);
    entry.payload_json = payload_json;
    entry.quality = quality;
    const auto now = now_ms();
    entry.created_at = now;
    entry.updated_at = now;
    entry.last_access_at = now;

    std::vector<Candidate> candidates = candidate_entries(text, reps, entry.hash);
    for (const auto& candidate : candidates) {
      const auto& existing = entries_[candidate.index];
      if (hamming_similarity(existing.hash, entry.hash) >= 0.90) {
        merge_entry(candidate.index, entry);
        return serialize_entry(entries_[candidate.index]);
      }
    }

    entries_.push_back(std::move(entry));
    const size_t index = entries_.size() - 1;
    index_entry(index);
    enforce_capacity();
    return serialize_entry(entries_.back());
  }

  std::string query(const std::string& raw_text, size_t top_k) {
    const std::string text = to_lower_ascii(raw_text);
    const auto query_reps = build_representations(text);
    const auto qhash = semantic_hash(text, bit_count_, seed_, &bit_bias_);
    const auto qhyper = prototype_vector(text, hyper_dim_, seed_);
    auto candidates = candidate_entries(text, query_reps, qhash);
    std::vector<Candidate> scored;
    scored.reserve(candidates.size());
    for (const auto& candidate : candidates) {
      const auto& entry = entries_[candidate.index];
      scored.push_back({
          candidate.index,
          score(query_reps, qhash, qhyper, entry),
          hamming_distance(qhash, entry.hash),
      });
    }
    std::sort(scored.begin(), scored.end(), [](const Candidate& a, const Candidate& b) {
      return a.score > b.score;
    });
    if (scored.size() > top_k) scored.resize(top_k);
    if (!scored.empty()) {
      auto& entry = entries_[scored.front().index];
      entry.last_access_at = now_ms();
      entry.access_count += 1;
    }
    return serialize_query(qhash, qhyper, scored);
  }

  void learn(const std::string& raw_text, double reward) {
    const std::string text = to_lower_ascii(raw_text);
    const auto sig = semantic_hash(text, bit_count_, seed_, &bit_bias_);
    const double rate = reward >= 0 ? 0.05 : 0.03;
    for (size_t i = 0; i < bit_count_; ++i) {
      const double bit = (sig[i >> 5] >> (i & 31u)) & 1u ? 1.0 : -1.0;
      bit_bias_[i] += rate * reward * bit;
      bit_bias_[i] = std::max(-4.0, std::min(4.0, bit_bias_[i]));
    }
  }

  std::string snapshot() const {
    std::ostringstream oss;
    oss << "{\"bitCount\":" << bit_count_
        << ",\"bandBits\":" << band_bits_
        << ",\"hyperDim\":" << hyper_dim_
        << ",\"profile\":\"" << (large_profile_ ? "large" : "default") << "\""
        << ",\"size\":" << entries_.size()
        << ",\"buckets\":" << total_buckets()
        << ",\"exactCollisions\":" << exact_collisions()
        << "}";
    return oss.str();
  }

  std::string bucket_stats() const {
    size_t occupied = 0;
    size_t collision_buckets = 0;
    size_t total_assignments = 0;
    size_t max_bucket_size = 0;
    for (const auto& map : band_maps_) {
      for (const auto& kv : map) {
        const size_t size = kv.second.size();
        occupied += 1;
        total_assignments += size;
        if (size > 1) {
          collision_buckets += 1;
        }
        if (size > max_bucket_size) {
          max_bucket_size = size;
        }
      }
    }
    const double avg_bucket_load = occupied == 0 ? 0.0 : static_cast<double>(total_assignments) / static_cast<double>(occupied);
    std::ostringstream oss;
    oss << "{\"occupiedBuckets\":" << occupied
        << ",\"collisionBuckets\":" << collision_buckets
        << ",\"totalAssignments\":" << total_assignments
        << ",\"maxBucketSize\":" << max_bucket_size
        << ",\"avgBucketLoad\":" << avg_bucket_load
        << "}";
    return oss.str();
  }

  std::string entries_json() const {
    std::ostringstream oss;
    oss << "[";
    for (size_t i = 0; i < entries_.size(); ++i) {
      const auto& entry = entries_[i];
      if (i) oss << ",";
      oss << "{\"id\":\"" << json_escape(entry.id)
          << "\",\"text\":\"" << json_escape(entry.text)
          << "\",\"hash\":\"" << hex_words(entry.hash)
          << "\",\"hyper\":\"" << hex_words(entry.hyper)
          << "\",\"payloadJson\":\"" << json_escape(entry.payload_json)
          << "\",\"payloadRepresentations\":{\"tokens\":" << json_array(entry.payload_tokens)
          << ",\"ngrams3\":" << json_array(entry.payload_ngrams3)
          << ",\"ngrams4\":" << json_array(entry.payload_ngrams4)
          << ",\"concepts\":" << json_array(entry.payload_concepts)
          << ",\"negated\":" << (entry.payload_negated ? "true" : "false")
          << "},\"quality\":" << entry.quality
          << ",\"createdAt\":" << entry.created_at
          << ",\"updatedAt\":" << entry.updated_at
          << ",\"lastAccessAt\":" << entry.last_access_at
          << ",\"accessCount\":" << entry.access_count
          << ",\"prototypeCount\":" << entry.prototype_count
          << "}";
    }
    oss << "]";
    return oss.str();
  }

  std::string dump_state() const {
    std::ostringstream oss;
    oss << "{\"snapshot\":" << snapshot()
        << ",\"bucketStats\":" << bucket_stats()
        << ",\"entries\":" << entries_json()
        << "}";
    return oss.str();
  }

  void clear() {
    entries_.clear();
    for (auto& map : band_maps_) {
      map.clear();
    }
    canonical_text_map_.clear();
    text_map_.clear();
    for (auto& map : token_maps_) {
      map.clear();
    }
    for (auto& map : payload_token_maps_) {
      map.clear();
    }
  }

  size_t size() const {
    return entries_.size();
  }

 private:
  size_t bit_count_;
  size_t band_bits_;
  size_t hyper_dim_;
  size_t max_entries_;
  size_t max_candidates_;
  uint32_t seed_;
  size_t band_count_ = 0;
  size_t words_per_band_ = 0;
  bool large_profile_ = false;
  std::vector<double> bit_bias_;
  std::vector<Entry> entries_;
  std::vector<std::unordered_map<std::string, std::vector<size_t>>> band_maps_;
  std::unordered_map<std::string, std::vector<size_t>> text_map_;
  std::unordered_map<std::string, std::vector<size_t>> canonical_text_map_;
  std::vector<std::unordered_map<std::string, std::vector<size_t>>> token_maps_;
  std::vector<std::unordered_map<std::string, std::vector<size_t>>> payload_token_maps_;

  static std::string generate_id(const std::string& text) {
    std::ostringstream oss;
    oss << std::hex << fnv1a32(text, 0x12345678u) << '-' << now_ms();
    return oss.str();
  }

  std::string band_key(const std::vector<uint32_t>& words, size_t band_index) const {
    const size_t start = band_index * words_per_band_;
    std::vector<uint32_t> slice(words.begin() + start, words.begin() + start + words_per_band_);
    return hex_words(slice);
  }

  void index_entry(size_t index) {
    const auto& entry = entries_[index];
    index_text(text_map_, entry.text, index);
    index_text(canonical_text_map_, entry.canonical_text, index);
    index_text(text_map_, entry.payload_json, index);
    index_text(canonical_text_map_, entry.payload_canonical_text, index);
    for (size_t band = 0; band < band_count_; ++band) {
      band_maps_[band][band_key(entry.hash, band)].push_back(index);
    }
    index_terms(token_maps_[0], entry.tokens, index);
    index_terms(token_maps_[1], entry.ngrams3, index);
    index_terms(token_maps_[2], entry.ngrams4, index);
    index_terms(token_maps_[3], entry.concepts, index);
    index_terms(payload_token_maps_[0], entry.payload_tokens, index);
    index_terms(payload_token_maps_[1], entry.payload_ngrams3, index);
    index_terms(payload_token_maps_[2], entry.payload_ngrams4, index);
    index_terms(payload_token_maps_[3], entry.payload_concepts, index);
  }

  void unindex_entry(size_t index) {
    const auto& entry = entries_[index];
    unindex_text(text_map_, entry.text, index);
    unindex_text(canonical_text_map_, entry.canonical_text, index);
    unindex_text(text_map_, entry.payload_json, index);
    unindex_text(canonical_text_map_, entry.payload_canonical_text, index);
    for (size_t band = 0; band < band_count_; ++band) {
      auto key = band_key(entry.hash, band);
      auto it = band_maps_[band].find(key);
      if (it == band_maps_[band].end()) continue;
      auto& vec = it->second;
      vec.erase(std::remove(vec.begin(), vec.end(), index), vec.end());
      if (vec.empty()) band_maps_[band].erase(it);
    }
    unindex_terms(token_maps_[0], entry.tokens, index);
    unindex_terms(token_maps_[1], entry.ngrams3, index);
    unindex_terms(token_maps_[2], entry.ngrams4, index);
    unindex_terms(token_maps_[3], entry.concepts, index);
    unindex_terms(payload_token_maps_[0], entry.payload_tokens, index);
    unindex_terms(payload_token_maps_[1], entry.payload_ngrams3, index);
    unindex_terms(payload_token_maps_[2], entry.payload_ngrams4, index);
    unindex_terms(payload_token_maps_[3], entry.payload_concepts, index);
  }

  std::vector<Candidate> candidate_entries(const std::string& query_text, const Representations& query_reps, const std::vector<uint32_t>& qhash) const {
    std::vector<Candidate> out;
    out.reserve(max_candidates_);
    std::unordered_set<size_t> seen;
    seen.reserve(max_candidates_ * 2);

    auto append_ids = [&](const std::vector<size_t>& ids) {
      for (size_t index : ids) {
        if (index >= entries_.size() || !seen.insert(index).second) continue;
        out.push_back({index, 0.0, 0});
        if (out.size() >= max_candidates_) return true;
      }
      return false;
    };
    if (append_ids(collect_text_candidates(query_text))) return out;
    if (append_ids(collect_text_candidates(query_reps.canonical_text, canonical_text_map_))) return out;
    if (append_ids(collect_band_candidates(qhash, std::max<size_t>(16, max_candidates_ / 2)))) return out;
    if (append_ids(collect_term_candidates(token_maps_[3], query_reps.concepts, 12))) return out;

    if (out.empty()) {
      for (size_t i = 0; i < entries_.size() && out.size() < max_candidates_; ++i) {
        out.push_back({i, 0.0, 0});
      }
    }
    return out;
  }

  double score(const Representations& query_reps, const std::vector<uint32_t>& qhash, const std::vector<uint32_t>& qhyper, const Entry& entry) const {
    const double hash_sim = hamming_similarity(qhash, entry.hash);
    const double hv_sim = hamming_similarity(qhyper, entry.hyper);
    Representations entry_reps;
    entry_reps.canonical_text = entry.canonical_text;
    entry_reps.tokens = entry.tokens;
    entry_reps.ngrams3 = entry.ngrams3;
    entry_reps.ngrams4 = entry.ngrams4;
    entry_reps.concepts = entry.concepts;
    entry_reps.negated = entry.negated;
    const auto sim = representation_similarity(query_reps, entry_reps);
    const auto age_ms = std::max<int64_t>(0, now_ms() - entry.last_access_at);
    const double recency = std::exp(-static_cast<double>(age_ms) / (30.0 * 60.0 * 1000.0));
    const double quality = std::max(0.0, std::min(1.0, entry.quality / 10.0));
    return 0.34 * hash_sim + 0.30 * hv_sim + 0.22 * sim.semantic + 0.10 * recency + 0.04 * quality + 0.02 * sim.negation_match;
  }

  void merge_entry(size_t target_index, const Entry& incoming) {
    unindex_entry(target_index);
    Entry& target = entries_[target_index];
    std::vector<uint32_t> merged_hash(target.hash.size(), 0);
    std::vector<uint32_t> merged_hyper(target.hyper.size(), 0);
    for (size_t i = 0; i < target.hash.size(); ++i) {
      merged_hash[i] = target.hash[i] | incoming.hash[i];
      merged_hyper[i] = target.hyper[i] | incoming.hyper[i];
    }
    target.hash = std::move(merged_hash);
    target.hyper = std::move(merged_hyper);
    target.tokens = merge_strings(target.tokens, incoming.tokens);
    target.ngrams3 = merge_strings(target.ngrams3, incoming.ngrams3);
    target.ngrams4 = merge_strings(target.ngrams4, incoming.ngrams4);
    target.concepts = merge_strings(target.concepts, incoming.concepts);
    target.negated = target.negated || incoming.negated;
    target.payload_tokens = merge_strings(target.payload_tokens, incoming.payload_tokens);
    target.payload_ngrams3 = merge_strings(target.payload_ngrams3, incoming.payload_ngrams3);
    target.payload_ngrams4 = merge_strings(target.payload_ngrams4, incoming.payload_ngrams4);
    target.payload_concepts = merge_strings(target.payload_concepts, incoming.payload_concepts);
    target.payload_negated = target.payload_negated || incoming.payload_negated;
    target.payload_json = merge_payloads(target.payload_json, incoming.payload_json);
    target.quality = std::max(0.0, std::min(10.0, 0.5 * (target.quality + incoming.quality)));
    target.updated_at = now_ms();
    target.prototype_count += 1;
    index_entry(target_index);
  }

  std::string merge_payloads(const std::string& a, const std::string& b) const {
    if (a.empty()) return b;
    if (b.empty()) return a;
    if (a == b) return a;
    return std::string("[") + a + "," + b + "]";
  }

  static void index_terms(std::unordered_map<std::string, std::vector<size_t>>& map, const std::vector<std::string>& terms, size_t index) {
    for (const auto& term : terms) {
      if (term.empty()) continue;
      map[term].push_back(index);
    }
  }

  static void unindex_terms(std::unordered_map<std::string, std::vector<size_t>>& map, const std::vector<std::string>& terms, size_t index) {
    for (const auto& term : terms) {
      if (term.empty()) continue;
      auto it = map.find(term);
      if (it == map.end()) continue;
      auto& vec = it->second;
      vec.erase(std::remove(vec.begin(), vec.end(), index), vec.end());
      if (vec.empty()) map.erase(it);
    }
  }

  static void index_text(std::unordered_map<std::string, std::vector<size_t>>& map, const std::string& text, size_t index) {
    if (text.empty()) return;
    map[text].push_back(index);
  }

  static void unindex_text(std::unordered_map<std::string, std::vector<size_t>>& map, const std::string& text, size_t index) {
    if (text.empty()) return;
    auto it = map.find(text);
    if (it == map.end()) return;
    auto& vec = it->second;
    vec.erase(std::remove(vec.begin(), vec.end(), index), vec.end());
    if (vec.empty()) map.erase(it);
  }

  std::vector<size_t> collect_text_candidates(const std::string& query_text) const {
    return collect_text_candidates(query_text, text_map_);
  }

  std::vector<size_t> collect_text_candidates(const std::string& query_text, const std::unordered_map<std::string, std::vector<size_t>>& map) const {
    std::vector<size_t> out;
    const auto it = map.find(query_text);
    if (it == map.end()) return out;
    for (size_t index : it->second) {
      out.push_back(index);
      if (out.size() >= max_candidates_) break;
    }
    return out;
  }

  std::vector<size_t> collect_band_candidates(const std::vector<uint32_t>& qhash, size_t limit) const {
    std::vector<size_t> out;
    out.reserve(limit);
    for (size_t band = 0; band < band_count_; ++band) {
      const auto key = band_key(qhash, band);
      const auto it = band_maps_[band].find(key);
      if (it == band_maps_[band].end()) continue;
      for (size_t index : it->second) {
        out.push_back(index);
        if (out.size() >= limit) return out;
      }
    }
    return out;
  }

  std::vector<size_t> collect_term_candidates(const std::unordered_map<std::string, std::vector<size_t>>& map, const std::vector<std::string>& terms, size_t limit) const {
    std::vector<size_t> out;
    out.reserve(limit);
    size_t processed = 0;
    for (const auto& term : terms) {
      if (processed++ >= limit) break;
      const auto it = map.find(term);
      if (it == map.end()) continue;
      for (size_t index : it->second) {
        out.push_back(index);
        if (out.size() >= limit) return out;
      }
    }
    return out;
  }

  void enforce_capacity() {
    if (entries_.size() <= max_entries_) return;
    while (entries_.size() > max_entries_) {
      size_t victim = 0;
      double worst = std::numeric_limits<double>::lowest();
      const auto now = now_ms();
      for (size_t i = 0; i < entries_.size(); ++i) {
        const auto& e = entries_[i];
        const double age = static_cast<double>(now - e.last_access_at);
        const double value = -age + e.quality * 100.0;
        if (value > worst) {
          worst = value;
          victim = i;
        }
      }
      unindex_entry(victim);
      entries_.erase(entries_.begin() + static_cast<std::ptrdiff_t>(victim));
    }
  }

  size_t total_buckets() const {
    size_t total = 0;
    for (const auto& map : band_maps_) total += map.size();
    return total;
  }

  size_t exact_collisions() const {
    std::unordered_map<std::string, size_t> counts;
    for (const auto& e : entries_) {
      counts[hex_words(e.hash)] += 1;
    }
    size_t collisions = 0;
    for (const auto& kv : counts) {
      if (kv.second > 1) collisions += kv.second - 1;
    }
    return collisions;
  }

  std::string serialize_entry(const Entry& entry) const {
    std::ostringstream oss;
    oss << "{\"id\":\"" << json_escape(entry.id)
        << "\",\"text\":\"" << json_escape(entry.text)
        << "\",\"representations\":{\"tokens\":" << json_array(entry.tokens)
        << ",\"ngrams3\":" << json_array(entry.ngrams3)
        << ",\"ngrams4\":" << json_array(entry.ngrams4)
        << ",\"concepts\":" << json_array(entry.concepts)
        << ",\"negated\":" << (entry.negated ? "true" : "false")
        << "},\"payloadRepresentations\":{\"tokens\":" << json_array(entry.payload_tokens)
        << ",\"ngrams3\":" << json_array(entry.payload_ngrams3)
        << ",\"ngrams4\":" << json_array(entry.payload_ngrams4)
        << ",\"concepts\":" << json_array(entry.payload_concepts)
        << ",\"negated\":" << (entry.payload_negated ? "true" : "false")
        << "},\"payloadJson\":\"" << json_escape(entry.payload_json)
        << "\",\"quality\":" << entry.quality
        << ",\"prototypeCount\":" << entry.prototype_count
        << "}";
    return oss.str();
  }

  std::string serialize_query(const std::vector<uint32_t>& qhash, const std::vector<uint32_t>& qhyper, const std::vector<Candidate>& candidates) const {
    std::ostringstream oss;
    oss << "{\"confidence\":" << confidence(candidates)
        << ",\"queryHash\":\"" << hex_words(qhash)
        << "\",\"candidates\":[";
    for (size_t i = 0; i < candidates.size(); ++i) {
      const auto& c = candidates[i];
      const auto& e = entries_[c.index];
      if (i) oss << ",";
      oss << "{\"id\":\"" << json_escape(e.id)
          << "\",\"text\":\"" << json_escape(e.text)
          << "\",\"representations\":{\"tokens\":" << json_array(e.tokens)
          << ",\"ngrams3\":" << json_array(e.ngrams3)
          << ",\"ngrams4\":" << json_array(e.ngrams4)
          << ",\"concepts\":" << json_array(e.concepts)
          << ",\"negated\":" << (e.negated ? "true" : "false")
          << "},\"payloadRepresentations\":{\"tokens\":" << json_array(e.payload_tokens)
          << ",\"ngrams3\":" << json_array(e.payload_ngrams3)
          << ",\"ngrams4\":" << json_array(e.payload_ngrams4)
          << ",\"concepts\":" << json_array(e.payload_concepts)
          << ",\"negated\":" << (e.payload_negated ? "true" : "false")
          << "},\"payloadJson\":\"" << json_escape(e.payload_json)
          << "\",\"score\":" << c.score
          << ",\"hashDistance\":" << c.hash_distance
          << ",\"quality\":" << e.quality
          << "}";
    }
    oss << "]}";
    return oss.str();
  }

  double confidence(const std::vector<Candidate>& candidates) const {
    if (candidates.empty()) return 0.0;
    if (candidates.size() == 1) return std::max(0.0, std::min(1.0, candidates[0].score));
    const double best = candidates[0].score;
    const double second = candidates[1].score;
    return std::max(0.0, std::min(1.0, 0.5 * best + 0.5 * (best - second)));
  }
};

static napi_ref constructor_ref;

static void throw_error(napi_env env, const std::string& message) {
  napi_throw_error(env, nullptr, message.c_str());
}

static bool get_double_arg(napi_env env, napi_callback_info info, size_t index, double* out) {
  size_t argc = 6;
  napi_value argv[6];
  napi_value this_arg;
  void* data;
  napi_get_cb_info(env, info, &argc, argv, &this_arg, &data);
  if (index >= argc) return false;
  return napi_get_value_double(env, argv[index], out) == napi_ok;
}

static CHLEngine* unwrap_engine(napi_env env, napi_value this_arg) {
  CHLEngine* engine = nullptr;
  napi_unwrap(env, this_arg, reinterpret_cast<void**>(&engine));
  return engine;
}

static napi_value engine_constructor(napi_env env, napi_callback_info info) {
  size_t argc = 7;
  napi_value argv[7];
  napi_value this_arg;
  napi_get_cb_info(env, info, &argc, argv, &this_arg, nullptr);
  if (argc < 7) {
    throw_error(env, "CHLEngine expects 7 constructor arguments");
    return nullptr;
  }
  double args[7];
  for (size_t i = 0; i < 7; ++i) {
    if (napi_get_value_double(env, argv[i], &args[i]) != napi_ok) {
      throw_error(env, "Invalid constructor argument");
      return nullptr;
    }
  }
  auto* engine = new CHLEngine(
      static_cast<size_t>(args[0]),
      static_cast<size_t>(args[1]),
      static_cast<size_t>(args[2]),
      static_cast<size_t>(args[3]),
      static_cast<size_t>(args[4]),
      static_cast<uint32_t>(args[5]),
      args[6] != 0.0);
  napi_wrap(env, this_arg, engine, [](napi_env env, void* data, void* hint) {
    delete reinterpret_cast<CHLEngine*>(data);
  }, nullptr, nullptr);
  return this_arg;
}

static std::string value_to_utf8(napi_env env, napi_value value) {
  size_t len = 0;
  napi_get_value_string_utf8(env, value, nullptr, 0, &len);
  std::string out(len, '\0');
  napi_get_value_string_utf8(env, value, out.data(), len + 1, &len);
  out.resize(len);
  return out;
}

static napi_value method_remember(napi_env env, napi_callback_info info) {
  size_t argc = 3;
  napi_value argv[3];
  napi_value this_arg;
  napi_get_cb_info(env, info, &argc, argv, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine || argc < 3) {
    throw_error(env, "remember(text, payloadJson, quality) expected");
    return nullptr;
  }
  std::string text = value_to_utf8(env, argv[0]);
  std::string payload = value_to_utf8(env, argv[1]);
  double quality = 1.0;
  napi_get_value_double(env, argv[2], &quality);
  std::string result = engine->remember(text, payload, quality);
  napi_value out;
  napi_create_string_utf8(env, result.c_str(), result.size(), &out);
  return out;
}

static napi_value method_query(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_value this_arg;
  napi_get_cb_info(env, info, &argc, argv, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine || argc < 2) {
    throw_error(env, "query(text, topK) expected");
    return nullptr;
  }
  std::string text = value_to_utf8(env, argv[0]);
  double topk_d = 5.0;
  napi_get_value_double(env, argv[1], &topk_d);
  std::string result = engine->query(text, static_cast<size_t>(topk_d));
  napi_value out;
  napi_create_string_utf8(env, result.c_str(), result.size(), &out);
  return out;
}

static napi_value method_learn(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_value this_arg;
  napi_get_cb_info(env, info, &argc, argv, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine || argc < 2) {
    throw_error(env, "learn(text, reward) expected");
    return nullptr;
  }
  std::string text = value_to_utf8(env, argv[0]);
  double reward = 0.0;
  napi_get_value_double(env, argv[1], &reward);
  engine->learn(text, reward);
  napi_value out;
  napi_get_undefined(env, &out);
  return out;
}

static napi_value method_snapshot(napi_env env, napi_callback_info info) {
  napi_value this_arg;
  napi_get_cb_info(env, info, nullptr, nullptr, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine) {
    throw_error(env, "invalid engine");
    return nullptr;
  }
  std::string result = engine->snapshot();
  napi_value out;
  napi_create_string_utf8(env, result.c_str(), result.size(), &out);
  return out;
}

static napi_value method_clear(napi_env env, napi_callback_info info) {
  napi_value this_arg;
  napi_get_cb_info(env, info, nullptr, nullptr, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine) {
    throw_error(env, "invalid engine");
    return nullptr;
  }
  engine->clear();
  napi_value out;
  napi_get_undefined(env, &out);
  return out;
}

static napi_value method_bucket_stats(napi_env env, napi_callback_info info) {
  napi_value this_arg;
  napi_get_cb_info(env, info, nullptr, nullptr, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine) {
    throw_error(env, "invalid engine");
    return nullptr;
  }
  std::string result = engine->bucket_stats();
  napi_value out;
  napi_create_string_utf8(env, result.c_str(), result.size(), &out);
  return out;
}

static napi_value method_entries(napi_env env, napi_callback_info info) {
  napi_value this_arg;
  napi_get_cb_info(env, info, nullptr, nullptr, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine) {
    throw_error(env, "invalid engine");
    return nullptr;
  }
  std::string result = engine->entries_json();
  napi_value out;
  napi_create_string_utf8(env, result.c_str(), result.size(), &out);
  return out;
}

static napi_value method_dump_state(napi_env env, napi_callback_info info) {
  napi_value this_arg;
  napi_get_cb_info(env, info, nullptr, nullptr, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine) {
    throw_error(env, "invalid engine");
    return nullptr;
  }
  std::string result = engine->dump_state();
  napi_value out;
  napi_create_string_utf8(env, result.c_str(), result.size(), &out);
  return out;
}

static napi_value method_size(napi_env env, napi_callback_info info) {
  napi_value this_arg;
  napi_get_cb_info(env, info, nullptr, nullptr, &this_arg, nullptr);
  CHLEngine* engine = unwrap_engine(env, this_arg);
  if (!engine) {
    throw_error(env, "invalid engine");
    return nullptr;
  }
  napi_value out;
  napi_create_uint32(env, static_cast<uint32_t>(engine->size()), &out);
  return out;
}

static napi_value init(napi_env env, napi_value exports) {
  napi_property_descriptor props[] = {
      {"remember", nullptr, method_remember, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"query", nullptr, method_query, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"learn", nullptr, method_learn, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"snapshot", nullptr, method_snapshot, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"bucketStats", nullptr, method_bucket_stats, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"entries", nullptr, method_entries, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"dumpState", nullptr, method_dump_state, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"clear", nullptr, method_clear, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"size", nullptr, method_size, nullptr, nullptr, nullptr, napi_default, nullptr},
  };

  napi_value cons;
  napi_define_class(env, "CHLEngine", NAPI_AUTO_LENGTH, engine_constructor, nullptr, std::size(props), props, &cons);
  napi_create_reference(env, cons, 1, &constructor_ref);
  napi_set_named_property(env, exports, "CHLEngine", cons);
  return exports;
}

}  // namespace

NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
