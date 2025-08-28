import weaviate
from weaviate import Client
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.init import Auth
from typing import List, Dict, Any
import numpy as np

class DistributedVectorMemory:
    def __init__(self, cluster_nodes: List[str], auth_config: Dict[str, str]):
        self.clients = []
        for node in cluster_nodes:
            client = weaviate.Client(
                url=node,
                auth_client_secret=Auth.api_key(auth_config['api_key']),
                additional_headers={
                    "X-OpenAI-Api-Key": auth_config.get('openai_key', '')
                }
            )
            self.clients.append(client)
        
        self.shard_manager = ShardManager(cluster_nodes)
        
    def initialize_schema(self):
        """Inicializa el esquema de la base de datos vectorial para experiencias"""
        experience_class = {
            "class": "NexusExperience",
            "description": "Una experiencia o recuerdo del sistema NEXUS",
            "vectorizer": "text2vec-openai",
            "moduleConfig": {
                "text2vec-openai": {
                    "model": "text-embedding-3-large",
                    "type": "text"
                }
            },
            "properties": [
                {
                    "name": "content",
                    "dataType": ["text"],
                    "description": "Contenido principal de la experiencia"
                },
                {
                    "name": "embedding",
                    "dataType": ["number[]"],
                    "description": "Embedding vector de la experiencia"
                },
                {
                    "name": "metadata",
                    "dataType": ["NexusMetadata"],
                    "description": "Metadatos de la experiencia"
                },
                {
                    "name": "timestamp",
                    "dataType": ["date"],
                    "description": "Timestamp de creación"
                },
                {
                    "name": "sourceNode",
                    "dataType": ["string"],
                    "description": "Nodo origen de la experiencia"
                },
                {
                    "name": "confidenceScore",
                    "dataType": ["number"],
                    "description": "Puntuación de confianza de validación"
                }
            ],
            "vectorIndexType": "hnsw",
            "vectorIndexConfig": {
                "distance": "cosine"
            }
        }
        
        for client in self.clients:
            client.schema.create_class(experience_class)