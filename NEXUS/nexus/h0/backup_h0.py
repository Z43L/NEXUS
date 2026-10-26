"""Create private, retention-aware SQLite backups of the H0 ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from router import purge_expired_content, utc_now_iso

BACKUP_NAME = re.compile(r"nexus_h0_\d{8}T\d{6}Z\.db\Z")


def _private_backup_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"backup directory must not grant group/other access: {resolved}")
    return resolved


def _prune_managed_backups(directory: Path, cutoff: datetime) -> int:
    removed = 0
    for candidate in directory.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if not BACKUP_NAME.fullmatch(candidate.name):
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            candidate.unlink()
            removed += 1
    return removed


def create_backup(database: Path, backup_dir: Path, retention_days: int = 30) -> Path:
    """Snapshot the DB, scrub expired content in the snapshot, compact and prune."""
    if not 1 <= retention_days <= 3650:
        raise ValueError("retention_days must be between 1 and 3650")
    source_path = database.resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("database path must be a regular file")
    directory = _private_backup_dir(backup_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"nexus_h0_{stamp}.db"
    if target.exists():
        raise FileExistsError(f"backup already exists for this second: {target}")

    fd, temp_name = tempfile.mkstemp(prefix=".nexus_h0_backup_", suffix=".db", dir=directory)
    temp_path = Path(temp_name)
    os.fchmod(fd, 0o600)
    os.close(fd)
    source_uri = source_path.as_uri() + "?mode=ro"
    try:
        source = sqlite3.connect(source_uri, uri=True)
        try:
            dest = sqlite3.connect(temp_path)
            try:
                source.backup(dest)
                dest.execute("PRAGMA secure_delete=ON")
                if dest.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                    raise RuntimeError("retention-aware backups require SQLite DELETE journal mode")
                columns = {row[1] for row in dest.execute("PRAGMA table_info(jobs)")}
                required = {"payload", "result_text", "content_expires_at", "content_purged"}
                if not required.issubset(columns):
                    raise RuntimeError("start Router once to migrate the ledger before backing it up")
                purge_expired_content(dest, utc_now_iso())
                dest.commit()
                dest.execute("VACUUM")
            finally:
                dest.close()
        finally:
            source.close()
        os.chmod(temp_path, 0o600)
        # Hard-link creation is atomic and refuses to overwrite a same-second
        # backup created concurrently by another operator process.
        os.link(temp_path, target)
        temp_path.unlink()
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        _prune_managed_backups(directory, cutoff)
        return target
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path,
                        help="path to the live nexus_h0.db")
    parser.add_argument("--backup-dir", required=True, type=Path,
                        help="private directory on encrypted storage")
    parser.add_argument("--retention-days", type=int, default=30,
                        help="maximum age for managed backup files (default: 30)")
    args = parser.parse_args()
    backup = create_backup(args.database, args.backup_dir, args.retention_days)
    print(f"H0 retention-aware backup created: {backup}")


if __name__ == "__main__":
    main()
