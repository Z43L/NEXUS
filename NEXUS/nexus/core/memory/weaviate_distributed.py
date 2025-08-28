import weaviate
from weaviate import WeaviateClient
from weaviate.connect import ConnectionParams
from weaviate.classes.config import DataType, Property
from typing import List, Dict, Any

from .shard_manager import ShardManager, ShardConfig

class DistributedWeaviateCluster:
    """Clúster distribuido de Weaviate con extensiones personalizadas"""

    def __init__(self, nodes: List[Dict[str, str]], auth_config: Dict[str, str], shard_config: ShardConfig):
        self.nodes = nodes
        self.auth_config = auth_config
        self.clients: List[WeaviateClient] = []
        self.shard_manager = ShardManager(shard_config)
        self._initialize_clients()

    def _initialize_clients(self):
        """Inicializa clientes para cada nodo del clúster"""
        for node in self.nodes:
            connection_params = ConnectionParams.from_url(node['url'], grpc_port=50051)
            client = WeaviateClient(
                connection_params=connection_params,
                additional_headers={
                    "X-OpenAI-Api-Key": self.auth_config.get('openai_key', ''),
                    "X-Weaviate-Cluster-Node": node['name']
                }
            )
            client.connect()
            self.clients.append(client)

    async def initialize_schema(self, schema_config: Dict[str, Any]):
        """Inicializa el esquema distribuido across all nodes"""
        # Definir propiedades mínimas compatibles con el cliente v4
        properties = [
            Property(name="content", data_type=DataType.TEXT, description="Contenido principal de la experiencia"),
            Property(
                name="metadata",
                data_type=DataType.OBJECT,
                description="Metadatos de la experiencia",
                nested_properties=[
                    Property(name="key", data_type=DataType.TEXT),
                    Property(name="value", data_type=DataType.TEXT),
                ],
            ),
            Property(name="timestamp", data_type=DataType.DATE, description="Timestamp de creación"),
            Property(name="sourceNode", data_type=DataType.TEXT, description="Nodo origen de la experiencia"),
            Property(name="confidenceScore", data_type=DataType.NUMBER, description="Puntuación de confianza de validation"),
        ]

        for client in self.clients:
            try:
                if not client.collections.exists("NexusExperience"):
                    client.collections.create(
                        name="NexusExperience",
                        properties=properties,
                    )
            except Exception as e:
                print(f"Error creando schema: {e}")
