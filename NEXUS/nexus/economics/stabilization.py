from decimal import Decimal
from typing import Dict

class TokenStabilization:
    """Sistema de estabilización del valor del token"""
    
    def __init__(self, reserve_assets: Dict[str, Decimal]):
        self.reserve_assets = reserve_assets
        self.stabilization_fund = Decimal('0')
        self.intervention_threshold = Decimal('0.2')  # 20% de desviación
        self.max_intervention = Decimal('0.1')         # Máximo 10% del fund por intervención
    
    async def should_intervene(self, price_deviation: Decimal, volume: Decimal) -> bool:
            """Determina si se debe intervenir para estabilizar el precio"""
            if abs(price_deviation) < self.intervention_threshold: # Removed 'Z'
                return False
            
            # Verificar que tenemos suficientes recursos
            required_intervention = volume * abs(price_deviation) * Decimal('0.5')
            if required_intervention > self.stabilization_fund * self.max_intervention:
                return False
            
            return True
    
    async def execute_intervention(self, price_deviation: Decimal, volume: Decimal) -> Dict:
        """Ejecuta una intervención de estabilización"""
        intervention_amount = volume * abs(price_deviation) * Decimal('0.5')
        intervention_amount = min(intervention_amount, self.stabilization_fund * self.max_intervention)
        
        if price_deviation > 0:
            # Precio muy alto - vender tokens del fund
            result = await self._sell_tokens(intervention_amount)
        else:
            # Precio muy bajo - comprar tokens
            result = await self._buy_tokens(intervention_amount)
        
        self.stabilization_fund -= intervention_amount
        return result
    
    async def rebalance_reserves(self, market_conditions: Dict) -> bool:
        """Rebalancea los activos de reserva basado en condiciones de mercado"""
        target_allocation = self._calculate_target_allocation(market_conditions)
        current_allocation = self._get_current_allocation()
        
        rebalance_needed = False
        for asset, target_percent in target_allocation.items():
            current_percent = current_allocation.get(asset, Decimal('0'))
            if abs(current_percent - target_percent) > Decimal('0.05'):  # 5% de desviación
                rebalance_needed = True
                break
        
        if rebalance_needed:
            await self._execute_rebalance(target_allocation)
            return True
        
        return False
