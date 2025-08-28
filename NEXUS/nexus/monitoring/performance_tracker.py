from prometheus_client import start_http_server, Gauge, Counter, Histogram
import time
from typing import Dict, List, Any
import asyncio

class NexusPerformanceMonitor:
    def __init__(self, port: int = 8000):
        self.port = port
        
        # Métricas de rendimiento
        self.inference_latency = Histogram(
            'nexus_inference_latency_seconds',
            'Latencia de las operaciones de inferencia',
            ['node_type', 'task_complexity']
        )
        
        self.memory_operations = Counter(
            'nexus_memory_operations_total',
            'Número total de operaciones de memoria',
            ['operation_type', 'status']
        )
        
        self.knowledge_updates = Counter(
            'nexus_knowledge_updates_total',
            'Número total de actualizaciones de conocimiento',
            ['update_type', 'validation_status']
        )
        
        self.node_performance = Gauge(
            'nexus_node_performance_score',
            'Puntuación de rendimiento del nodo',
            ['node_id', 'node_type']
        )
    
    def start_monitoring_server(self):
        """Inicia el servidor de métricas"""
        start_http_server(self.port)
        print(f"📊 Servidor de monitorización iniciado en puerto {self.port}")
    
    def track_inference(self, node_type: str, task_complexity: str):
        """Decorador para trackear operaciones de inferencia"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                start_time = time.time()
                result = func(*args, **kwargs)
                latency = time.time() - start_time
                
                self.inference_latency.labels(
                    node_type=node_type,
                    task_complexity=task_complexity
                ).observe(latency)
                
                return result
            return wrapper
        return decorator
    
    def record_memory_operation(self, operation_type: str, success: bool):
        """Registra una operación de memoria"""
        status = "success" if success else "failure"
        self.memory_operations.labels(
            operation_type=operation_type,
            status=status
        ).inc()
    
    def record_knowledge_update(self, update_type: str, validated: bool):
        """Registra una actualización de conocimiento"""
        status = "validated" if validated else "rejected"
        self.knowledge_updates.labels(
            update_type=update_type,
            validation_status=status
        ).inc()