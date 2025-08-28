from typing import Dict, List
from decimal import Decimal
from datetime import datetime

class RewardDistribution:
    """Sistema de distribución de recompensas por contribuciones"""
    
    def __init__(self, token_contract):
        self.token_contract = token_contract
        self.reward_pools = {
            'computation': Decimal('0.4'),    # 40% para cómputo
            'storage': Decimal('0.3'),        # 30% para almacenamiento
            'validation': Decimal('0.2'),      # 20% para validación
            'governance': Decimal('0.1')       # 10% para gobernanza
        }
    
    async def distribute_rewards(self, contributions: Dict[str, List[Dict]]) -> Dict[str, Decimal]:
        """Distribuye recompensas basado en contribuciones verificadas"""
        total_rewards = await self._calculate_total_rewards()
        distributed_rewards = {}
        
        for contribution_type, contributions_list in contributions.items():
            pool_share = self.reward_pools.get(contribution_type, Decimal('0'))
            pool_rewards = total_rewards * pool_share
            
            if contributions_list:
                rewards = await self._distribute_pool_rewards(contributions_list, pool_rewards)
                distributed_rewards[contribution_type] = rewards
        
        return distributed_rewards
    
    async def _distribute_pool_rewards(self, contributions: List[Dict], pool_rewards: Decimal) -> Decimal:
        """Distribuye recompensas dentro de un pool específico"""
        total_contribution_value = sum(contrib['value'] for contrib in contributions)
        
        if total_contribution_value == 0:
            return Decimal('0')
        
        distributed_total = Decimal('0')
        for contribution in contributions:
            share = contribution['value'] / total_contribution_value
            reward = pool_rewards * share
            
            await self.token_contract.transfer(
                contribution['contributor'], 
                reward
            )
            distributed_total += reward
        
        return distributed_total