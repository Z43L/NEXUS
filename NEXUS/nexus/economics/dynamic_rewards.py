from typing import Dict
from decimal import Decimal
from datetime import datetime

class DynamicRewardSystem:
    """Sistema de recompensas dinámicas basado en oferta/demanda"""
    
    def __init__(self, base_rewards: Dict[str, Decimal]):
        self.base_rewards = base_rewards
        self.demand_factors = {
            'computation': Decimal('1.0'),
            'storage': Decimal('1.0'),
            'validation': Decimal('1.0'),
            'bandwidth': Decimal('1.0')
        }
        self.supply_factors = {
            'computation': Decimal('1.0'),
            'storage': Decimal('1.0'),
            'validation': Decimal('1.0'),
            'bandwidth': Decimal('1.0')
        }
    
    def calculate_dynamic_reward(self, resource_type: str, contribution_amount: Decimal) -> Decimal:
        """Calcula recompensa dinámica basada en oferta/demanda"""
        base_reward = self.base_rewards.get(resource_type, Decimal('0'))
        demand_factor = self.demand_factors.get(resource_type, Decimal('1.0'))
        supply_factor = self.supply_factors.get(resource_type, Decimal('1.0'))
        
        dynamic_reward = base_reward * demand_factor / supply_factor * contribution_amount
        return max(Decimal('0.01'), dynamic_reward)  # Recompensa mínima
    
    def update_market_factors(self, network_metrics: Dict[str, Decimal]):
        """Actualiza factores de oferta/demanda basado en métricas de red"""
        # Oferta: recursos disponibles en la red
        computation_supply = network_metrics.get('available_computation', Decimal('1000'))
        storage_supply = network_metrics.get('available_storage', Decimal('1000000'))
        validation_supply = network_metrics.get('available_validators', Decimal('1000'))
        
        # Demanda: recursos solicitados por usuarios
        computation_demand = network_metrics.get('computation_demand', Decimal('500'))
        storage_demand = network_metrics.get('storage_demand', Decimal('500000'))
        validation_demand = network_metrics.get('validation_demand', Decimal('500'))
        
        # Actualizar factores
        self.supply_factors['computation'] = computation_supply / Decimal('1000')
        self.demand_factors['computation'] = computation_demand / Decimal('500')
        
        self.supply_factors['storage'] = storage_supply / Decimal('1000000')
        self.demand_factors['storage'] = storage_demand / Decimal('500000')
        
        self.supply_factors['validation'] = validation_supply / Decimal('1000')
        self.demand_factors['validation'] = validation_demand / Decimal('500')
    
    def get_current_rewards(self) -> Dict[str, Decimal]:
        """Obtiene las recompensas actuales para cada tipo de recurso"""
        return {
            'computation': self.calculate_dynamic_reward('computation', Decimal('1')),
            'storage': self.calculate_dynamic_reward('storage', Decimal('1')),
            'validation': self.calculate_dynamic_reward('validation', Decimal('1')),
            'bandwidth': self.calculate_dynamic_reward('bandwidth', Decimal('1'))
        }