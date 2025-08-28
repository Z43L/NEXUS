from typing import Dict, List, Optional
from web3 import Web3
from .schema import KnowledgeRecord, KnowledgeCategory
import hashlib
import json
from datetime import datetime

class IntegrityVerifier:
    """Sistema de verificación de integridad del conocimiento"""
    
    def __init__(self, web3_provider, contract_address, contract_abi):
        self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        self.contract = self.web3.eth.contract(
            address=contract_address,
            abi=contract_abi
        )
    
    async def verify_knowledge_integrity(self, knowledge_hash: str, original_content: str) -> Dict:
        """
        Verifica la integridad de una pieza de conocimiento
        
        Args:
            knowledge_hash: Hash del conocimiento a verificar
            original_content: Contenido original para comparar
            
        Returns:
            Dict con resultados de la verificación
        """
        try:
            # Obtener registro de blockchain
            blockchain_record = await self._get_knowledge_record(knowledge_hash)
            
            if not blockchain_record:
                return {"verified": False, "error": "Knowledge not found"}
            
            # Verificar hash del contenido
            current_content_hash = hashlib.sha256(original_content.encode()).hexdigest()
            if blockchain_record['content_hash'] != current_content_hash:
                return {
                    "verified": False,
                    "error": "Content has been modified",
                    "expected_hash": blockchain_record['content_hash'],
                    "current_hash": current_content_hash
                }
            
            # Verificar validez temporal
            validity_check = await self._check_temporal_validity(blockchain_record)
            if not validity_check['valid']:
                return {
                    "verified": False,
                    "error": "Temporal validity expired",
                    "details": validity_check
                }
            
            # Verificar estado de consenso
            consensus_check = await self._check_consensus_state(knowledge_hash)
            if not consensus_check['valid']:
                return {
                    "verified": False,
                    "error": "Consensus requirements not met",
                    "details": consensus_check
                }
            
            return {
                "verified": True,
                "block_number": blockchain_record['block_number'],
                "transaction_hash": blockchain_record['transaction_hash'],
                "validation_count": blockchain_record['validation_count'],
                "confidence_score": blockchain_record['confidence_score']
            }
            
        except Exception as e:
            return {"verified": False, "error": str(e)}
    
    async def _get_knowledge_record(self, knowledge_hash: str) -> Optional[Dict]:
        """Obtiene el registro de conocimiento de la blockchain"""
        try:
            record = self.contract.functions.getKnowledgeRecord(knowledge_hash).call()
            return {
                'content_hash': record[0],
                'category': KnowledgeCategory(record[1]),
                'block_number': record[2],
                'transaction_hash': record[3],
                'validation_count': record[4],
                'confidence_score': record[5],
                'metadata': json.loads(record[6])
            }
        except:
            return None
    
    async def _check_temporal_validity(self, record: Dict) -> Dict:
        """Verifica la validez temporal del conocimiento"""
        metadata = record['metadata']
        
        if 'expiration_timestamp' in metadata:
            expiration = datetime.fromisoformat(metadata['expiration_timestamp'])
            if datetime.now() > expiration:
                return {
                    "valid": False,
                    "reason": "Explicit expiration",
                    "expired_at": expiration.isoformat()
                }
        
        # Conocimiento estadístico puede tener validez decreciente con el tiempo
        if record['category'] == KnowledgeCategory.STATISTICAL:
            age_days = (datetime.now() - datetime.fromisoformat(metadata['validation_timestamp'])).days
            if age_days > 365:  # Datos estadísticos mayores a 1 año pierden validez
                return {
                    "valid": False,
                    "reason": "Statistical data too old",
                    "age_days": age_days
                }
        
        return {"valid": True}