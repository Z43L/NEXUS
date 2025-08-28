#!/usr/bin/env python3
"""
Script de despliegue para el Agente Razonador de NEXUS
"""

import asyncio
import yaml
from pathlib import Path
from loguru import logger
from nexus.reasoning.agent_architecture import ReasoningOrchestrator
from nexus.reasoning.modules.analysis_module import AnalysisModule
from nexus.reasoning.modules.planning_module import PlanningModule
from nexus.reasoning.modules.validation_module import ValidationModule
from nexus.llm.dynamic_model import DynamicLLMCore
from nexus.knowledge.graph_engine import KnowledgeGraphEngine
from nexus.tools.tool_manager import ToolManager
from nexus.tools.predefined_tools import PREDEFINED_TOOLS

async def deploy_reasoning_agent(config_path: str = "config/reasoning_agent.yaml"):
    """Despliega e inicializa el Agente Razonador"""
    
    # Cargar configuración
    config = load_config(config_path)
    
    try:
        logger.info("🚀 Iniciando despliegue del Agente Razonador...")
        
        # Inicializar componentes dependientes
        llm_core = await initialize_llm(config['llm'])
        knowledge_graph = await initialize_knowledge_graph()
        tool_manager = await initialize_tool_manager()
        
        # Crear orquestador
        orchestrator = ReasoningOrchestrator()
        
        # Registrar módulos
        analysis_module = AnalysisModule(llm_core)
        planning_module = PlanningModule(llm_core, tool_manager, config=config)
        validation_module = ValidationModule(knowledge_graph)
        
        orchestrator.register_module(analysis_module)
        orchestrator.register_module(planning_module)
        orchestrator.register_module(validation_module)
        
        # Inicializar monitorización
        await initialize_monitoring(config['monitoring'])
        
        logger.success("✅ Agente Razonador desplegado exitosamente!")
        return orchestrator
        
    except Exception as e:
        logger.error(f"❌ Error desplegando Agente Razonador: {e}")
        raise

async def initialize_llm(llm_config: Dict[str, Any]) -> DynamicLLMCore:
    """Inicializa el núcleo LLM"""
    logger.info("Initializando LLM Core...")
    llm = DynamicLLMCore(llm_config.get('model', 'llama3-70b'))
    await llm.initialize_model()
    return llm

async def initialize_knowledge_graph() -> KnowledgeGraphEngine:
    """Inicializa el motor de grafos de conocimiento"""
    logger.info("Initializando Knowledge Graph...")
    # Configuración de conexión a Neo4j
    graph_config = {
        "uri": "bolt://localhost:7687",
        "auth": ("neo4j", "password"),
        "encrypted": False
    }
    graph_engine = KnowledgeGraphEngine(graph_config)
    await graph_engine.initialize()
    return graph_engine

async def initialize_tool_manager() -> ToolManager:
    """Inicializa el gestor de herramientas"""
    logger.info("Initializando Tool Manager...")
    tool_manager = ToolManager()
    
    # Registrar herramientas predefinidas
    for tool in PREDEFINED_TOOLS:
        tool_manager.register_tool(tool)
    
    return tool_manager

async def initialize_monitoring(monitoring_config: Dict[str, Any]):
    """Inicializa el sistema de monitorización"""
    if monitoring_config.get('enabled', False):
        logger.info("📈 Configurando monitorización...")
        # Iniciar servidor de métricas
        from prometheus_client import start_http_server
        start_http_server(monitoring_config.get('prometheus_port', 9090))
        logger.info(f"📊 Servidor de métricas iniciado en puerto {monitoring_config.get('prometheus_port', 9090)}")

def load_config(config_path: str) -> Dict[str, Any]:
    """Carga configuración desde archivo YAML"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
    
    with open(path, 'r') as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    # Ejemplo de uso del agente
    async def main():
        try:
            agent = await deploy_reasoning_agent()
            
            # Ejemplo de ejecución de tarea
            result = await agent.execute_reasoning(
                "Analiza el impacto del cambio climático en la agricultura europea y propón estrategias de adaptación",
                constraints={"max_resources": 5, "time_limit": 300}
            )
            
            logger.info(f"Resultado de la tarea: {result.get('status', 'unknown')}")
            
        except KeyboardInterrupt:
            logger.info("Apagando Agente Razonador...")
        except Exception as e:
            logger.error(f"Error fatal: {e}")
    
    asyncio.run(main())