from typing import Dict, List, Any, Optional
import networkx as nx
from ..agent_architecture import ReasoningModule, ReasoningContext
from ...llm.dynamic_model import DynamicLLMCore
from ...tools.tool_manager import ToolManager

class PlanningModule(ReasoningModule):
    """Módulo de planificación y ejecución de tareas"""
    
    def __init__(self, llm_core: DynamicLLMCore, tool_manager: ToolManager, config: Optional[Dict[str, Any]] = None):
        super().__init__("planning", priority=2)
        self.llm = llm_core
        self.tool_manager = tool_manager
        self.config = config or {}
        self.execution_graph = nx.DiGraph()
    
    async def execute(self, context: ReasoningContext) -> ReasoningContext:
        """Planifica y ejecuta las subtareas"""
        subtasks = context.current_state.get("subtasks", [])
        
        if not subtasks:
            # Si no hay subtasks, ejecutar directamente
            result = await self._execute_single_task(context.task_description, context)
            context.current_state["final_result"] = result
            return context
        
        # Construir grafo de dependencias
        self._build_execution_graph(subtasks)
        
        # Ejecutar en orden topológico
        execution_order = list(nx.topological_sort(self.execution_graph))
        
        for task_id in execution_order:
            task = next(t for t in subtasks if t["id"] == task_id)
            
            # Verificar dependencias
            dependencies_met = await self._check_dependencies(task, context)
            
            if dependencies_met:
                # Ejecutar subtarea
                result = await self._execute_subtask(task, context)
                
                # Almacenar resultado
                context.current_state["subtask_results"].append({
                    "task_id": task_id,
                    "result": result,
                    "success": result.get("success", False)
                })
                
                context.execution_history.append({
                    "module": self.name,
                    "action": "subtask_execution",
                    "task_id": task_id,
                    "result": result
                })
        
        # Sintetizar resultados finales
        final_result = await self._synthesize_results(context)
        context.current_state["final_result"] = final_result
        
        return context
    
    def _build_execution_graph(self, subtasks: List[Dict[str, Any]]):
        """Construye grafo de dependencias para ejecución"""
        self.execution_graph.clear()
        
        for task in subtasks:
            self.execution_graph.add_node(task["id"], task=task)
            
            for dep in task.get("dependencies", []):
                self.execution_graph.add_edge(dep, task["id"])
    
    async def _execute_subtask(self, task: Dict[str, Any], context: ReasoningContext) -> Dict[str, Any]:
        """Ejecuta una subtarea individual"""
        task_description = task["description"]
        
        # Determinar si requiere herramientas externas
        requires_tools = await self._requires_external_tools(task_description)
        
        if requires_tools:
            # Usar herramientas para ejecución
            return await self._execute_with_tools(task_description, context)
        else:
            # Ejecución con LLM
            return await self._execute_with_llm(task_description, context)
    
    async def _execute_with_tools(self, task: str, context: ReasoningContext) -> Dict[str, Any]:
        """Ejecuta una tarea usando herramientas externas"""
        from ...tools.tool_manager import ToolExecutionResult
        
        # Planificar uso de herramientas
        tool_plan = await self._plan_tool_usage(task)
        
        # Preparar contexto para herramientas, inyectando configuración del proveedor
        tool_context = {
            "ethereum": {
                "provider_url": self.config.get("blockchain", {}).get("ethereum_provider_url")
            }
        }

        # Ejecutar plan
        results = []
        for step in tool_plan:
            try:
                result = await self.tool_manager.execute_tool(
                    step["tool"], step["parameters"], tool_context
                )
                results.append(result.to_dict())
            except Exception as e:
                results.append({"error": str(e), "success": False})
        
        return {
            "success": all(r.get("success", False) for r in results),
            "tool_results": results,
            "task": task
        }