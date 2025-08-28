# guias/NEXUS/nexus/api/core/api_server.py

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from typing import Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime
import asyncio
import yaml  # Añadido para cargar config
from pathlib import Path  # Añadido para la ruta de config

# --- CORRECCIÓN ---
# Importar el inicializador en lugar de la clase inexistente
from nexus.core.initialization import NexusCoreInitializer
from nexus.api.endpoints import cognitive  # Importar los endpoints cognitivos

# --- Objeto Global para los Componentes de NEXUS ---
# Este objeto contendrá todos los componentes inicializados (cerebro, memoria, etc.)
# y estará disponible para toda la aplicación.
nexus_components: Dict[str, any] = {}

# --- FastAPI App ---
app = FastAPI(
    title="NEXUS Public API",
    description="API pública para interactuar con la mente colmena descentralizada NEXUS",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Eventos de Inicio y Apagado de la App ---

@app.on_event("startup")
async def startup_event():
    """
    Esta función se ejecuta una sola vez cuando el servidor se inicia.
    Carga la configuración, inicializa todos los componentes de NEXUS
    y los almacena en el objeto global `nexus_components`.
    """
    print("🚀 Iniciando el núcleo de NEXUS...")
    
    # Cargar la configuración principal del agente
    config_path = Path(__file__).parent.parent.parent.parent / "config/reasoning_agent.yaml"
    config = {}
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Cargar la configuración de la memoria
    memory_config_path = Path(__file__).parent.parent.parent.parent / "config/memory_config.yaml"
    with open(memory_config_path, 'r') as f:
        memory_config = yaml.safe_load(f)
    config['memory'] = memory_config

    # Añadir configuraciones dummy para memoria y grafo que el inicializador espera
    # En un despliegue real, estas vendrían de sus propios ficheros de config.
    config['knowledge_graph'] = {
        'database': {
            'host': 'postgres-age', 'database': 'nexus',
            'user': 'nexus', 'password': 'nexus', 'port': 5432
        }
    }
    
    # Inicializar el núcleo de NEXUS
    initializer = NexusCoreInitializer(config)
    initialized_components = await initializer.initialize_core_components()
    
    # Guardar los componentes para que los endpoints los puedan usar
    nexus_components.update(initialized_components)
    
    # Hacer que los componentes estén disponibles para los endpoints
    cognitive.nexus_agent = nexus_components.get("agent")
    
    print("✅ Núcleo de NEXUS listo y operativo.")


@app.on_event("shutdown")
async def shutdown_event():
    """Cierra conexiones y libera recursos."""
    mem = nexus_components.get('memory')
    if mem and hasattr(mem, 'close'):
        try:
            mem.close()
        except Exception:
            pass


# --- Endpoints ---

# Incluir los endpoints del router cognitivo
app.include_router(cognitive.router)

class StandardResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    request_id: str
    timestamp: datetime

@app.get("/health", response_model=StandardResponse, tags=["System"])
async def health_check():
    """Endpoint de health check para verificar que la API está viva."""
    return StandardResponse(
        success=True,
        data={"status": "healthy", "components_loaded": list(nexus_components.keys())},
        request_id="health_check",
        timestamp=datetime.now()
    )