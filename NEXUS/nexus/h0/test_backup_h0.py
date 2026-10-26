"""Retention-aware backup regression tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import backup_h0
import router


class H0BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="nexus-h0-backup-")
        self.root = Path(self.temp.name)
        self.database = self.root / "nexus_h0.db"
        self.backup_dir = self.root / "backups"
        self.backup_dir.mkdir(mode=0o700)
        self.previous_db = router._db_path
        router._db_path = self.database
        router.init_db()

    def tearDown(self) -> None:
        router._db_path = self.previous_db
        self.temp.cleanup()

    def test_backup_scrubs_expired_data_prunes_only_managed_backups(self) -> None:
        expired_prompt = "EXPIRED_PROMPT_MARKER_" + "p" * 96
        expired_output = "EXPIRED_OUTPUT_MARKER_" + "o" * 96
        active_prompt = "ACTIVE_PROMPT_MARKER_" + "a" * 96
        future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with router.db() as conn:
            conn.execute(
                "INSERT INTO jobs(job_id, created_at, payload, result_text, status, "
                "content_expires_at) VALUES(?,?,?,?,?,?)",
                ("expired", "2020-01-01T00:00:00Z", expired_prompt, expired_output,
                 "done", "2000-01-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO jobs(job_id, created_at, payload, result_text, status, "
                "content_expires_at) VALUES(?,?,?,?,?,?)",
                ("active", "2026-10-26T00:00:00Z", active_prompt, "active output",
                 "done", future),
            )
            conn.execute(
                "INSERT INTO receipts(job_id, node_id, receipt, verified) "
                "VALUES('expired','node','receipt metadata',1)"
            )

        stale = self.backup_dir / "nexus_h0_20200101T000000Z.db"
        recent = self.backup_dir / "nexus_h0_20261025T000000Z.db"
        unrelated = self.backup_dir / "manual.db"
        for path in (stale, recent, unrelated):
            path.write_bytes(b"operator data")
        now = datetime.now(timezone.utc).timestamp()
        os.utime(stale, (now - 31 * 86400, now - 31 * 86400))
        os.utime(recent, (now - 2 * 86400, now - 2 * 86400))
        os.utime(unrelated, (now - 100 * 86400, now - 100 * 86400))
        symlink = self.backup_dir / "nexus_h0_20190101T000000Z.db"
        symlink.symlink_to(unrelated)

        backup = backup_h0.create_backup(self.database, self.backup_dir, retention_days=30)

        self.assertTrue(backup.exists())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        content = backup.read_bytes()
        self.assertNotIn(expired_prompt.encode(), content)
        self.assertNotIn(expired_output.encode(), content)
        self.assertIn(active_prompt.encode(), content)
        self.assertNotIn(b"EXPIRED", content)
        self.assertFalse(stale.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(symlink.is_symlink())
        with sqlite3.connect(backup) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], 1)
            row = conn.execute(
                "SELECT content_purged, payload, result_text FROM jobs WHERE job_id='expired'"
            ).fetchone()
            self.assertEqual(tuple(row), (1, "{}", None))

        # The backup is a privacy-scrubbed snapshot; live source remains unchanged.
        self.assertIn(expired_prompt.encode(), self.database.read_bytes())

    def test_backup_directory_must_be_private(self) -> None:
        public_dir = self.root / "public-backups"
        public_dir.mkdir(mode=0o755)
        public_dir.chmod(0o755)
        with self.assertRaises(PermissionError):
            backup_h0.create_backup(self.database, public_dir)

if __name__ == "__main__":
    unittest.main()
