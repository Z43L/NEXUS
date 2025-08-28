import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from sklearn.cluster import KMeans
import asyncio
from loguru import logger

@dataclass
class ShardConfig:
    """Configuración de sharding"""
    total_shards: int
    replicas_per_shard: int
    embedding_dimension: int
    recluster_interval: int = 3600  # segundos entre re-clustering
    min_shard_size: int = 10000     # tamaño mínimo antes de considerar división

class ShardManager:
    """Gestor de sharding inteligente basado en embeddings"""
    
    def __init__(self, config: ShardConfig):
        self.config = config
        self.shard_centroids: Dict[str, np.ndarray] = {}
        self.shard_statistics: Dict[str, Dict[str, Any]] = {}
        self._initialize_shards()
    
    def _initialize_shards(self):
        """Inicializa los shards con centroides aleatorios"""
        for i in range(self.config.total_shards):
            shard_id = f"shard_{i:03d}"
            # Centroide aleatorio en espacio de embedding
            centroid = np.random.randn(self.config.embedding_dimension)
            centroid = centroid / np.linalg.norm(centroid)  # Normalizar
            self.shard_centroids[shard_id] = centroid
            self.shard_statistics[shard_id] = {
                'count': 0,
                'last_updated': None,
                'size_bytes': 0
            }
    
    async def initialize(self):
        """Inicialización asíncrona del gestor de shards"""
        logger.info("Inicializando Shard Manager...")
        # Cargar estadísticas existentes si aplica
        await self._load_existing_statistics()
        # Iniciar tarea de mantenimiento periódico
        asyncio.create_task(self._periodic_maintenance())
    
    def locate_shard(self, embedding: List[float]) -> str:
        """
        Encuentra el shard más apropiado para un embedding dado
        
        Args:
            embedding: Vector de embedding a ubicar
            
        Returns:
            str: ID del shard objetivo
        """
        embedding_np = np.array(embedding)
        embedding_np = embedding_np / np.linalg.norm(embedding_np)  # Normalizar
        
        best_shard = None
        best_similarity = -1.0
        
        for shard_id, centroid in self.shard_centroids.items():
            similarity = np.dot(embedding_np, centroid)
            if similarity > best_similarity:
                best_similarity = similarity
                best_shard = shard_id
        
        return best_shard or list(self.shard_centroids.keys())[0]
    
    def identify_relevant_shards(self, query_embedding: List[float], limit: int) -> List[str]:
        """
        Identifica shards relevantes para una consulta de búsqueda
        
        Args:
            query_embedding: Embedding de consulta
            limit: Número máximo de resultados deseados
            
        Returns:
            List[str]: Lista de shards a consultar
        """
        query_np = np.array(query_embedding)
        query_np = query_np / np.linalg.norm(query_np)
        
        # Calcular similitudes con todos los centroides
        similarities = []
        for shard_id, centroid in self.shard_centroids.items():
            similarity = np.dot(query_np, centroid)
            similarities.append((shard_id, similarity))
        
        # Ordenar por similitud descendente
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Seleccionar shards más relevantes
        # Para limit pequeño, consultar menos shards para mejor rendimiento
        max_shards_to_query = min(len(similarities), max(3, limit // 1000))
        return [shard_id for shard_id, sim in similarities[:max_shards_to_query]]
    
    def get_replica_shards(self, primary_shard: str) -> List[str]:
        """
        Obtiene la lista de shards de réplica para un shard primario
        
        Args:
            primary_shard: ID del shard primario
            
        Returns:
            List[str]: IDs de shards de réplica
        """
        # Implementación simple: réplicas consecutivas
        shard_index = int(primary_shard.split('_')[1])
        replica_shards = []
        
        for i in range(1, self.config.replicas_per_shard + 1):
            replica_index = (shard_index + i) % self.config.total_shards
            replica_shards.append(f"shard_{replica_index:03d}")
        
        return replica_shards
