from typing import Dict, List, Optional
from datetime import datetime, timedelta

class VoteDelegationSystem:
    """Sistema de delegación de votos para gobierno descentralizado"""
    
    def __init__(self):
        self.delegations: Dict[str, str] = {}  # delegator -> delegatee
        self.delegation_history: Dict[str, List[Dict]] = {}
        self.delegatee_scores: Dict[str, Decimal] = {}
    
    def delegate_vote(self, delegator: str, delegatee: str) -> bool:
        """Delega el voto a otro address"""
        if delegator == delegatee:
            return False  # No auto-delegación
        
        # Registrar delegación
        self.delegations[delegator] = delegatee
        
        # Actualizar historial
        if delegator not in self.delegation_history:
            self.delegation_history[delegator] = []
        
        self.delegation_history[delegator].append({
            'delegatee': delegatee,
            'timestamp': datetime.now(),
            'block_number': 0  # Se actualizaría con el block number real
        })
        
        return True
    
    def undelegate_vote(self, delegator: str) -> bool:
        """Revoca la delegación de voto"""
        if delegator not in self.delegations:
            return False
        
        del self.delegations[delegator]
        return True
    
    def calculate_voting_power(self, voter: str, token_balance: Decimal) -> Decimal:
        """Calcula el poder de voto considerando delegaciones"""
        # Seguir la cadena de delegación
        current_voter = voter
        visited = set()
        
        while current_voter in self.delegations:
            if current_voter in visited:
                break  # Evitar ciclos
            visited.add(current_voter)
            current_voter = self.delegations[current_voter]
        
        # Si el voto termina delegado, el poder va al delegatee
        if current_voter != voter:
            return Decimal('0')  # El delegador original no vota directamente
        
        # Calcular poder de voto total incluyendo delegaciones recibidas
        total_power = token_balance
        for delegator, delegatee in self.delegations.items():
            if delegatee == voter:
                # Añadir poder de los delegadores
                delegator_balance = self._get_token_balance(delegator)
                total_power += delegator_balance
        
        return total_power
    
    def get_delegation_chain(self, voter: str) -> List[str]:
        """Obtiene la cadena completa de delegación"""
        chain = [voter]
        current = voter
        
        while current in self.delegations:
            next_delegatee = self.delegations[current]
            if next_delegatee in chain:
                break  # Evitar ciclos
            chain.append(next_delegatee)
            current = next_delegatee
        
        return chain
    
    def _get_token_balance(self, address: str) -> Decimal:
        """Obtiene el balance de tokens de una dirección"""
        # Implementación real conectaría con el contrato de tokens
        return Decimal('0')