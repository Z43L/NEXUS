from typing import Dict, List, Any, Optional
from datetime import datetime
import hashlib
import json
from loguru import logger

class KnowledgeVersioningSystem:
    """Sistema de versionado y auditoría para el grafo de conocimiento"""
    
    def __init__(self, storage_backend):
        self.storage = storage_backend
        self.change_log = []
        self.current_version = None
    
    async def record_change(self, 
                          change_type: str, 
                          item: Dict[str, Any],
                          user: str,
                          timestamp: datetime) -> str:
        """
        Registra un cambio en el grafo con información de auditoría
        
        Args:
            change_type: Tipo de cambio (create, update, delete)
            item: Item afectado por el cambio
            user: Usuario o sistema que realizó el cambio
            timestamp: Momento del cambio
            
        Returns:
            Hash del cambio registrado
        """
        change_record = {
            "type": change_type,
            "item": item,
            "user": user,
            "timestamp": timestamp.isoformat(),
            "version_hash": self._generate_hash(item)
        }
        
        self.change_log.append(change_record)
        
        # Almacenar en backend persistente
        await self.storage.store_change(change_record)
        
        return change_record["version_hash"]
    
    async def restore_version(self, version_hash: str) -> bool:
        """
        Restaura el grafo a una versión específica
        
        Args:
            version_hash: Hash de la versión a restaurar
            
        Returns:
            True si la restauración fue exitosa
        """
        try:
            # Recuperar el estado de esa versión
            version_state = await self.storage.retrieve_version(version_hash)
            
            if not version_state:
                logger.error(f"Versión no encontrada: {version_hash}")
                return False
            
            # Aplicar cambios para restaurar el estado
            await self._apply_version_state(version_state)
            
            self.current_version = version_hash
            logger.info(f"Grafo restaurado a versión: {version_hash}")
            return True
            
        except Exception as e:
            logger.error(f"Error restaurando versión {version_hash}: {e}")
            return False
    
    def _generate_hash(self, data: Dict[str, Any]) -> str:
        """Genera hash único para un conjunto de datos"""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
