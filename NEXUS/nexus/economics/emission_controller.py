from decimal import Decimal
from typing import Dict

class ControlledEmissionModel:
    """Modelo de emisión controlada de tokens"""
    
    def __init__(self, base_emission_rate: Decimal, adjustment_factors: Dict[str, Decimal]):
        self.base_emission_rate = base_emission_rate
        self.adjustment_factors = adjustment_factors
        self.current_emission_rate = base_emission_rate
        self.emission_history = []
    
    def calculate_emission(self, total_supply: Decimal, network_metrics: Dict[str, Decimal]) -> Decimal:
        """Calcula la emisión para el período actual"""
        # Factores de ajuste basados en métricas de red
        utilization_factor = self._calculate_utilization_factor(network_metrics)
        demand_factor = self._calculate_demand_factor(network_metrics)
        velocity_factor = self._calculate_velocity_factor(network_metrics)
        
        # Tasa de emisión ajustada
        adjusted_rate = self.base_emission_rate * utilization_factor * demand_factor * velocity_factor
        
        # Limitar ajustes para evitar cambios bruscos
        max_change = Decimal('0.1')  # Máximo 10% de cambio por período
        if abs(adjusted_rate - self.current_emission_rate) > max_change:
            if adjusted_rate > self.current_emission_rate:
                adjusted_rate = self.current_emission_rate + max_change
            else:
                adjusted_rate = self.current_emission_rate - max_change
        
        self.current_emission_rate = max(Decimal('0.01'), adjusted_rate)  # Mínimo 1%
        
        # Calcular emisión absoluta
        emission_amount = total_supply * self.current_emission_rate
        
        # Registrar en historial
        self.emission_history.append({
            'rate': self.current_emission_rate,
            'amount': emission_amount,
            'timestamp': datetime.now(),
            'metrics': network_metrics
        })
        
        return emission_amount
    
    def _calculate_utilization_factor(self, metrics: Dict[str, Decimal]) -> Decimal:
        """Calcula factor basado en utilización de recursos"""
        utilization = metrics.get('resource_utilization', Decimal('0.5'))
        # Mayor utilización -> menor emisión
        return Decimal('1.5') - utilization  # 1.0 cuando utilization es 0.5
    
    def _calculate_demand_factor(self, metrics: Dict[str, Decimal]) -> Decimal:
        """Calcula factor basado en demanda de servicios"""
        demand = metrics.get('service_demand', Decimal('0.5'))
        # Mayor demanda -> mayor emisión
        return Decimal('0.5') + demand
    
    def _calculate_velocity_factor(self, metrics: Dict[str, Decimal]) -> Decimal:
        """Calcula factor basado en velocidad del dinero"""
        velocity = metrics.get('token_velocity', Decimal('1.0'))
        # Mayor velocidad -> menor emisión
        return Decimal('2.0') - velocity