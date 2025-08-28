from typing import Dict, Optional
from decimal import Decimal
from datetime import datetime, timedelta

class DisputeResolution:
    """Sistema de resolución de disputas para gobernanza"""
    
    def __init__(self, token_contract, reputation_system):
        self.token_contract = token_contract
        self.reputation_system = reputation_system
        self.active_disputes: Dict[str, Dict] = {}
        self.dispute_rounds: Dict[str, List] = {}
    
    async def create_dispute(self, dispute_type: str, target_id: str, reason: str, creator: str) -> Optional[str]:
        """Crea una nueva disputa"""
        # Verificar requisitos mínimos para crear disputa
        creator_tokens = await self.token_contract.balance_of(creator)
        if creator_tokens < Decimal('10000'):  # 10k tokens mínimos
            return None
        
        dispute_id = f"dispute_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        dispute = {
            'id': dispute_id,
            'type': dispute_type,
            'target_id': target_id,
            'reason': reason,
            'creator': creator,
            'created_at': datetime.now(),
            'status': 'active',
            'total_bond': Decimal('0'),
            'votes_for': Decimal('0'),
            'votes_against': Decimal('0')
        }
        
        self.active_disputes[dispute_id] = dispute
        return dispute_id
    
    async def add_dispute_bond(self, dispute_id: str, amount: Decimal, supporter: str, supports: bool) -> bool:
        """Añade fianza a una disputa existente"""
        if dispute_id not in self.active_disputes:
            return False
        
        dispute = self.active_disputes[dispute_id]
        
        # Verificar que el supporter tiene los fondos
        supporter_balance = await self.token_contract.balance_of(supporter)
        if supporter_balance < amount:
            return False
        
        # Transferir fianza
        await self.token_contract.transfer(supporter, self.treasury_address, amount)
        
        # Registrar apoyo
        if supports:
            dispute['votes_for'] += amount
        else:
            dispute['votes_against'] += amount
        
        dispute['total_bond'] += amount
        
        # Iniciar votación si se alcanza el umbral de fianza
        if dispute['total_bond'] >= await self._get_required_bond(dispute['type']):
            await self._start_dispute_voting(dispute_id)
        
        return True
    
    async def _start_dispute_voting(self, dispute_id: str):
        """Inicia la votación para una disputa"""
        dispute = self.active_disputes[dispute_id]
        dispute['voting_start'] = datetime.now()
        dispute['voting_end'] = datetime.now() + timedelta(days=7)
        dispute['status'] = 'voting'
    
    async def resolve_dispute(self, dispute_id: str) -> Dict:
        """Resuelve una disputa basado en los votos y fianzas"""
        if dispute_id not in self.active_disputes:
            return {'error': 'Dispute not found'}
        
        dispute = self.active_disputes[dispute_id]
        
        if dispute['status'] != 'voting':
            return {'error': 'Dispute not in voting phase'}
        
        if datetime.now() < dispute['voting_end']:
            return {'error': 'Voting period not ended'}
        
        total_votes = dispute['votes_for'] + dispute['votes_against']
        if total_votes == 0:
            return {'error': 'No votes cast'}
        
        # Determinar resultado
        if dispute['votes_for'] > dispute['votes_against']:
            dispute['status'] = 'resolved_for'
            outcome = 'for'
        else:
            dispute['status'] = 'resolved_against'
            outcome = 'against'
        
        # Distribuir recompensas/penalizaciones
        await self._distribute_dispute_outcome(dispute_id, outcome)
        
        return {
            'dispute_id': dispute_id,
            'outcome': outcome,
            'votes_for': dispute['votes_for'],
            'votes_against': dispute['votes_against'],
            'total_bond': dispute['total_bond']
        }
