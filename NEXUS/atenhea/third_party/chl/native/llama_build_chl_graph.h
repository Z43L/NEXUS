// native/llama_build_chl_graph.h
#pragma once
#include "../llama.cpp/include/llama.h"
#include "hyperembed_engine.h"

struct llama_chl_model {
    struct llama_model * base_model;
    
    // Tensores de las capas intermedias entrenadas
    struct ggml_tensor * tok_embeddings; // Embeddings base de los tokens
    struct ggml_tensor * W_chl;          // Dimensión: [d_model, d_model]
    struct ggml_tensor * W_reason;       // Dimensión: [d_model, d_model]
};

struct llama_chl_context {
    struct llama_context * base_ctx;
    hyperembed::HyperEmbedEngine * chl_engine; // Motor HDC de 10,000 bits
    
    // Buffer compartido (Memoria Unificada para Mac)
    float * chl_cpu_buffer; 
};