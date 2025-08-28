from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime, timedelta

class GovernanceProcess:
    """Gestor del proceso completo de gobernanza"""
    
    def __init__(self, token_contract, voting_system):
        self.token_contract = token_contract
        self.voting_system = voting_system
        self.active_proposals: Dict[str, GovernanceProposal] = {}
        self.completed_proposals: Dict[str, GovernanceProposal] = {}
        self.proposal_requirements = ProposalRequirements()
    
    async def create_proposal(self, proposer: str, proposal_type: ProposalType, 
                           title: str, description: str) -> Optional[str]:
        """Crea una nueva propuesta de gobernanza"""
        # Verificar requisitos mínimos
        proposer_balance = await self.token_contract.balance_of(proposer)
        if not self.proposal_requirements.validate_proposal(proposal_type, proposer_balance):
            return None
        
        proposal_id = f"prop_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        proposal = GovernanceProposal(
            proposal_id=proposal_id,
            proposal_type=proposal_type,
            title=title,
            description=description
        )
        
        self.active_proposals[proposal_id] = proposal
        return proposal_id
    
    async def start_proposal_voting(self, proposal_id: str) -> bool:
        """Inicia el período de votación para una propuesta"""
        if proposal_id not in self.active_proposals:
            return False
        
        proposal = self.active_proposals[proposal_id]
        return proposal.start_voting_period()
    
    async def cast_vote(self, proposal_id: str, voter: str, support: bool) -> bool:
        """Emite un voto en una propuesta"""
        if proposal_id not in self.active_proposals:
            return False
        
        proposal = self.active_proposals[proposal_id]
        
        # Calcular poder de voto del votante
        voting_power = await self.voting_system.calculate_voting_power(voter)
        
        return proposal.add_vote(voter, voting_power, support)
    
    async def check_proposal_results(self) -> List[Dict]:
        """Verifica y procesa los resultados de propuestas finalizadas"""
        current_time = datetime.now()
        finalized_proposals = []
        
        for proposal_id, proposal in list(self.active_proposals.items()):
            if proposal.voting_end and current_time > proposal.voting_end:
                # Propuesta finalizada, procesar resultados
                result = proposal.get_current_result()
                reqs = self.proposal_requirements.get_requirements(proposal.proposal_type)
                
                # Verificar quórum y umbral de aprobación
                quorum_required = reqs.get('quorum_percentage', Decimal('0.2'))
                approval_threshold = reqs.get('approval_threshold', Decimal('0.6'))
                
                total_possible_votes = await self.token_contract.total_supply()
                quorum_achieved = (result['total_votes'] / total_possible_votes) >= quorum_required
                approval_achieved = result['approval_percentage'] >= approval_threshold * 100
                
                if quorum_achieved and approval_achieved:
                    proposal.current_status = ProposalStatus.APPROVED
                    # Ejecutar propuesta aprobada
                    await self._execute_proposal(proposal)
                else:
                    proposal.current_status = ProposalStatus.REJECTED
                
                # Mover a propuestas completadas
                self.completed_proposals[proposal_id] = proposal
                del self.active_proposals[proposal_id]
                
                finalized_proposals.append({
                    'proposal_id': proposal_id,
                    'status': proposal.current_status,
                    'result': result
                })
        
        return finalized_proposals
    
    async def _execute_proposal(self, proposal: GovernanceProposal):
        """Ejecuta una propuesta aprobada"""
        # Implementación específica según tipo de propuesta
        # Esto podría interactuar con otros contratos del sistema
        
        if proposal.proposal_type == ProposalType.PARAMETER_CHANGE:
            await self._execute_parameter_change(proposal)
        elif proposal.proposal_type == ProposalType.TREASURY_MANAGEMENT:
            await self._execute_treasury_operation(proposal)
        elif proposal.proposal_type == ProposalType.PROTOCOL_UPGRADE:
            await self._execute_protocol_upgrade(proposal)