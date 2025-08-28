# guias/NEXUS/nexus/llm/dynamic_model.py

from typing import Dict, Any
from loguru import logger

class DynamicLLMCore:
    """
    Contenedor para el cliente LLM (ahora gestionado por LangChain).
    Las funcionalidades de fine-tuning y hot-swapping no aplican para modelos de API.
    """
    
    def __init__(self, llm_client: Any):
        self.model = llm_client
        self.base_model_name = llm_client.model_name
        logger.info(f"LLM Core inicializado con el modelo de API: {self.base_model_name}")
        
    async def generate_response(self, prompt: str, **kwargs) -> str:
        """Genera una respuesta utilizando el cliente LLM de LangChain."""
        try:
            # Los modelos de Chat de LangChain esperan una lista de mensajes
            from langchain_core.messages import HumanMessage
            response = await self.model.ainvoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            logger.error(f"Error generando respuesta desde la API: {e}")
            return "Lo siento, ha ocurrido un error al procesar tu solicitud."

    async def integrate_new_knowledge(self, knowledge_data: Dict[str, Any]):
        """
        Placeholder: El fine-tuning no está disponible para modelos de API como OpenRouter.
        """
        logger.warning("La integración de conocimiento (fine-tuning) no es compatible con modelos de API.")
        return {"success": False, "reason": "Fine-tuning no soportado en este modelo."}