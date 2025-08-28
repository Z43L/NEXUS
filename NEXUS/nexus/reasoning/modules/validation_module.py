from typing import Dict, List, Any, Optional
from ..agent_architecture import ReasoningModule, ReasoningContext
from ...knowledge.graph_engine import KnowledgeGraphEngine

class ValidationModule(ReasoningModule):
    """Módulo de validación y aprendizaje"""
    
    def __init__(self, knowledge_graph: KnowledgeGraphEngine):
        super().__init__("validation", priority=3)
        self.knowledge_graph = knowledge_graph
        self.validation_rules = self._load_validation_rules()
    
    async def execute(self, context: ReasoningContext) -> ReasoningContext:
        """Valida resultados y extrae aprendizajes"""
        final_result = context.current_state.get("final_result")
        task = context.task_description
        
        if not final_result:
            logger.warning("No hay resultado final para validar")
            return context
        
        # Validar contra conocimiento existente
        validation_result = await self._validate_against_knowledge(final_result, task)
        
        # Extraer aprendizajes
        learnings = await self._extract_learnings(context)
        
        # Actualizar grafo de conocimiento
        if validation_result.get("is_valid", False):
            await self._update_knowledge_graph(task, final_result, learnings)
        
        context.current_state.update({
            "validation_result": validation_result,
            "learnings_extracted": learnings,
            "is_valid": validation_result.get("is_valid", False)
        })
        
        context.execution_history.append({
            "module": self.name,
            "action": "result_validation",
            "result": validation_result
        })
        
        return context
    
    async def _validate_against_knowledge(self, result: Dict[str, Any], task: str) -> Dict[str, Any]:
        """Valida el resultado contra el conocimiento existente"""
        # Consultar conocimiento relevante
        relevant_knowledge = await self.knowledge_graph.query({
            "type": "semantic",
            "term": task,
            "similarity_threshold": 0.7
        })
        
        # Verificar consistencia
        inconsistencies = await self._find_inconsistencies(result, relevant_knowledge)
        
        # Calcular score de confianza
        confidence_score = await self._calculate_confidence(result, inconsistencies)
        
        return {
            "is_valid": confidence_score > 0.7,
            "confidence_score": confidence_score,
            "inconsistencies": inconsistencies,
            "relevant_knowledge_used": relevant_knowledge.get("results", [])
        }
    
    async def _extract_learnings(self, context: ReasoningContext) -> List[Dict[str, Any]]:
        """Extrae aprendizajes del proceso de ejecución"""
        learnings = []
        
        # Aprendizajes de ejecución
        execution_learnings = await self._analyze_execution_patterns(context)
        learnings.extend(execution_learnings)
        
        # Aprendizajes de resultados
        result_learnings = await self._analyze_results(context)
        learnings.extend(result_learnings)
        
        # Aprendizajes de errores
        error_learnings = await self._analyze_errors(context)
        learnings.extend(error_learnings)
        
        return learnings
    
    async def _update_knowledge_graph(self, task: str, result: Dict[str, Any], learnings: List[Dict[str, Any]]):
        """Actualiza el grafo de conocimiento con nuevos aprendizajes"""
        # Crear entidad para la tarea completada
        task_entity = {
            "type": "CompletedTask",
            "name": task,
            "properties": {
                "result": result,
                "execution_timestamp": context.current_state.get("execution_timestamp"),
                "complexity": context.current_state.get("complexity_score", 0.5)
            }
        }
        
        # Añadir aprendizajes como relaciones
        for learning in learnings:
            learning_entity = {
                "type": "Learning",
                "name": learning.get("insight"),
                "properties": learning
            }
            
            await self.knowledge_graph.create_entity(learning_entity)
            await self.knowledge_graph.create_relationship({
                "type": "PROVIDES_LEARNING",
                "source_id": task_entity["id"],
                "target_id": learning_entity["id"],
                "properties": {"confidence": learning.get("confidence", 0.8)}
            })