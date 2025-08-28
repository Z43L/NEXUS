from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

class NodeRole(Enum):
    INFERENCE = "inference"      # Procesamiento de modelos de IA
    VALIDATION = "validation"    # Validación de conocimiento
    STORAGE = "storage"          # Almacenamiento distribuido
    HYBRID = "hybrid"           # Múltiples roles (para nodos potentes)

@dataclass
class NodeRequirements:
    """Requisitos mínimos para cada tipo de nodo"""
    min_memory_gb: int
    min_storage_gb: int
    min_cpu_cores: int
    min_network_mbps: int
    gpu_required: bool
    gpu_memory_min: Optional[int] = None
    ssd_required: bool = False

@dataclass
class NodeSpecs:
    """Especificaciones técnicas de un nodo"""
    node_id: str
    role: NodeRole
    public_key: str
    ip_address: str
    region: str
    specs: NodeRequirements
    reputation: float
    last_seen: datetime
    available_resources: Dict[str, float]

# Requisitos por tipo de nodo
NODE_REQUIREMENTS = {
    NodeRole.INFERENCE: NodeRequirements(
        min_memory_gb=16,
        min_storage_gb=100,
        min_cpu_cores=8,
        min_network_mbps=1000,
        gpu_required=True,
        gpu_memory_min=16,
        ssd_required=True
    ),
    NodeRole.VALIDATION: NodeRequirements(
        min_memory_gb=8,
        min_storage_gb=50,
        min_cpu_cores=4,
        min_network_mbps=500,
        gpu_required=False
    ),
    NodeRole.STORAGE: NodeRequirements(
        min_memory_gb=4,
        min_storage_gb=1000,  # 1TB mínimo
        min_cpu_cores=2,
        min_network_mbps=100,
        gpu_required=False
    ),
    NodeRole.HYBRID: NodeRequirements(
        min_memory_gb=32,
        min_storage_gb=500,
        min_cpu_cores=16,
        min_network_mbps=1000,
        gpu_required=True,
        gpu_memory_min=24
    )
}