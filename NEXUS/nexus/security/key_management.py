from typing import Dict, List, Optional
import os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet
import base64
from datetime import datetime, timedelta

class KeyManager:
    """Gestor seguro de claves criptográficas"""
    
    def __init__(self, storage_backend):
        self.storage = storage_backend
        self.current_keys = {}
        self.key_rotation_intervals = {
            'encryption': timedelta(days=90),
            'signing': timedelta(days=30),
            'authentication': timedelta(days=60)
        }
    
    async def generate_key_pair(self, key_type: str, key_size: int = 2048) -> Dict:
        """Genera un nuevo par de claves"""
        if key_type == 'rsa':
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=key_size,
                backend=default_backend()
            )
        else:
            raise ValueError(f"Tipo de clave no soportado: {key_type}")
        
        public_key = private_key.public_key()
        
        key_id = f"key_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        # Serializar y almacenar claves
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        await self.storage.store_key(key_id, {
            'private_key': base64.b64encode(private_pem).decode('utf-8'),
            'public_key': base64.b64encode(public_pem).decode('utf-8'),
            'key_type': key_type,
            'created_at': datetime.utcnow().isoformat(),
            'expires_at': (datetime.utcnow() + self.key_rotation_intervals['encryption']).isoformat()
        })
        
        self.current_keys[key_id] = {
            'private_key': private_key,
            'public_key': public_key,
            'expires_at': datetime.utcnow() + self.key_rotation_intervals['encryption']
        }
        
        return {'key_id': key_id, 'public_key': public_pem}
    
    async def rotate_keys(self) -> List[str]:
        """Rota las claves expiradas"""
        rotated_keys = []
        current_time = datetime.utcnow()
        
        for key_id, key_info in list(self.current_keys.items()):
            if current_time >= key_info['expires_at']:
                # Generar nueva clave
                new_key = await self.generate_key_pair('rsa')
                rotated_keys.append(key_id)
                
                # Programar eliminación segura de la clave antigua
                await self.schedule_key_destruction(key_id)
        
        return rotated_keys
    
    async def encrypt_data(self, data: bytes, key_id: str) -> Dict:
        """Encripta datos usando una clave específica"""
        if key_id not in self.current_keys:
            raise ValueError(f"Clave no encontrada: {key_id}")
        
        public_key = self.current_keys[key_id]['public_key']
        
        # Encriptación híbrida: RSA + AES
        aes_key = Fernet.generate_key()
        fernet = Fernet(aes_key)
        
        # Encriptar datos con AES
        encrypted_data = fernet.encrypt(data)
        
        # Encriptar clave AES con RSA
        encrypted_aes_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        return {
            'encrypted_data': base64.b64encode(encrypted_data).decode('utf-8'),
            'encrypted_key': base64.b64encode(encrypted_aes_key).decode('utf-8'),
            'key_id': key_id,
            'timestamp': datetime.utcnow().isoformat()
        }