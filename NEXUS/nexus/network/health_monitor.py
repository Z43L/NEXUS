from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
from prometheus_client import Gauge, Counter, Histogram

class NetworkHealthMonitor:
    """Sistema de monitorización de salud de la red"""
    
    def __init__(self):
        self.node_metrics: Dict[str, Dict] = {}
        self.network_metrics = {
            'total_nodes': 0,
            'active_nodes': 0,
            'avg_uptime': 0.0,
            'network_throughput': 0.0,
            'validation_speed': 0.0
        }
        
        # Métricas Prometheus
        self.node_count_gauge = Gauge('nexus_network_nodes_total', 'Total nodes in network', ['type'])
        self.uptime_gauge = Gauge('nexus_network_uptime_avg', 'Average node uptime')
        self.throughput_gauge = Gauge('nexus_network_throughput', 'Network throughput in operations/sec')
        self.latency_histogram = Histogram('nexus_network_latency', 'Network latency distribution')
    
    async def start_monitoring(self):
        """Inicia la monitorización continua de la red"""
        asyncio.create_task(self._update_network_metrics())
        asyncio.create_task(self._check_node_health())
        asyncio.create_task(self._publish_metrics())
    
    async def _update_network_metrics(self):
        """Actualiza las métricas de la red periódicamente"""
        while True:
            try:
                # Obtener estadísticas actualizadas
                total_nodes = await self._get_total_node_count()
                active_nodes = await self._get_active_node_count()
                
                self.network_metrics.update({
                    'total_nodes': total_nodes,
                    'active_nodes': active_nodes,
                    'avg_uptime': await self._calculate_avg_uptime(),
                    'network_throughput': await self._measure_throughput(),
                    'validation_speed': await self._measure_validation_speed()
                })
                
                # Actualizar métricas Prometheus
                self.node_count_gauge.labels(type='total').set(total_nodes)
                self.node_count_gauge.labels(type='active').set(active_nodes)
                self.uptime_gauge.set(self.network_metrics['avg_uptime'])
                self.throughput_gauge.set(self.network_metrics['network_throughput'])
                
                await asyncio.sleep(60)  # Actualizar cada minuto
                
            except Exception as e:
                print(f"Error actualizando métricas de red: {e}")
                await asyncio.sleep(30)
    
    async def _check_node_health(self):
        """Verifica la salud de los nodos individuales"""
        while True:
            try:
                nodes_to_check = list(self.node_metrics.keys())
                
                for node_id in nodes_to_check:
                    health_status = await self._check_single_node_health(node_id)
                    self.node_metrics[node_id]['health'] = health_status
                    
                    if health_status == 'unhealthy':
                        await self._handle_unhealthy_node(node_id)
                
                await asyncio.sleep(300)  # Verificar cada 5 minutos
                
            except Exception as e:
                print(f"Error verificando salud de nodos: {e}")
                await asyncio.sleep(60)
    
    async def _check_single_node_health(self, node_id: str) -> str:
        """Verifica la salud de un nodo específico"""
        try:
            # Verificar conectividad
            if not await self._check_connectivity(node_id):
                return "unhealthy"
            
            # Verificar recursos
            resources_ok = await self._check_node_resources(node_id)
            if not resources_ok:
                return "degraded"
            
            # Verificar desempeño
            performance_ok = await self._check_performance(node_id)
            if not performance_ok:
                return "degraded"
            
            return "healthy"
            
        except Exception:
            return "unhealthy"
    
    async def _handle_unhealthy_node(self, node_id: str):
        """Maneja un nodo que reporta健康问题"""
        node_data = self.node_metrics.get(node_id, {})
        
        # Intentar reconectar
        if await self._attempt_reconnect(node_id):
            return
        
        # Si no se puede reconectar, marcarlo como inactivo
        print(f"Node {node_id} is unhealthy and cannot reconnect")
        
        # Notificar al sistema de reputación
        await self._report_node_failure(node_id)
    
    async def _publish_metrics(self):
        """Publica métricas para monitorización externa"""
        while True:
            try:
                # Exportar métricas en formato para dashboards
                metrics_to_publish = {
                    'timestamp': datetime.now().isoformat(),
                    'network_metrics': self.network_metrics,
                    'node_health_summary': await self._get_health_summary()
                }
                
                # Publicar a sistema de monitorización (ej: Prometheus push gateway)
                await self._push_metrics(metrics_to_publish)
                
                await asyncio.sleep(60)  # Publicar cada minuto
                
            except Exception as e:
                print(f"Error publicando métricas: {e}")
                await asyncio.sleep(30)