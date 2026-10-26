"""Regression coverage for private operator provisioning of browser users."""
import json
from pathlib import Path
import stat
import tempfile
import unittest

from nexus.api import manage_api_users


class ManageApiUsersTests(unittest.TestCase):
    def test_add_list_reset_and_remove_never_store_or_print_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / "api_users.json"
            manage_api_users.manage(path, "add", "alice", password="initial secret")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("initial secret", raw)
            self.assertIn("user-alice", raw)
            self.assertNotIn("password_scrypt", manage_api_users.manage(path, "list"))
            manage_api_users.manage(path, "set-password", "alice", password="rotated secret")
            registry = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("initial secret", path.read_text(encoding="utf-8"))
            self.assertNotEqual(registry["users"][0]["password_scrypt"]["hash"], "rotated secret")
            manage_api_users.manage(path, "remove", "alice")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["users"], [])

    def test_provisioning_rejects_duplicates_and_unsafe_registry_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / "api_users.json"
            manage_api_users.manage(path, "add", "alice", password="initial secret")
            with self.assertRaises(ValueError):
                manage_api_users.manage(path, "add", "alice", password="another secret")
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                manage_api_users.manage(path, "list")


if __name__ == "__main__":
    unittest.main()
