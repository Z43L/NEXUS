from typing import Dict, Optional
from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
from datetime import datetime, timedelta

class EncryptionService:
    """Servicio de cifrado para datos en reposo y tránsito"""
    
    def __init__(self, key_manager):
        self.key_manager = key_manager
        self.fernet_keys = self._initialize_fernet_keys()
    
    def _initialize_fernet_keys(self) -> MultiFernet:
        """Inicializa las claves Fernet para cifrado simétrico"""
        # En producción, estas claves deberían venir de un HSM o KMS
        keys = [
            Fernet(base64.urlsafe_b64encode(os.urandom(32))),
            Fernet(base64.urlsafe_b64encode(os.urandom(32)))
        ]
        return MultiFernet(keys)
    
    async def encrypt_field(self, field_value: str, context: Dict) -> Dict:
        """Cifra un campo individual con metadatos de contexto"""
        # Derivar clave específica del contexto
        context_key = self._derive_context_key(context)
        
        # Cifrar el valor
        encrypted_value = context_key.encrypt(field_value.encode('utf-8'))
        
        return {
            'encrypted_value': base64.b64encode(encrypted_value).decode('utf-8'),
            'context_hash': self._hash_context(context),
            'timestamp': datetime.utcnow().isoformat(),
            'algorithm': 'AES256-GCM'
        }
    
    async def decrypt_field(self, encrypted_data: Dict, context: Dict) -> str:
        """Descifra un campo usando el contexto"""
        # Verificar que el contexto coincide
        expected_hash = self._hash_context(context)
        if encrypted_data['context_hash'] != expected_hash:
            raise ValueError("Context mismatch - cannot decrypt")
        
        # Derivar la clave del contexto
        context_key = self._derive_context_key(context)
        
        # Descifrar el valor
        encrypted_bytes = base64.b64decode(encrypted_data['encrypted_value'])
        decrypted_bytes = context_key.decrypt(encrypted_bytes)
        
        return decrypted_bytes.decode('utf-8')
    
    def _derive_context_key(self, context: Dict) -> Fernet:
        """Deriva una clave Fernet del contexto"""
        # Serializar y hashear el contexto
        context_str = str(sorted(context.items()))
        context_hash = hashes.Hash(hashes.SHA256())
        context_hash.update(context_str.encode('utf-8'))
        context_digest = context_hash.finalize()
        
        # Usar KDF para derivar clave
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=context_digest[:16],
            iterations=100000
        )
        
        key = kdf.derive(context_digest)
        return Fernet(base64.urlsafe_b64encode(key))
    
    def _hash_context(self, context: Dict) -> str:
        """Calcula hash del contexto para verificación"""
        context_str = str(sorted(context.items()))
        context_hash = hashes.Hash(hashes.SHA256())
        context_hash.update(context_str.encode('utf-8'))
        return base64.b64encode(context_hash.finalize()).decode('utf-8')