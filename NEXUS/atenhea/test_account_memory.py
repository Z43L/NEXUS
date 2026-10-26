"""NEXUS traffic uses a CHL memory per account and never the operator memory."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from episodic_memory import DEFAULT_MEMORY, EpisodicMemory, user_memory_path
from onram import Onram


class UserMemoryPathTests(unittest.TestCase):
    def test_accepts_plain_account_identifiers(self) -> None:
        base = Path("/models")
        self.assertEqual(user_memory_path(base, "user-alice"),
                         base / "users" / "user-alice" / "athenea.memory")

    def test_rejects_identifiers_that_could_escape_the_directory(self) -> None:
        for bad in ("", "..", "../etc", "a/b", "a\\b", ".hidden", "x" * 65, None, 7):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                user_memory_path(Path("/models"), bad)


class AccountMemoryRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory(prefix="athenea-account-memory-")
        self.base = Path(self._folder.name) / "models"
        self.operator_path = self.base / "athenea.memory"
        # Build an engine-like object without loading a model.
        self.app = Onram.__new__(Onram)
        self.app.episodic = EpisodicMemory(self.operator_path)
        self.app.chl_base = self.base
        self.app.user_episodic = {}
        self.app.user_episodic_lock = threading.Lock()
        self.app.memory_error = None
        self.app.auto_learn = False
        self.app._stable_model_alias = "test-model"
        # Seed alice's account memory with a verified fact.
        alice = self.app.episodic_for_user("user-alice")
        self.assertIsNotNone(alice)
        alice.remember("capital de Francia", "París", verified=True)

    def tearDown(self) -> None:
        self._folder.cleanup()

    def _worker_body(self, user: str | None) -> bytes:
        data = {"model": "test-model", "nexus_worker": True,
                "messages": [{"role": "user", "content": "capital de Francia"}]}
        if user is not None:
            data["nexus_user"] = user
        return json.dumps(data).encode("utf-8")

    def test_owner_receives_only_their_own_context(self) -> None:
        body = json.loads(self.app.augment_request("/v1/chat/completions",
                                                   self._worker_body("user-alice")))
        self.assertNotIn("nexus_worker", body)
        self.assertNotIn("nexus_user", body)
        self.assertIn("París", json.dumps(body, ensure_ascii=False))

    def test_other_account_does_not_see_alice_memory(self) -> None:
        body = json.loads(self.app.augment_request("/v1/chat/completions",
                                                   self._worker_body("user-bob")))
        self.assertNotIn("París", json.dumps(body, ensure_ascii=False))

    def test_worker_without_account_gets_no_memory(self) -> None:
        body = json.loads(self.app.augment_request("/v1/chat/completions",
                                                   self._worker_body(None)))
        self.assertNotIn("París", json.dumps(body, ensure_ascii=False))

    def test_invalid_account_gets_no_memory(self) -> None:
        body = json.loads(self.app.augment_request("/v1/chat/completions",
                                                   self._worker_body("../user-alice")))
        self.assertNotIn("París", json.dumps(body, ensure_ascii=False))
        self.assertFalse(self.operator_path.exists() and
                         "París" in self.operator_path.read_bytes().decode("latin-1"))

    def test_nexus_capture_stays_out_of_operator_memory(self) -> None:
        request = self._worker_body("user-bob")
        answer = "La capital de Francia es París."
        response = json.dumps({"choices": [{"finish_reason": "stop",
                                            "message": {"role": "assistant",
                                                        "content": answer}}]}).encode()
        self.app.record_interaction("/v1/chat/completions", request, response)
        operator = EpisodicMemory(self.operator_path).call("export_all")
        self.assertFalse(any(row.get("completion") == answer for row in operator))
        bob = self.app.episodic_for_user("user-bob").call("export_all")
        self.assertTrue(any(row.get("completion") == answer for row in bob))

    def test_default_operator_memory_path_is_unchanged(self) -> None:
        self.assertEqual(DEFAULT_MEMORY.name, "athenea.memory")


if __name__ == "__main__":
    unittest.main()
