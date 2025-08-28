from decimal import Decimal
from typing import Dict

class InitialDistribution:
    """Configuración de la distribución inicial de tokens"""
    
    def __init__(self):
        self.distribution = {
            'ecosystem_fund': Decimal('0.25'),      # 25% - Fondo para desarrollo del ecosistema
            'team_and_contributors': Decimal('0.15'), # 15% - Equipo y contribuidores iniciales
            'public_sale': Decimal('0.10'),         # 10% - Venta pública
            'liquidity_provision': Decimal('0.05'),   # 5% - Provisión de liquidez
            'community_rewards': Decimal('0.20'),    # 20% - Recompensas comunitarias
            'network_incentives': Decimal('0.25')    # 25% - Incentivos de red
        }
        
        self.vesting_schedules = {
            'team_and_contributors': {
                'cliff': 365,       # 1 año de cliff
                'duration': 1095,    # 3 años de vesting
                'release_interval': 30  # Liberación mensual
            },
            'ecosystem_fund': {
                'cliff': 180,
                'duration': 1825,   # 5 años de vesting
                'release_interval': 90  # Liberación trimestral
            }
        }
    
    def get_initial_allocation(self, total_supply: Decimal) -> Dict[str, Decimal]:
        """Calcula la asignación inicial de tokens"""
        return {
            category: total_supply * percentage
            for category, percentage in self.distribution.items()
        }