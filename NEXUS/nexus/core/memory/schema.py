from pydantic import BaseModel, Field, validator
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from enum import Enum
import uuid

class MemoryType(str, Enum):
    """Tipos de memorias/experiencias en el sistema"""
    USER_INTERACTION = "user_interaction"
    KNOWLEDGE_UPDATE = "knowledge_update"
    SYSTEM_EVENT = "system_event"
    LEARNING_EXPERIENCE = "learning_experience"
    INFERENCE_RESULT = "inference_result"

class ConfidenceLevel(str, Enum):
    """Niveles de confianza para la validación"""
    UNVERIFIED = "unverified"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERIFIED = "verified"

class VectorEmbedding(BaseModel):
    """Estructura para embeddings vectoriales"""
    vector: List[float] = Field(..., description="El vector de embedding")
    model: str = Field(..., description="Modelo usado para generar el embedding")
    dimension: int = Field(..., description="Dimensión del vector")
    timestamp: datetime = Field(default_factory=datetime.now)

class MemoryMetadata(BaseModel):
    """Metadatos extensibles para experiencias"""
    source_node: str = Field(..., description="Nodo que originó la experiencia")
    confidence: ConfidenceLevel = Field(ConfidenceLevel.UNVERIFIED, description="Nivel de confianza")
    validation_count: int = Field(0, description="Número de validaciones recibidas")
    expiration: Optional[datetime] = Field(None, description="Tiempo de expiración opcional")
    custom_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos personalizados")

class NexusExperience(BaseModel):
    """Estructura principal para experiencias de NEXUS"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str = Field(..., description="Contenido principal de la experiencia", min_length=1)
    embedding: VectorEmbedding = Field(..., description="Embedding vectorial del contenido")
    memory_type: MemoryType = Field(..., description="Tipo de memoria")
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: MemoryMetadata = Field(..., description="Metadatos de la experiencia")
    related_entities: List[str] = Field(default_factory=list, description="IDs de entidades relacionadas en el grafo")
    context_window: Optional[Dict[str, Any]] = Field(None, description="Contexto temporal y espacial")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
    
    @validator('content')
    def validate_content_length(cls, v):
        if len(v.strip()) == 0:
            raise ValueError('El contenido no puede estar vacío')
        return v.strip()
    
    @validator('embedding')
    def validate_embedding_dimension(cls, v, values):
        if 'embedding' in values and len(v.vector) != v.dimension:
            raise ValueError('La dimensión del vector no coincide con la especificada')
        return v