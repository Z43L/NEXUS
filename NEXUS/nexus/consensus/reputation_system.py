from typing import Dict, List, Optional
from datetime import datetime, timedelta
import numpy as np
from enum import Enum

class ReputationTier(Enum):
    NOVICE = "novice"        # 0.0 - 0.3
    APPRENTICE = "apprentice" # 0.3 - 0.6  
    EXPERT = "expert"        # 0.6 - 0.8
    MASTER = "master"        # 0.8 - 1.0

class ReputationSystem:
    """Sistema de reputación para validadores de la red"""
    
    def __init__(self):
        self.node_reputations: Dict[str, float] = {}
        self.voting_history: Dict[str, List[Dict]] = {}
        self.performance_metrics: Dict[str, Dict] = {}
        
    async def initialize_reputation(self, node_id: str, initial_reputation: float = 0.5):
        """Inicializa la reputación de un nuevo nodo"""
        if node_id not in self.node_reputations:
            self.node_reputations[node_id] = initial_reputation
            self.voting_history[node_id] = []
            self.performance_metrics[node_id] = {
                'total_votes': 0,
                'correct_votes': 0,
                'accuracy': 0.0,
                'participation_rate': 0.0,
                'last_activity': datetime.now()
            }
    
    async def adjust_reputation(self, node_id: str, delta: float) -> float:
        """Ajusta la reputación de un nodo"""
        if node_id not in self.node_reputations:
            await self.initialize_reputation(node_id)
        
        current_rep = self.node_reputations[node_id]
        new_rep = max(0.0, min(1.0, current_rep + delta))
        
        self.node_reputations[node_id] = new_rep
        return new_rep
    
    async def record_vote_outcome(self, node_id: str, was_correct: bool, confidence: float):
        """Registra el resultado de un voto para cálculo de precisión"""
        if node_id not in self.performance_metrics:
            await self.initialize_reputation(node_id)
        
        metrics = self.performance_metrics[node_id]
        metrics['total_votes'] += 1
        
        if was_correct:
            metrics['correct_votes'] += 1
        
        metrics['accuracy'] = metrics['correct_votes'] / metrics['total_votes']
        metrics['last_activity'] = datetime.now()
        
        # Añadir al historial de votos
        self.voting_history[node_id].append({
            'timestamp': datetime.now(),
            'was_correct': was_correct,
            'confidence': confidence,
            'reputation_at_time': self.node_reputations[node_id]
        })
        
        # Limitar historial para evitar crecimiento excesivo
        if len(self.voting_history[node_id]) > 1000:
            self.voting_history[node_id] = self.voting_history[node_id][-1000:]
    
    async def calculate_quality_score(self, node_id: str) -> float:
        """Calcula un score de calidad basado en el desempeño histórico"""
        if node_id not in self.voting_history or not self.voting_history[node_id]:
            return 0.5
        
        recent_votes = self.voting_history[node_id][-100:]  # Últimos 100 votos
        
        if not recent_votes:
            return 0.5
        
        # Ponderar votos recientes más heavily
        weights = np.linspace(0.5, 1.5, len(recent_votes))
        weighted_sum = 0.0
        total_weight = 0.0
        
        for i, vote in enumerate(recent_votes):
            weight = weights[i]
            vote_value = 1.0 if vote['was_correct'] else 0.0
            weighted_sum += vote_value * weight * vote['confidence']
            total_weight += weight
        
        return weighted_sum / total_weight if total_weight > 0 else 0.5
    
    async def get_validation_weight(self, node_id: str) -> float:
        """Calcula el peso de voto para un validador"""
        base_reputation = self.node_reputations.get(node_id, 0.5)
        quality_score = await self.calculate_quality_score(node_id)
        activity_score = self._calculate_activity_score(node_id)
        
        # Combinar scores con ponderaciones
        weight = (
            0.5 * base_reputation +
            0.3 * quality_score + 
            0.2 * activity_score
        )
        
        return max(0.1, min(1.0, weight))  # Mantener dentro de rango
    
    def _calculate_activity_score(self, node_id: str) -> float:
        """Calcula score basado en actividad reciente"""
        if node_id not in self.performance_metrics:
            return 0.0
        
        last_activity = self.performance_metrics[node_id]['last_activity']
        hours_inactive = (datetime.now() - last_activity).total_seconds() / 3600
        
        # Decaimiento exponencial de actividad
        activity_score = np.exp(-hours_inactive / 24)  # Decae a 1/e en 24 horas
        return max(0.0, min(1.0, activity_score))
    
    async def get_reputation_tier(self, node_id: str) -> ReputationTier:
        """Obtiene el tier de reputación de un nodo"""
        reputation = self.node_reputations.get(node_id, 0.0)
        
        if reputation >= 0.8:
            return ReputationTier.MASTER
        elif reputation >= 0.6:
            return ReputationTier.EXPERT
        elif reputation >= 0.3:
            return ReputationTier.APPRENTICE
        else:
            return ReputationTier.NOVICE
