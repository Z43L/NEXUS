"""ModelManifest: canonical, versioned, author-signed description of a published model."""
import hashlib
import json
from dataclasses import MISSING, asdict, dataclass, fields

from .errors import ManifestError
from .signing import Signer, verify_signature

FORMAT = "nexus-manifest/1"


@dataclass
class ModelManifest:
    """slots: [{slot, slice, chunk_cids (chunk-major, n fragments per chunk), merkle_root, size, layer_range}]"""
    model_id: str
    version: str
    n_layers: int
    n_slots: int
    n_slices: int
    ec_k: int
    ec_n: int
    cipher: str
    license: str
    author_pubkey: str
    royalty_bps: int
    slots: list
    signature: str = ""
    chunk_size: int = 1 << 20
    format: str = FORMAT

    def _body(self) -> dict:
        d = asdict(self)
        d.pop("signature")
        return d

    def signing_bytes(self) -> bytes:
        """Canonical bytes that the author signs (everything except the signature)."""
        return json.dumps(self._body(), sort_keys=True, separators=(",", ":")).encode()

    def sign(self, signer: Signer) -> "ModelManifest":
        """Set author_pubkey from the signer and sign. Returns self."""
        self.author_pubkey = signer.public_key_hex
        self.signature = signer.sign(self.signing_bytes()).hex()
        return self

    def to_json(self) -> str:
        """Canonical JSON (sorted keys, no whitespace) including the signature."""
        d = self._body()
        d["signature"] = self.signature
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_json(s: str) -> "ModelManifest":
        """Parse; raises ManifestError on unknown format or missing/extra fields."""
        try:
            d = json.loads(s)
        except ValueError as e:
            raise ManifestError("invalid JSON: %s" % e)
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise ManifestError("unsupported manifest format")
        names = {f.name for f in fields(ModelManifest)}
        required = {f.name for f in fields(ModelManifest) if f.default is MISSING}
        if set(d) - names or required - set(d):
            raise ManifestError("manifest fields mismatch")
        return ModelManifest(**d)

    def manifest_id(self) -> str:
        """SHA-256 of the signed manifest: the value to anchor on-chain."""
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    def verify(self) -> bool:
        """True iff the structure is consistent and the author signature is valid."""
        try:
            if self.format != FORMAT or not (1 <= self.ec_k <= self.ec_n <= 255):
                return False
            if len(self.slots) != self.n_slots * self.n_slices or self.chunk_size <= 0:
                return False
            return verify_signature(self.author_pubkey, self.signing_bytes(), bytes.fromhex(self.signature))
        except Exception:
            return False
