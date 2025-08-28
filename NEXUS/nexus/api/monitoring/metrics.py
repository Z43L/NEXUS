from typing import Dict, List
from datetime import datetime, timedelta
import prometheus_client
from prometheus_client import Counter, Histogram, Gauge
from fastapi import Request

class APIMetrics:
    """Sistema de métricas y monitorización para la API"""
    
    def __init__(self):
        # Métricas de requests
        self.requests_total = Counter(
            'nexus_api_requests_total',
            'Total API requests',
            ['method', 'endpoint', 'status_code']
        )
        
        self.request_duration = Histogram(
            'nexus_api_request_duration_seconds',
            'API request duration',
            ['method', 'endpoint'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
        )
        
        self.active_connections = Gauge(
            'nexus_api_active_connections',
            'Active API connections'
        )
        
        # Métricas de negocio
        self.queries_total = Counter(
            'nexus_api_queries_total',
            'Total knowledge queries',
            ['type', 'complexity']
        )
        
        self.inferences_total = Counter(
            'nexus_api_inferences_total',
            'Total inferences performed',
            ['task_type', 'success']
        )
    
    async def track_request(self, request: Request, response, duration: float):
        """Registra métricas de una request HTTP"""
        method = request.method
        endpoint = request.url.path
        status_code = response.status_code
        
        self.requests_total.labels(method, endpoint, status_code).inc()
        self.request_duration.labels(method, endpoint).observe(duration)
    
    async def track_query(self, query_type: str, complexity: str):
        """Registra métricas de consultas de conocimiento"""
        self.queries_total.labels(query_type, complexity).inc()
    
    async def track_inference(self, task_type: str, success: bool):
        """Registra métricas de inferencias"""
        self.inferences_total.labels(task_type, success).inc()
    
    async def get_api_metrics(self) -> Dict:
        """Obtiene métricas agregadas de la API"""
        return {
            'total_requests': self._get_total_requests(),
            'average_response_time': self._get_avg_response_time(),
            'success_rate': self._get_success_rate(),
            'top_endpoints': self._get_top_endpoints(),
            'user_activity': self._get_user_activity()
        }
    
    async def generate_usage_report(self, period: timedelta = timedelta(days=30)) -> Dict:
        """Genera reporte de uso para el período especificado"""
        end_time = datetime.now()
        start_time = end_time - period
        
        return {
            'period': {
                'start': start_time,
                'end': end_time
            },
            'total_requests': await self._get_requests_in_period(start_time, end_time),
            'unique_users': await self._get_unique_users(start_time, end_time),
            'most_popular_endpoints': await self._get_popular_endpoints(start_time, end_time),
            'error_rates': await self._get_error_rates(start_time, end_time),
            'peak_usage_times': await self._get_peak_usage_times(start_time, end_time)
        }