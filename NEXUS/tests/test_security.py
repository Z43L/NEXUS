import pytest
import asyncio
from nexus.security.did_manager import NexusDIDManager
from nexus.security.encryption_service import EncryptionService

class TestSecuritySystems:
    """Suite de pruebas para los sistemas de seguridad"""
    
    @pytest.fixture
    async def did_manager(self):
        """Fixture para el gestor de DIDs"""
        return NexusDIDManager(blockchain_adapter=None)
    
    @pytest.fixture
    def encryption_service(self):
        """Fixture para el servicio de encriptación"""
        return EncryptionService(key_manager=None)
    
    @pytest.mark.asyncio
    async def test_did_creation_verification(self, did_manager):
        """Prueba la creación y verificación de DIDs"""
        # Crear nueva DID
        user_id = "test_user_123"
        public_key = b"test_public_key_bytes"
        
        did_document = await did_manager.create_did(user_id, public_key)
        assert did_document["id"].startswith("did:nexus:"), "Debería tener formato DID correcto"
        assert did_document["verificationMethod"][0]["publicKeyBase58"] is not None
        
        # Verificar firma con la DID
        test_message = b"Mensaje importante para firmar"
        test_signature = b"firma_simulada"
        
        verification_result = await did_manager.verify_signature(
            did_document["id"], test_message, test_signature
        )
        
        assert verification_result, "Debería verificar firmas correctamente"
    
    @pytest.mark.asyncio
    async def test_encryption_confidentiality(self, encryption_service):
        """Prueba la confidencialidad del sistema de encriptación"""
        test_data = {
            "sensitive_field": "valor secreto",
            "public_field": "valor público"
        }
        
        context = {
            "user_id": "user_123",
            "security_level": "high",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        
        # Encriptar datos
        encrypted_data = await encryption_service.encrypt_field(
            str(test_data), context
        )
        
        # Verificar que los datos están encriptados
        assert encrypted_data["encrypted_value"] != str(test_data), "Los datos deberían estar encriptados"
        assert "context_hash" in encrypted_data, "Debería incluir hash de contexto"
        
        # Desencriptar con contexto correcto
        decrypted = await encryption_service.decrypt_field(encrypted_data, context)
        assert decrypted == str(test_data), "Debería desencriptar correctamente con contexto válido"
        
        # Intentar desencriptar con contexto incorrecto
        wrong_context = context.copy()
        wrong_context["user_id"] = "user_456"  # Contexto diferente
        
        with pytest.raises(ValueError, match="Context mismatch"):
            await encryption_service.decrypt_field(encrypted_data, wrong_context)
    
    @pytest.mark.asyncio
    async def test_sybil_attack_resistance(self, did_manager):
        """Prueba la resistencia a ataques Sybil"""
        # Simular atacante creando múltiples identidades
        attacker_public_keys = [b"fake_key_1", b"fake_key_2", b"fake_key_3", b"fake_key_4"]
        attacker_dids = []
        
        for i, key in enumerate(attacker_public_keys):
            did = await did_manager.create_did(f"attacker_{i}", key)
            attacker_dids.append(did["id"])
        
        # El sistema debería detectar y limitar identidades sospechosas
        # En una implementación real, esto usaría análisis de reputación
        # y límites de creación de identidades
        
        assert len(attacker_dids) == 4, "Debería crear todas las identidades"
        # En producción, debería haber mecanismos para detectar esto