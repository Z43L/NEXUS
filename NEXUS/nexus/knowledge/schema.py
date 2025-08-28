from pydantic import BaseModel, Field, validator
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime
import uuid

class EntityType(str, Enum):
    """Tipos de entidades en el grafo de conocimiento"""
    CONCEPT = "Concept"
    EVENT = "Event"
    AGENT = "Agent"
    OBJECT = "Object"
    LOCATION = "Location"
    TIME = "Time"
    DOCUMENT = "Document"

class RelationType(str, Enum):
    """Tipos de relaciones semánticas"""
    RELATED_TO = "RELATED_TO"
    PART_OF = "PART_OF"
    CAUSES = "CAUSES"
    PRECEDES = "PRECEDES"
    SIMILAR_TO = "SIMILAR_TO"
    USES = "USES"
    CREATES = "CREATES"

class KnowledgeEntity(BaseModel):
    """Estructura para entidades del grafo de conocimiento"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EntityType
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    
    class Config:
        use_enum_values = True
    
    @validator('name')
    def validate_name_length(cls, v):
        if len(v.strip()) < 2:
            raise ValueError('El nombre debe tener al menos 2 caracteres')
        return v.strip()

class KnowledgeRelation(BaseModel):
    """Estructura para relaciones del grafo de conocimiento"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: RelationType
    source_id: str
    target_id: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    
    class Config:
        use_enum_values = True
    
    @validator('source_id', 'target_id')
    def validate_entity_ids(cls, v):
        if not v.strip():
            raise ValueError('Los IDs de entidades no pueden estar vacíos')
        return v.strip()