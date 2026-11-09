"""nexus_storage: publish a model as encrypted, erasure-coded, Merkle-anchored slots; fetch verified slots."""
from .chunker import merkle_proof, merkle_root, split_chunks, verify_proof
from .crypto import (AesGcmCipher, Cipher, HmacCtrCipher, derive_slot_key, get_cipher,
                     hkdf, new_master_key)
from .erasure import decode, encode
from .errors import (AttestationError, DecryptionError, IntegrityError, ManifestError,
                     NexusStorageError, QuorumError)
from .manifest import ModelManifest
from .publish import fetch_slot, publish_model
from .signing import (CryptographyEd25519Signer, Ed25519Signer, PurePythonEd25519Signer,
                      Signer, generate_signer, verify_signature)
from .store import DirStore, FragmentStore, MemoryStore, cid_of
from .vault import KeyVault

__all__ = [n for n in dir() if not n.startswith("_")]
