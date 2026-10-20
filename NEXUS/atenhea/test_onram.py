import unittest
import hashlib
import json
import threading
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from onram import Onram, ROOT
from onram import handler_for
from interaction_learning import InteractionBuffer


class OnramTests(unittest.TestCase):
    def test_completion_options_translate_ollama_options(self):
        options = Onram._completion_options("prompt", {
            "num_predict": 32,
            "temperature": 0.25,
            "top_k": 12,
            "top_p": 0.8,
            "repeat_penalty": 1.2,
            "stop": ["END"],
        })
        self.assertEqual(options["n_predict"], 32)
        self.assertEqual(options["temperature"], 0.25)
        self.assertEqual(options["top_k"], 12)
        self.assertEqual(options["top_p"], 0.8)
        self.assertEqual(options["repeat_penalty"], 1.2)
        self.assertEqual(options["stop"], ["END"])

    def test_completion_options_reject_context_overflow(self):
        with self.assertRaisesRegex(ValueError, "num_predict"):
            Onram._completion_options("prompt", {"num_predict": 513})

    def test_dataset_selection_cannot_escape_project_data(self):
        self.assertEqual(Onram._dataset("nra_qa_train.jsonl"), ROOT / "data" / "nra_qa_train.jsonl")
        with self.assertRaises(ValueError):
            Onram._dataset("../../etc/passwd")

    def test_name_tracks_the_active_gguf(self):
        app = Onram.__new__(Onram)
        app.model_path = Path("/models/small-Q4_K_M.gguf")
        self.assertEqual(app.model_name, "small:latest")

    def test_non_q4_gguf_name_is_preserved(self):
        app = Onram.__new__(Onram)
        app.model_path = Path("/models/custom-instruct-f16.gguf")
        self.assertEqual(app.model_name, "custom-instruct-f16:latest")

    def test_gguf_trace_aggregates_layers_without_saving_conversation_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = Onram.__new__(Onram)
            app.inference_debug = True
            app.model_path = Path("/models/private-model-Q4_K_M.gguf")
            app.trace_scratch = root / "scratch.jsonl"
            app.trace_ledger = root / "ledger.jsonl"
            app.debug_trace_count = 0
            app.debug_status = {"enabled": True, "state": "capturing"}
            app.trace_scratch.write_text("\n".join((
                json.dumps({"layer": 0, "positions": 2, "hidden_size": 4,
                            "output_rms": 2.0, "top_channels": [
                                {"channel": 1, "mean_abs": 3.0},
                            ]}),
                json.dumps({"layer": 0, "positions": 1, "hidden_size": 4,
                            "output_rms": 1.0, "top_channels": [
                                {"channel": 1, "mean_abs": 1.0},
                                {"channel": 2, "mean_abs": 2.0},
                            ]}),
                json.dumps({"layer": 1, "positions": 1, "hidden_size": 4,
                            "output_rms": 0.5, "top_channels": []}),
            )) + "\n", encoding="utf-8")
            prompt = "Secreto de usuario: Ana-private-phrase"
            completion = "Respuesta confidencial: output-private-phrase"
            request = json.dumps({"messages": [{"role": "user", "content": prompt}]}).encode()
            response = json.dumps({
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": completion}],
            }).encode()

            app.finish_runtime_trace("/v1/messages", request, response, 200)

            report = json.loads(app.trace_ledger.read_text(encoding="utf-8"))
            saved = app.trace_ledger.read_text(encoding="utf-8")
            self.assertEqual(report["backend"], "llama.cpp-gguf")
            self.assertEqual(report["callback_events"], 3)
            self.assertEqual(report["layer_count"], 2)
            self.assertAlmostEqual(report["layers"][0]["output_rms"], 3.0 ** 0.5)
            self.assertEqual(report["layers"][0]["top_mean_abs_channels"][0], {
                "channel": 1, "mean_abs": 7 / 3,
            })
            self.assertEqual(report["prompt_sha256"], hashlib.sha256(prompt.encode()).hexdigest())
            self.assertEqual(report["completion_sha256"], hashlib.sha256(completion.encode()).hexdigest())
            self.assertNotIn(prompt, saved)
            self.assertNotIn(completion, saved)
            self.assertNotIn("Ana-private-phrase", saved)
            self.assertNotIn("output-private-phrase", saved)
            self.assertEqual(app.debug_status["state"], "ready")
            self.assertEqual(app.debug_status["trace_count"], 1)
            self.assertEqual(app.trace_scratch.stat().st_size, 0)


class OnramLearningFeedbackTests(unittest.TestCase):
    def test_bad_trace_feedback_replaces_target_with_user_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = "Implementa una función segura de ejemplo."
            original = "La respuesta incorrecta propone eval(input())."
            corrected = "Usa ast.literal_eval y valida estrictamente el tipo recibido."
            learning = InteractionBuffer(root / "learning")
            learning.add(prompt, original)
            trace_id = "trace-bad-001"
            app = Onram.__new__(Onram)
            app.trace_ledger = root / "learning" / "inference-traces.jsonl"
            app.trace_ledger.write_text(json.dumps({
                "trace_id": trace_id,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "completion_sha256": hashlib.sha256(original.encode()).hexdigest(),
                "callback_events": 16,
            }) + "\n", encoding="utf-8")
            app.learning = learning
            app.learning_lock = threading.Lock()
            app.learning_status = {}
            app.auto_learn = False

            result = app.record_feedback({
                "trace_id": trace_id, "rating": "bad",
                "corrected_completion": corrected,
            })

            self.assertTrue(result["accepted"])
            self.assertTrue(result["has_correction"])
            self.assertEqual(result["corrected_bad_feedback_count"], 1)
            train_path, validation_path = root / "train.jsonl", root / "validation.jsonl"
            train_count, validation_count = learning.write_split(train_path, validation_path)
            examples = [json.loads(line) for path in (train_path, validation_path)
                        for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(train_count + validation_count, 1)
            self.assertEqual(examples[0]["completion"], corrected)
            self.assertEqual(examples[0]["runtime_feedback"], "bad_corrected")
            self.assertEqual(examples[0]["runtime_trace_id"], trace_id)
            self.assertNotIn(original, json.dumps(examples))


class OnramProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class BackendHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            last_request = None

            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                type(self).last_request = {
                    "path": self.path,
                    "body": self.rfile.read(length),
                    "headers": dict(self.headers.items()),
                }
                chunks = (
                    b"event: message_start\n",
                    b"data: {\"type\":\"message_start\"}\n\n",
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")

        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
        cls.backend_thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.backend_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.backend_thread.join(timeout=2)

    def setUp(self):
        backend_port = self.backend.server_address[1]
        self.app = SimpleNamespace(
            api_key="agent-secret",
            backend_url=f"http://127.0.0.1:{backend_port}",
            model_name="local-coder:latest",
            model_path=Path(__file__).resolve(),
            lock=threading.RLock(),
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_openai_models_lists_the_active_onram_alias(self):
        request = urllib.request.Request(self.base_url + "/v1/models?client_version=0.163.0", headers={
            "Authorization": "Bearer agent-secret",
        })
        with urllib.request.urlopen(request) as response:
            listing = json.loads(response.read())
        self.assertEqual(listing["data"][0]["id"], "local-coder:latest")
        self.assertEqual(listing["data"][0]["owned_by"], "onram")

    def test_agent_routes_preserve_protocol_bodies_and_sse_streams(self):
        schema = {"type": "object", "properties": {"value": {"type": "string"}}}
        cases = (
            ("/v1/messages?beta=1", {"anthropic-version": "2023-06-01", "x-api-key": "agent-secret"}, {
                "model": "local-coder:latest", "max_tokens": 24, "stream": True,
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [{"name": "inspect", "description": "inspect", "input_schema": schema}],
                "tool_choice": {"type": "auto"},
            }),
            ("/v1/responses", {"authorization": "Bearer agent-secret"}, {
                "model": "local-coder:latest", "input": "hello", "stream": True,
                "tools": [{"type": "function", "name": "inspect", "parameters": schema}],
            }),
            ("/v1/chat/completions", {"authorization": "Bearer agent-secret"}, {
                "model": "local-coder:latest", "messages": [{"role": "user", "content": "hello"}],
                "stream": True, "tools": [{"type": "function", "function": {
                    "name": "inspect", "parameters": schema,
                }}], "tool_choice": "auto",
            }),
        )
        for path, headers, value in cases:
            with self.subTest(path=path):
                payload = json.dumps(value).encode()
                request = urllib.request.Request(self.base_url + path, data=payload, headers={
                    "Content-Type": "application/json", **headers,
                })
                with urllib.request.urlopen(request) as response:
                    body = response.read()
                self.assertEqual(response.headers.get_content_type(), "text/event-stream")
                recorded = self.backend.RequestHandlerClass.last_request
                expected_path = "/v1/messages?beta=1" if path.endswith("beta=1") else path
                self.assertEqual(recorded["path"], expected_path)
                self.assertEqual(recorded["body"], payload)
                self.assertIn(b"event: message_start", body)

    def test_configured_key_accepts_bearer_and_anthropic_x_api_key(self):
        request = urllib.request.Request(self.base_url + "/v1/messages", data=b"{}", headers={
            "Content-Type": "application/json", "x-api-key": "wrong",
        })
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()

        request = urllib.request.Request(self.base_url + "/v1/messages", data=b"{}", headers={
            "Content-Type": "application/json", "x-api-key": "agent-secret",
        })
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
