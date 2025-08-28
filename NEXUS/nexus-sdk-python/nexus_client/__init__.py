import aiohttp
import json
from typing import Dict, List, Optional, AsyncGenerator
from datetime import datetime
from pydantic import BaseModel

class NexusClient:
    """Cliente Python para la API de NEXUS"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.nexus.ai"):
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Método interno para realizar requests"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        async with self.session.request(method, url, headers=headers, **kwargs) as response:
            if response.status != 200:
                error_data = await response.json()
                raise NexusAPIError(
                    f"API request failed: {error_data.get('error', 'Unknown error')}",
                    response.status
                )
            
            return await response.json()
    
    async def query(self, query: str, **kwargs) -> Dict:
        """Realiza una consulta de conocimiento"""
        data = {"query": query, **kwargs}
        return await self._make_request("POST", "/v1/cognitive/query", json=data)
    
    async def infer(self, task: str, **kwargs) -> Dict:
        """Solicita inferencia compleja"""
        data = {"task": task, **kwargs}
        return await self._make_request("POST", "/v1/cognitive/infer", json=data)
    
    async def chat(self, message: str, context: Optional[Dict] = None) -> AsyncGenerator[str, None]:
        """Streaming de chat con NEXUS"""
        data = {"message": message, "context": context or {}, "stream": True}
        
        async with self.session.post(
            f"{self.base_url}/v1/cognitive/chat",
            headers={"X-API-Key": self.api_key},
            json=data
        ) as response:
            async for line in response.content:
                if line:
                    yield line.decode().strip()
    
    async def upload_knowledge(self, content: str, metadata: Optional[Dict] = None) -> str:
        """Sube conocimiento a NEXUS"""
        data = {"content": content, "metadata": metadata or {}}
        response = await self._make_request("POST", "/v1/knowledge/upload", json=data)
        return response["knowledge_id"]
    
    async def get_rate_limit_info(self) -> Dict:
        """Obtiene información de rate limit"""
        return await self._make_request("GET", "/v1/auth/rate_limit")

class NexusAPIError(Exception):
    """Excepción personalizada para errores de la API"""
    
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code

# Ejemplo de uso
async def example_usage():
    async with NexusClient("your_api_key") as client:
        # Consulta simple
        result = await client.query("¿Qué es el aprendizaje por refuerzo?")
        print(result)
        
        # Chat streaming
        async for chunk in client.chat("Explícame la teoría de la relatividad"):
            print(chunk, end="")