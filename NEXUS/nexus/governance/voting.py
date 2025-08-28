from typing import Dict, List, Optional
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime

@dataclass
class VotingPower:
    """Estructura que representa el poder de voto de un participante"""
    token_weight: Decimal
    reputation_weight: Decimal
    tenure_weight: Decimal
    contribution_weight: Decimal
    total_power: Decimal

class ReputationWeightedVoting:
    """Sistema de votación ponderada por reputación"""
    
    def __init__(self, token_contract, reputation_system):
        self.token_contract = token_contract
        self.reputation_system = reputation_system
        self.vote_history: Dict[str, List] = {}
        
    async def calculate_voting_power(self, voter_address: str) -> VotingPower:
        """Calcula el poder de voto completo de un participante"""
        # Peso base por tokens
        token_balance = await self.token_contract.balance_of(voter_address)
        token_weight = token_balance * Decimal('0.6')  # 60% peso base
        
        # Peso por reputación
        reputation_score = await self.reputation_system.get_reputation(voter_address)
        reputation_weight = reputation_score * Decimal('1000') * Decimal('0.2')  # 20% peso
        
        # Peso por antigüedad en la red
        tenure = await self._calculate_tenure(voter_address)
        tenure_weight = tenure * Decimal('0.1')  # 10% peso
        
        # Peso por contribuciones recientes
        contributions = await self._get_recent_contributions(voter_address)
        contribution_weight = contributions * Decimal('0.1')  # 10% peso
        
        total_power = token_weight + reputation_weight + tenure_weight + contribution_weight
        
        return VotingPower(
            token_weight=token_weight,
            reputation_weight=reputation_weight,
            tenure_weight=tenure_weight,
            contribution_weight=contribution_weight,
            total_power=total_power
        )
    
    async def cast_vote(self, proposal_id: str, voter_address: str, support: bool, voting_power: Decimal) -> bool:
        """Emite un voto en una propuesta específica"""
        if proposal_id not in self.vote_history:
            self.vote_history[proposal_id] = []
        
        vote_record = {
            'voter': voter_address,
            'support': support,
            'voting_power': voting_power,
            'timestamp': datetime.now(),
            'calculated_power': await self.calculate_voting_power(voter_address)
        }
        
        self.vote_history[proposal_id].append(vote_record)
        return True
    
    async def get_proposal_result(self, proposal_id: str) -> Dict:
        """Calcula el resultado actual de una propuesta"""
        if proposal_id not in self.vote_history:
            return {'total_votes': 0, 'for_votes': 0, 'against_votes': 0}
        
        votes = self.vote_history[proposal_id]
        for_votes = sum(vote['voting_power'] for vote in votes if vote['support'])
        against_votes = sum(vote['voting_power'] for vote in votes if not vote['support'])
        total_votes = for_votes + against_votes
        
        return {
            'total_votes': total_votes,
            'for_votes': for_votes,
            'against_votes': against_votes,
            'approval_percentage': (for_votes / total_votes * 100) if total_votes > 0 else 0
        }