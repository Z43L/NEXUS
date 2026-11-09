"""KeyVault: releases per-slot keys to attested, non-revoked nodes and logs every grant."""
import time
from typing import Callable, Dict, List, Optional

from .crypto import derive_slot_key
from .errors import AttestationError


class KeyVault:
    """grant/revoke over a model master key.

    attestation_verifier(node_id, slot, attestation) -> bool is a SIMULATED stand-in for TEE
    attestation. revoke() blocks future grants only: a key already released cannot be recalled
    (rotate by republishing under a new master key).
    """

    def __init__(self, master_key: bytes,
                 attestation_verifier: Optional[Callable[[str, int, Optional[dict]], bool]] = None) -> None:
        self._master = master_key
        self._verify = attestation_verifier
        self.revoked: set = set()
        self.grants: List[Dict] = []  # audit log: {node_id, slot, ts, ok, reason}

    def _log(self, node_id, slot, ok, reason):
        self.grants.append({"node_id": node_id, "slot": slot, "ts": time.time(), "ok": ok, "reason": reason})

    def grant(self, node_id: str, slot: int, *, attestation: Optional[dict] = None) -> bytes:
        """Return the slot key or raise AttestationError."""
        if node_id in self.revoked:
            self._log(node_id, slot, False, "revoked")
            raise AttestationError("node %s is revoked" % node_id)
        if self._verify is not None and not self._verify(node_id, slot, attestation):
            self._log(node_id, slot, False, "attestation failed")
            raise AttestationError("attestation failed for node %s" % node_id)
        self._log(node_id, slot, True, "ok")
        return derive_slot_key(self._master, slot)

    def revoke(self, node_id: str) -> None:
        """Refuse all further grants to node_id."""
        self.revoked.add(node_id)

    def granted_slots(self, node_id: str) -> List[int]:
        """Slots successfully granted to node_id so far."""
        return sorted({g["slot"] for g in self.grants if g["node_id"] == node_id and g["ok"]})
