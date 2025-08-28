from prometheus_client import Counter, Gauge, Histogram
from datetime import datetime
from typing import Dict, Any

class LLMMonitoringSystem:
    """Sistema de monitorización para el LLM extendido"""
    
    def __init__(self):
        # Métricas de rendimiento
        self.inference_latency = Histogram(
            'llm_inference_latency_seconds',
            'Latencia de inferencia del LLM',
            ['model_version', 'task_type']
        )
        
        self.training_operations = Counter(
            'llm_training_operations_total',
            'Número de operaciones de training',
            ['operation_type', 'status']
        )
        
        self.knowledge_updates = Counter(
            'llm_knowledge_updates_total',
            'Número de actualizaciones de conocimiento',
            ['update_type', 'validation_status']
        )
        
        self.model_accuracy = Gauge(
            'llm_model_accuracy',
            'Precisión actual del modelo',
            ['model_version', 'domain']
        )
    
    def record_inference(self, model_version: str, task_type: str, latency: float):
        """Registra métricas de inferencia"""
        self.inference_latency.labels(
            model_version=model_version,
            task_type=task_type
        ).observe(latency)
    
    def record_training_operation(self, operation_type: str, success: bool):
        """Registra operaciones de training"""
        status = "success" if success else "failure"
        self.training_operations.labels(
            operation_type=operation_type,
            status=status
        ).inc()
    
    def update_accuracy_metrics(self, 
                              model_version: str, 
                              domain: str, 
                              accuracy: float):
        """Actualiza métricas de precisión"""
        self.model_accuracy.labels(
            model_version=model_version,
            domain=domain
        ).set(accuracy)