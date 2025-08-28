import aiohttp
import aiofiles
import json
from typing import Dict, Any, Optional
from .tool_manager import ToolDefinition, ToolType

# Herramienta para llamadas API
async def api_call_tool(parameters: Dict[str, Any], context: Optional[Dict] = None) -> Any:
    """Herramienta para realizar llamadas HTTP"""
    url = parameters.get("url")
    method = parameters.get("method", "GET")
    headers = parameters.get("headers", {})
    data = parameters.get("data")
    
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers=headers, json=data) as response:
            response.raise_for_status()
            return await response.json()

# Herramienta para consultas de base de datos
async def database_query_tool(parameters: Dict[str, Any], context: Optional[Dict] = None) -> Any:
    """Herramienta para consultas de base de datos"""
    query = parameters.get("query")
    db_type = parameters.get("db_type", "postgresql")
    
    # Implementación específica según tipo de base de datos
    if db_type == "postgresql":
        import asyncpg
        connection = await asyncpg.connect(parameters.get("connection_string"))
        return await connection.fetch(query)
    else:
        raise ValueError(f"Tipo de base de datos no soportado: {db_type}")

# Herramienta para operaciones de archivo
async def file_operation_tool(parameters: Dict[str, Any], context: Optional[Dict] = None) -> Any:
    """Herramienta para operaciones con archivos"""
    operation = parameters.get("operation")
    file_path = parameters.get("file_path")
    content = parameters.get("content")
    
    if operation == "read":
        async with aiofiles.open(file_path, 'r') as f:
            return await f.read()
    elif operation == "write":
        async with aiofiles.open(file_path, 'w') as f:
            await f.write(content)
        return {"status": "success", "file_written": file_path}
    else:
        raise ValueError(f"Operación no soportada: {operation}")

# Registrar herramientas predefinidas
PREDEFINED_TOOLS = [
    ToolDefinition(
        name="http_request",
        description="Realiza peticiones HTTP a APIs REST",
        type=ToolType.API_CALL,
        parameters={"url": "string", "method": "string", "headers": "object", "data": "object"},
        required_params=["url"],
        execution_function=api_call_tool
    ),
    ToolDefinition(
        name="database_query",
        description="Ejecuta consultas SQL en bases de datos",
        type=ToolType.DATABASE_QUERY,
        parameters={"query": "string", "db_type": "string", "connection_string": "string"},
        required_params=["query"],
        execution_function=database_query_tool
    ),
    ToolDefinition(
        name="file_operations",
        description="Operaciones de lectura/escritura de archivos",
        type=ToolType.FILE_OPERATION,
        parameters={"operation": "string", "file_path": "string", "content": "string"},
        required_params=["operation", "file_path"],
        execution_function=file_operation_tool
    )
]