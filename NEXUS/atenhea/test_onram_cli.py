from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onram_cli import (
    COMMANDS,
    PROJECT_ROOT,
    ROOT,
    build_agent_invocation,
    check_onram,
    configure_pi_provider,
    resolve,
    downloaded_models,
)


class UnifiedCliTests(unittest.TestCase):
    def test_local_inventory_groups_shards_and_ignores_incomplete_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("gemma.gguf", "qwen-00001-of-00002.gguf", "qwen-00002-of-00002.gguf",
                         "incomplete-00001-of-00002.gguf", "model.gguf.part", "dense.bin"):
                (root / name).write_bytes(b"weights")
            models = downloaded_models(root)
            self.assertEqual([m['name'] for m in models], ['gemma.gguf', 'qwen.gguf'])
            self.assertEqual(models[1]['size_bytes'], 14)
            self.assertEqual(len(models[1]['files']), 2)

    def test_list_and_models_dispatch_without_server(self):
        for command in ('list', 'models'):
            self.assertEqual(resolve([command, '--json']), (None, ROOT, ['--json'], 'list'))

    def test_every_registered_command_has_a_source_file(self):
        for name, (script, _cwd) in COMMANDS.items():
            with self.subTest(name=name):
                self.assertTrue(script.is_file(), script)

    def test_project_nram_tools_are_exposed_by_one_cli(self):
        for name in ("nram", "nram-eval", "nram-sweep", "nram-memory", "nram-adapt", "nram-prepare-data"):
            with self.subTest(name=name):
                self.assertIn(name, COMMANDS)
                script, cwd = COMMANDS[name]
                self.assertEqual(cwd, PROJECT_ROOT)
                self.assertTrue(script.is_file())

    def test_known_command_forwards_all_arguments(self):
        script, cwd, forwarded, action = resolve(["convert", "--model", "local", "--output", "x.nram"])
        self.assertEqual(script, ROOT / "nram_convert.py")
        self.assertEqual(cwd, ROOT)
        self.assertEqual(forwarded, ["--model", "local", "--output", "x.nram"])
        self.assertIsNone(action)

    def test_legacy_server_invocations_remain_available(self):
        script, cwd, forwarded, action = resolve(["--model", "m.gguf", "--port", "1234"])
        self.assertEqual(script, ROOT / "onram.py")
        self.assertEqual(cwd, ROOT)
        self.assertEqual(forwarded, ["--model", "m.gguf", "--port", "1234"])
        self.assertIsNone(action)
        self.assertEqual(resolve([])[0], ROOT / "onram.py")

    def test_help_and_version_are_frontend_commands(self):
        self.assertEqual(resolve(["--help"])[3], "help")
        self.assertEqual(resolve(["--version"])[3], "version")

    def test_launch_is_a_frontend_command(self):
        self.assertEqual(resolve(["launch", "claude"]), (None, ROOT, ["claude"], "launch"))

    def test_health_check_discovers_model_and_sends_onram_key(self):
        response = io.BytesIO(b'{"data":[{"id":"coder-v2:latest"}]}')
        with patch("onram_cli.urllib.request.urlopen", return_value=response) as urlopen:
            model = check_onram("http://127.0.0.1:11434/", "secret")
        self.assertEqual(model, "coder-v2:latest")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_claude_launch_routes_locally_without_leaking_existing_api_key(self):
        command, env = build_agent_invocation(
            "claude", "/bin/claude", ["--print", "hello"],
            base_url="http://127.0.0.1:11434/", model="coder:latest",
            env={"ANTHROPIC_API_KEY": "cloud-secret"},
        )
        self.assertEqual(command, ["/bin/claude", "--print", "hello"])
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:11434")
        self.assertEqual(env["ANTHROPIC_MODEL"], "coder:latest")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "local-onram")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_codex_launch_uses_responses_provider_and_optional_key(self):
        command, _env = build_agent_invocation(
            "codex", "/bin/codex", ["--full-auto"],
            base_url="http://127.0.0.1:11434", model="coder:latest",
            env={
                "ONRAM_API_KEY": "secret",
                "OPENAI_API_KEY": "cloud-secret",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
            },
        )
        config = [command[index + 1] for index, arg in enumerate(command[:-1]) if arg == "--config"]
        self.assertIn('model_provider="onram"', config)
        self.assertIn('model_providers.onram.base_url="http://127.0.0.1:11434/v1"', config)
        self.assertIn('model_providers.onram.wire_api="responses"', config)
        self.assertIn('model_providers.onram.env_key="ONRAM_API_KEY"', config)
        self.assertEqual(command[-1], "--full-auto")
        self.assertNotIn("OPENAI_API_KEY", _env)
        self.assertNotIn("OPENAI_BASE_URL", _env)

    def test_pi_provider_merges_existing_configuration_and_uses_env_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            agent_dir = Path(temp_dir) / "pi-agent"
            agent_dir.mkdir()
            path = agent_dir / "models.json"
            path.write_text(json.dumps({"providers": {"other": {"baseUrl": "https://example.test/v1"}}}))
            configure_pi_provider(agent_dir, "http://127.0.0.1:11434", "coder:latest", "secret")
            config = json.loads(path.read_text())
        self.assertIn("other", config["providers"])
        self.assertEqual(config["providers"]["onram"]["baseUrl"], "http://127.0.0.1:11434/v1")
        self.assertEqual(config["providers"]["onram"]["apiKey"], "${ONRAM_API_KEY}")
        self.assertEqual(config["providers"]["onram"]["models"][0]["id"], "coder:latest")

    def test_cli_launch_executes_agent_and_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            capture_path = temp_path / "captured.json"
            agent = temp_path / "claude"
            agent.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "with open(os.environ['ONRAM_LAUNCH_CAPTURE'], 'w') as output:\n"
                "    json.dump({'args': sys.argv[1:], 'base': os.environ.get('ANTHROPIC_BASE_URL'), "
                "'model': os.environ.get('ANTHROPIC_MODEL')}, output)\n",
                encoding="utf-8",
            )
            agent.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = f"{temp_dir}{os.pathsep}{env.get('PATH', '')}"
            env["ONRAM_LAUNCH_CAPTURE"] = str(capture_path)
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "onram_cli.py"), "launch", "claude",
                    "--no-check", "--model", "test-model", "--", "--print", "hello",
                ],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            captured = json.loads(capture_path.read_text(encoding="utf-8"))
        self.assertEqual(captured["args"], ["--print", "hello"])
        self.assertEqual(captured["base"], "http://127.0.0.1:11434")
        self.assertEqual(captured["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
