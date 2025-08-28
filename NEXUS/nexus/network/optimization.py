from typing import Dict, List, Set
import asyncio
from datetime import datetime
import zlib
import math

class CommunicationOptimizer:
    """Sistema de optimización para comunicaciones de red"""
    
    def __init__(self):
        self.message_stats: Dict[MessageType, Dict] = {}
        self.node_latencies: Dict[str, List[float]] = {}
        self.compression_threshold = 1024  # 1KB
        self.adaptive_routing_table: Dict[str, Dict] = {}
        
    async def optimize_message(self, message: NexusMessage) -> NexusMessage:
        """Aplica optimizaciones a un mensaje basado en estadísticas"""
        optimized_message = message
        
        # Decidir compresión basado en tamaño y tipo
        if len(message.payload) > self.compression_threshold:
            optimized_message = optimized_message._replace(
                compression=True,
                payload=zlib.compress(message.payload)
            )
        
        # Decidir encriptación basado en sensibilidad
        if self._requires_encryption(message):
            optimized_message = optimized_message._replace(encryption=True)
        
        # Optimizar ruta basado en latencias
        if message.destination_node:
            best_route = await self._get_optimal_route(message.destination_node)
            optimized_message = optimized_message._replace(
                # Añadir información de ruta optimizada
                payload=self._add_routing_info(message.payload, best_route)
            )
        
        return optimized_message
    
    def _requires_encryption(self, message: NexusMessage) -> bool:
        """Determina si un mensaje requiere encriptación"""
        sensitive_types = {
            MessageType.VALIDATION_REQUEST,
            MessageType.CONSENSUS_MESSAGE,
            MessageType.KNOWLEDGE_UPDATE
        }
        return message.type in sensitive_types
    
    async def _get_optimal_route(self, destination: str) -> List[str]:
        """Obtiene la ruta óptima hacia un nodo destino"""
        if destination in self.adaptive_routing_table:
            return self.adaptive_routing_table[destination]['best_route']
        
        # Calcular nueva ruta usando información de latencia
        return await self._calculate_new_route(destination)
    
    async def update_latency_stats(self, node_id: str, latency: float):
        """Actualiza las estadísticas de latencia para un nodo"""
        if node_id not in self.node_latencies:
            self.node_latencies[node_id] = []
        
        self.node_latencies[node_id].append(latency)
        
        # Mantener sólo las últimas 100 mediciones
        if len(self.node_latencies[node_id]) > 100:
            self.node_latencies[node_id] = self.node_latencies[node_id][-100:]
    
    async def calculate_network_health(self) -> Dict:
        """Calcula métricas de salud de la red"""
        avg_latencies = {}
        for node_id, latencies in self.node_latencies.items():
            if latencies:
                avg_latencies[node_id] = sum(latencies) / len(latencies)
        
        overall_latency = sum(avg_latencies.values()) / len(avg_latencies) if avg_latencies else 0
        
        return {
            'average_latency_ms': overall_latency,
            'node_count': len(self.node_latencies),
            'health_score': self._calculate_health_score(overall_latency),
            'timestamp': datetime.now().isoformat()
        }
    
    def _calculate_health_score(self, latency: float) -> float:
        """Calcula un score de salud basado en la latencia"""
        # Score entre 0-100, donde 100 es perfecto
        if latency <= 50:
            return 100.0
        elif latency >= 1000:
            return 0.0
        else:
            return 100.0 * (1 - math.log10(latency / 50) / math.log10(20))