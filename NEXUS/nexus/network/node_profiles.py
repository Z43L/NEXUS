from typing import Dict, List
from enum import Enum

class NodeTier(Enum):
    TIER_1 = "tier_1"    # Nodos enterprise - Máxima capacidad
    TIER_2 = "tier_2"    # Nodos profesionales - Alta capacidad  
    TIER_3 = "tier_3"    # Nodos estándar - Capacidad media
    TIER_4 = "tier_4"    # Nodos básicos - Capacidad mínima

class Specialization(Enum):
    LLM_INFERENCE = "llm_inference"          # Especializado en inferencia de modelos
    KNOWLEDGE_VALIDATION = "knowledge_validation" # Validación de conocimiento
    VECTOR_SEARCH = "vector_search"          # Búsqueda vectorial
    GRAPH_PROCESSING = "graph_processing"    # Procesamiento de grafos
    ARCHIVAL_STORAGE = "archival_storage"    # Almacenamiento a largo plazo

NODE_TIERS = {
    NodeTier.TIER_1: {
        "description": "Nodos Enterprise",
        "requirements": {
            "cpu_cores": 32,
            "memory_gb": 128,
            "storage_gb": 2000,
            "network_gbps": 10
        },
        "expected_uptime": 99.99,
        "reward_multiplier": 2.0
    },
    NodeTier.TIER_2: {
        "description": "Nodos Profesionales", 
        "requirements": {
            "cpu_cores": 16,
            "memory_gb": 64,
            "storage_gb": 1000,
            "network_gbps": 5
        },
        "expected_uptime": 99.9,
        "reward_multiplier": 1.5
    },
    NodeTier.TIER_3: {
        "description": "Nodos Estándar",
        "requirements": {
            "cpu_cores": 8,
            "memory_gb": 32,
            "storage_gb": 500,
            "network_gbps": 1
        },
        "expected_uptime": 99.0,
        "reward_multiplier": 1.0
    },
    NodeTier.TIER_4: {
        "description": "Nodos Básicos",
        "requirements": {
            "cpu_cores": 4,
            "memory_gb": 16,
            "storage_gb": 250,
            "network_gbps": 0.5
        },
        "expected_uptime": 95.0,
        "reward_multiplier": 0.7
    }
}