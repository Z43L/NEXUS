"""Content-addressed fragment stores (CID = hex SHA-256)."""
import hashlib
import os
import tempfile
from typing import Dict, Optional


def cid_of(data: bytes) -> str:
    """Content id of data."""
    return hashlib.sha256(data).hexdigest()


class FragmentStore:
    """Interface: put returns the cid; get returns None if absent."""

    def put(self, data: bytes) -> str:
        raise NotImplementedError

    def get(self, cid: str) -> Optional[bytes]:
        raise NotImplementedError

    def has(self, cid: str) -> bool:
        raise NotImplementedError


class MemoryStore(FragmentStore):
    """In-memory store (tests, demos)."""

    def __init__(self) -> None:
        self.blobs: Dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        c = cid_of(data)
        self.blobs[c] = bytes(data)
        return c

    def get(self, cid: str) -> Optional[bytes]:
        return self.blobs.get(cid)

    def has(self, cid: str) -> bool:
        return cid in self.blobs


class DirStore(FragmentStore):
    """Directory store: root/<cid[:2]>/<cid>; atomic writes (tmp + fsync + rename).

    get() returns raw bytes without re-hashing; callers verify the cid (fetch_slot does).
    """

    def __init__(self, root: str) -> None:
        self.root = str(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, cid: str) -> str:
        if len(cid) != 64 or any(ch not in "0123456789abcdef" for ch in cid):
            raise ValueError("bad cid")
        return os.path.join(self.root, cid[:2], cid)

    def put(self, data: bytes) -> str:
        c = cid_of(data)
        p = self._path(c)
        if os.path.exists(p):
            return c
        d = os.path.dirname(p)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return c

    def get(self, cid: str) -> Optional[bytes]:
        try:
            with open(self._path(cid), "rb") as f:
                return f.read()
        except (FileNotFoundError, ValueError):
            return None

    def has(self, cid: str) -> bool:
        try:
            return os.path.exists(self._path(cid))
        except ValueError:
            return False
