from typing import Dict, List, Any, Optional
import asyncio
from loguru import logger

class KnowledgeIntegrationService:
    """Servicio de integración con otros componentes de NEXUS"""
    
    def __init__(self, graph_engine, memory_manager, reasoning_agent):
        self.graph_engine = graph_engine
        self.memory_manager = memory_manager
        self.reasoning_agent = reasoning_agent
        self.integration_handlers = {
            "memory_sync": self._handle_memory_sync,
            "reasoning_support": self._handle_reasoning_support,
            "validation_request": self._handle_validation_request
        }
    
    async def handle_integration_request(self, 
                                      request_type: str, 
                                      data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Maneja solicitudes de integración de otros componentes
        
        Args:
            request_type: Tipo de solicitud
            data: Datos de la solicitud
            
        Returns:
            Respuesta a la solicitud
        """
        handler = self.integration_handlers.get(request_type)
        
        if not handler:
            return {"error": f"Tipo de solicitud no soportado: {request_type}"}
        
        try:
            return await handler(data)
        except Exception as e:
            logger.error(f"Error manejando solicitud {request_type}: {e}")
            return {"error": str(e)}
    
    async def _handle_memory_sync(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sincroniza conocimiento entre el grafo y la memoria extendida"""
        # Implementar sincronización bidireccional
        sync_direction = data.get("direction", "both")
        
        if sync_direction in ["graph_to_memory", "both"]:
            await self._sync_graph_to_memory()
        
        if sync_direction in ["memory_to_graph", "both"]:
            await self._sync_memory_to_graph()
        
        return {"status": "sync_completed", "direction": sync_direction}
    
    async def _handle_reasoning_support(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Proporciona soporte de conocimiento para el agente razonador"""
        query = data.get("query", {})
        context = data.get("context", {})
        
        # Ejecutar consulta en el grafo
        results = await self.graph_engine.execute_query(query)
        
        # Enriquecer resultados con contexto
        enriched_results = await self._enrich_with_context(results, context)
        
        return {
            "results": enriched_results,
            "context_used": context
        }
