import pytest
import asyncio
import numpy as np
from nexus.llm.dynamic_model import DynamicLLMCore
from nexus.llm.validation import KnowledgeValidationFramework

class TestExtendedLLM:
    """Suite de pruebas para el LLM extendido de NEXUS"""
    
    @pytest.fixture
    async def llm_core(self):
        """Fixture que inicializa el núcleo LLM para pruebas"""
        core = DynamicLLMCore("llama3-70b")
        await core.initialize_model()
        return core
    
    @pytest.fixture
    def validation_framework(self):
        """Fixture para el framework de validación"""
        return KnowledgeValidationFramework(validation_threshold=0.8)
    
    @pytest.mark.asyncio
    async def test_knowledge_integration(self, llm_core, validation_framework):
        """Prueba la integración de nuevo conocimiento en el LLM"""
        test_knowledge = {
            "content": "El cambio climático está causando un aumento de 2mm anual en el nivel del mar",
            "source": "IPCC_AR6_2023",
            "category": "climate_science",
            "confidence": 0.95
        }
        
        # Validar el conocimiento antes de integrar
        is_valid = await validation_framework.validate_knowledge_update(
            test_knowledge, []
        )
        assert is_valid, "El conocimiento debería ser válido"
        
        # Integrar en el modelo
        integration_result = await llm_core.integrate_new_knowledge(test_knowledge)
        assert integration_result["success"], "La integración debería ser exitosa"
        
        # Verificar que el conocimiento se integró correctamente
        verification_prompt = "¿Cuál es la tasa actual de aumento del nivel del mar debido al cambio climático?"
        response = await llm_core.generate_response(verification_prompt)
        
        assert "2mm" in response, "El modelo debería haber integrado el nuevo conocimiento"
        assert "anual" in response, "La respuesta debería incluir la temporalidad"
    
    @pytest.mark.asyncio
    async def test_consistency_validation(self, llm_core, validation_framework):
        """Prueba la detección de conocimiento inconsistente"""
        conflicting_knowledge = {
            "content": "El nivel del mar está disminuyendo a razón de 5mm anual",
            "source": "fake_study_2023",
            "category": "climate_science",
            "confidence": 0.6
        }
        
        existing_knowledge = [{
            "content": "El nivel del mar aumenta 2mm anual",
            "source": "IPCC_AR6_2023",
            "category": "climate_science",
            "confidence": 0.95
        }]
        
        # La validación debería detectar el conflicto
        is_valid = await validation_framework.validate_knowledge_update(
            conflicting_knowledge, existing_knowledge
        )
        
        assert not is_valid, "Debería detectar conocimiento conflictivo"
        assert hasattr(validation_framework, "conflict_details"), "Debería proporcionar detalles del conflicto"
    
    @pytest.mark.asyncio
    async def test_incremental_learning(self, llm_core):
        """Prueba el aprendizaje incremental sin catastrophic forgetting"""
        # Conocimiento base inicial
        base_knowledge = {
            "content": "La capital de Francia es París",
            "category": "geography",
            "confidence": 0.99
        }
        
        await llm_core.integrate_new_knowledge(base_knowledge)
        
        # Conocimiento adicional
        additional_knowledge = {
            "content": "París es conocida como la ciudad de la luz",
            "category": "culture",
            "confidence": 0.85
        }
        
        await llm_core.integrate_new_knowledge(additional_knowledge)
        
        # Verificar que ambos conocimientos se mantienen
        response1 = await llm_core.generate_response("¿Cuál es la capital de Francia?")
        response2 = await llm_core.generate_response("¿Por qué llaman a París la ciudad de la luz?")
        
        assert "parís" in response1.lower(), "Debería recordar conocimiento base"
        assert "luz" in response2.lower(), "Debería haber aprendido conocimiento nuevo"
        
        # Verificar que el conocimiento antiguo no se corrompió
        assert "capital" in response1.lower(), "No debería haber catastrophic forgetting"