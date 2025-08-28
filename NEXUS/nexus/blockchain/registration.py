from typing import Dict, List, Optional
from web3 import Web3
from .schema import KnowledgeRecord, KnowledgeCategory, KnowledgeMetadata
from datetime import datetime
import hashlib
import json

class KnowledgeRegistrar:
    """Gestor del registro de conocimiento en blockchain"""
    
    def __init__(self, web3_provider, contract_address, contract_abi):
        self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        self.contract = self.web3.eth.contract(
            address=contract_address,
            abi=contract_abi
        )
        self.pending_registrations = {}
    
    async def register_knowledge(
        self,
        content: str,
        category: KnowledgeCategory,
        metadata: Dict,
        submitter_address: str,
        private_key: str
    ) -> str:
        """
        Registra una nueva pieza de conocimiento en la blockchain
        
        Args:
            content: Contenido del conocimiento a registrar
            category: Categoría del conocimiento
            metadata: Metadatos adicionales
            submitter_address: Dirección del que envía
            private_key: Llave privada para firmar
            
        Returns:
            Hash de la transacción
        """
        try:
            # Calcular hashes de contenido y conocimiento
            content_hash = self._calculate_content_hash(content)
            knowledge_hash = self._calculate_knowledge_hash(content_hash, category)
            
            # Verificar que no existe
            if await self._knowledge_exists(knowledge_hash):
                raise ValueError("Knowledge already registered")
            
            # Preparar metadatos
            knowledge_metadata = KnowledgeMetadata(
                source_nodes=metadata.get('source_nodes', []),
                validation_timestamp=datetime.now(),
                average_confidence=metadata.get('confidence', 0.0),
                validation_threshold=metadata.get('threshold', 0.7),
                context_information=metadata.get('context', {}),
                related_entities=metadata.get('related_entities', [])
            )
            
            # Crear transacción
            transaction = self.contract.functions.registerKnowledge(
                knowledge_hash,
                content_hash,
                category.value,
                json.dumps(knowledge_metadata.dict())
            ).build_transaction({
                'from': submitter_address,
                'gas': 2000000,
                'gasPrice': self.web3.to_wei('50', 'gwei'),
                'nonce': self.web3.eth.get_transaction_count(submitter_address)
            })
            
            # Firmar y enviar transacción
            signed_txn = self.web3.eth.account.sign_transaction(transaction, private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            # Esperar confirmación
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                return tx_hash.hex()
            else:
                raise Exception("Transaction failed")
                
        except Exception as e:
            print(f"Error registering knowledge: {e}")
            raise
    
    def _calculate_content_hash(self, content: str) -> str:
        """Calcula el hash del contenido del conocimiento"""
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _calculate_knowledge_hash(self, content_hash: str, category: KnowledgeCategory) -> str:
        """Calcula el hash único del conocimiento"""
        return hashlib.sha256(f"{content_hash}:{category.value}".encode()).hexdigest()
    
    async def _knowledge_exists(self, knowledge_hash: str) -> bool:
        """Verifica si el conocimiento ya está registrado"""
        try:
            return self.contract.functions.knowledgeExists(knowledge_hash).call()
        except:
            return False