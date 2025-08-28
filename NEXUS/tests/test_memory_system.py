import pytest
import asyncio
import numpy as np
from nexus.core.memory.memory_manager import MemoryManager
from nexus.core.memory.schema import NexusExperience, MemoryType, ConfidenceLevel

class TestDistributedMemory:
    """Suite de pruebas para el sistema de memoria distribuida"""
    
    @pytest.fixture
    async def memory_manager(self):
        """Fixture que inicializa el gestor de memoria para pruebas"""
        config = {
            "nodes": ["http://localhost:8080"],
            "auth": {"api_key": "test_key"},
            "sharding": {"total_shards": 2, "replicas_per_shard": 1},
            "consistency": {"default_level": "eventual"}
        }
        manager = MemoryManager(config)
        await manager.initialize()
        return manager
    
    @pytest.mark.asyncio
    async def test_experience_storage_retrieval(self, memory_manager):
        """Prueba el almacenamiento y recuperación de experiencias"""
        test_experience = NexusExperience(
            content="El aprendizaje por refuerzo es clave para AGI",
            embedding=[0.1, 0.2, 0.3, 0.4],
            memory_type=MemoryType.KNOWLEDGE_UPDATE,
            metadata={
                "source_node": "test_node",
                "confidence": ConfidenceLevel.HIGH,
                "validation_count": 3
            }
        )
        
        # Almacenar experiencia
        experience_id = await memory_manager.store_experience(test_experience)
        assert experience_id is not None, "Debería generar un ID único"
        
        # Recuperar experiencia
        retrieved = await memory_manager.retrieve_experience(experience_id)
        assert retrieved is not None, "Debería recuperar la experiencia"
        assert retrieved.content == test_experience.content, "El contenido debería ser idéntico"
        assert retrieved.memory_type == test_experience.memory_type, "El tipo debería coincidir"
    
    @pytest.mark.asyncio
    async def test_semantic_search(self, memory_manager):
        """Prueba la búsqueda semántica por similitud"""
        # Almacenar múltiples experiencias relacionadas
        experiences = [
            ("Machine learning requiere grandes datasets", [0.1, 0.2, 0.3]),
            ("Deep learning usa redes neuronales profundas", [0.2, 0.3, 0.4]),
            ("El reinforcement learning se basa en recompensas", [0.15, 0.25, 0.35])
        ]
        
        for content, embedding in experiences:
            experience = NexusExperience(
                content=content,
                embedding=embedding,
                memory_type=MemoryType.KNOWLEDGE_UPDATE
            )
            await memory_manager.store_experience(experience)
        
        # Búsqueda por similitud semántica
        query_embedding = [0.12, 0.22, 0.32]  # Embedding similar al primer resultado
        results = await memory_manager.search_similar_experiences(
            query_embedding=query_embedding,
            limit=2,
            min_confidence=ConfidenceLevel.MEDIUM
        )
        
        assert len(results) == 2, "Debería encontrar resultados similares"
        assert "machine learning" in results[0].content.lower(), "Debería encontrar el más similar"
    
    @pytest.mark.asyncio
    async def test_consistency_under_failure(self, memory_manager):
        """Prueba la consistencia ante fallos de nodos"""
        # Simular fallo de un nodo durante una operación
        original_store = memory_manager.cluster.store_experience
        
        async def failing_store(*args, **kwargs):
            raise ConnectionError("Nodo no disponible")
        
        # Inyectar fallo
        memory_manager.cluster.store_experience = failing_store
        
        try:
            experience = NexusExperience(
                content="Test de tolerancia a fallos",
                embedding=[0.1, 0.2, 0.3],
                memory_type=MemoryType.SYSTEM_EVENT
            )
            
            # Debería manejar el fallo gracefulmente
            with pytest.raises(Exception):
                await memory_manager.store_experience(experience)
                
        finally:
            # Restaurar función original
            memory_manager.cluster.store_experience = original_store
        
        # Verificar que el sistema se recupera
        experience = NexusExperience(
            content="Test de recuperación",
            embedding=[0.1, 0.2, 0.3],
            memory_type=MemoryType.SYSTEM_EVENT
        )
        
        experience_id = await memory_manager.store_experience(experience)
        assert experience_id is not None, "Debería recuperarse después del fallo"