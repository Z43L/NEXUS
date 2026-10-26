"""Offline regression tests for Compose Router certificate renewal."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("rotate-compose-router-cert.sh")


def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


class ComposeRouterCertificateRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="nexus-cert-rotation-")
        self.root = Path(self.temp.name)
        self.secrets = self.root / "secrets"
        self.offline = self.root / "offline-media"
        self.bin = self.root / "bin"
        self.secrets.mkdir(mode=0o700)
        self.offline.mkdir(mode=0o700)
        self.bin.mkdir()
        self.env_file = self.root / ".env.h0"
        self.env_file.write_text("API_HOST_PORT=8000\n", encoding="utf-8")
        self.compose_file = self.root / "compose.yml"
        self.compose_file.write_text("services: {}\n", encoding="utf-8")
        self.calls = self.root / "docker-calls.log"
        ca_key, ca_cert = self._make_ca("ca")
        self.ca_key = self.offline / "ca.key"
        self.ca_key.write_bytes(ca_key.read_bytes())
        self.ca_key.chmod(0o600)
        self.ca_cert = self.secrets / "ca.crt"
        self.ca_cert.write_bytes(ca_cert.read_bytes())
        self._make_old_router_certificate()
        docker = self.bin / "docker"
        docker.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$DOCKER_CALL_LOG\"\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_ca(self, suffix: str) -> tuple[Path, Path]:
        key = self.secrets / f"{suffix}.key"
        cert = self.secrets / f"{suffix}.crt"
        run(
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "3650", "-keyout", str(key), "-out", str(cert),
            "-subj", f"/CN={suffix} test CA", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash",
        )
        return key, cert

    def _make_old_router_certificate(self) -> None:
        run(
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "90", "-keyout", str(self.secrets / "router.key"),
            "-out", str(self.secrets / "router.crt"), "-subj", "/CN=old-router",
        )

    def _run_rotation(self, ca_key: Path | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update({
            "PATH": f"{self.bin}{os.pathsep}{env['PATH']}",
            "DOCKER_CALL_LOG": str(self.calls),
            "NEXUS_H0_SECRETS_DIR": str(self.secrets),
            "NEXUS_H0_ENV_FILE": str(self.env_file),
            "NEXUS_H0_COMPOSE_FILE": str(self.compose_file),
            "NEXUS_H0_CA_KEY_FILE": str(self.ca_key),
        })
        if ca_key is not None:
            self.ca_key.write_bytes(ca_key.read_bytes())
            self.ca_key.chmod(0o600)
        return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)

    def test_renews_certificate_and_requests_health_checked_recreation(self) -> None:
        old_key = (self.secrets / "router.key").read_bytes()
        old_cert = (self.secrets / "router.crt").read_bytes()

        result = self._run_rotation()

        self.assertEqual(result.returncode, 0, result.stderr)
        new_key = self.secrets / "router.key"
        new_cert = self.secrets / "router.crt"
        self.assertNotEqual(new_key.read_bytes(), old_key)
        self.assertNotEqual(new_cert.read_bytes(), old_cert)
        run("openssl", "verify", "-CAfile", str(self.secrets / "ca.crt"), str(new_cert))
        run("openssl", "verify", "-x509_strict", "-CAfile",
            str(self.secrets / "ca.crt"), str(new_cert))
        for host in ("router", "localhost"):
            run("openssl", "x509", "-in", str(new_cert), "-noout", "-checkhost", host)
        for address in ("127.0.0.1",):
            run("openssl", "x509", "-in", str(new_cert), "-noout", "-checkip", address)
        run("openssl", "x509", "-in", str(new_cert), "-noout", "-checkend", "7689600")
        self.assertEqual(new_key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(new_cert.stat().st_mode & 0o777, 0o600)

        backups = list(self.secrets.glob("router-cert-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "router.key").read_bytes(), old_key)
        self.assertEqual((backups[0] / "router.crt").read_bytes(), old_cert)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o700)
        calls = self.calls.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 3)
        self.assertIn("config --quiet", calls[0])
        self.assertIn("up --detach --force-recreate router", calls[1])
        self.assertIn("up --detach --wait --wait-timeout 300 web", calls[2])

    def test_mismatched_ca_key_fails_before_touching_router_or_compose(self) -> None:
        other_key, _ = self._make_ca("other")
        old_key = (self.secrets / "router.key").read_bytes()
        old_cert = (self.secrets / "router.crt").read_bytes()

        result = self._run_rotation(other_key)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Private CA key does not match", result.stderr)
        self.assertEqual((self.secrets / "router.key").read_bytes(), old_key)
        self.assertEqual((self.secrets / "router.crt").read_bytes(), old_cert)
        self.assertFalse(self.calls.exists())
        self.assertFalse(list(self.secrets.glob("router-cert-backup-*")))

    def test_partial_install_failure_restores_both_previous_files(self) -> None:
        old_key = (self.secrets / "router.key").read_bytes()
        old_cert = (self.secrets / "router.crt").read_bytes()
        real_mv = shutil.which("mv")
        self.assertIsNotNone(real_mv)
        marker = self.root / "mv-failed-once"
        wrapper = self.bin / "mv"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"if [ \"$2\" = {str(self.secrets / 'router.crt')!r} ] && [ ! -e {str(marker)!r} ]; then\n"
            f"  : > {str(marker)!r}; exit 73\n"
            "fi\n"
            f"exec {real_mv!r} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

        result = self._run_rotation()

        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertIn("restoring the previous Router certificate pair", result.stderr)
        self.assertEqual((self.secrets / "router.key").read_bytes(), old_key)
        self.assertEqual((self.secrets / "router.crt").read_bytes(), old_cert)
        calls = self.calls.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 3)
        self.assertIn("up --detach --force-recreate router", calls[1])
        self.assertIn("up --detach --wait --wait-timeout 300 web", calls[2])


if __name__ == "__main__":
    unittest.main()
