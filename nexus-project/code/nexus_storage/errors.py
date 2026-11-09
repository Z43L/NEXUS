"""Exception types for nexus_storage."""


class NexusStorageError(Exception):
    """Base class for all nexus_storage errors."""


class QuorumError(NexusStorageError):
    """Fewer than k valid fragments are available for a chunk."""


class IntegrityError(NexusStorageError):
    """Reconstructed data does not match the Merkle root / CID."""


class DecryptionError(NexusStorageError):
    """Authentication tag mismatch: wrong key or tampered ciphertext."""


class ManifestError(NexusStorageError):
    """Manifest is malformed or its signature does not verify."""


class AttestationError(NexusStorageError, PermissionError):
    """Key release refused (failed attestation or revoked node)."""
