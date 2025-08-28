from decimal import Decimal
from datetime import datetime, timedelta

class EmissionSchedule:
    """Calendario de emisión controlada de tokens"""
    
    def __init__(self, initial_supply: Decimal, max_supply: Decimal):
        self.initial_supply = initial_supply
        self.max_supply = max_supply
        self.current_supply = initial_supply
        self.emission_events = []
        
        # Parámetros de emisión ajustables
        self.base_emission_rate = Decimal('0.05')  # 5% anual inicial
        self.adjustment_factor = Decimal('0.8')    # Factor de ajuste por uso
        self.min_emission_rate = Decimal('0.01')   # 1% mínimo
        self.max_emission_rate = Decimal('0.15')   # 15% máximo
    
    async def calculate_emission(self, network_metrics: Dict) -> Decimal:
        """Calcula la emisión para el período actual basado en métricas de red"""
        utilization = network_metrics.get('network_utilization', Decimal('0.5'))
        demand = network_metrics.get('service_demand', Decimal('0.5'))
        
        # Tasa base ajustada por utilización y demanda
        adjusted_rate = self.base_emission_rate * (Decimal('1') + utilization * demand)
        
        # Aplicar límites
        emission_rate = max(self.min_emission_rate, min(adjusted_rate, self.max_emission_rate))
        
        emission_amount = self.current_supply * emission_rate
        
        # Verificar límite de supply máximo
        if self.current_supply + emission_amount > self.max_supply:
            emission_amount = self.max_supply - self.current_supply
        
        self.current_supply += emission_amount
        self.emission_events.append({
            'rate': emission_rate,
            'amount': emission_amount,
            'timestamp': datetime.now(),
            'metrics': network_metrics
        })
        
        return emission_amount