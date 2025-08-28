from enum import Enum
from decimal import Decimal
from typing import Dict, Optional
from datetime import datetime, timedelta

class ProposalType(Enum):
    """Tipos de propuestas de gobernanza soportadas"""
    PARAMETER_CHANGE = "parameter_change"      # Cambio de parámetros del protocolo
    TREASURY_MANAGEMENT = "treasury_management" # Gestión de fondos de la tesorería
    PROTOCOL_UPGRADE = "protocol_upgrade"      # Actualizaciones del protocolo
    EMERGENCY_MEASURE = "emergency_measure"     # Medidas de emergencia
    COMMUNITY_INITIATIVE = "community_initiative" # Iniciativas comunitarias
    ECOSYSTEM_FUNDING = "ecosystem_funding"     # Financiamiento de ecosistema

class ProposalRequirements:
    """Requisitos específicos para cada tipo de propuesta"""
    
    def __init__(self):
        self.requirements = {
            ProposalType.PARAMETER_CHANGE: {
                'min_tokens': Decimal('50000'),      # 50k tokens para proponer
                'voting_period': timedelta(days=3),
                'quorum_percentage': Decimal('0.20'), # 20% de quórum
                'approval_threshold': Decimal('0.60') # 60% de aprobación
            },
            ProposalType.TREASURY_MANAGEMENT: {
                'min_tokens': Decimal('100000'),
                'voting_period': timedelta(days=7),
                'quorum_percentage': Decimal('0.30'),
                'approval_threshold': Decimal('0.70')
            },
            ProposalType.PROTOCOL_UPGRADE: {
                'min_tokens': Decimal('200000'),
                'voting_period': timedelta(days=14),
                'quorum_percentage': Decimal('0.40'),
                'approval_threshold': Decimal('0.80')
            },
            ProposalType.EMERGENCY_MEASURE: {
                'min_tokens': Decimal('50000'),
                'voting_period': timedelta(hours=24),
                'quorum_percentage': Decimal('0.15'),
                'approval_threshold': Decimal('0.75')
            }
        }
    
    def get_requirements(self, proposal_type: ProposalType) -> Dict:
        """Obtiene los requisitos para un tipo de propuesta específico"""
        return self.requirements.get(proposal_type, {})
    
    def validate_proposal(self, proposal_type: ProposalType, proposer_tokens: Decimal) -> bool:
        """Valida si una propuesta cumple con los requisitos mínimos"""
        reqs = self.get_requirements(proposal_type)
        return proposer_tokens >= reqs.get('min_tokens', Decimal('0'))

class GovernanceProposal:
    """Estructura completa de una propuesta de gobernanza"""
    
    def __init__(self, proposal_id: str, proposal_type: ProposalType, title: str, description: str):
        self.proposal_id = proposal_id
        self.proposal_type = proposal_type
        self.title = title
        self.description = description
        self.created_at = datetime.now()
        self.voting_start: Optional[datetime] = None
        self.voting_end: Optional[datetime] = None
        self.current_status = ProposalStatus.DRAFT
        self.for_votes = Decimal('0')
        self.against_votes = Decimal('0')
        self.abstain_votes = Decimal('0')
        self.voters: Dict[str, Decimal] = {}
    
    def start_voting_period(self) -> bool:
        """Inicia el período de votación para la propuesta"""
        if self.current_status != ProposalStatus.DRAFT:
            return False
        
        reqs = ProposalRequirements().get_requirements(self.proposal_type)
        voting_period = reqs.get('voting_period', timedelta(days=7))
        
        self.voting_start = datetime.now()
        self.voting_end = self.voting_start + voting_period
        self.current_status = ProposalStatus.ACTIVE
        
        return True
    
    def add_vote(self, voter: str, voting_power: Decimal, support: bool) -> bool:
        """Añade un voto a la propuesta"""
        if self.current_status != ProposalStatus.ACTIVE:
            return False
        
        if datetime.now() > self.voting_end:
            self.current_status = ProposalStatus.EXPIRED
            return False
        
        if voter in self.voters:
            return False  # No votación múltiple
        
        self.voters[voter] = voting_power
        
        if support:
            self.for_votes += voting_power
        else:
            self.against_votes += voting_power
        
        return True
    
    def get_current_result(self) -> Dict:
        """Obtiene el resultado actual de la votación"""
        total_votes = self.for_votes + self.against_votes + self.abstain_votes
        reqs = ProposalRequirements().get_requirements(self.proposal_type)
        
        return {
            'for_votes': self.for_votes,
            'against_votes': self.against_votes,
            'abstain_votes': self.abstain_votes,
            'total_votes': total_votes,
            'approval_percentage': (self.for_votes / total_votes * 100) if total_votes > 0 else 0,
            'quorum_required': reqs.get('quorum_percentage', Decimal('0.2')) * 100,
            'approval_threshold': reqs.get('approval_threshold', Decimal('0.6')) * 100
        }