import pytest
import asyncio
from nexus.network.p2p_protocol import NexusP2PProtocol
from nexus.network.discovery import PeerDiscoveryService

class TestP2PNetwork:
    """Suite de pruebas para la red P2P de NEXUS"""
    
    @pytest.fixture
    async def p2p_protocol(self):
        """Fixture que inicializa el protocolo P2P"""
        config = {
            "listen_addr": "/ip4/127.0.0.1/tcp/0",
            "bootstrap_nodes": []
        }
        protocol = NexusP2PProtocol(config)
        await protocol.initialize()
        return protocol
    
    @pytest.mark.asyncio
    async def test_peer_discovery(self, p2p_protocol):
        """Prueba el descubrimiento automático de peers"""
        discovery = PeerDiscoveryService(p2p_protocol, [])
        await discovery.start_discovery()
        
        # Simular anuncio de peers
        test_peers = [
            {
                "node_id": "peer_1",
                "multiaddrs": ["/ip4/192.168.1.1/tcp/4001"],
                "roles": ["validation", "storage"],
                "region": "us-west"
            },
            {
                "node_id": "peer_2", 
                "multiaddrs": ["/ip4/192.168.1.2/tcp/4001"],
                "roles": ["inference"],
                "region": "eu-central"
            }
        ]
        
        for peer_info in test_peers:
            await discovery.handle_announcement(peer_info)
        
        # Verificar que se descubrieron los peers
        known_peers = discovery.get_known_peers()
        assert len(known_peers) == 2, "Debería conocer ambos peers"
        assert "peer_1" in known_peers, "Debería conocer peer_1"
        assert "peer_2" in known_peers, "Debería conocer peer_2"
        
        # Verificar información de roles
        peer_1_info = known_peers["peer_1"]
        assert "validation" in peer_1_info.roles, "Debería tener rol de validación"
        assert "storage" in peer_1_info.roles, "Debería tener rol de almacenamiento"
    
    @pytest.mark.asyncio
    async def test_message_reliability(self, p2p_protocol):
        """Prueba la confiabilidad de la mensajería P2P"""
        test_messages = []
        
        def message_handler(message):
            test_messages.append(message)
        
        # Registrar handler de test
        p2p_protocol.register_message_handler("test_message", message_handler)
        
        # Enviar mensaje de prueba
        test_message = {
            "type": "test_message",
            "payload": b"test_payload",
            "message_id": "test_123",
            "timestamp": asyncio.get_event_loop().time()
        }
        
        # Simular recepción de mensaje
        await p2p_protocol.handle_incoming_message(test_message)
        
        assert len(test_messages) == 1, "Debería haber recibido el mensaje"
        assert test_messages[0]["payload"] == b"test_payload", "El payload debería ser idéntico"
        
        # Prueba de retransmisión
        retransmit_count = 0
        original_send = p2p_protocol.send_message
        
        async def counting_send(*args, **kwargs):
            nonlocal retransmit_count
            retransmit_count += 1
            return await original_send(*args, **kwargs)
        
        p2p_protocol.send_message = counting_send
        
        # Enviar mensaje con requerimiento de ACK
        reliable_message = {
            "type": "important_message",
            "payload": b"important_data",
            "priority": 5,  # Máxima prioridad
            "requires_ack": True
        }
        
        await p2p_protocol.send_message(reliable_message)
        assert retransmit_count >= 1, "Debería intentar retransmisión para mensajes importantes"