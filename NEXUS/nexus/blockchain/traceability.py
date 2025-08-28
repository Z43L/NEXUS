from typing import Dict, List, Optional, Set
from web3 import Web3
import networkx as nx
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd

class KnowledgeTraceability:
    """Sistema de análisis de trazabilidad del conocimiento"""
    
    def __init__(self, web3_provider, contract_address, contract_abi):
        self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        self.contract = self.web3.eth.contract(
            address=contract_address,
            abi=contract_abi
        )
        self.knowledge_graph = nx.DiGraph()
    
    async def build_knowledge_graph(self, root_hash: str, max_depth: int = 3) -> nx.DiGraph:
        """
        Construye un grafo de conocimiento a partir de un hash raíz
        
        Args:
            root_hash: Hash del conocimiento raíz
            max_depth: Profundidad máxima de exploración
            
        Returns:
            Grafo de conocimiento con relaciones
        """
        await self._explore_knowledge_tree(root_hash, 0, max_depth)
        return self.knowledge_graph
    
    async def _explore_knowledge_tree(self, knowledge_hash: str, current_depth: int, max_depth: int):
        """Explora recursivamente el árbol de conocimiento"""
        if current_depth >= max_depth:
            return
        
        if knowledge_hash in self.knowledge_graph:
            return
        
        # Obtener información del conocimiento
        knowledge_info = await self._get_knowledge_info(knowledge_hash)
        if not knowledge_info:
            return
        
        # Añadir nodo al grafo
        self.knowledge_graph.add_node(knowledge_hash, **knowledge_info)
        
        # Explorar conocimientos relacionados
        related_hashes = await self._get_related_knowledge(knowledge_hash)
        
        for related_hash in related_hashes:
            # Añadir arista de relación
            self.knowledge_graph.add_edge(knowledge_hash, related_hash)
            
            # Explorar recursivamente
            await self._explore_knowledge_tree(related_hash, current_depth + 1, max_depth)
    
    async def analyze_knowledge_flow(self, start_hash: str, end_hash: str) -> Optional[List]:
        """
        Analiza el flujo de conocimiento entre dos puntos
        
        Args:
            start_hash: Hash de inicio
            end_hash: Hash de destino
            
        Returns:
            Camino óptimo entre los conocimientos
        """
        if start_hash not in self.knowledge_graph or end_hash not in self.knowledge_graph:
            await self.build_knowledge_graph(start_hash, max_depth=5)
        
        try:
            path = nx.shortest_path(self.knowledge_graph, start_hash, end_hash)
            return path
        except nx.NetworkXNoPath:
            return None
    
    def visualize_knowledge_graph(self, graph: nx.DiGraph, output_path: str):
        """
        Visualiza el grafo de conocimiento
        
        Args:
            graph: Grafo a visualizar
            output_path: Ruta donde guardar la visualización
        """
        plt.figure(figsize=(12, 8))
        
        pos = nx.spring_layout(graph, k=0.5, iterations=50)
        nx.draw_networkx_nodes(graph, pos, node_color='lightblue', node_size=500)
        nx.draw_networkx_edges(graph, pos, edge_color='gray', arrows=True)
        nx.draw_networkx_labels(graph, pos, font_size=8)
        
        plt.title("Knowledge Relationship Graph")
        plt.axis('off')
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()