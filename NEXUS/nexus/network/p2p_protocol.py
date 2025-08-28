import asyncio
from libp2p import new_node
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import PeerStore
from libp2p.crypto.secp256k1 import create_new_key_pair
from typing import Dict, List, Optional
from multiaddr import Multiaddr

class NexusP2PProtocol:
    """Protocolo P2P para comunicación entre nodos NEXUS"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.node = None
        self.peer_store = PeerStore()
        self.connected_peers = set()
        self.message_handlers = {}
        
    async def initialize(self):
        """Inicializa el nodo P2P"""
        key_pair = create_new_key_pair()
        
        self.node = await new_node(
            key_pair=key_pair,
            listen_addrs=[Multiaddr(self.config['listen_addr'])],
            peerstore=self.peer_store
        )
        
        # Configurar protocolos
        await self._setup_protocols()
        
        # Iniciar descubrimiento de peers
        await self._start_peer_discovery()
        
        print(f"Nodo P2P inicializado con ID: {self.node.get_id()}")
    
    async def _setup_protocols(self):
        """Configura los protocolos soportados"""
        # Protocolo de mensajería básica
        await self.node.set_stream_handler(
            "/nexus/message/1.0.0", 
            self._handle_message
        )
        
        # Protocolo de descubrimiento de servicios
        await self.node.set_stream_handler(
            "/nexus/discovery/1.0.0",
            self._handle_discovery
        )
        
        # Protocolo de sincronización de estado
        await self.node.set_stream_handler(
            "/nexus/sync/1.0.0", 
            self._handle_sync
        )
    
    async def _handle_message(self, stream):
        """Maneja mensajes entrantes"""
        try:
            data = await stream.read()
            message = self._decode_message(data)
            
            if message['type'] in self.message_handlers:
                await self.message_handlers[message['type']](message, stream)
            else:
                print(f"Tipo de mensaje no manejado: {message['type']}")
                
        except Exception as e:
            print(f"Error manejando mensaje: {e}")
        finally:
            await stream.close()
    
    async def broadcast_message(self, message_type: str, payload: Dict):
        """Transmite un mensaje a todos los peers conectados"""
        message = {
            'type': message_type,
            'payload': payload,
            'timestamp': asyncio.get_event_loop().time(),
            'node_id': str(self.node.get_id())
        }
        
        encoded = self._encode_message(message)
        
        for peer_id in self.connected_peers:
            try:
                stream = await self.node.new_stream(peer_id, "/nexus/message/1.0.0")
                await stream.write(encoded)
                await stream.close()
            except Exception as e:
                print(f"Error enviando mensaje a {peer_id}: {e}")
                self.connected_peers.remove(peer_id)
    
    def register_message_handler(self, message_type: str, handler):
        """Registra un manejador para un tipo de mensaje específico"""
        self.message_handlers[message_type] = handler