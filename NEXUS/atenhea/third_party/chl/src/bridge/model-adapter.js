/**
 * ModelAdapter — Capa de abstracción sobre proveedores de LLM.
 *
 * Unifica OpenAI, Anthropic, Ollama (local), OpenRouter, Groq, etc.
 * bajo una misma interfaz. El bridge no necesita saber qué modelo
 * hay detrás.
 *
 * Soporta:
 * - OpenAI (GPT-4, GPT-5, o3, o4-mini, etc.)
 * - Anthropic (Claude Opus, Sonnet, Haiku)
 * - Ollama (cualquier modelo local: llama3, mistral, qwen, etc.)
 * - OpenRouter (proxy unificado a cientos de modelos)
 * - Generic OpenAI-compatible (vLLM, LiteLLM, etc.)
 *
 * Cada llamada incluye:
 * - system prompt (contexto CHL)
 * - tools (herramientas CHL que el modelo puede invocar)
 * - mensajes del historial de sesión
 */

const CHL_TOOLS_FOR_LLM = [
  {
    type: "function",
    function: {
      name: "chl_remember",
      description: "Guarda un hecho, preferencia, decisión o contexto en la memoria persistente CHL.",
      parameters: {
        type: "object",
        properties: {
          input: { type: "string", description: "El texto a recordar." },
          payload: { type: "string", description: "Datos estructurados opcionales (JSON)." },
          metadata: { type: "object", description: "Metadatos ligeros (tags, source, etc.)." },
        },
        required: ["input"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "chl_recall",
      description: "Recupera memorias relacionadas con una query. Puede filtrar por tipo de memoria, intención y ventana temporal.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Texto de búsqueda." },
          topK: { type: "number", description: "Número máximo de resultados (default 5)." },
          memoryType: { type: "string", description: "Restringir a un tipo: ephemeral, short_term, medium_term, long_term, user_profile, self_profile, knowledge, episodic." },
          excludeTypes: { type: "array", items: { type: "string" }, description: "Tipos a excluir." },
          intent: { type: "string", description: "Intención de la query: self_reflection, user_recall, personal_preference, fact_lookup, procedural, general_chat." },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "chl_remember_typed",
      description: "Guarda un hecho con un tipo de memoria explícito (útil para perfiles de usuario, personalidad de la IA, conocimiento o hechos temporales).",
      parameters: {
        type: "object",
        properties: {
          input: { type: "string", description: "El texto a recordar." },
          memoryType: { type: "string", description: "Tipo: ephemeral, short_term, medium_term, long_term, user_profile, self_profile, knowledge, episodic." },
          payload: { type: "string", description: "Datos estructurados opcionales (JSON)." },
          source: { type: "string", description: "Origen: user, ai, ingest, etc." },
          ttlSeconds: { type: "number", description: "Tiempo de vida en segundos." },
        },
        required: ["input", "memoryType"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "chl_recall_personalized",
      description: "Recupera memorias priorizando el perfil del usuario y la personalidad de la IA. Usa intención auto-detectada.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Texto de búsqueda." },
          topK: { type: "number", description: "Número máximo de resultados (default 5)." },
          intent: { type: "string", description: "Sobrescribir intención detectada." },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "chl_learn",
      description: "Refuerza (reward > 0), suprime (reward < 0) o da feedback neutro (reward = 0) sobre una asociación en memoria.",
      parameters: {
        type: "object",
        properties: {
          input: { type: "string", description: "El texto o concepto sobre el que se aprende." },
          reward: { type: "number", description: "Valor entre -1 y 1. Positivo = reforzar, negativo = suprimir." },
        },
        required: ["input", "reward"],
      },
    },
  },
];

/**
 * Crea un adaptador para el proveedor especificado.
 *
 * @param {"openai"|"anthropic"|"ollama"|"openrouter"|"openai-compat"} provider
 * @param {Object} opts
 * @param {string} opts.apiKey      - API key
 * @param {string} opts.baseURL     - URL base (para Ollama, OpenRouter, compat)
 * @param {string} opts.model       - nombre del modelo (defaults según provider)
 */
function createAdapter(provider = "openai", opts = {}) {
  switch (provider) {
    case "openai":
      return new OpenAIAdapter(opts);
    case "anthropic":
      return new AnthropicAdapter(opts);
    case "ollama":
      return new OllamaAdapter(opts);
    case "openrouter":
      return new OpenRouterAdapter(opts);
    case "openai-compat":
      return new OpenAICompatAdapter(opts);
    default:
      throw new Error(`Provider no soportado: ${provider}. Usa: openai, anthropic, ollama, openrouter, openai-compat`);
  }
}

// ─── OpenAI ───────────────────────────────────────────────

class OpenAIAdapter {
  constructor(opts = {}) {
    this.apiKey = opts.apiKey || process.env.OPENAI_API_KEY || "";
    this.baseURL = opts.baseURL || "https://api.openai.com/v1";
    this.model = opts.model || "gpt-4o";
    this.maxTokens = opts.maxTokens || 4096;
    this.temperature = opts.temperature ?? 0.3;
  }

  async chat(messages, tools = CHL_TOOLS_FOR_LLM) {
    const body = {
      model: this.model,
      messages,
      max_tokens: this.maxTokens,
      temperature: this.temperature,
    };
    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = "auto";
    }

    const res = await fetch(`${this.baseURL}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`OpenAI error ${res.status}: ${err}`);
    }

    const data = await res.json();
    return {
      content: data.choices?.[0]?.message?.content || "",
      toolCalls: data.choices?.[0]?.message?.tool_calls || [],
      usage: data.usage || {},
      model: data.model || this.model,
    };
  }
}

// ─── Anthropic ────────────────────────────────────────────

class AnthropicAdapter {
  constructor(opts = {}) {
    this.apiKey = opts.apiKey || process.env.ANTHROPIC_API_KEY || "";
    this.baseURL = opts.baseURL || "https://api.anthropic.com/v1";
    this.model = opts.model || "claude-sonnet-4-20250514";
    this.maxTokens = opts.maxTokens || 4096;
    this.temperature = opts.temperature ?? 0.3;
  }

  async chat(messages, tools = CHL_TOOLS_FOR_LLM) {
    // Anthropic usa system separado
    const systemMsg = messages.find(m => m.role === "system");
    const chatMsgs = messages.filter(m => m.role !== "system");

    // Convertir tools de OpenAI format a Anthropic format
    const anthropicTools = tools.map(t => ({
      name: t.function.name,
      description: t.function.description,
      input_schema: t.function.parameters,
    }));

    const body = {
      model: this.model,
      max_tokens: this.maxTokens,
      temperature: this.temperature,
      system: systemMsg?.content || "",
      messages: chatMsgs.map(m => ({
        role: m.role === "assistant" ? "assistant" : "user",
        content: m.content,
      })),
      tools: anthropicTools,
    };

    const res = await fetch(`${this.baseURL}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": this.apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Anthropic error ${res.status}: ${err}`);
    }

    const data = await res.json();
    const toolUseBlocks = data.content?.filter(c => c.type === "tool_use") || [];
    const textBlocks = data.content?.filter(c => c.type === "text") || [];

    return {
      content: textBlocks.map(b => b.text).join("\n"),
      toolCalls: toolUseBlocks.map(b => ({
        id: b.id,
        function: { name: b.name, arguments: JSON.stringify(b.input) },
      })),
      usage: data.usage || {},
      model: data.model || this.model,
    };
  }
}

// ─── Ollama (local) ───────────────────────────────────────

class OllamaAdapter {
  constructor(opts = {}) {
    this.baseURL = opts.baseURL || process.env.OLLAMA_BASE_URL || "http://localhost:11434";
    this.model = opts.model || "llama3";
    this.maxTokens = opts.maxTokens || 2048;
    this.temperature = opts.temperature ?? 0.3;
  }

  async chat(messages, tools = CHL_TOOLS_FOR_LLM) {
    const body = {
      model: this.model,
      messages,
      stream: false,
      options: {
        num_predict: this.maxTokens,
        temperature: this.temperature,
      },
    };

    // Ollama soporta tools en versiones recientes
    if (tools && tools.length > 0) {
      body.tools = tools;
    }

    const res = await fetch(`${this.baseURL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Ollama error ${res.status}: ${err}`);
    }

    const data = await res.json();
    return {
      content: data.message?.content || "",
      toolCalls: data.message?.tool_calls || [],
      usage: {
        prompt_tokens: data.prompt_eval_count || 0,
        completion_tokens: data.eval_count || 0,
      },
      model: data.model || this.model,
    };
  }
}

// ─── OpenRouter ───────────────────────────────────────────

class OpenRouterAdapter {
  constructor(opts = {}) {
    this.apiKey = opts.apiKey || process.env.OPENROUTER_API_KEY || "";
    this.baseURL = "https://openrouter.ai/api/v1";
    this.model = opts.model || "openai/gpt-4o";
    this.maxTokens = opts.maxTokens || 4096;
    this.temperature = opts.temperature ?? 0.3;
  }

  async chat(messages, tools = CHL_TOOLS_FOR_LLM) {
    const body = {
      model: this.model,
      messages,
      max_tokens: this.maxTokens,
      temperature: this.temperature,
    };
    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = "auto";
    }

    const res = await fetch(`${this.baseURL}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
        "HTTP-Referer": "https://github.com/chl-memory",
        "X-Title": "CHL Memory Bridge",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`OpenRouter error ${res.status}: ${err}`);
    }

    const data = await res.json();
    return {
      content: data.choices?.[0]?.message?.content || "",
      toolCalls: data.choices?.[0]?.message?.tool_calls || [],
      usage: data.usage || {},
      model: data.model || this.model,
    };
  }
}

// ─── OpenAI-compatible (vLLM, LiteLLM, LocalAI, etc.) ────

class OpenAICompatAdapter {
  constructor(opts = {}) {
    this.apiKey = opts.apiKey || process.env.OPENAI_COMPAT_API_KEY || "not-needed";
    this.baseURL = opts.baseURL || process.env.OPENAI_COMPAT_BASE_URL || "http://localhost:8000/v1";
    this.model = opts.model || "default";
    this.maxTokens = opts.maxTokens || 4096;
    this.temperature = opts.temperature ?? 0.3;
  }

  async chat(messages, tools = CHL_TOOLS_FOR_LLM) {
    const body = {
      model: this.model,
      messages,
      max_tokens: this.maxTokens,
      temperature: this.temperature,
    };
    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = "auto";
    }

    const res = await fetch(`${this.baseURL}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(this.apiKey !== "not-needed" ? { Authorization: `Bearer ${this.apiKey}` } : {}),
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(`OpenAI-compat error ${res.status}: ${err}`);
    }

    const data = await res.json();
    return {
      content: data.choices?.[0]?.message?.content || "",
      toolCalls: data.choices?.[0]?.message?.tool_calls || [],
      usage: data.usage || {},
      model: data.model || this.model,
    };
  }
}

// Helper functions for Ollama‑compatible shim
function getModelTags() {
  // Use the model name from CHL_MODEL (used by `serve:ollama`) or default
  const tag = process.env.CHL_MODEL || 'chl-episodic-agent-memory';
  return [tag];
}

/**
 * Handles Ollama /api/generate requests by delegating to the CHL bridge.
 * Expects a payload with at least { model, prompt }.
 */
async function handleOllamaGenerate(body) {
  const { model, prompt } = body;
  // Import bridge lazily to avoid circular dependency issues
  const { createBridge } = require('./bridge');
  const bridge = createBridge({ provider: 'ollama', model });
  const result = await bridge.turn(prompt);
  await bridge.close();
  
  return {
    model: model || 'chl-episodic-agent-memory',
    created_at: new Date().toISOString(),
    response: result.response,
    done: true,
  };
}

/**
 * Handles Ollama /api/chat requests. Expects a payload with a `messages` array.
 * The last user message is sent to the bridge; the response is wrapped in the
 * Ollama response shape.
 */
async function handleOllamaChat(body) {
  const { model, messages } = body;
  const userMsg = messages?.reverse().find(m => m.role === 'user');
  const prompt = userMsg?.content || '';
  const { createBridge } = require('./bridge');
  const bridge = createBridge({ provider: 'ollama', model });
  const result = await bridge.turn(prompt);
  await bridge.close();
  
  return {
    model: model || 'chl-episodic-agent-memory',
    created_at: new Date().toISOString(),
    response: result.response,
    done: true,
  };
}

module.exports = {
  createAdapter,
  CHL_TOOLS_FOR_LLM,
  OpenAIAdapter,
  AnthropicAdapter,
  OllamaAdapter,
  OpenRouterAdapter,
  OpenAICompatAdapter,
  // Ollama shim helpers
  getModelTags,
  handleOllamaGenerate,
  handleOllamaChat,
};
