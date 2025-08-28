# guias/NEXUS/nexus/core/memory/memory_manager.py

from typing import Dict, Any, List
from loguru import logger
import asyncio

from .weaviate_distributed import DistributedWeaviateCluster
from .shard_manager import ShardConfig
from weaviate.classes.query import NearVector

class MemoryManager:
    """
    Gestiona la conexión y las operaciones con el clúster distribuido de Weaviate.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        shard_config = ShardConfig(**config['sharding'])
        cluster_config = config.get('cluster', {})
        
        self.cluster = DistributedWeaviateCluster(
            nodes=cluster_config.get('nodes', []),
            auth_config=cluster_config.get('auth', {}),
            shard_config=shard_config
        )
        self.client = None
    
    async def initialize(self):
        """Inicializa la conexión con el clúster de Weaviate y crea el esquema."""
        logger.info("🧠 Inicializando el gestor de memoria...")
        retries = 5
        for i in range(retries):
            try:
                if not self.cluster.clients:
                    raise ConnectionError("No se inicializaron clientes de Weaviate.")
                
                self.client = self.cluster.clients[0]

                if not self.client.is_ready():
                     raise ConnectionError(f"El cliente de Weaviate no está listo.")

                await self.cluster.initialize_schema({})
                
                logger.success("✅ Gestor de memoria conectado y esquema asegurado.")
                return
            except Exception as e:
                logger.warning(f"No se pudo conectar a Weaviate (intento {i+1}/{retries}): {e}")
                await asyncio.sleep(5)
        
        logger.error("❌ No se pudo inicializar el gestor de memoria después de varios intentos.")
        raise ConnectionError("No se pudo conectar al clúster de Weaviate.")
    
    async def store_memory(self, collection: str, data: Dict[str, Any], vector: List[float] = None):
        """Almacena una memoria en la base de datos vectorial."""
        if not self.client:
            raise ConnectionError("El cliente de memoria no está inicializado.")
        
        try:
            with self.client.batch.fixed_vector(collection=collection) as batch:
                batch.add_object(
                    properties=data,
                    vector=vector
                )
            logger.info(f"Memoria almacenada en la colección '{collection}'.")
        except Exception as e:
            logger.error(f"Error al almacenar memoria: {e}")

    async def retrieve_memory(self, collection: str, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Recupera memorias relevantes basadas en un vector de consulta."""
        if not self.client:
            raise ConnectionError("El cliente de memoria no está inicializado.")
        
        try:
            response = self.client.query.get(
                collection,
                ["content", "metadata", "timestamp", "sourceNode", "confidenceScore"]
            ).with_near_vector(
                NearVector(vector=query_vector)
            ).with_limit(limit).fetch_objects()
            
            memories = [obj.properties for obj in response.objects]
            logger.info(f"{len(memories)} memorias recuperadas de '{collection}'.")
            return memories
        except Exception as e:
            logger.error(f"Error al recuperar memoria: {e}")
            return []

    def close(self):
        """Cierra todas las conexiones del clúster de Weaviate."""
        try:
            for c in getattr(self.cluster, 'clients', []) or []:
                try:
                    c.close()
                except Exception:
                    pass
        except Exception:
            pass