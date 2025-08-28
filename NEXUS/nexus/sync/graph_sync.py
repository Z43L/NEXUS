from typing import Dict, List, Set
import asyncio
import hashlib
from dataclasses import dataclass

@dataclass
class GraphSyncState:
    """Estado de sincronización de grafo"""
    node_checksums: Dict[str, str]  # checksum por nodo del grafo
    edge_checksums: Dict[str, str]  # checksum por relación
    timestamp: float
    version: int

class GraphSynchronization:
    """Sistema de sincronización para grafos de conocimiento"""
    
    def __init__(self, graph_db, network_protocol):
        self.graph_db = graph_db
        self.network = network_protocol
        self.sync_states: Dict[str, GraphSyncState] = {}  # Estado por peer
    
    async def synchronize_graph(self, peer_id: str):
        """Sincroniza el grafo de conocimiento con un peer"""
        # Obtener nuestro estado actual
        our_state = await self._get_current_state()
        
        # Obtener estado del peer
        peer_state = await self._request_graph_state(peer_id)
        
        # Comparar estados y identificar diferencias
        differences = await self._compare_states(our_state, peer_state)
        
        if not differences:
            logger.info(f"Grafos ya sincronizados con {peer_id}")
            return
        
        # Sincronizar diferencias
        await self._sync_differences(peer_id, differences)
        
        # Actualizar estado de sincronización
        self.sync_states[peer_id] = our_state
    
    async def _get_current_state(self) -> GraphSyncState:
        """Obtiene el estado actual del grafo"""
        nodes = await self.graph_db.get_all_nodes()
        edges = await self.graph_db.get_all_edges()
        
        node_checksums = {}
        for node in nodes:
            node_checksums[node['id']] = self._calculate_node_checksum(node)
        
        edge_checksums = {}
        for edge in edges:
            edge_checksums[edge['id']] = self._calculate_edge_checksum(edge)
        
        return GraphSyncState(
            node_checksums=node_checksums,
            edge_checksums=edge_checksums,
            timestamp=asyncio.get_event_loop().time(),
            version=await self.graph_db.get_version()
        )
    
    def _calculate_node_checksum(self, node: Dict) -> str:
        """Calcula checksum para un nodo del grafo"""
        content = f"{node['id']}:{node['properties']}:{node['labels']}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _calculate_edge_checksum(self, edge: Dict) -> str:
        """Calcula checksum para una relación del grafo"""
        content = f"{edge['id']}:{edge['source']}:{edge['target']}:{edge['type']}:{edge['properties']}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def _compare_states(self, state_a: GraphSyncState, state_b: GraphSyncState) -> Dict:
        """Compara dos estados de grafo y identifica diferencias"""
        differences = {
            'nodes_missing_in_b': [],
            'nodes_missing_in_a': [],
            'nodes_different': [],
            'edges_missing_in_b': [],
            'edges_missing_in_a': [],
            'edges_different': []
        }
        
        # Comparar nodos
        for node_id, checksum_a in state_a.node_checksums.items():
            if node_id not in state_b.node_checksums:
                differences['nodes_missing_in_b'].append(node_id)
            elif checksum_a != state_b.node_checksums[node_id]:
                differences['nodes_different'].append(node_id)
        
        for node_id, checksum_b in state_b.node_checksums.items():
            if node_id not in state_a.node_checksums:
                differences['nodes_missing_in_a'].append(node_id)
        
        # Comparar relaciones
        for edge_id, checksum_a in state_a.edge_checksums.items():
            if edge_id not in state_b.edge_checksums:
                differences['edges_missing_in_b'].append(edge_id)
            elif checksum_a != state_b.edge_checksums[edge_id]:
                differences['edges_different'].append(edge_id)
        
        for edge_id, checksum_b in state_b.edge_checksums.items():
            if edge_id not in state_a.edge_checksums:
                differences['edges_missing_in_a'].append(edge_id)
        
        return differences