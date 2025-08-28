# guias/NEXUS/nexus/api/endpoints/cognitive.py

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional, Dict
from pydantic import BaseModel
from datetime import datetime
import uuid
import asyncio

# --- Objeto Global que se llenará en el arranque ---
nexus_agent = None

router = APIRouter(prefix="/cognitive", tags=["Cognitive Functions"])

# Modelos de datos para las peticiones (sin cambios)
class KnowledgeQuery(BaseModel):
    query: str
    context: Optional[Dict] = None
    max_results: int = 10
    min_confidence: float = 0.7

class InferenceRequest(BaseModel):
    task: str
    parameters: Optional[Dict] = None
    constraints: Optional[List[str]] = None
    timeout: int = 60
    
class StandardResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    request_id: str
    timestamp: datetime

# --- Endpoints Actualizados ---

@router.post("/query", response_model=StandardResponse)
async def query_knowledge(query: KnowledgeQuery):
    """Realiza una consulta de conocimiento compleja a NEXUS."""
    if not nexus_agent:
        raise HTTPException(status_code=503, detail="NEXUS Core no está inicializado.")
    
    try:
        # Usamos el agente para ejecutar la tarea de consulta
        result = await nexus_agent.execute_complex_task(task_description=query.query)
        
        return StandardResponse(
            success=True,
            data={"results": result},
            request_id=str(uuid.uuid4()),
            timestamp=datetime.now()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/infer", response_model=StandardResponse)
async def perform_inference(request: InferenceRequest):
    """Solicita a NEXUS que realice una tarea de inferencia compleja."""
    if not nexus_agent:
        raise HTTPException(status_code=503, detail="NEXUS Core no está inicializado.")
        
    try:
        # El agente es perfecto para manejar tareas de inferencia
        result = await asyncio.wait_for(
            nexus_agent.execute_complex_task(
                task_description=request.task,
                context=request.parameters
            ),
            timeout=request.timeout
        )
        
        return StandardResponse(
            success=True,
            data={"inference_result": result},
            request_id=str(uuid.uuid4()),
            timestamp=datetime.now()
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="La inferencia ha superado el tiempo de espera.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))