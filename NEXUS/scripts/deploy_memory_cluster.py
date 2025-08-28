#!/usr/bin/env python3
"""
Script de despliegue para el clúster de memoria de NEXUS
"""

import asyncio
import yaml
from pathlib import Path
from nexus.core.memory.memory_manager import MemoryManager
from loguru import logger

async def deploy_memory_cluster(config_path: str = "config/memory_config.yaml"):
    """Despliega y configura el clúster de memoria"""
    
    # Cargar configuración
    config = load_config(config_path)
    
    try:
        logger.info("🚀 Iniciando despliegue del clúster de memoria...")
        
        # Inicializar gestor de memoria
        memory_manager = MemoryManager(config)
        
        # Inicializar todos los componentes
        await memory_manager.initialize()
        
        # Verificar estado del clúster
        cluster_status = await memory_manager.cluster.get_status()
        logger.info(f"📊 Estado del clúster: {cluster_status}")
        
        # Configurar monitorización
        await setup_monitoring(config['monitoring'])
        
        logger.success("✅ Clúster de memoria desplegado exitosamente!")
        
        return memory_manager
        
    except Exception as e:
        logger.error(f"❌ Error desplegando clúster de memoria: {e}")
        raise

def load_config(config_path: str) -> dict:
    """Carga la configuración desde archivo YAML"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
    
    with open(path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Reemplazar variables de entorno
    config = resolve_env_variables(config)
    
    return config

def resolve_env_variables(config: dict) -> dict:
    """Resuelve variables de entorno en la configuración"""
    import os
    import re
    
    def resolve_value(value):
        if isinstance(value, str):
            match = re.match(r'^\$\{(.+)\}$', value)
            if match:
                env_var = match.group(1)
                return os.getenv(env_var, value)
        elif isinstance(value, dict):
            return {k: resolve_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [resolve_value(v) for v in value]
        return value
    
    return resolve_value(config)

async def setup_monitoring(monitoring_config: dict):
    """Configura el sistema de monitorización"""
    if monitoring_config.get('enabled', False):
        logger.info("📈 Configurando monitorización...")
        # Implementar configuración de Prometheus, Grafana, etc.
        from prometheus_client import start_http_server
        start_http_server(monitoring_config.get('prometheus_port', 9090))
        logger.info(f"📊 Servidor de métricas iniciado en puerto {monitoring_config.get('prometheus_port', 9090)}")

if __name__ == "__main__":
    # Ejemplo de uso
    async def main():
        try:
            manager = await deploy_memory_cluster()
            
            # Mantener el servicio corriendo
            while True:
                await asyncio.sleep(3600)  # Esperar 1 hora
                
        except KeyboardInterrupt:
            logger.info("Apagando clúster de memoria...")
        except Exception as e:
            logger.error(f"Error fatal: {e}")
    
    asyncio.run(main())