from typing import Dict, List
import asyncio
from datetime import datetime, timedelta

class NodeAnnouncementProtocol:
    """Protocolo para anuncio y mantenimiento de presencia en la red"""
    
    def __init__(self, discovery_protocol, announce_interval: int = 300):
        self.discovery = discovery_protocol
        self.announce_interval = announce_interval
        self.last_announcement = datetime.min
        
    async def start_announcements(self):
        """Inicia los anuncios periódicos de presencia"""
        while True:
            try:
                await self._announce_presence()
                await asyncio.sleep(self.announce_interval)
            except Exception as e:
                logger.error(f"Error en anuncio de presencia: {e}")
                await asyncio.sleep(60)
    
    async def _announce_presence(self):
        """Anuncia la presencia del nodo a la red"""
        announcement = {
            'node_id': self.discovery.node_id,
            'multiaddrs': self.discovery.listen_addr,
            'roles': self.discovery.node_roles,
            'timestamp': datetime.now().isoformat(),
            'protocol_version': self.discovery.protocol_version,
            'capacity': self._get_current_capacity()
        }
        
        # Transmitir anuncio a todos los peers conectados
        await self._broadcast_announcement(announcement)
        self.last_announcement = datetime.now()
    
    def _get_current_capacity(self) -> Dict:
        """Obtiene la capacidad actual del nodo"""
        return {
            'cpu_available': self._get_cpu_availability(),
            'memory_available': self._get_memory_availability(),
            'storage_available': self._get_storage_availability(),
            'network_bandwidth': self._get_network_bandwidth()
        }
    
    async def _broadcast_announcement(self, announcement: Dict):
        """Transmite el anuncio a todos los peers"""
        for peer_id in self.discovery.active_connections:
            try:
                await self._send_to_peer(peer_id, 'node_announcement', announcement)
            except Exception as e:
                logger.warning(f"Error enviando anuncio a {peer_id}: {e}")
    
    async def handle_announcement(self, announcement: Dict):
        """Maneja un anuncio de presencia recibido"""
        node_id = announcement['node_id']
        
        # Actualizar información del nodo
        if node_id in self.discovery.known_nodes:
            self.discovery.known_nodes[node_id].last_seen = datetime.now()
            self.discovery.known_nodes[node_id].capacity = announcement['capacity']
        else:
            # Añadir nuevo nodo a la lista conocida
            self.discovery.known_nodes[node_id] = NodeInfo(
                node_id=node_id,
                multiaddrs=announcement['multiaddrs'],
                roles=set(announcement['roles']),
                last_seen=datetime.now(),
                reputation=0.5,  # Reputación inicial
                region=announcement.get('region', 'unknown'),
                protocol_version=announcement['protocol_version']
            )