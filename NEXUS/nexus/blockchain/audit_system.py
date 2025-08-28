from typing import Dict, List, Optional
from web3 import Web3
from web3._utils.filters import LogFilter
import pandas as pd
from datetime import datetime, timedelta

class KnowledgeAuditSystem:
    """Sistema completo de auditoría para el conocimiento registrado"""
    
    def __init__(self, web3_provider, contract_address, contract_abi):
        self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        self.contract = self.web3.eth.contract(
            address=contract_address,
            abi=contract_abi
        )
    
    async def get_knowledge_history(self, knowledge_hash: str) -> List[Dict]:
        """
        Obtiene el historial completo de una pieza de conocimiento
        
        Args:
            knowledge_hash: Hash del conocimiento
            
        Returns:
            Lista de eventos históricos
        """
        try:
            # Obtener eventos de registro
            register_filter = self.contract.events.KnowledgeRegistered.create_filter(
                fromBlock=0,
                argument_filters={'knowledgeHash': knowledge_hash}
            )
            register_events = register_filter.get_all_entries()
            
            # Obtener eventos de validación
            validation_filter = self.contract.events.ValidationRecorded.create_filter(
                fromBlock=0,
                argument_filters={'knowledgeHash': knowledge_hash}
            )
            validation_events = validation_filter.get_all_entries()
            
            # Combinar y ordenar eventos
            all_events = []
            
            for event in register_events:
                all_events.append({
                    'type': 'registration',
                    'block_number': event['blockNumber'],
                    'timestamp': self._get_block_timestamp(event['blockNumber']),
                    'data': event['args']
                })
            
            for event in validation_events:
                all_events.append({
                    'type': 'validation',
                    'block_number': event['blockNumber'],
                    'timestamp': self._get_block_timestamp(event['blockNumber']),
                    'data': event['args']
                })
            
            # Ordenar por bloque y timestamp
            all_events.sort(key=lambda x: x['block_number'])
            
            return all_events
            
        except Exception as e:
            print(f"Error getting knowledge history: {e}")
            return []
    
    async def generate_audit_report(self, knowledge_hash: str) -> Dict:
        """
        Genera un reporte completo de auditoría
        
        Args:
            knowledge_hash: Hash del conocimiento a auditar
            
        Returns:
            Reporte de auditoría detallado
        """
        history = await self.get_knowledge_history(knowledge_hash)
        
        if not history:
            return {"error": "No history found for this knowledge"}
        
        # Estadísticas básicas
        registration_event = next((e for e in history if e['type'] == 'registration'), None)
        validation_events = [e for e in history if e['type'] == 'validation']
        
        # Calcular métricas de confianza
        trust_metrics = self._calculate_trust_metrics(validation_events)
        
        # Verificar integridad de la cadena
        integrity_check = await self._verify_chain_integrity(history)
        
        return {
            "knowledge_hash": knowledge_hash,
            "registration_details": registration_event,
            "validation_count": len(validation_events),
            "trust_metrics": trust_metrics,
            "integrity_check": integrity_check,
            "complete_history": history,
            "generated_at": datetime.now().isoformat()
        }
    
    def _calculate_trust_metrics(self, validation_events: List[Dict]) -> Dict:
        """Calcula métricas de confianza basadas en validaciones"""
        if not validation_events:
            return {"score": 0.0, "confidence": "low"}
        
        # Calcular score basado en número y distribución de validaciones
        total_validations = len(validation_events)
        unique_validators = len(set(e['data']['validator'] for e in validation_events))
        
        # Score base por número de validaciones
        base_score = min(1.0, total_validations / 10.0)
        
        # Bonus por diversidad de validadores
        diversity_bonus = min(0.3, unique_validators / total_validations)
        
        total_score = base_score + diversity_bonus
        
        return {
            "score": round(total_score, 3),
            "total_validations": total_validations,
            "unique_validators": unique_validators,
            "confidence": self._score_to_confidence(total_score)
        }
    
    def _score_to_confidence(self, score: float) -> str:
        """Convierte score numérico a nivel de confianza"""
        if score >= 0.8:
            return "very_high"
        elif score >= 0.6:
            return "high"
        elif score >= 0.4:
            return "medium"
        elif score >= 0.2:
            return "low"
        else:
            return "very_low"