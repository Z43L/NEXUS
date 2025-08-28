from typing import Dict, List
from datetime import datetime
import pandas as pd
import plotly.express as px

class GovernanceDashboard:
    """Dashboard de monitorización de la gobernanza en tiempo real"""
    
    def __init__(self, governance_contract, voting_system):
        self.governance = governance_contract
        self.voting = voting_system
        self.historical_data: List[Dict] = []
    
    async def generate_participation_report(self) -> Dict:
        """Genera reporte de participación en gobernanza"""
        current_period = await self._get_current_voting_period()
        participation_data = []
        
        for proposal_id in await self.governance.get_active_proposals():
            proposal_data = await self.governance.get_proposal_data(proposal_id)
            votes = await self.voting.get_proposal_votes(proposal_id)
            
            participation_rate = (votes['total_votes'] / await self.token_contract.total_supply()) * 100
            
            participation_data.append({
                'proposal_id': proposal_id,
                'type': proposal_data['type'],
                'participation_rate': participation_rate,
                'voter_count': len(votes['voters']),
                'timestamp': datetime.now()
            })
        
        self.historical_data.extend(participation_data)
        return participation_data
    
    async def generate_representative_report(self) -> Dict:
        """Genera reporte de desempeño de representantes"""
        representatives = await self.representative_system.get_elected_representatives()
        report_data = []
        
        for rep in representatives:
            voting_record = await self._get_representative_voting_record(rep)
            delegator_count = await self.representative_system.get_delegator_count(rep)
            participation_rate = await self._calculate_representative_participation(rep)
            
            report_data.append({
                'representative': rep,
                'delegator_count': delegator_count,
                'participation_rate': participation_rate,
                'votes_cast': len(voting_record),
                'average_voting_power': await self._get_average_voting_power(rep)
            })
        
        return report_data
    
    async def create_participation_visualization(self) -> str:
        """Crea visualización de la participación en gobernanza"""
        report_data = await self.generate_participation_report()
        
        df = pd.DataFrame(report_data)
        fig = px.line(
            df, 
            x='timestamp', 
            y='participation_rate',
            color='type',
            title='Participación en Gobernanza por Tipo de Propuesta',
            labels={'participation_rate': 'Tasa de Participación (%)', 'timestamp': 'Fecha'}
        )
        
        return fig.to_html()
    
    async def get_governance_health_metrics(self) -> Dict:
        """Calcula métricas de salud de la gobernanza"""
        participation_data = await self.generate_participation_report()
        rep_data = await self.generate_representative_report()
        
        avg_participation = sum(d['participation_rate'] for d in participation_data) / len(participation_data)
        avg_rep_participation = sum(d['participation_rate'] for d in rep_data) / len(rep_data)
        
        return {
            'average_participation_rate': avg_participation,
            'average_representative_participation': avg_rep_participation,
            'total_active_proposals': len(participation_data),
            'total_voters': sum(d['voter_count'] for d in participation_data),
            'governance_health_score': self._calculate_health_score(avg_participation, avg_rep_participation)
        }