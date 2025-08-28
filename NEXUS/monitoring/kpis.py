from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
from prometheus_client import Gauge, Counter, Histogram

@dataclass
class PerformanceKPIs:
    # Rendimiento de la Red
    network_throughput: Gauge = Gauge('network_throughput', 'Throughput de la red en TPS')
    latency: Histogram = Histogram('request_latency', 'Latencia de las requests')
    uptime: Gauge = Gauge('system_uptime', 'Tiempo de actividad del sistema')
    
    # Calidad del Conocimiento
    knowledge_accuracy: Gauge = Gauge('knowledge_accuracy', 'Precisión del conocimiento validado')
    validation_speed: Histogram = Histogram('validation_speed', 'Velocidad de validación')
    consensus_rate: Gauge = Gauge('consensus_rate', 'Tasa de consenso alcanzado')
    
    # Participación y Crecimiento
    active_nodes: Gauge = Gauge('active_nodes', 'Número de nodos activos')
    daily_users: Counter = Counter('daily_users', 'Usuarios activos diarios')
    token_velocity: Gauge = Gauge('token_velocity', 'Velocidad de circulación de tokens')
    
    # Capacidades Cognitivas
    task_success_rate: Gauge = Gauge('task_success_rate', 'Tasa de éxito en tareas complejas')
    learning_efficiency: Gauge = Gauge('learning_efficiency', 'Eficiencia del aprendizaje')
    reasoning_depth: Histogram = Histogram('reasoning_depth', 'Profundidad del razonamiento')

class SuccessMetrics:
    """Métricas para medir el éxito del proyecto"""
    
    @staticmethod
    def calculate_network_health() -> Dict[str, float]:
        """Calcula la salud general de la red"""
        return {
            'availability': 99.95,  # Objetivo: 99.9%
            'throughput': 1500,     # TPS objetivo: 1000+
            'latency': 0.150        # Objetivo: <200ms
        }
    
    @staticmethod
    def calculate_knowledge_quality() -> Dict[str, float]:
        """Calcula la calidad del conocimiento"""
        return {
            'accuracy': 0.98,       # Objetivo: >95%
            'freshness': 0.90,      # Objetivo: >85%
            'consistency': 0.96     # Objetivo: >90%
        }
    
    @staticmethod
    def calculate_ecosystem_growth() -> Dict[str, int]:
        """Calcula el crecimiento del ecosistema"""
        return {
            'active_nodes': 750,    # Objetivo: 500+
            'daily_users': 10000,   # Objetivo: 5000+
            'developers': 250       # Objetivo: 100+
        }