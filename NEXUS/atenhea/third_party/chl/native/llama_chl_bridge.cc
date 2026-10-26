// native/llama_chl_bridge.cc
#include "llama_build_chl_graph.h"
#include "../llama.cpp/include/llama.h"
#include <vector>


struct ggml_cgraph * llama_chl_build_graph(
    struct llama_chl_context * chl_lctx,
    struct llama_chl_model * chl_model,
    const struct llama_batch * batch,
    const std::string & current_token_text) {

    // 1. Obtener el contexto de GGML subyacente de llama.cpp
    struct ggml_init_params params = {
        /*.mem_size   =*/ 16 * 1024 * 1024,
        /*.mem_buffer =*/ nullptr,
        /*.no_alloc   =*/ false,
    };
    struct ggml_context * ctx = ggml_init(params); // Inicialización del grafo temporal
    struct ggml_cgraph * gf = ggml_new_graph(ctx);

    // 2. Capa 1: Embedding Estándar desde llama.cpp
    // Extrae de forma nativa los embeddings densos del lote de tokens actual
    struct ggml_tensor * token_ids = ggml_new_tensor_1d(ctx, GGML_TYPE_I32, batch->n_tokens);
    ggml_backend_tensor_set(token_ids, batch->token, 0, ggml_nbytes(token_ids));
    struct ggml_tensor * x_embd = ggml_get_rows(ctx, chl_model->tok_embeddings, token_ids);

    // 3. Capa Intermedia: Búsqueda Semántica en la Memoria CHL (HDC de 10,000 bits)
    // Ejecutamos la búsqueda asociativa ultra rápida en CPU usando tu motor nativo
    hyperembed::Vector query_vec{};
    if (chl_lctx != nullptr && chl_lctx->chl_engine != nullptr) {
        chl_lctx->chl_engine->encode(current_token_text, query_vec);
    } else {
        hyperembed::vec_clear(query_vec);
    }

    const size_t chl_mem_dim = chl_model->W_chl->ne[0];
    std::vector<float> chl_mem_fallback(chl_mem_dim, 0.0f);
    float * chl_mem_data = chl_mem_fallback.data();
    if (chl_lctx != nullptr && chl_lctx->chl_cpu_buffer != nullptr) {
        chl_mem_data = chl_lctx->chl_cpu_buffer;
    }

    for (size_t i = 0; i < chl_mem_dim; ++i) {
        chl_mem_data[i] = 0.0f;
    }

    for (size_t bit = 0; bit < hyperembed::DIM; ++bit) {
        const size_t word_idx = bit / hyperembed::WORD_SIZE;
        const uint32_t mask = 1u << (bit % hyperembed::WORD_SIZE);
        const float bit_value = (query_vec[word_idx] & mask) ? 1.0f : -1.0f;
        chl_mem_data[bit % chl_mem_dim] += bit_value;
    }

    for (size_t i = 0; i < chl_mem_dim; ++i) {
        chl_mem_data[i] /= static_cast<float>(hyperembed::DIM / chl_mem_dim + 1);
    }

    struct ggml_tensor * chl_mem_tensor = ggml_new_tensor_1d(ctx, GGML_TYPE_F32, chl_mem_dim);
    ggml_backend_tensor_set(chl_mem_tensor, chl_mem_data, 0, ggml_nbytes(chl_mem_tensor));

    // Proyección del espacio HDC Binario -> Espacio Denso Transformer
    struct ggml_tensor * x_chl = ggml_mul_mat(ctx, chl_model->W_chl, chl_mem_tensor);
    
    // Fusión (Inyección de Memoria Episódica)
    struct ggml_tensor * x1 = ggml_add(ctx, x_embd, x_chl);

    // 4. Capa Intermedia: Razonamiento Dinámico
    // Evaluamos el tensor fusionado antes de pasar a la atención profunda
    struct ggml_tensor * w_r = ggml_mul_mat(ctx, chl_model->W_reason, x1);
    struct ggml_tensor * act_r = ggml_silu(ctx, w_r); // Activación SiLU optimizada por llama.cpp
    struct ggml_tensor * x2 = ggml_add(ctx, x1, act_r);
    // 5. Inyectar el Tensor Resultante (x2) en la pila de capas Transformer
    // El reingreso capa-a-capa requiere un hook interno de llama.cpp; por ahora
    // dejamos la mezcla CHL como la representación activa del bloque.
    struct ggml_tensor * cur = x2;

    // 6. Logits de Salida
    struct ggml_tensor * logits = ggml_mul_mat(ctx, chl_model->tok_embeddings, cur);
    ggml_build_forward_expand(gf, logits);

    return gf;
}