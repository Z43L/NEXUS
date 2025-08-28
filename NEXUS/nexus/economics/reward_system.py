from typing import Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import asyncio

class RewardSystem:
    """Sistema de recompensas por contribuciones a la red"""
    
    def __init__(self, token_contract, reputation_system):
        self.token_contract = token_contract
        self.reputation = reputation_system
        self.contributions: Dict[str, List[Dict]] = {}
        self.pending_rewards: Dict[str, Decimal] = {}
        
    async def record_contribution(self, node_id: str, contribution_type: str, 
                                value: Decimal, difficulty: float = 1.0):
        """Registra una contribución a la red"""
        contribution = {
            'type': contribution_type,
            'value': value,
            'difficulty': difficulty,
            'timestamp': datetime.now(),
            'reputation_at_time': await self.reputation.get_reputation(node_id)
        }
        
        if node_id not in self.contributions:
            self.contributions[node_id] = []
        
        self.contributions[node_id].append(contribution)
        
        # Calcular recompensa inmediata
        reward = await self._calculate_reward(contribution)
        await self._add_pending_reward(node_id, reward)
    
    async def _calculate_reward(self, contribution: Dict) -> Decimal:
        """Calcula la recompensa por una contribución"""
        base_reward = {
            'validation': Decimal('10.0'),
            'storage': Decimal('5.0'),
            'computation': Decimal('15.0'),
            'bandwidth': Decimal('2.0')
        }.get(contribution['type'], Decimal('1.0'))
        
        # Modificar por dificultad y reputación
        difficulty_multiplier = Decimal(str(contribution['difficulty']))
        reputation_multiplier = Decimal(str(contribution['reputation_at_time']))
        
        reward = base_reward * difficulty_multiplier * reputation_multiplier
        return max(Decimal('0.1'), reward)  # Recompensa mínima
    
    async def _add_pending_reward(self, node_id: str, reward: Decimal):
        """Añade recompensa al pendiente de pago"""
        if node_id not in self.pending_rewards:
            self.pending_rewards[node_id] = Decimal('0.0')
        
        self.pending_rewards[node_id] += reward
        
        # Si las recompensas pendientes superan el umbral, procesar pago
        if self.pending_rewards[node_id] >= Decimal('50.0'):
            await self.process_rewards(node_id)
    
    async def process_rewards(self, node_id: str):
        """Procesa el pago de recompensas pendientes"""
        if node_id not in self.pending_rewards or self.pending_rewards[node_id] <= 0:
            return
        
        amount = self.pending_rewards[node_id]
        
        try:
            # Ejecutar transferencia en el contrato de tokens
            success = await self.token_contract.transfer(
                to_address=node_id,
                amount=amount
            )
            
            if success:
                print(f"Recompensa de {amount} tokens pagada a {node_id}")
                self.pending_rewards[node_id] = Decimal('0.0')
            else:
                print(f"Error procesando recompensa para {node_id}")
                
        except Exception as e:
            print(f"Excepción procesando recompensa: {e}")
    
    async def calculate_apy(self, node_id: str) -> float:
        """Calcula el APY estimado para un nodo"""
        if node_id not in self.contributions or not self.contributions[node_id]:
            return 0.0
        
        # Calcular recompensas diarias promedio
        recent_contributions = [
            c for c in self.contributions[node_id]
            if datetime.now() - c['timestamp'] < timedelta(days=30)
        ]
        
        if not recent_contributions:
            return 0.0
        
        daily_rewards = sum(
            float(await self._calculate_reward(c)) 
            for c in recent_contributions
        ) / 30  # Promedio diario de 30 días
        
        # Asumir valor de stake para cálculo de APY (simplificado)
        # En implementación real, esto vendría del contrato de staking
        assumed_stake = 1000.0  # 1000 tokens de stake
        
        if assumed_stake <= 0:
            return 0.0
        
        # Calcular APY anualizado
        apy = (daily_rewards * 365) / assumed_stake * 100
        return apy