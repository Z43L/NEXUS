from typing import Dict, List, Any, Optional
from datetime import datetime
import time
from prometheus_client import Counter, Gauge, Histogram, Summary
from loguru import logger

class ReasoningMonitor:
    """Sistema de monitorización para el agente razonador"""
    
    def __init__(self):
        # Métricas de rendimiento
        self.task_execution_time = Histogram(
            'reasoning_task_execution_seconds',
            'Tiempo de ejecución de tareas',
            ['task_type', 'complexity']
        )
        
        self.successful_tasks = Counter(
            'reasoning_successful_tasks_total',
            'Tareas completadas exitosamente',
            ['task_type']
        )
        
        self.failed_tasks = Counter(
            'reasoning_failed_tasks_total',
            'Tareas que fallaron',
            ['task_type', 'error_type']
        )
        
        self.tool_usage = Counter(
            'reasoning_tool_usage_total',
            'Uso de herramientas externas',
            ['tool_name', 'status']
        )
        
        self.learning_events = Counter(
            'reasoning_learning_events_total',
            'Eventos de aprendizaje',
            ['learning_type']
        )
    
    def record_task_start(self, task_description: str, complexity: float):
        """Registra el inicio de una tarea"""
        self.current_task = {
            "description": task_description,
            "start_time": time.time(),
            "complexity": complexity
        }
    
    def record_task_end(self, success: bool, error: Optional[str] = None):
        """Registra el fin de una tarea"""
        if hasattr(self, 'current_task'):
            execution_time = time.time() - self.current_task["start_time"]
            
            self.task_execution_time.labels(
                task_type=self._categorize_task(self.current_task["description"]),
                complexity=self._categorize_complexity(self.current_task["complexity"])
            ).observe(execution_time)
            
            if success:
                self.successful_tasks.labels(
                    task_type=self._categorize_task(self.current_task["description"])
                ).inc()
            else:
                self.failed_tasks.labels(
                    task_type=self._categorize_task(self.current_task["description"]),
                    error_type=self._categorize_error(error)
                ).inc()
    
    def record_tool_usage(self, tool_name: str, success: bool):
        """Registra uso de herramienta"""
        status = "success" if success else "failure"
        self.tool_usage.labels(tool_name=tool_name, status=status).inc()
    
    def record_learning_event(self, learning_type: str):
        """Registra evento de aprendizaje"""
        self.learning_events.labels(learning_type=learning_type).inc()
    
    def _categorize_task(self, description: str) -> str:
        """Categoriza el tipo de tarea para métricas"""
        description = description.lower()
        if any(word in description for word in ["analyze", "analysis"]):
            return "analysis"
        elif any(word in description for word in ["plan", "strategy"]):
            return "planning"
        elif any(word in description for word in ["execute", "run"]):
            return "execution"
        elif any(word in description for word in ["validate", "verify"]):
            return "validation"
        else:
            return "general"
    
    def _categorize_complexity(self, complexity: float) -> str:
        """Categoriza la complejidad para métricas"""
        if complexity < 0.3:
            return "low"
        elif complexity < 0.7:
            return "medium"
        else:
            return "high"
    
    def _categorize_error(self, error: Optional[str]) -> str:
        """Categoriza el tipo de error"""
        if not error:
            return "unknown"
        
        error = error.lower()
        if any(word in error for word in ["timeout", "timed out"]):
            return "timeout"
        elif any(word in error for word in ["memory", "out of memory"]):
            return "memory"
        elif any(word in error for word in ["network", "connection"]):
            return "network"
        elif any(word in error for word in ["validation", "invalid"]):
            return "validation"
        else:
            return "other"