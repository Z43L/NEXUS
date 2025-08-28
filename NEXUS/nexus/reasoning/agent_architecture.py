from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import asyncio
from loguru import logger

class ReasoningState(str, Enum):
    """Estados del proceso de razonamiento"""
    INITIALIZING = "initializing"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VALIDATING = "validating"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ReasoningContext:
    """Contexto completo para el proceso de razonamiento"""
    task_description: str
    initial_state: Dict[str, Any]
    current_state: Dict[str, Any]
    execution_history: List[Dict[str, Any]]
    constraints: Dict[str, Any]
    available_tools: List[str]
    max_iterations: int = 10
    current_iteration: int = 0

class ReasoningModule:
    """Módulo base para componentes de razonamiento"""
    
    def __init__(self, name: str, priority: int = 1):
        self.name = name
        self.priority = priority
        self.is_active = True
    
    async def execute(self, context: ReasoningContext) -> ReasoningContext:
        """Método base para ejecución de módulos"""
        raise NotImplementedError("Los módulos deben implementar execute()")
    
    def _validate_context(self, context: ReasoningContext) -> bool:
        """Valida que el contexto tenga la información necesaria"""
        required_fields = ['task_description', 'current_state']
        return all(field in context for field in required_fields)

class ReasoningOrchestrator:
    """Orquestador principal del proceso de razonamiento"""
    
    def __init__(self):
        self.modules: Dict[str, ReasoningModule] = {}
        self.execution_pipeline: List[str] = []
        self.state_history: List[ReasoningState] = []
    
    def register_module(self, module: ReasoningModule):
        """Registra un módulo de razonamiento"""
        self.modules[module.name] = module
        self.execution_pipeline.append(module.name)
        self.execution_pipeline.sort(key=lambda x: self.modules[x].priority)
    
    async def execute_reasoning(self, task: str, constraints: Optional[Dict] = None) -> Dict[str, Any]:
        """Ejecuta el proceso completo de razonamiento para una tarea"""
        context = ReasoningContext(
            task_description=task,
            initial_state={},
            current_state={"task": task},
            execution_history=[],
            constraints=constraints or {},
            available_tools=self._get_available_tools()
        )
        
        self.state_history.append(ReasoningState.INITIALIZING)
        
        try:
            # Ejecutar todos los módulos en el pipeline
            for module_name in self.execution_pipeline:
                module = self.modules[module_name]
                if module.is_active:
                    logger.info(f"Ejecutando módulo: {module_name}")
                    context = await module.execute(context)
                    self.state_history.append(ReasoningState(module_name.upper()))
            
            self.state_history.append(ReasoningState.COMPLETED)
            return self._prepare_final_result(context)
            
        except Exception as e:
            logger.error(f"Error en el proceso de razonamiento: {e}")
            self.state_history.append(ReasoningState.FAILED)
            return {"error": str(e), "state_history": self.state_history}
