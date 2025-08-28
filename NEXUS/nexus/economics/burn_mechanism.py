from decimal import Decimal
from typing import Dict

class TokenBurnMechanism:
    """Mecanismo de quemado de tokens para sostenibilidad económica"""
    
    def __init__(self, burn_rates: Dict[str, Decimal]):
        self.burn_rates = burn_rates
        self.total_burned = Decimal('0')
        self.burn_events = []
    
    def calculate_burn_amount(self, transaction_type: str, amount: Decimal) -> Decimal:
        """Calcula la cantidad a quemar para una transacción"""
        burn_rate = self.burn_rates.get(transaction_type, Decimal('0.01'))
        burn_amount = amount * burn_rate
        return burn_amount
    
    def record_burn(self, transaction_type: str, amount: Decimal, burned_amount: Decimal):
        """Registra una operación de quemado"""
        self.total_burned += burned_amount
        self.burn_events.append({
            'type': transaction_type,
            'original_amount': amount,
            'burned_amount': burned_amount,
            'timestamp': datetime.now()
        })
    
    def get_burn_statistics(self) -> Dict[str, Decimal]:
        """Obtiene estadísticas de quemado"""
        total_by_type = {}
        for event in self.burn_events:
            if event['type'] not in total_by_type:
                total_by_type[event['type']] = Decimal('0')
            total_by_type[event['type']] += event['burned_amount']
        
        return {
            'total_burned': self.total_burned,
            'burn_by_type': total_by_type,
            'burn_events_count': len(self.burn_events)
        }
    
    def adjust_burn_rates(self, market_conditions: Dict[str, Decimal]):
        """Ajusta las tasas de quemado basado en condiciones de mercado"""
        price_volatility = market_conditions.get('price_volatility', Decimal('0.1'))
        trading_volume = market_conditions.get('trading_volume', Decimal('1000000'))
        
        # Ajustar tasas basado en volatilidad y volumen
        for tx_type in self.burn_rates:
            base_rate = self.burn_rates[tx_type]
            adjusted_rate = base_rate * (Decimal('1') + price_volatility)
            
            # Reducir tasa si el volumen es bajo
            if trading_volume < Decimal('500000'):
                adjusted_rate *= Decimal('0.8')
            
            self.burn_rates[tx_type] = max(Decimal('0.005'), min(adjusted_rate, Decimal('0.1')))