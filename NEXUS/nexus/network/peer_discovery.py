from typing import Dict, List, Set, Optional
import asyncio
from datetime import datetime, timedelta
import random
from .p2p_protocol import NexusP2PProtocol

class PeerDiscoveryService:
    """Servicio de descubrimiento y gestión de peers"""
    
    def __init__(self, p2p_protocol, bootstrap_nodes: List[str]):
        self.p2p = p2p_protocol
        self.bootstrap_nodes = bootstrap_nodes
        self.known_peers: Set[str] = set()
        self.active_peers: Dict[str, datetime] = {}
        self.peer_metrics: Dict[str, Dict] = {}
        
        # Registrar manejadores de mensajes
        self.p2p.register_message_handler("peer_announce", self._handle_peer_announce)
        self.p2p.register_message_handler("peer_query", self._handle_peer_query)
    
    async def start_discovery(self):
        """Inicia el proceso de descubrimiento de peers"""
        # Conectar a nodos bootstrap iniciales
        for bootstrap_addr in self.bootstrap_nodes:
            await self._connect_to_peer(bootstrap_addr)
        
        # Programa descubrimiento periódico
        asyncio.create_task(self._periodic_discovery())
        
        # Programa mantenimiento de peers
        asyncio.create_task(self._peer_maintenance())
    
    async def _periodic_discovery(self):
        """Descubrimiento periódico de nuevos peers"""
        while True:
            try:
                # Consultar peers conocidos por nuevos peers
                await self._query_peers_for_peers()
                
                # Intentar conectar con nuevos peers descubiertos
                await self._connect_to_new_peers()
                
                await asyncio.sleep(300)  # Cada 5 minutos
                
            except Exception as e:
                print(f"Error en descubrimiento periódico: {e}")
                await asyncio.sleep(60)
    
    async def _query_peers_for_peers(self):
        """Pregunta a peers conocidos por sus listas de peers"""
        query_message = {
            'type': 'peer_query',
            'max_results': 10,
            'required_roles': []  # Puede filtrar por roles específicos
        }
        
        await self.p2p.broadcast_message("peer_query", query_message)
    
    async def _handle_peer_announce(self, message, stream):
        """Maneja anuncios de nuevos peers"""
        peer_info = message['payload']
        peer_id = peer_info['node_id']
        
        if peer_id not in self.known_peers:
            self.known_peers.add(peer_id)
            self.peer_metrics[peer_id] = {
                'first_seen': datetime.now(),
                'last_seen': datetime.now(),
                'response_time': message.get('response_time', 0),
                'role': peer_info.get('role'),
                'region': peer_info.get('region')
            }
    
    async def _connect_to_peer(self, peer_addr: str) -> bool:
        """Intenta conectar con un peer específico"""
        try:
            peer_info = PeerInfo.from_string(peer_addr)
            await self.p2p.node.connect(peer_info)
            
            self.connected_peers.add(peer_info.peer_id)
            self.active_peers[peer_info.peer_id] = datetime.now()
            
            print(f"Conectado exitosamente a peer: {peer_info.peer_id}")
            return True
            
        except Exception as e:
            print(f"Error conectando a peer {peer_addr}: {e}")
            return False
    
    async def _peer_maintenance(self):
        """Mantenimiento periódico de la lista de peers"""
        while True:
            try:
                current_time = datetime.now()
                
                # Remover peers inactivos
                inactive_peers = [
                    peer_id for peer_id, last_seen in self.active_peers.items()
                    if current_time - last_seen > timedelta(minutes=15)
                ]
                
                for peer_id in inactive_peers:
                    self.active_peers.pop(peer_id, None)
                    print(f"Peer marcado como inactivo: {peer_id}")
                
                # Intentar reconectar con peers conocidos pero no conectados
                known_but_not_connected = self.known_peers - set(self.active_peers.keys())
                for peer_id in random.sample(list(known_but_not_connected), min(5, len(known_but_not_connected))):
                    await self._attempt_reconnect(peer_id)
                
                await asyncio.sleep(60)  # Cada minuto
                
            except Exception as e:
                print(f"Error en mantenimiento de peers: {e}")
                await asyncio.sleep(30)