from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime, timedelta

class GovernanceRepresentatives:
    """Sistema de representantes de gobernanza elegidos"""
    
    def __init__(self, token_contract, delegation_contract):
        self.token_contract = token_contract
        self.delegation_contract = delegation_contract
        self.representatives: Dict[str, Dict] = {}
        self.election_period = timedelta(days=90)  # Elecciones trimestrales
        self.next_election = datetime.now() + self.election_period
    
    async def elect_representatives(self, num_representatives: int = 21) -> List[str]:
        """Realiza elecciones para elegir representantes"""
        # Obtener todos los holders con poder de voto significativo
        significant_holders = await self._get_significant_holders()
        
        # Ordenar por poder de voto (incluyendo delegaciones)
        holders_with_power = []
        for holder in significant_holders:
            voting_power = await self.delegation_contract.get_effective_voting_power(holder)
            holders_with_power.append((holder, voting_power))
        
        # Ordenar por poder de voto descendente
        holders_with_power.sort(key=lambda x: x[1], reverse=True)
        
        # Seleccionar los N principales como representantes
        elected_representatives = [holder for holder, power in holders_with_power[:num_representatives]]
        
        # Actualizar lista de representantes
        for rep in elected_representatives:
            self.representatives[rep] = {
                'elected_at': datetime.now(),
                'voting_power': await self.delegation_contract.get_effective_voting_power(rep),
                'delegator_count': await self._get_delegator_count(rep)
            }
        
        self.next_election = datetime.now() + self.election_period
        return elected_representatives
    
    async def can_propose_as_representative(self, representative: str) -> bool:
        """Verifica si un representante puede proponer en nombre de sus delegantes"""
        if representative not in self.representatives:
            return False
        
        rep_info = self.representatives[representative]
        total_delegated_power = rep_info['voting_power'] - await self.token_contract.balance_of(representative)
        
        # Puede proponer si tiene poder delegado significativo
        return total_delegated_power > Decimal('100000')  # 100k tokens delegados
    
    async def vote_as_representative(self, representative: str, proposal_id: str, support: bool) -> bool:
        """Vota en nombre de los delegantes"""
        if representative not in self.representatives:
            return False
        
        # Obtener poder de voto total (incluyendo delegaciones)
        total_voting_power = await self.delegation_contract.get_effective_voting_power(representative)
        
        # Emitir voto con el poder total
        return await self.voting_system.cast_vote(proposal_id, representative, support, total_voting_power)
    
    async def get_representation_metrics(self) -> Dict:
        """Obtiene métricas sobre la representación en la gobernanza"""
        total_supply = await self.token_contract.total_supply()
        delegated_tokens = Decimal('0')
        
        for rep in self.representatives:
            rep_power = await self.delegation_contract.get_effective_voting_power(rep)
            own_tokens = await self.token_contract.balance_of(rep)
            delegated_tokens += (rep_power - own_tokens)
        
        representation_ratio = (delegated_tokens / total_supply) * 100
        
        return {
            'total_representatives': len(self.representatives),
            'delegated_tokens': delegated_tokens,
            'representation_ratio': representation_ratio,
            'average_delegators_per_rep': await self._get_average_delegator_count()
        }
