#include <node_api.h>
#include "hyperembed_engine.h"
#include <string>
#include <cstring>
#include <vector>
#include <utility>

namespace {

hyperembed::HyperEmbedEngine* engine = nullptr;

// Helper: get string from JS value
std::string value_to_string(napi_env env, napi_value val) {
  size_t len;
  napi_get_value_string_utf8(env, val, nullptr, 0, &len);
  std::string result(len, '\0');
  napi_get_value_string_utf8(env, val, result.data(), len + 1, &len);
  return result;
}

// Helper: create JS string
napi_value string_to_value(napi_env env, const std::string& str) {
  napi_value result;
  napi_create_string_utf8(env, str.c_str(), str.size(), &result);
  return result;
}

// Helper: create JS number
napi_value number_to_value(napi_env env, double num) {
  napi_value result;
  napi_create_double(env, num, &result);
  return result;
}

// Helper: create JS object
napi_value create_object(napi_env env) {
  napi_value obj;
  napi_create_object(env, &obj);
  return obj;
}

// ─── learn(text) ──────────────────────────────────────────
napi_value method_learn(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "learn(text) expected");
    return nullptr;
  }
  
  std::string text = value_to_string(env, argv[0]);
  engine->learn(text);
  
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

// ─── encode(text) → array of 313 uint32 ───────────────────
napi_value method_encode(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "encode(text) expected");
    return nullptr;
  }
  
  std::string text = value_to_string(env, argv[0]);
  hyperembed::Vector vec;
  engine->encode(text, vec);
  
  napi_value arr;
  napi_create_array_with_length(env, hyperembed::VEC_WORDS, &arr);
  for (size_t i = 0; i < hyperembed::VEC_WORDS; ++i) {
    napi_value num;
    napi_create_uint32(env, vec[i], &num);
    napi_set_element(env, arr, i, num);
  }
  
  return arr;
}

// ─── similarity(textA, textB) → double ───────────────────
napi_value method_similarity(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 2 || !engine) {
    napi_throw_error(env, nullptr, "similarity(a, b) expected");
    return nullptr;
  }
  
  std::string a = value_to_string(env, argv[0]);
  std::string b = value_to_string(env, argv[1]);
  double sim = engine->textSimilarity(a, b);
  
  return number_to_value(env, sim);
}

// ─── index(id, text) ─────────────────────────────────────
napi_value method_index(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 2 || !engine) {
    napi_throw_error(env, nullptr, "index(id, text) expected");
    return nullptr;
  }
  
  std::string id = value_to_string(env, argv[0]);
  std::string text = value_to_string(env, argv[1]);
  engine->indexDocument(id, text);
  
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

// ─── indexBatch([{id, text}, ...]) ───────────────────────
napi_value method_index_batch(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "indexBatch(items) expected");
    return nullptr;
  }

  bool is_array = false;
  napi_is_array(env, argv[0], &is_array);
  if (!is_array) {
    napi_throw_error(env, nullptr, "indexBatch(items) expects an array");
    return nullptr;
  }

  uint32_t len = 0;
  napi_get_array_length(env, argv[0], &len);
  std::vector<std::pair<std::string, std::string>> docs;
  docs.reserve(len);

  for (uint32_t i = 0; i < len; ++i) {
    napi_value item;
    napi_get_element(env, argv[0], i, &item);

    napi_value idv, textv;
    napi_get_named_property(env, item, "id", &idv);
    napi_get_named_property(env, item, "text", &textv);
    docs.emplace_back(value_to_string(env, idv), value_to_string(env, textv));
  }

  engine->indexBatch(docs);

  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

// ─── clearIndex() ────────────────────────────────────────
napi_value method_clear_index(napi_env env, napi_callback_info info) {
  if (!engine) {
    napi_throw_error(env, nullptr, "engine not initialized");
    return nullptr;
  }
  engine->clearIndex();
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

// ─── query(text, topK) → array of {id, text, similarity} ─
napi_value method_query(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "query(text, topK) expected");
    return nullptr;
  }
  
  std::string query = value_to_string(env, argv[0]);
  int64_t top_k = 5;
  if (argc >= 2) napi_get_value_int64(env, argv[1], &top_k);
  
  auto candidates = engine->query(query, (size_t)top_k);
  
  napi_value arr;
  napi_create_array_with_length(env, candidates.size(), &arr);
  
  for (size_t i = 0; i < candidates.size(); ++i) {
    napi_value obj = create_object(env);
    
    napi_set_named_property(env, obj, "id", string_to_value(env, candidates[i].id));
    napi_set_named_property(env, obj, "text", string_to_value(env, candidates[i].text));
    napi_set_named_property(env, obj, "similarity", number_to_value(env, candidates[i].similarity));
    
    napi_set_element(env, arr, i, obj);
  }
  
  return arr;
}

// ─── nearestNeighbors(text, k) ────────────────────────────
napi_value method_neighbors(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "neighbors(text, k) expected");
    return nullptr;
  }
  
  std::string text = value_to_string(env, argv[0]);
  int64_t k = 5;
  if (argc >= 2) napi_get_value_int64(env, argv[1], &k);
  
  hyperembed::Vector vec;
  engine->encode(text, vec);
  auto neighbors = engine->nearestNeighbors(vec, (size_t)k);
  
  napi_value arr;
  napi_create_array_with_length(env, neighbors.size(), &arr);
  for (size_t i = 0; i < neighbors.size(); ++i) {
    napi_set_element(env, arr, i, string_to_value(env, neighbors[i]));
  }
  
  return arr;
}

// ─── save(path) ───────────────────────────────────────────
napi_value method_save(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "save(path) expected");
    return nullptr;
  }
  
  std::string path = value_to_string(env, argv[0]);
  bool ok = engine->save(path);
  
  napi_value result;
  napi_get_boolean(env, ok, &result);
  return result;
}

// ─── load(path) ───────────────────────────────────────────
napi_value method_load(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value argv[1];
  napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
  
  if (argc < 1 || !engine) {
    napi_throw_error(env, nullptr, "load(path) expected");
    return nullptr;
  }
  
  std::string path = value_to_string(env, argv[0]);
  bool ok = engine->load(path);
  
  napi_value result;
  napi_get_boolean(env, ok, &result);
  return result;
}

// ─── snapshot() ───────────────────────────────────────────
napi_value method_snapshot(napi_env env, napi_callback_info info) {
  if (!engine) {
    napi_throw_error(env, nullptr, "engine not initialized");
    return nullptr;
  }
  
  napi_value obj = create_object(env);
  napi_set_named_property(env, obj, "vocabSize", number_to_value(env, (double)engine->vocabSize()));
  napi_set_named_property(env, obj, "docCount", number_to_value(env, (double)engine->docCount()));
  napi_set_named_property(env, obj, "coocPairs", number_to_value(env, (double)engine->coocPairs()));
  
  return obj;
}

// ─── Constructor ──────────────────────────────────────────
napi_value constructor(napi_env env, napi_callback_info info) {
  if (engine) delete engine;
  engine = new hyperembed::HyperEmbedEngine();
  
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

// ─── Init ─────────────────────────────────────────────────
napi_value init(napi_env env, napi_value exports) {
  napi_property_descriptor props[] = {
    {"learn", nullptr, method_learn, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"encode", nullptr, method_encode, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"similarity", nullptr, method_similarity, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"index", nullptr, method_index, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"indexBatch", nullptr, method_index_batch, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"clearIndex", nullptr, method_clear_index, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"query", nullptr, method_query, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"neighbors", nullptr, method_neighbors, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"save", nullptr, method_save, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"load", nullptr, method_load, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"snapshot", nullptr, method_snapshot, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  
  napi_value cons;
  napi_define_class(env, "NativeHyperEmbed", NAPI_AUTO_LENGTH, constructor, nullptr, 
                     sizeof(props) / sizeof(props[0]), props, &cons);
  napi_set_named_property(env, exports, "NativeHyperEmbed", cons);
  
  return exports;
}

NAPI_MODULE(NODE_GYP_MODULE_NAME, init)

} // namespace
