from decimal import Decimal
from typing import Dict
from datetime import datetime

class NexusEconomicEngine:
    """Motor económico principal que integra todos los componentes"""
    
    def __init__(self, token_contract, initial_supply: Decimal):
        self.token_contract = token_contract
        self.current_supply = initial_supply
        self.total_burned = Decimal('0')
        self.economic_cycles = []
        
        # Subsistemas económicos
        self.reward_system = RewardDistribution(token_contract)
        self.emission_schedule = EmissionSchedule(initial_supply, initial_supply * Decimal('2'))
        self.equilibrium = EconomicEquilibrium()
        self.stabilization = TokenStabilization({'ETH': Decimal('1000')})
    
    async def run_economic_cycle(self, network_metrics: Dict) -> Dict:
        """Ejecuta un ciclo económico completo"""
        # 1. Calcular y emitir nuevas recompensas
        emission = await self.emission_schedule.calculate_emission(network_metrics)
        await self.token_contract.mint(emission)
        self.current_supply += emission
        
        # 2. Distribuir recompensas a contribuidores
        contributions = await self._get_network_contributions()
        rewards = await self.reward_system.distribute_rewards(contributions)
        
        # 3. Aplicar mecanismos de quema
        burn_amount = await self._calculate_burn_amount(network_metrics)
        if burn_amount > 0:
            await self.token_contract.burn(burn_amount)
            self.current_supply -= burn_amount
            self.total_burned += burn_amount
        
        # 4. Ajustar parámetros económicos
        adjustments = await self.equilibrium.adjust_economic_parameters(network_metrics)
        
        # 5. Registrar ciclo económico
        cycle_data = {
            'emission': emission,
            'rewards_distributed': sum(rewards.values()),
            'burned': burn_amount,
            'new_supply': self.current_supply,
            'adjustments': adjustments,
            'timestamp': datetime.now()
        }
        self.economic_cycles.append(cycle_data)
        
        return cycle_data
    
    async def get_economic_status(self) -> Dict:
        """Obtiene el estado económico actual"""
        if not self.economic_cycles:
            return {}
        
        last_cycle = self.economic_cycles[-1]
        health_score = await self.equilibrium.calculate_economic_health({
            'token_velocity': Decimal('1.2'),
            'utilization_rate': Decimal('0.65'),
            'inflation_rate': last_cycle['emission'] / self.current_supply
        })
        
        return {
            'current_supply': self.current_supply,
            'total_burned': self.total_burned,
            'circulating_supply': self.current_supply - self.total_burned,
            'health_score': health_score,
            'last_cycle': last_cycle
        }