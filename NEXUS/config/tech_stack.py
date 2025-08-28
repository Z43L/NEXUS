from typing import Dict, List
from dataclasses import dataclass

@dataclass
class TechnologyStack:
    # Blockchain y Consenso
    blockchain_framework: str = "Substrate (Rust)"
    consensus_algorithm: str = "Proof-of-Knowledge"
    smart_contract_lang: str = "ink! (Rust)"
    
    # Procesamiento de Lenguaje Natural
    llm_base: str = "LLaMA 3 70B"  # Base inicial, con capacidad de fine-tuning
    embedding_models: List[str] = ["text-embedding-3-large"]
    nlp_framework: str = "LangChain + custom extensions"
    
    # Almacenamiento y Bases de Datos
    vector_database: str = "Weaviate con extensiones personalizadas"
    graph_database: str = "Apache AGE (PostgreSQL extension)"
    distributed_storage: str = "IPFS + S3 compatible storage"
    
    # Infraestructura y Red
    p2p_network: str = "libp2p"
    containerization: str = "Docker + Kubernetes"
    monitoring: str = "Prometheus + Grafana"
    
    # Desarrollo y APIs
    api_framework: str = "FastAPI"
    sdks: List[str] = ["Python", "JavaScript", "Rust", "Go"]
    ci_cd: str = "GitHub Actions + ArgoCD"

# Configuración específica para cada entorno
DEVELOPMENT_STACK = TechnologyStack()
PRODUCTION_STACK = TechnologyStack(
    llm_base="LLaMA 3 400B",  # Modelo más potente para producción
    embedding_models=["text-embedding-3-large", "custom-trained-embeddings"]
)