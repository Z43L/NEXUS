from typing import Dict, List, Any, Optional, Callable
import asyncio
from dataclasses import dataclass
from enum import Enum
import inspect
from loguru import logger

class ToolType(str, Enum):
    API_CALL = "api_call"
    DATABASE_QUERY = "database_query"
    FILE_OPERATION = "file_operation"
    EXTERNAL_PROCESS = "external_process"
    CUSTOM_FUNCTION = "custom_function"

@dataclass
class ToolDefinition:
    name: str
    description: str
    type: ToolType
    parameters: Dict[str, Any]
    execution_function: Callable
    required_params: List[str]
    timeout: int = 30

class ToolExecutionResult:
    """Resultado de la ejecución de una herramienta"""
    
    def __init__(self, success: bool, data: Any = None, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "data": self.data, "error": self.error}

class ToolManager:
    """Gestor de herramientas para ejecución de tareas"""
    
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.execution_history: List[Dict[str, Any]] = []
    
    def register_tool(self, tool: ToolDefinition):
        """Registra una nueva herramienta"""
        self.tools[tool.name] = tool
        logger.info(f"Herramienta registrada: {tool.name}")
    
    async def execute_tool(self, 
                         tool_name: str, 
                         parameters: Dict[str, Any], 
                         context: Optional[Dict] = None) -> ToolExecutionResult:
        """Ejecuta una herramienta con los parámetros dados"""
        if tool_name not in self.tools:
            return ToolExecutionResult(False, error=f"Herramienta no encontrada: {tool_name}")
        
        tool = self.tools[tool_name]
        
        # Validar parámetros requeridos
        missing_params = [p for p in tool.required_params if p not in parameters]
        if missing_params:
            return ToolExecutionResult(
                False, 
                error=f"Parámetros requeridos faltantes: {missing_params}"
            )
        
        try:
            # Ejecutar con timeout
            if inspect.iscoroutinefunction(tool.execution_function):
                result = await asyncio.wait_for(
                    tool.execution_function(parameters, context),
                    timeout=tool.timeout
                )
            else:
                # Ejecutar función sincrónica en thread separado
                result = await asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: tool.execution_function(parameters, context)
                )
            
            self.execution_history.append({
                "tool": tool_name,
                "parameters": parameters,
                "success": True,
                "timestamp": asyncio.get_event_loop().time()
            })
            
            return ToolExecutionResult(True, data=result)
            
        except asyncio.TimeoutError:
            error_msg = f"Timeout ejecutando herramienta {tool_name}"
            logger.error(error_msg)
            return ToolExecutionResult(False, error=error_msg)
            
        except Exception as e:
            error_msg = f"Error ejecutando herramienta {tool_name}: {str(e)}"
            logger.error(error_msg)
            return ToolExecutionResult(False, error=error_msg)
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Devuelve lista de herramientas disponibles"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "type": tool.type.value,
                "required_params": tool.required_params
            }
            for tool in self.tools.values()
        ]