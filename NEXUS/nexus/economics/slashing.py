from typing import Dict, List
from decimal import Decimal
from datetime import datetime, timedelta

class SlashingMechanism:
    """Mecanismo de slashing para desincentivar mala conducta"""
    
    def __init__(self, base_slash_rates: Dict[str, Decimal]):
        self.base_slash_rates = base_slash_rates
        self.infraction_history: Dict[str, List[Dict]] = {}
        self.reputation_scores: Dict[str, Decimal] = {}
    
    def record_infraction(self, node_id: str, infraction_type: str, severity: Decimal) -> Decimal:
        """Registra una infracción y calcula la penalización"""
        slash_rate = self.base_slash_rates.get(infraction_type, Decimal('0.05'))
        penalty = slash_rate * severity
        
        # Añadir al historial
        if node_id not in self.infraction_history:
            self.infraction_history[node_id] = []
        
        self.infraction_history[node_id].append({
            'type': infraction_type,
            'severity': severity,
            'penalty': penalty,
            'timestamp': datetime.now()
        })
        
        # Actualizar score de reputación
        self._update_reputation_score(node_id, penalty)
        
        return penalty
    
    def _update_reputation_score(self, node_id: str, penalty: Decimal):
        """Actualiza el score de reputación de un nodo"""
        if node_id not in self.reputation_scores:
            self.reputation_scores[node_id] = Decimal('1.0')
        
        self.reputation_scores[node_id] -= penalty
        self.reputation_scores[node_id] = max(Decimal('0.0'), self.reputation_scores[node_id])
    
    def calculate_slashing_amount(self, node_id: str, staked_amount: Decimal) -> Decimal:
        """Calcula la cantidad a slashear basado en el historial"""
        if node_id not in self.infraction_history:
            return Decimal('0')
        
        total_penalty = Decimal('0')
        recent_infractions = [
            inf for inf in self.infraction_history[node_id]
            if datetime.now() - inf['timestamp'] < timedelta(days=90)
        ]
        
        for infraction in recent_infractions:
            total_penalty += infraction['penalty']
        
        # Aplicar penalización máxima del 100%
        total_penalty = min(total_penalty, Decimal('1.0'))
        
        return staked_amount * total_penalty
    
    def get_reputation_score(self, node_id: str) -> Decimal:
        """Obtiene el score de reputación actual de un nodo"""
        return self.reputation_scores.get(node_id, Decimal('1.0'))
