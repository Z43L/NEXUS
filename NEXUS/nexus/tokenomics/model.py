from typing import Dict, List
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

@dataclass
class TokenomicsConfig:
    """Configuración completa de la economía de tokens"""
    total_supply: Decimal
    initial_distribution: Dict[str, Decimal]
    inflation_rate: Decimal
    staking_rewards: Decimal
    validation_rewards: Decimal
    storage_rewards: Decimal
    burn_rate: Decimal
    governance_weight: Dict[str, Decimal]

class TripleLayerTokenomics:
    """Modelo tokenómico de triple capa para NEXUS"""
    
    def __init__(self, config: TokenomicsConfig):
        self.config = config
        self.current_supply = config.total_supply
        self.distribution_history = []
        self.reward_pools = {
            'staking': Decimal('0'),
            'validation': Decimal('0'),
            'storage': Decimal('0'),
            'governance': Decimal('0')
        }
    
    def calculate_emission(self, time_period: timedelta) -> Decimal:
        """Calcula la emisión de tokens para un período dado"""
        base_emission = self.current_supply * self.config.inflation_rate
        adjusted_emission = base_emission * (time_period.days / 365)
        return adjusted_emission
    
    def distribute_rewards(self, contributions: Dict[str, Decimal]) -> Dict[str, Decimal]:
        """Distribuye recompensas basado en contribuciones"""
        total_emission = self.calculate_emission(timedelta(days=1))
        
        rewards = {}
        for pool_name, pool_amount in self.reward_pools.items():
            pool_share = contributions.get(pool_name, Decimal('0'))
            rewards[pool_name] = total_emission * pool_share
        
        # Actualizar supply
        self.current_supply += total_emission
        
        return rewards
    
    def adjust_reward_pools(self, network_metrics: Dict[str, Decimal]):
        """Ajusta dinámicamente los pools de recompensa"""
        # Lógica de ajuste basada en métricas de red
        storage_utilization = network_metrics.get('storage_utilization', Decimal('0.5'))
        validation_accuracy = network_metrics.get('validation_accuracy', Decimal('0.8'))
        staking_participation = network_metrics.get('staking_participation', Decimal('0.6'))
        
        # Ajustar pesos según necesidades de la red
        self.reward_pools['storage'] = storage_utilization
        self.reward_pools['validation'] = validation_accuracy
        self.reward_pools['staking'] = staking_participation