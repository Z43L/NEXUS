from typing import Dict, List, Optional
from web3 import Web3
from .schema import KnowledgeRecord, KnowledgeCategory
import hashlib
import json

class KnowledgeUpdateManager:
    """Gestor de actualizaciones y revisiones de conocimiento"""
    
    def __init__(self, web3_provider, contract_address, contract_abi):
        self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        self.contract = self.web3.eth.contract(
            address=contract_address,
            abi=contract_abi
        )
    
    async def propose_update(
        self,
        original_hash: str,
        new_content: str,
        update_reason: str,
        submitter_address: str,
        private_key: str
    ) -> str:
        """
        Propone una actualización para conocimiento existente
        
        Args:
            original_hash: Hash del conocimiento original
            new_content: Nuevo contenido propuesto
            update_reason: Razón para la actualización
            submitter_address: Dirección del proponente
            private_key: Llave privada para firmar
            
        Returns:
            Hash de la transacción
        """
        try:
            # Verificar que el conocimiento original existe
            original_exists = await self._knowledge_exists(original_hash)
            if not original_exists:
                raise ValueError("Original knowledge not found")
            
            # Crear nuevo hash para el contenido actualizado
            new_content_hash = hashlib.sha256(new_content.encode()).hexdigest()
            
            # Crear transacción de propuesta
            transaction = self.contract.functions.proposeUpdate(
                original_hash,
                new_content_hash,
                update_reason
            ).build_transaction({
                'from': submitter_address,
                'gas': 1500000,
                'gasPrice': self.web3.to_wei('40', 'gwei'),
                'nonce': self.web3.eth.get_transaction_count(submitter_address)
            })
            
            # Firmar y enviar
            signed_txn = self.web3.eth.account.sign_transaction(transaction, private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            return tx_hash.hex()
            
        except Exception as e:
            print(f"Error proposing update: {e}")
            raise
    
    async def vote_on_update(
        self,
        update_proposal_hash: str,
        support: bool,
        voter_address: str,
        private_key: str,
        rationale: str = ""
    ) -> str:
        """
        Vota sobre una propuesta de actualización
        
        Args:
            update_proposal_hash: Hash de la propuesta
            support: True para apoyar, False para rechazar
            voter_address: Dirección del votante
            private_key: Llave privada para firmar
            rationale: Razón del voto
            
        Returns:
            Hash de la transacción
        """
        try:
            transaction = self.contract.functions.voteOnUpdate(
                update_proposal_hash,
                support,
                rationale
            ).build_transaction({
                'from': voter_address,
                'gas': 200000,
                'gasPrice': self.web3.to_wei('30', 'gwei'),
                'nonce': self.web3.eth.get_transaction_count(voter_address)
            })
            
            signed_txn = self.web3.eth.account.sign_transaction(transaction, private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            return tx_hash.hex()
            
        except Exception as e:
            print(f"Error voting on update: {e}")
            raise
    
    async def get_update_status(self, update_proposal_hash: str) -> Dict:
        """
        Obtiene el estado de una propuesta de actualización
        
        Args:
            update_proposal_hash: Hash de la propuesta
            
        Returns:
            Estado actual de la propuesta
        """
        try:
            proposal = self.contract.functions.getUpdateProposal(update_proposal_hash).call()
            
            return {
                'original_hash': proposal[0],
                'proposed_hash': proposal[1],
                'proposer': proposal[2],
                'reason': proposal[3],
                'support_votes': proposal[4],
                'oppose_votes': proposal[5],
                'total_votes': proposal[4] + proposal[5],
                'status': self._get_proposal_status(proposal[4], proposal[5])
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _get_proposal_status(self, support_votes: int, oppose_votes: int) -> str:
        """Determina el estado de una propuesta basado en los votos"""
        total_votes = support_votes + oppose_votes
        
        if total_votes == 0:
            return "pending"
        elif support_votes >= oppose_votes * 2:  # 2:1 ratio para aprobar
            return "approved"
        elif oppose_votes >= support_votes * 2:  # 2:1 ratio para rechazar
            return "rejected"
        else:
            return "contested"