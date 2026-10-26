from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parent


class ComposeBootstrapTests(unittest.TestCase):
    def _project_copy(self, root: Path) -> Path:
        project = root / "NEXUS"
        (project / "nexus-h1-node").mkdir(parents=True)
        shutil.copy2(SOURCE / "bootstrap-compose-h0.sh",
                     project / "nexus-h1-node" / "bootstrap-compose-h0.sh")
        shutil.copy2(SOURCE.parent / ".env.h0.example", project / ".env.h0.example")
        return project

    def _run(self, project: Path, env: dict[str, str] | None = None):
        ca_key = project.parent / "offline-ca" / "ca.key"
        ca_key.parent.mkdir(mode=0o700, exist_ok=True)
        return subprocess.run(
            [str(project / "nexus-h1-node" / "bootstrap-compose-h0.sh")],
            text=True, capture_output=True, timeout=60,
            env={**os.environ, "NEXUS_H0_CA_KEY_OUT": str(ca_key), **(env or {})},
        )

    def test_success_creates_private_consistent_credentials_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="nexus-bootstrap-success-") as tmp:
            project = self._project_copy(Path(tmp))
            result = self._run(project)
            self.assertEqual(result.returncode, 0, result.stderr)
            secrets_dir = project / ".secrets"
            self.assertEqual(stat.S_IMODE(secrets_dir.stat().st_mode), 0o700)
            token = (secrets_dir / "api.token").read_text(encoding="utf-8").strip()
            self.assertTrue((secrets_dir / "atenea_api.key").is_file())
            self.assertEqual(stat.S_IMODE((secrets_dir / "atenea_api.key").stat().st_mode), 0o600)
            self.assertGreaterEqual(len((secrets_dir / "atenea_api.key").read_text().strip()), 32)
            registry_path = secrets_dir / "api_clients.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["clients"][0]["token_sha256"],
                             hashlib.sha256(token.encode()).hexdigest())
            self.assertNotIn(token, registry_path.read_text(encoding="utf-8"))
            self.assertIn("auth:session", registry["clients"][0]["scopes"])
            users = json.loads((secrets_dir / "api_users.json").read_text(encoding="utf-8"))
            self.assertEqual(users, {"version": 1, "users": []})
            redis_url = (secrets_dir / "redis.url").read_text(encoding="utf-8").strip()
            self.assertTrue(redis_url.startswith("redis://:"))
            self.assertIn("requirepass", (secrets_dir / "valkey.conf").read_text(encoding="utf-8"))
            self.assertTrue((project / "data" / "h0-valkey").is_dir())
            for path in secrets_dir.iterdir():
                if path.is_file():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)
            self.assertEqual(stat.S_IMODE((project / ".env.h0").stat().st_mode), 0o600)
            self.assertFalse((project / ".bootstrap-h0.lock").exists())
            self.assertTrue((project / ".secrets" / "router.crt").exists())
            subprocess.run([
                "openssl", "verify", "-x509_strict", "-CAfile",
                str(secrets_dir / "ca.crt"), str(secrets_dir / "router.crt"),
            ], check=True, capture_output=True, text=True)
            subprocess.run([
                "openssl", "verify", "-x509_strict", "-CAfile",
                str(secrets_dir / "ca.crt"), str(secrets_dir / "ca.crt"),
            ], check=True, capture_output=True, text=True)
            self.assertFalse((secrets_dir / "ca.key").exists())
            self.assertEqual(stat.S_IMODE((project.parent / "offline-ca" / "ca.key").stat().st_mode), 0o600)

            repeated = self._run(project)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual((secrets_dir / "api.token").read_text().strip(), token)

    def test_failure_during_publish_rolls_back_staged_secrets_and_env(self):
        with tempfile.TemporaryDirectory(prefix="nexus-bootstrap-failure-") as tmp:
            project = self._project_copy(Path(tmp))
            wrapper_dir = Path(tmp) / "bin"
            wrapper_dir.mkdir()
            real_mv = shutil.which("mv")
            self.assertIsNotNone(real_mv)
            wrapper = wrapper_dir / "mv"
            wrapper.write_text(
                "#!/bin/sh\n"
                "case \"$2\" in */.secrets) exit 73;; esac\n"
                f"exec {real_mv!r} \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o700)
            result = self._run(project, {"PATH": str(wrapper_dir) + os.pathsep + os.environ["PATH"]})
            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertFalse((project / ".secrets").exists())
            self.assertFalse((project / ".env.h0").exists())
            self.assertFalse((project.parent / "offline-ca" / "ca.key").exists())
            self.assertFalse((project / ".bootstrap-h0.lock").exists())
            self.assertEqual(list(project.glob(".secrets.tmp.*")), [])
            self.assertEqual(list(project.glob(".env.h0.tmp.*")), [])

    def test_ca_key_destination_is_mandatory_and_outside_project(self):
        with tempfile.TemporaryDirectory(prefix="nexus-bootstrap-ca-path-") as tmp:
            project = self._project_copy(Path(tmp))
            script = project / "nexus-h1-node" / "bootstrap-compose-h0.sh"
            env = os.environ.copy()
            env.pop("NEXUS_H0_CA_KEY_OUT", None)
            missing = subprocess.run([str(script)], text=True, capture_output=True,
                                     timeout=10, env=env)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("NEXUS_H0_CA_KEY_OUT", missing.stderr)

            inside = project / "offline" / "ca.key"
            inside.parent.mkdir()
            result = self._run(project, {"NEXUS_H0_CA_KEY_OUT": str(inside)})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the online project", result.stderr)


if __name__ == "__main__":
    unittest.main()
