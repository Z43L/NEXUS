from typing import Dict, List, Optional, Set
import hashlib
import json
from datetime import datetime, timedelta
import asyncio
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from enum import Enum

class ValidationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFLICT = "conflict"

class ProofOfKnowledgeConsensus:
    """Mecanismo de consenso Proof-of-Knowledge para validación descentralizada"""
    
    def __init__(self, network_layer, reputation_system):
        self.network = network_layer
        self.reputation = reputation_system
        self.active_validations: Dict[str, Dict] = {}
        self.validation_results: Dict[str, Dict] = {}
        
    async def submit_for_validation(self, knowledge_update: Dict, urgency: int = 1) -> str:
        """Envía una actualización de conocimiento para validación"""
        validation_id = self._generate_validation_id(knowledge_update)
        
        # Crear objeto de validación
        validation = {
            'id': validation_id,
            'knowledge': knowledge_update,
            'submission_time': datetime.now(),
            'status': ValidationStatus.PENDING,
            'votes': {},
            'required_consensus': self._calculate_required_consensus(urgency),
            'timeout': datetime.now() + timedelta(minutes=5 * urgency)
        }
        
        self.active_validations[validation_id] = validation
        
        # Transmitir a la red para validación
        await self._broadcast_validation_request(validation)
        
        # Iniciar timeout
        asyncio.create_task(self._validation_timeout(validation_id))
        
        return validation_id
    
    async def process_vote(self, vote_data: Dict, voter_id: str, signature: bytes) -> bool:
        """Procesa un voto de validación"""
        validation_id = vote_data['validation_id']
        
        if validation_id not in self.active_validations:
            return False
        
        # Verificar firma del votante
        if not await self._verify_vote_signature(vote_data, voter_id, signature):
            return False
        
        validation = self.active_validations[validation_id]
        
        # Verificar que el votante tenga derecho a votar
        if not await self._can_vote(voter_id, validation):
            return False
        
        # Registrar voto
        validation['votes'][voter_id] = {
            'vote': vote_data['vote'],
            'confidence': vote_data.get('confidence', 1.0),
            'timestamp': datetime.now(),
            'reasoning': vote_data.get('reasoning', '')
        }
        
        # Verificar si se alcanzó consenso
        consensus_reached = await self._check_consensus(validation)
        
        if consensus_reached:
            await self._finalize_validation(validation_id)
        
        return True
    
    async def _check_consensus(self, validation: Dict) -> bool:
        """Verifica si se alcanzó consenso en una validación"""
        votes = validation['votes']
        required_consensus = validation['required_consensus']
        
        if len(votes) < required_consensus['min_votes']:
            return False
        
        # Calcular peso de los votos basado en reputación
        total_weight = 0
        approve_weight = 0
        reject_weight = 0
        
        for voter_id, vote_info in votes.items():
            voter_reputation = await self.reputation.get_reputation(voter_id)
            weight = voter_reputation * vote_info['confidence']
            
            total_weight += weight
            if vote_info['vote']:
                approve_weight += weight
            else:
                reject_weight += weight
        
        # Verificar umbrales de consenso
        if total_weight >= required_consensus['min_weight']:
            approval_ratio = approve_weight / total_weight
            
            if approval_ratio >= required_consensus['approval_threshold']:
                validation['status'] = ValidationStatus.APPROVED
                return True
            elif (1 - approval_ratio) >= required_consensus['rejection_threshold']:
                validation['status'] = ValidationStatus.REJECTED
                return True
        
        return False
    
    async def _finalize_validation(self, validation_id: str):
        """Finaliza una validación y actualiza reputaciones"""
        validation = self.active_validations[validation_id]
        
        # Aplicar resultado de la validation
        if validation['status'] == ValidationStatus.APPROVED:
            await self._apply_knowledge_update(validation['knowledge'])
        else:
            await self._reject_knowledge_update(validation['knowledge'])
        
        # Actualizar reputaciones de los votantes
        await self._update_voter_reputations(validation)
        
        # Mover a resultados finalizados
        self.validation_results[validation_id] = validation
        del self.active_validations[validation_id]
        
        # Transmitir resultado final
        await self._broadcast_validation_result(validation)
    
    async def _update_voter_reputations(self, validation: Dict):
        """Actualiza las reputaciones basado en el consenso final"""
        final_decision = validation['status'] == ValidationStatus.APPROVED
        
        for voter_id, vote_info in validation['votes'].items():
            voter_was_correct = (vote_info['vote'] == final_decision)
            confidence = vote_info['confidence']
            
            # Ajustar reputación basado en precisión y confianza
            if voter_was_correct:
                reputation_change = 0.1 * confidence
            else:
                reputation_change = -0.2 * confidence  # Mayor penalización por errores
            
            await self.reputation.adjust_reputation(voter_id, reputation_change)
