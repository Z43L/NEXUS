from typing import Dict, List
import asyncio
from datetime import datetime, timedelta
import time
from prometheus_client import Counter, Gauge, Histogram

class NetworkMonitor:
    """Sistema de monitorización para comunicaciones de red"""
    
    def __init__(self):
        self.metrics = {
            'messages_sent': Counter('nexus_network_messages_sent', 'Mensajes enviados', ['type', 'destination']),
            'messages_received': Counter('nexus_network_messages_received', 'Mensajes recibidos', ['type', 'source']),
            'message_latency': Histogram('nexus_network_message_latency', 'Latencia de mensajes', ['type']),
            'node_connectivity': Gauge('nexus_network_node_connectivity', 'Conectividad de nodos', ['node_id']),
            'bandwidth_usage': Gauge('nexus_network_bandwidth_bytes', 'Uso de ancho de banda', ['direction'])
        }
        
        self.latency_measurements: Dict[str, List[float]] = {}
        self.throughput_measurements: Dict[str, List[float]] = {}
        
    async def start_monitoring(self):
        """Inicia la monitorización continua"""
        asyncio.create_task(self._measure_latencies())
        asyncio.create_task(self._measure_throughput())
        asyncio.create_task(self._report_metrics())
    
    async def record_message_sent(self, message_type: str, destination: str, size: int):
        """Registra un mensaje enviado"""
        self.metrics['messages_sent'].labels(type=message_type, destination=destination).inc()
        self.metrics['bandwidth_usage'].labels(direction='out').inc(size)
    
    async def record_message_received(self, message_type: str, source: str, size: int):
        """Registra un mensaje recibido"""
        self.metrics['messages_received'].labels(type=message_type, source=source).inc()
        self.metrics['bandwidth_usage'].labels(direction='in').inc(size)
    
    async def record_latency(self, message_type: str, latency: float):
        """Registra la latencia de un mensaje"""
        self.metrics['message_latency'].labels(type=message_type).observe(latency)
        
        if message_type not in self.latency_measurements:
            self.latency_measurements[message_type] = []
        
        self.latency_measurements[message_type].append(latency)
        
        # Mantener sólo las últimas 1000 mediciones
        if len(self.latency_measurements[message_type]) > 1000:
            self.latency_measurements[message_type] = self.latency_measurements[message_type][-1000:]
    
    async def _measure_latencies(self):
        """Mide latencias de forma activa"""
        while True:
            try:
                # Medir latencia con nodos conectados
                # await self._ping_connected_nodes()
                await asyncio.sleep(30)  # Medir cada 30 segundos
            except Exception as e:
                logger.error(f"Error midiendo latencias: {e}")
                await asyncio.sleep(60)
    
    async def _measure_throughput(self):
        """Mide throughput de la red"""
        while True:
            try:
                # Calcular throughput basado en métricas recientes
                await self._calculate_throughput()
                await asyncio.sleep(60)  # Medir cada minuto
            except Exception as e:
                logger.error(f"Error midiendo throughput: {e}")
                await asyncio.sleep(60)
    
    async def _report_metrics(self):
        """Reporta métricas agregadas"""
        while True:
            try:
                await self._generate_network_report()
                await asyncio.sleep(300)  # Reportar cada 5 minutos
            except Exception as e:
                logger.error(f"Error generando reporte: {e}")
                await asyncio.sleep(300)