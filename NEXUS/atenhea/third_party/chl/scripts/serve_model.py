#!/usr/bin/env python3
"""
CHL Inference Engine & OpenAI API Server
Loads the fine-tuned model checkpoint (Qwen 3B + LoRA + CHL Layer)
and exposes an OpenAI-compatible API or launches a CLI chat.

Usage:
  # To run interactive terminal chat:
  python scripts/serve_model.py --checkpoint chkpt/best --chat
  
  # To run OpenAI API Server:
  python scripts/serve_model.py --checkpoint chkpt/best --serve --port 3040
"""

import os
import sys
import json
import shutil
import argparse
import time
import warnings
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

# Optimizacion de threads y advertencias en entornos Mac/CPU
NUM_PHYSICAL_CORES = os.cpu_count() or 4
torch.set_num_threads(min(10, NUM_PHYSICAL_CORES))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*torch_dtype.*deprecated.*")
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

# =====================================================================
# 1. Model Definitions (sincronizadas con Colab)
# =====================================================================

class ShadowMemoryIndex:
    def __init__(self, mem_slots, mem_dim, d_model, device="cpu", dtype=torch.bfloat16):
        self.mem_slots = mem_slots
        self.mem_dim = mem_dim
        self.d_model = d_model
        self.device = device
        self.ptr = 0
        self.dtype = dtype
        self.keys = torch.zeros(mem_slots, mem_dim, device=device, dtype=dtype)
        self.vals = torch.zeros(mem_slots, d_model, device=device, dtype=dtype)
        self.age = torch.zeros(mem_slots, device=device, dtype=dtype)

    def query(self, q, top_k=5):
        q_norm = F.normalize(q, p=2, dim=-1)
        k_norm = F.normalize(self.keys, p=2, dim=-1)
        # Busqueda aproximada por top-k para reducir carga computacional
        scores = torch.einsum("btd,md->btm", q_norm, k_norm)
        # top_k eficiente sobre slots de memoria
        tk = min(top_k, self.mem_slots)
        top_scores, top_idx = torch.topk(scores, tk, dim=-1)
        weights = F.softmax(top_scores / 0.5, dim=-1)
        # Recuperar solo los valores top-k y combinar
        selected_vals = self.vals[top_idx]  # B, T, tk, D
        mem_context = torch.einsum("btk,btkd->btd", weights, selected_vals)
        return mem_context, weights

    def write(self, key, val):
        slot = self.ptr % self.mem_slots
        self.keys[slot] = key.detach()
        self.vals[slot] = val.detach()
        self.age[slot] = 0.0
        self.ptr += 1

    def to(self, device):
        self.device = device
        self.keys = self.keys.to(device)
        self.vals = self.vals.to(device)
        self.age = self.age.to(device)
        return self

class CHLReActLayer(nn.Module):
    def __init__(self, d_model, mem_dim=128, hyper_dim=64, num_heads=1,
                 mem_slots=2048, top_k=3, dropout=0.05, device="cpu", dtype=torch.bfloat16):
        super().__init__()
        self.d_model = d_model
        self.mem_dim = mem_dim
        self.top_k = top_k
        self.device = device
        self.dtype = dtype

        self.query_proj = nn.Linear(d_model, hyper_dim, dtype=dtype)
        self.dense_query = nn.Linear(d_model, mem_dim, dtype=dtype)
        self.memory_gate = nn.Sequential(
            nn.Linear(d_model, 128, dtype=dtype), nn.ReLU(), nn.Linear(128, 1, dtype=dtype)
        )
        self.reasoning_norm = nn.LayerNorm(d_model, dtype=dtype)
        self.reasoning_head = nn.MultiheadAttention(
            embed_dim=d_model, num_heads=num_heads,
            batch_first=True, dropout=dropout, dtype=dtype
        )
        self.reasoning_proj = nn.Linear(d_model, d_model, dtype=dtype)
        self.fusion = nn.Linear(d_model * 2, d_model, dtype=dtype)
        self.fusion_norm = nn.LayerNorm(d_model, dtype=dtype)
        self.dropout = nn.Dropout(dropout)
        self.shadow = ShadowMemoryIndex(mem_slots, mem_dim, d_model, device, dtype=dtype)

    def forward(self, hidden):
        hidden = hidden.to(self.dtype)
        gate_logits = self.memory_gate(hidden)
        need_mem = torch.sigmoid(gate_logits)
        dense_q = self.dense_query(hidden)
        mem_context, _ = self.shadow.query(dense_q, self.top_k)

        reasoning_input = self.reasoning_norm(hidden + mem_context)
        reasoned, _ = self.reasoning_head(reasoning_input, reasoning_input, reasoning_input)
        reasoned = self.reasoning_proj(reasoned)
        combined = torch.cat([hidden, reasoned], dim=-1)
        fused = self.fusion(combined)
        fused = self.fusion_norm(fused)
        fused = self.dropout(fused)
        output = hidden + need_mem * fused
        return output

    # External memory persistence methods
    def load_external_memory(self, path):
        """Load shadow memory from a .memory file if it exists."""
        p = Path(path)
        if p.exists():
            state = torch.load(p, map_location=self.device)
            self.shadow.keys = state["keys"].to(self.device)
            self.shadow.vals = state["vals"].to(self.device)
            self.shadow.ptr = int(state["ptr"].item())

    def save_external_memory(self, path):
        """Save shadow memory to a .memory file."""
        state = {
            "keys": self.shadow.keys.cpu(),
            "vals": self.shadow.vals.cpu(),
            "ptr": torch.tensor([self.shadow.ptr])
        }
        torch.save(state, path)

class CHLAugmentedModel(nn.Module):
    def __init__(self, config, device="auto", adapter_path=None, max_context=1024):
        super().__init__()
        self.cfg = config
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device
        self.max_context = max_context

        # Elegir dtype optimo segun backend
        if "cuda" in device:
            self.dtype = torch.bfloat16
        else:
            # MPS y CPU tienen mejor soporte nativo para float16 que bfloat16
            self.dtype = torch.float16
            if device == "mps":
                os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

        model_path = config["model_path"]
        print(f"[CHL] Cargando modelo base {model_path} en {device} (dtype={self.dtype})...")

        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Configuracion de cuantizacion opcional si estamos en CUDA
        if "cuda" in device:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=self.dtype,
                bnb_4bit_use_double_quant=True,
            )
            base_model = AutoModelForCausalLM.from_pretrained(
                model_path,
                quantization_config=bnb_config,
                device_map="auto",
                torch_dtype=self.dtype,
                trust_remote_code=True,
            )
        else:
            base_model = AutoModelForCausalLM.from_pretrained(
                model_path,
                torch_dtype=self.dtype,
                trust_remote_code=True,
            )

        if adapter_path:
            print(f"[CHL] Cargando LoRA adapter desde {adapter_path}...")
            self.model = PeftModel.from_pretrained(base_model, adapter_path)
        else:
            self.model = base_model

        if "cuda" not in device:
            print(f"[CHL] Moviendo modelo a dispositivo: {device}...")
            self.model = self.model.to(self.device)

        # torch.compile puede mejorar throughput pero ralentiza enormemente la primera inferencia
        # en MPS/CPU. Se activa solo explicitamente con CHL_ENABLE_COMPILE=1.
        if "cuda" not in device and os.environ.get("CHL_ENABLE_COMPILE") == "1":
            try:
                print("[CHL] Intentando torch.compile(mode=reduce-overhead)...")
                self.model = torch.compile(self.model, mode="reduce-overhead", fullgraph=False)
                print("[CHL] torch.compile activado.")
            except Exception as e:
                print(f"[CHL] torch.compile no disponible: {e}. Continuando sin compilar.")

        d_model = self.model.config.hidden_size
        chl_cfg = config["chl"]
        self.chl_layer = CHLReActLayer(
            d_model=d_model,
            mem_dim=chl_cfg["mem_dim"],
            hyper_dim=chl_cfg["hyper_dim"],
            num_heads=chl_cfg["reasoning_heads"],
            mem_slots=chl_cfg["mem_slots"],
            top_k=chl_cfg["top_k"],
            device=self.device,
            dtype=self.dtype,
        )
        # Load external memory if configured
        self.memory_path = config.get("chl_memory_path")
        if self.memory_path:
            self.chl_layer.load_external_memory(self.memory_path)
        self.chl_layer.to(self.device)
        self.chl_layer.shadow.to(self.device)

    def forward(self, input_ids, attention_mask=None, past_key_values=None, position_ids=None, use_cache=False):
        outputs = self.model.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            past_key_values=past_key_values,
            position_ids=position_ids,
            output_hidden_states=True,
            use_cache=use_cache,
        )
        hidden = outputs.hidden_states[-1]
        augmented_hidden = self.chl_layer(hidden)
        logits = self.model.lm_head(augmented_hidden)
        if use_cache:
            return logits, outputs.past_key_values
        return logits

    @classmethod
    def load(cls, path, device="auto", max_context=1024):
        path = Path(path)
        with open(path / "config.json") as f:
            cfg = json.load(f)
        inst = cls(cfg, device=device, adapter_path=path / "lora", max_context=max_context)

        # Load CHL weights and possibly external memory
        chl_weights_file = path / "chl_weights.pt"
        if chl_weights_file.exists():
            print(f"[CHL] Cargando pesos CHL desde {chl_weights_file}...")
            chl_state = torch.load(chl_weights_file, map_location=inst.device)
            params_dict = {k: v for k, v in chl_state.items() if k in dict(inst.chl_layer.named_parameters())}
            inst.chl_layer.load_state_dict(params_dict, strict=False)
            if "shadow_keys" in chl_state:
                inst.chl_layer.shadow.keys = chl_state["shadow_keys"].to(inst.device).to(inst.dtype)
            if "shadow_vals" in chl_state:
                inst.chl_layer.shadow.vals = chl_state["shadow_vals"].to(inst.device).to(inst.dtype)
            if "shadow_ptr" in chl_state:
                inst.chl_layer.shadow.ptr = int(chl_state["shadow_ptr"].item())
        # Load external memory if configured
        if hasattr(inst, "memory_path") and inst.memory_path:
            memory_file = Path(inst.memory_path)
            if memory_file.exists():
                inst.chl_layer.load_external_memory(memory_file)
        return inst

    def save(self, path):
        """Save model, CHL weights, and external memory to the given directory."""
        Path(path).mkdir(parents=True, exist_ok=True)
        # Save LoRA adapters
        self.model.save_pretrained(Path(path) / "lora")
        # Save CHL weights
        chl_state = {k: v.cpu() for k, v in self.chl_layer.state_dict().items()}
        chl_state["shadow_keys"] = self.chl_layer.shadow.keys.cpu()
        chl_state["shadow_vals"] = self.chl_layer.shadow.vals.cpu()
        chl_state["shadow_ptr"] = torch.tensor([self.chl_layer.shadow.ptr])
        torch.save(chl_state, Path(path) / "chl_weights.pt")
        # Save external memory file if present
        if hasattr(self, "memory_path") and Path(self.memory_path).exists():
            shutil.copy(self.memory_path, Path(path) / Path(self.memory_path).name)

    @torch.no_grad()
    def generate(self, prompt, max_new_tokens=256, temperature=0.7, top_k=50, stream=False):
        """Generate text from prompt using KV-cache internal per-turn.
        No conversation history is kept between calls; the cache is discarded after generation.
        If stream=True, yields token strings incrementally.
        """
        self.eval()
        prompt_ids = self.tokenizer.encode(prompt, return_tensors="pt")
        # Respetar limite de contexto total: truncar prompt por la izquierda si es necesario
        if prompt_ids.shape[-1] > self.max_context:
            keep = self.max_context - max_new_tokens - 1
            keep = max(keep, int(self.max_context * 0.25))
            prompt_ids = prompt_ids[:, -keep:]
            print(f"[CHL] Prompt truncado a {keep} tokens por limite de contexto.")
        input_ids = prompt_ids.to(self.device)
        prompt_len = input_ids.shape[-1]

        # Prefill del prompt completo una sola vez
        attention_mask = torch.ones(input_ids.shape, device=self.device, dtype=torch.long)
        outputs = self(input_ids, attention_mask=attention_mask, use_cache=True)
        logits, past_key_values = outputs if isinstance(outputs, tuple) else (outputs, None)
        next_token_logits = logits[:, -1, :] / (temperature if temperature > 0 else 1.0)

        if stream:
            def generator_helper():
                nonlocal input_ids, past_key_values, next_token_logits
                for _ in range(max_new_tokens):
                    if temperature > 0:
                        indices_to_remove = next_token_logits < torch.topk(next_token_logits, top_k)[0][..., -1, None]
                        next_token_logits[indices_to_remove] = -float('inf')
                        probs = F.softmax(next_token_logits, dim=-1)
                        next_token = torch.multinomial(probs, num_samples=1)
                    else:
                        next_token = torch.argmax(next_token_logits, dim=-1, keepdim=True)

                    token_id = next_token.item()
                    if token_id == self.tokenizer.eos_token_id:
                        break
                    token_str = self.tokenizer.decode([token_id], skip_special_tokens=True)
                    yield token_str

                    # Forward usando solo el ultimo token + KV cache
                    input_ids = next_token
                    out = self(input_ids, past_key_values=past_key_values, use_cache=True)
                    logits, past_key_values = out if isinstance(out, tuple) else (out, None)
                    next_token_logits = logits[:, -1, :] / (temperature if temperature > 0 else 1.0)
            return generator_helper()
        else:
            generated = []
            for _ in range(max_new_tokens):
                if temperature > 0:
                    indices_to_remove = next_token_logits < torch.topk(next_token_logits, top_k)[0][..., -1, None]
                    next_token_logits[indices_to_remove] = -float('inf')
                    probs = F.softmax(next_token_logits, dim=-1)
                    next_token = torch.multinomial(probs, num_samples=1)
                else:
                    next_token = torch.argmax(next_token_logits, dim=-1, keepdim=True)

                token_id = next_token.item()
                if token_id == self.tokenizer.eos_token_id:
                    break
                token_str = self.tokenizer.decode([token_id], skip_special_tokens=True)
                generated.append(token_str)

                # Forward usando solo el ultimo token + KV cache
                input_ids = next_token
                out = self(input_ids, past_key_values=past_key_values, use_cache=True)
                logits, past_key_values = out if isinstance(out, tuple) else (out, None)
                next_token_logits = logits[:, -1, :] / (temperature if temperature > 0 else 1.0)

            # Fallback robusto: decodificar tokens generados acumulados
            if generated:
                return "".join(generated).strip()
            return ""

# =====================================================================
# 2. Servidor API OpenAI Compatible
# =====================================================================

global_model = None

class OpenAIAPIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Desactivar logs estándar en consola para salida limpia
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        if self.path == "/v1/models" or self.path == "/models":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            res = {
                "object": "list",
                "data": [
                    {
                        "id": global_model.cfg["model_path"],
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "chl"
                    }
                ]
            }
            self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/v1/chat/completions" or self.path == "/chat/completions":
            content_length = int(self.headers["Content-Length"])
            body = self.rfile.read(content_length)
            req_data = json.loads(body.decode("utf-8"))
            
            messages = req_data.get("messages", [])
            temperature = float(req_data.get("temperature", 0.7))
            max_tokens = int(req_data.get("max_tokens", 256))
            stream = bool(req_data.get("stream", False))
            
            # Formatear la conversación al chat template de Qwen
            formatted_prompt = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                formatted_prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
            formatted_prompt += "<|im_start|>assistant\n"
            
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                
                print(f"[API] Procesando pregunta (streaming, {len(messages)} mensajes)...")
                start = time.time()
                tokens_generator = global_model.generate(
                    prompt=formatted_prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    stream=True
                )
                # Enviar tokens agrupados en pequenos lotes para reducir overhead de HTTP
                batch = []
                batch_size = 2  # agrupar 2 tokens por chunk; aumentar si se quiere mas fluidez
                flush_every = 0.05  # forzar flush si pasa demasiado tiempo
                last_flush = time.time()
                for token_str in tokens_generator:
                    batch.append(token_str)
                    now = time.time()
                    if len(batch) >= batch_size or (now - last_flush) > flush_every:
                        content = "".join(batch)
                        chunk = {
                            "id": f"chatcmpl-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": global_model.cfg["model_path"],
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "content": content
                                    },
                                    "finish_reason": None
                                }
                            ]
                        }
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        batch = []
                        last_flush = now
                
                if batch:
                    content = "".join(batch)
                    chunk = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": global_model.cfg["model_path"],
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content": content
                                },
                                "finish_reason": None
                            }
                        ]
                    }
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                elapsed = time.time() - start
                print(f"[API] Generado (stream) en {elapsed:.2f}s")
            else:
                print(f"[API] Procesando pregunta ({len(messages)} mensajes)...")
                start = time.time()
                response_text = global_model.generate(
                    prompt=formatted_prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    stream=False
                )
                elapsed = time.time() - start
                print(f"[API] Generado en {elapsed:.2f}s")
                
                res = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": global_model.cfg["model_path"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": response_text.strip()
                            },
                            "finish_reason": "stop"
                        }
                    ],
                    "usage": {
                        "prompt_tokens": -1,
                        "completion_tokens": -1,
                        "total_tokens": -1
                    }
                }
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

def run_server(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), OpenAIAPIHandler)
    print(f"🚀 Servidor API OpenAI compatible corriendo en http://localhost:{port}/v1")
    print(f"   Endpoint de completions: http://localhost:{port}/v1/chat/completions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor...")
        server.server_close()

# =====================================================================
# 3. Modo Chat Interactivo
# =====================================================================

def run_chat():
    print("\n=========================================")
    print("  CHL Chat Mode (Modelo Finetuneado)")
    print("  Escribe tu mensaje y presiona Enter.")
    print("  Escribe '/exit' para salir.")
    print("=========================================\n")
    
    history = []
    
    # Agregar instrucciones de sistema iniciales
    system_prompt = "Eres un asistente con memoria episódica. Responde las preguntas de forma concisa basándote en lo aprendido."
    
    while True:
        try:
            user_input = input("tú> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break
            
        if not user_input:
            continue
        if user_input == "/exit":
            print("Bye!")
            break
            
        # Reconstruir contexto completo de la conversación
        prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        for turn_user, turn_bot in history:
            prompt += f"<|im_start|>user\n{turn_user}<|im_end|>\n"
            prompt += f"<|im_start|>assistant\n{turn_bot}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{user_input}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        
        print("bot> pensando...", end="\r")
        start = time.time()
        response = global_model.generate(prompt, max_new_tokens=256, temperature=0.7)
        elapsed = time.time() - start
        
        response = response.strip()
        print(f"bot> {response}  ({elapsed:.2f}s)")
        
        # Guardar en historial
        history.append((user_input, response))
        # Mantener historial corto para eficiencia
        if len(history) > 10:
            history.pop(0)

# =====================================================================
# 4. Entrypoint
# =====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inferencia del modelo finetuneado con CHL")
    parser.add_argument("--checkpoint", type=str, default="chkpt/best", help="Ruta al checkpoint del modelo finetuneado")
    parser.add_argument("--serve", action="store_true", help="Correr en modo servidor API OpenAI compatible")
    parser.add_argument("--chat", action="store_true", help="Correr en modo chat interactivo en terminal")
    parser.add_argument("--port", type=int, default=3040, help="Puerto para el servidor API")
    parser.add_argument("--device", type=str, default="auto", help="Dispositivo (cuda, mps, cpu, auto)")
    parser.add_argument("--max-context", type=int, default=1024, help="Maximo de tokens totales de contexto (prompt + generacion)")

    args = parser.parse_args()
    
    if not args.serve and not args.chat:
        # Por defecto si no se especifica nada, iniciar chat
        args.chat = True
        
    checkpoint_path = Path(args.checkpoint)
    if not checkpoint_path.exists() or not (checkpoint_path / "config.json").exists():
        print(f"❌ Error: El checkpoint en '{args.checkpoint}' no parece válido o no existe.")
        print("   Asegúrate de que la ruta contiene config.json, lora/ y chl_weights.pt")
        sys.exit(1)
        
    print(f"[CHL] Inicializando inferencia desde '{args.checkpoint}'...")
    print(f"[CHL] Maximo contexto configurado: {args.max_context} tokens")
    try:
        global_model = CHLAugmentedModel.load(args.checkpoint, device=args.device, max_context=args.max_context)
        print("✅ Modelo cargado exitosamente.")
    except Exception as e:
        print(f"❌ Error al cargar el modelo: {e}")
        sys.exit(1)
        
    if args.serve:
        run_server(args.port)
    elif args.chat:
        run_chat()
