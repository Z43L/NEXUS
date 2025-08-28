# guias/NEXUS/nexus/core/initialization.py

from nexus.core.memory.memory_manager import MemoryManager
from nexus.knowledge.dynamic_graph_engine import DynamicKnowledgeGraph
from nexus.reasoning.advanced_agent import NexusReasoningAgent
from langchain_openai import ChatOpenAI # <-- Importación cambiada
from langchain_community.embeddings import OpenAIEmbeddings
import asyncio
from typing import Dict, Any, List

class NexusCoreInitializer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.components = {}
    
    async def initialize_core_components(self):
        """Inicializa todos los componentes centrales de NEXUS"""
        
        print("🔄 Inicializando componentes centrales de NEXUS...")
        
        # 1. Inicializar modelo de lenguaje base desde OpenRouter
        print("🔌 Configurando LLM desde OpenRouter...")
        self.components['llm'] = ChatOpenAI(
            model_name=self.config['llm']['model'],
            temperature=self.config['llm']['temperature'],
            max_tokens=self.config['llm']['max_tokens'],
            openai_api_key=self.config['llm']['api_key'],
            openai_api_base="https://openrouter.ai/api/v1", # <-- URL de la API de OpenRouter
        )
        
        # 2. Inicializar sistema de memoria (sin cambios)
        self.components['memory'] = MemoryManager(
            self.config['memory']
        )
        await self.components['memory'].initialize()

        # 3. Inicializar grafos de conocimiento (sin cambios)
        self.components['knowledge_graph'] = DynamicKnowledgeGraph(
            db_config=self.config['knowledge_graph']['database']
        )
        self.components['knowledge_graph'].create_knowledge_graph("nexus_core")
        
        # 4. Inicializar embeddings (usando la misma clave de OpenRouter)
        self.components['embeddings'] = OpenAIEmbeddings(
            openai_api_key=self.config['llm']['api_key'],
            openai_api_base="https://openrouter.ai/api/v1",
            model="sentence-transformers/all-minilm-l6-v2" # Modelo de embeddings gratuito en OpenRouter
        )
        
        # 5. Inicializar agente razonador (sin cambios)
        tools = self._initialize_tools()
        self.components['agent'] = NexusReasoningAgent(
            llm=self.components['llm'],
            tools=tools,
            memory_manager=self.components['memory'],
            knowledge_graph=self.components['knowledge_graph']
        )
        
        print("✅ Componentes centrales inicializados exitosamente!")
        return self.components
    
    def _initialize_tools(self) -> List:
        """Inicializa las herramientas del agente"""
        # Implementación de herramientas específicas
        return []