from typing import Dict, List, Optional
import json
import base58
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from datetime import datetime, timedelta
import uuid

class NexusDIDManager:
    """Gestor de Identidades Descentralizadas para NEXUS"""
    
    def __init__(self, blockchain_adapter):
        self.blockchain = blockchain_adapter
        self.did_cache = {}
        
    async def create_did(self, user_id: str, public_key: bytes) -> Dict:
        """Crea una nueva identidad descentralizada"""
        did = f"did:nexus:{user_id}:{uuid.uuid4().hex}"
        
        did_document = {
            "@context": "https://www.w3.org/ns/did/v1",
            "id": did,
            "created": datetime.utcnow().isoformat() + "Z",
            "verificationMethod": [{
                "id": f"{did}#keys-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyBase58": base58.b58encode(public_key).decode('utf-8')
            }],
            "authentication": [f"{did}#keys-1"],
            "assertionMethod": [f"{did}#keys-1"]
        }
        
        # Registrar en blockchain
        tx_hash = await self.blockchain.register_did(did, did_document)
        
        return {
            "did": did,
            "document": did_document,
            "transaction_hash": tx_hash
        }
    
    async def verify_signature(self, did: str, message: bytes, signature: bytes) -> bool:
        """Verifica una firma usando la DID"""
        did_doc = await self.resolve_did(did)
        if not did_doc:
            return False
        
        public_key_base58 = did_doc['verificationMethod'][0]['publicKeyBase58']
        public_key_bytes = base58.b58decode(public_key_base58)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
        
        try:
            public_key.verify(signature, message)
            return True
        except:
            return False
    
    async def resolve_did(self, did: str) -> Optional[Dict]:
        """Resuelve una DID a su documento"""
        if did in self.did_cache:
            return self.did_cache[did]
        
        doc = await self.blockchain.resolve_did(did)
        if doc:
            self.did_cache[did] = doc
        return doc