from typing import Dict, List, Any, Optional
import asyncio
from loguru import logger
from .schema import KnowledgeEntity, KnowledgeRelation

class KnowledgeProcessingPipeline:
    """Pipeline para procesamiento y extracción de conocimiento"""
    
    def __init__(self, nlp_processor, graph_engine):
        self.nlp_processor = nlp_processor
        self.graph_engine = graph_engine
        self.pipeline_stages = [
            self._stage_text_normalization,
            self._stage_entity_extraction,
            self._stage_relation_extraction,
            self._stage_knowledge_validation,
            self._stage_graph_integration
        ]
    
    async def process_text(self, text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Procesa texto para extraer conocimiento y actualizar el grafo
        
        Args:
            text: Texto a procesar
            context: Contexto adicional para el procesamiento
            
        Returns:
            Dict con entidades y relaciones extraídas
        """
        results = {
            "entities": [],
            "relations": [],
            "metadata": {
                "processing_time": 0,
                "entities_extracted": 0,
                "relations_extracted": 0
            }
        }
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Ejecutar todas las etapas del pipeline
            current_data = {"text": text, "context": context or {}}
            
            for stage in self.pipeline_stages:
                current_data = await stage(current_data)
                if "error" in current_data:
                    raise Exception(f"Error en etapa del pipeline: {current_data['error']}")
            
            # Recopilar resultados
            results["entities"] = current_data.get("entities", [])
            results["relations"] = current_data.get("relations", [])
            results["metadata"]["entities_extracted"] = len(results["entities"])
            results["metadata"]["relations_extracted"] = len(results["relations"])
            
        except Exception as e:
            logger.error(f"Error procesando texto: {e}")
            results["error"] = str(e)
        
        finally:
            results["metadata"]["processing_time"] = asyncio.get_event_loop().time() - start_time
            return results
    
    async def _stage_text_normalization(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Etapa de normalización y preprocesamiento de texto"""
        text = data["text"]
        
        # Implementar normalización: lowercase, remove special chars, etc.
        normalized_text = text.lower().strip()
        
        # Tokenización y otros procesos NLP
        tokens = await self.nlp_processor.tokenize(normalized_text)
        
        return {**data, "normalized_text": normalized_text, "tokens": tokens}
    
    async def _stage_entity_extraction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Etapa de extracción de entidades"""
        # Usar modelos NLP para identificar entidades
        entities = await self.nlp_processor.extract_entities(
            data["normalized_text"], 
            data["context"]
        )
        
        # Convertir a formato KnowledgeEntity
        knowledge_entities = [
            KnowledgeEntity(
                type=entity["type"],
                name=entity["text"],
                properties=entity.get("properties", {}),
                confidence=entity.get("confidence", 0.8)
            )
            for entity in entities
        ]
        
        return {**data, "entities": knowledge_entities}
    
    async def _stage_relation_extraction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Etapa de extracción de relaciones"""
        entities = data["entities"]
        
        if len(entities) < 2:
            return {**data, "relations": []}
        
        # Extraer relaciones entre entidades
        relations = await self.nlp_processor.extract_relations(
            data["normalized_text"],
            entities,
            data["context"]
        )
        
        # Convertir a formato KnowledgeRelation
        knowledge_relations = [
            KnowledgeRelation(
                type=relation["type"],
                source_id=relation["source_id"],
                target_id=relation["target_id"],
                properties=relation.get("properties", {}),
                confidence=relation.get("confidence", 0.7)
            )
            for relation in relations
        ]
        
        return {**data, "relations": knowledge_relations}