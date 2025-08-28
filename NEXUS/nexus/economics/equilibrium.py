from decimal import Decimal
from typing import Dict

class EconomicEquilibrium:
    """Mecanismos para mantener el equilibrio económico del ecosistema"""
    
    def __init__(self):
        self.burn_rates = {
            'transaction': Decimal('0.01'),    # 1% de quema por transacción
            'service_fee': Decimal('0.02'),     # 2% de quema por tarifas de servicio
            'governance': Decimal('0.005')      # 0.5% de quema por gobernanza
        }
        
        self.target_metrics = {
            'token_velocity': Decimal('1.2'),    # Velocidad objetivo del token
            'utilization_rate': Decimal('0.7'),  # Tasa de utilización objetivo
            'inflation_rate': Decimal('0.03')    # Inflación objetivo del 3%
        }
    
    async def adjust_economic_parameters(self, current_metrics: Dict) -> Dict:
        """Ajusta los parámetros económicos basado en métricas actuales"""
        adjustments = {}
        
        # Ajustar tasas de quema basado en velocidad del token
        velocity_ratio = current_metrics.get('token_velocity', Decimal('1.0')) / self.target_metrics['token_velocity']
        adjustments['burn_rates'] = {
            rate_type: rate * velocity_ratio
            for rate_type, rate in self.burn_rates.items()
        }
        
        # Ajustar emisión basado en utilización
        utilization_ratio = current_metrics.get('utilization_rate', Decimal('0.5')) / self.target_metrics['utilization_rate']
        adjustments['emission_rate'] = self.target_metrics['inflation_rate'] * utilization_ratio
        
        return adjustments
    
    async def calculate_economic_health(self, metrics: Dict) -> Dict:
        """Calcula la salud económica actual del ecosistema"""
        health_scores = {}
        
        # Score de velocidad (ideal cerca de 1.0)
        velocity_score = 1 - abs(metrics.get('token_velocity', Decimal('1.0')) - self.target_metrics['token_velocity'])
        health_scores['velocity'] = max(Decimal('0'), min(Decimal('1'), velocity_score))
        
        # Score de utilización (ideal alto)
        utilization_score = metrics.get('utilization_rate', Decimal('0'))
        health_scores['utilization'] = utilization_score
        
        # Score de inflación (controlada)
        inflation_score = 1 - abs(metrics.get('inflation_rate', Decimal('0')) - self.target_metrics['inflation_rate'])
        health_scores['inflation_control'] = max(Decimal('0'), min(Decimal('1'), inflation_score))
        
        # Score general (promedio ponderado)
        weights = {
            'velocity': Decimal('0.3'),
            'utilization': Decimal('0.4'),
            'inflation_control': Decimal('0.3')
        }
        
        overall_score = sum(health_scores[metric] * weights[metric] for metric in health_scores)
        health_scores['overall'] = overall_score
        
        return health_scores