from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from pydantic import BaseModel, Field, validator
import hashlib
import json

class KnowledgeCategory(str, Enum):
    FACTUAL = "factual"
    STATISTICAL = "statistical"
    INFERENTIAL = "inferential"
    EXPERIENTIAL = "experiential"
    PREDICTIVE = "predictive"

class ValidationLevel(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERIFIED = "verified"

@dataclass
class KnowledgeMetadata:
    """Metadatos para el registro de conocimiento"""
    source_nodes: List[str]
    validation_timestamp: datetime
    average_confidence: float
    validation_threshold: float
    context_information: Dict[str, str]
    related_entities: List[str]
    expiration_block: Optional[int] = None

class KnowledgeRecord(BaseModel):
    """Estructura principal para registros de conocimiento"""
    knowledge_hash: str = Field(..., description="Hash único del contenido de conocimiento")
    content_hash: str = Field(..., description="Hash del contenido original")
    category: KnowledgeCategory = Field(..., description="Categoría del conocimiento")
    block_number: int = Field(..., description="Número de bloque donde se registró")
    transaction_hash: str = Field(..., description="Hash de la transacción de registro")
    metadata: KnowledgeMetadata = Field(..., description="Metadatos de validación")
    validations: List[str] = Field(default_factory=list, description="Lista de hashes de validación")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    @validator('knowledge_hash')
    def validate_knowledge_hash(cls, v, values):
        """Valida que el hash del conocimiento sea consistente"""
        if 'content_hash' in values and 'category' in values:
            expected_hash = hashlib.sha256(
                f"{values['content_hash']}:{values['category']}".encode()
            ).hexdigest()
            if v != expected_hash:
                raise ValueError('Knowledge hash does not match content and category')
        return v
    
    def calculate_integrity_score(self) -> float:
        """Calcula un score de integridad basado en las validaciones"""
        base_score = {
            ValidationLevel.WEAK: 0.3,
            ValidationLevel.MODERATE: 0.6,
            ValidationLevel.STRONG: 0.8,
            ValidationLevel.VERIFIED: 1.0
        }
        
        if not self.validations:
            return 0.0
        
        total_score = sum(base_score.get(val, 0.0) for val in self.validations)
        return total_score / len(self.validations)