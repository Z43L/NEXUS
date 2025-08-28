from typing import Dict, List, Any, Optional
import re
from ..agent_architecture import ReasoningModule, ReasoningContext
from ...llm.dynamic_model import DynamicLLMCore

class AnalysisModule(ReasoningModule):
    """Módulo de análisis y descomposición de problemas"""
    
    def __init__(self, llm_core: DynamicLLMCore):
        super().__init__("analysis", priority=1)
        self.llm = llm_core
        self.patterns = self._load_analysis_patterns()
    
    async def execute(self, context: ReasoningContext) -> ReasoningContext:
        """Analiza la tarea y la descompone en subtareas"""
        task = context.task_description
        
        # Análisis de complejidad
        complexity_score = await self._assess_complexity(task)
        
        # Identificación de componentes clave
        components = await self._identify_components(task)
        
        # Descomposición en subtareas
        subtasks = await self._decompose_task(task, complexity_score)
        
        # Actualizar contexto
        context.current_state.update({
            "complexity_score": complexity_score,
            "identified_components": components,
            "subtasks": subtasks,
            "current_subtask_index": 0,
            "subtask_results": []
        })
        
        context.execution_history.append({
            "module": self.name,
            "action": "task_decomposition",
            "result": {"subtasks": subtasks, "complexity": complexity_score}
        })
        
        return context
    
    async def _assess_complexity(self, task: str) -> float:
        """Evalúa la complejidad de la tarea"""
        prompt = f"""
        Evalúa la complejidad de la siguiente tarea en una escala de 0.0 a 1.0.
        Considera: amplitud del tema, profundidad requerida, número de conceptos involucrados.
        
        Tarea: {task}
        
        Responde solo con el número de punto flotante.
        """
        
        response = await self.llm.generate(prompt, max_tokens=10)
        try:
            return float(response.strip())
        except ValueError:
            return 0.5  # Valor por defecto
    
    async def _decompose_task(self, task: str, complexity: float) -> List[Dict[str, Any]]:
        """Descompone una tarea compleja en subtareas"""
        prompt = f"""
        Descompone la siguiente tarea en subtareas ordenadas lógicamente.
        Complejidad estimada: {complexity:.2f}
        
        Tarea: {task}
        
        Devuelve una lista JSON con cada subtarea que tenga:
        - id: identificador único
        - description: descripción clara
        - dependencies: tareas previas requeridas
        - estimated_effort: esfuerzo estimado (1-5)
        
        Ejemplo formato: [{{"id": "s1", "description": "...", "dependencies": [], "estimated_effort": 3}}]
        """
        
        response = await self.llm.generate(prompt, max_tokens=500)
        
        try:
            # Extraer JSON de la respuesta
            import json
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return [{"id": "default", "description": task, "dependencies": [], "estimated_effort": 3}]
        except json.JSONDecodeError:
            return [{"id": "default", "description": task, "dependencies": [], "estimated_effort": 3}]