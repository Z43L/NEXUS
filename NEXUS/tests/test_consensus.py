import pytest
import asyncio
from nexus.consensus.proof_of_knowledge import ProofOfKnowledgeConsensus
from nexus.consensus.reputation_system import ReputationSystem

class TestProofOfKnowledgeConsensus:
    """Suite de pruebas para el consenso Proof-of-Knowledge"""
    
    @pytest.fixture
    async def consensus_system(self):
        """Fixture que inicializa el sistema de consenso"""
        consensus = ProofOfKnowledgeConsensus(network_layer=None, reputation_system=None)
        return consensus
    
    @pytest.fixture
    async def reputation_system(self):
        """Fixture para el sistema de reputación"""
        return ReputationSystem()
    
    @pytest.mark.asyncio
    async def test_knowledge_validation_process(self, consensus_system, reputation_system):
        """Prueba el proceso completo de validación de conocimiento"""
        test_knowledge = {
            "content": "La teoría de la relatividad general fue publicada en 1915",
            "category": "physics_history",
            "sources": ["einstein_1915"],
            "confidence": 0.95
        }
        
        # Simular múltiples validadores
        validator_nodes = ["validator_1", "validator_2", "validator_3", "validator_4"]
        
        # Configurar reputaciones
        for i, node in enumerate(validator_nodes):
            await reputation_system.initialize_reputation(node, 0.5 + i * 0.1)
        
        # Ejecutar validación
        validation_id = await consensus_system.submit_for_validation(test_knowledge, urgency=2)
        assert validation_id is not None, "Debería crear ID de validación"
        
        # Simular votos
        votes = [
            (validator_nodes[0], True, 0.9),  # Voto positivo con alta confianza
            (validator_nodes[1], True, 0.8),  # Voto positivo
            (validator_nodes[2], False, 0.7), # Voto negativo
            (validator_nodes[3], True, 0.85)  # Voto positivo
        ]
        
        for validator, vote, confidence in votes:
            vote_data = {
                "validation_id": validation_id,
                "vote": vote,
                "confidence": confidence,
                "rationale": "Test vote"
            }
            await consensus_system.process_vote(vote_data, validator, b"signature")
        
        # Verificar resultado (debería aprobarse con 3/4 votos positivos)
        validation_result = consensus_system.get_validation_result(validation_id)
        assert validation_result["approved"], "Debería aprobarse por mayoría"
        assert validation_result["confidence"] > 0.8, "Debería tener alta confianza"
        
        # Verificar actualización de reputaciones
        rep_1 = await reputation_system.get_reputation(validator_nodes[0])
        rep_2 = await reputation_system.get_reputation(validator_nodes[2])
        
        assert rep_1 > 0.6, "Validador correcto debería ganar reputación"
        assert rep_2 < 0.5, "Validador incorrecto debería perder reputación"
    
    @pytest.mark.asyncio
    async def test_consensus_timeout_handling(self, consensus_system):
        """Prueba el manejo de timeouts en el consenso"""
        slow_knowledge = {
            "content": "Este conocimiento tendrá validadores lentos",
            "category": "test",
            "confidence": 0.7
        }
        
        validation_id = await consensus_system.submit_for_validation(slow_knowledge, urgency=1)
        
        # Simular timeout
        import time
        time.sleep(consensus_system.validation_timeout + 1)
        
        # Debería tener resultado por timeout
        result = consensus_system.get_validation_result(validation_id)
        assert result["status"] == "timeout", "Debería manejar timeout adecuadamente"
        assert not result["approved"], "No debería aprobarse sin quórum"