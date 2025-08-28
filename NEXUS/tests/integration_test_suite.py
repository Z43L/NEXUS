import pytest
import asyncio
from nexus.core.initialization import NexusCoreInitializer
from config.test_config import TEST_CONFIG

class TestNexusIntegration:
    @pytest.fixture(scope="class")
    async def initialized_nexus(self):
        """Fixture que inicializa NEXUS para pruebas"""
        initializer = NexusCoreInitializer(TEST_CONFIG)
        components = await initializer.initialize_core_components()
        yield components
        # Cleanup
        await components['memory'].cleanup()
    
    @pytest.mark.asyncio
    async def test_memory_retrieval(self, initialized_nexus):
        """Prueba la recuperación de memoria"""
        memory = initialized_nexus['memory']
        
        # Almacenar experiencia de prueba
        test_experience = {
            "content": "Prueba de recuperación de memoria",
            "embedding": await initialized_nexus['embeddings'].embed_query("Prueba de memoria"),
            "metadata": {"test": True, "confidence": 0.95},
            "timestamp": "2024-01-01T00:00:00Z"
        }
        
        await memory.store_experience(test_experience)
        
        # Recuperar experiencias similares
        results = await memory.retrieve_relevant_experiences(
            "prueba memoria", 
            limit=5
        )
        
        assert len(results) > 0
        assert results[0]['content'] == test_experience['content']
    
    @pytest.mark.asyncio
    async def test_knowledge_graph_update(self, initialized_nexus):
        """Prueba la actualización del grafo de conocimiento"""
        kg = initialized_nexus['knowledge_graph']
        
        # Añadir entidad de prueba
        entity_id = kg.add_entity(
            "nexus_core",
            "TestConcept",
            {"name": "Inteligencia Artificial", "type": "concept"}
        )
        
        # Verificar que la entidad existe
        assert entity_id is not None
        
        # Actualizar propiedades
        kg.update_entity(
            "nexus_core",
            entity_id,
            {"description": "Sistema capaz de realizar tareas que requieren inteligencia humana"}
        )
    
    @pytest.mark.asyncio
    async def test_agent_reasoning(self, initialized_nexus):
        """Prueba las capacidades de razonamiento del agente"""
        agent = initialized_nexus['agent']
        
        # Tarea de prueba compleja
        result = await agent.execute_complex_task(
            "Analiza las implicaciones éticas de la inteligencia artificial descentralizada " +
            "y propón un framework de gobernanza adecuado."
        )
        
        assert result is not None
        assert 'analysis' in result
        assert 'framework' in result