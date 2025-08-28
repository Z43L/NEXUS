from enum import Enum
from typing import List, Dict, Tuple
from dataclasses import dataclass

class RiskLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

class RiskCategory(Enum):
    TECHNICAL = "Technical"
    OPERATIONAL = "Operational"
    FINANCIAL = "Financial"
    REGULATORY = "Regulatory"

@dataclass
class Risk:
    id: str
    description: str
    category: RiskCategory
    probability: RiskLevel
    impact: RiskLevel
    mitigation_plan: List[str]
    contingency_plan: List[str]
    
    @property
    def severity(self) -> RiskLevel:
        return RiskLevel(max(self.probability.value, self.impact.value))

# Matriz de riesgos principales
KEY_RISKS = [
    Risk(
        id="RISK-001",
        description="Escalabilidad de la blockchain para consenso de conocimiento",
        category=RiskCategory.TECHNICAL,
        probability=RiskLevel.HIGH,
        impact=RiskLevel.CRITICAL,
        mitigation_plan=[
            "Implementar sharding de segundo nivel",
            "Optimizar algoritmo de consenso",
            "Usar soluciones Layer 2 para almacenamiento"
        ],
        contingency_plan=[
            "Reducir frecuencia de actualizaciones en caso de congestión",
            "Aumentar requisitos para validadores durante picos"
        ]
    ),
    Risk(
        id="RISK-002",
        description="Calidad del conocimiento validado descentralizadamente",
        category=RiskCategory.OPERATIONAL,
        probability=RiskLevel.MEDIUM,
        impact=RiskLevel.HIGH,
        mitigation_plan=[
            "Implementar múltiples capas de validación",
            "Sistema de reputación para validadores",
            "Mecanismos de desafío y verificación"
        ],
        contingency_plan=[
            "Revertir actualizaciones problemáticas",
            "Cuarentena de conocimiento no verificado"
        ]
    ),
    Risk(
        id="RISK-003",
        description="Regulación de criptoactivos y sistemas descentralizados",
        category=RiskCategory.REGULATORY,
        probability=RiskLevel.HIGH,
        impact=RiskLevel.HIGH,
        mitigation_plan=[
            "Asesoramiento legal continuo",
            "Diseño compliant con regulaciones principales",
            "Engagement proactivo con reguladores"
        ],
        contingency_plan=[
            "Reestructuración jurídica si es necesario",
            "Geofencing para regiones problemáticas"
        ]
    )
]

def get_critical_risks() -> List[Risk]:
    """Obtiene riesgos críticos que requieren atención inmediata"""
    return [risk for risk in KEY_RISKS if risk.severity == RiskLevel.CRITICAL]