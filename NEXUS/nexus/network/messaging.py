from typing import Dict, List, Optional, Callable
import asyncio
from dataclasses import dataclass
from enum import Enum
import json
import zlib
from cryptography.fernet import Fernet

class MessageType(Enum):
    """Tipos de mensajes soportados"""
    NODE_ANNOUNCEMENT = "node_announcement"
    KNOWLEDGE_UPDATE = "knowledge_update"
    VALIDATION_REQUEST = "validation_request"
    SYNC_REQUEST = "sync_request"
    CONSENSUS_MESSAGE = "consensus_message"
    HEARTBEAT = "heartbeat"

@dataclass
class NexusMessage:
    """Estructura de mensajes de la red NEXUS"""
    message_id: str
    type: MessageType
    payload: bytes
    timestamp: float
    source_node: str
    destination_node: Optional[str] = None  # None para broadcast
    compression: bool = False
    encryption: bool = False
    priority: int = 1  # 1-5, donde 5 es máxima prioridad

class NexusMessagingProtocol:
    """Protocolo de mensajería para comunicación entre nodos"""
    
    def __init__(self, encryption_key: Optional[bytes] = None):
        self.encryption_key = encryption_key
        self.fernet = Fernet(encryption_key) if encryption_key else None
        self.message_handlers: Dict[MessageType, Callable] = {}
        self.pending_messages: Dict[str, asyncio.Future] = {}
        self.message_queue = asyncio.PriorityQueue()
        
    async def send_message(self, message: NexusMessage, timeout: float = 30.0) -> bool:
        """
        Envía un mensaje de manera confiable
        
        Args:
            message: Mensaje a enviar
            timeout: Timeout para confirmación
            
        Returns:
            True si el mensaje fue confirmado
        """
        try:
            # Procesar mensaje (comprimir, encriptar)
            processed_message = await self._process_outgoing_message(message)
            
            # Enviar a través de la red
            if message.destination_node:
                # Mensaje dirigido
                success = await self._send_directed_message(processed_message)
            else:
                # Broadcast
                success = await self._broadcast_message(processed_message)
            
            if not success:
                return False
            
            # Esperar confirmación si es requerida
            if message.priority >= 3:  # Mensajes de prioridad media/alta requieren ACK
                return await self._wait_for_confirmation(message.message_id, timeout)
            
            return True
            
        except Exception as e:
            logger.error(f"Error enviando mensaje {message.message_id}: {e}")
            return False
    
    async def _process_outgoing_message(self, message: NexusMessage) -> NexusMessage:
        """Procesa un mensaje saliente (compresión, encriptación)"""
        processed_payload = message.payload
        
        # Compresión
        if message.compression:
            processed_payload = zlib.compress(processed_payload)
        
        # Encriptación
        if message.encryption and self.fernet:
            processed_payload = self.fernet.encrypt(processed_payload)
        
        return NexusMessage(
            message_id=message.message_id,
            type=message.type,
            payload=processed_payload,
            timestamp=message.timestamp,
            source_node=message.source_node,
            destination_node=message.destination_node,
            compression=message.compression,
            encryption=message.encryption,
            priority=message.priority
        )
    
    async def _send_directed_message(self, message: NexusMessage) -> bool:
        """Envía un mensaje dirigido a un nodo específico"""
        # Implementación específica de envío dirigido
        # Esto usaría la conexión directa al nodo destino
        return True
    
    async def _broadcast_message(self, message: NexusMessage) -> bool:
        """Transmite un mensaje a todos los nodos conectados"""
        # Implementación de broadcast eficiente
        # Esto podría usar flooding controlado o árboles de expansión
        return True
    
    async def handle_incoming_message(self, raw_message: bytes):
        """Maneja un mensaje entrante"""
        try:
            message = await self._parse_incoming_message(raw_message)
            
            # Procesar mensaje (desencriptar, descomprimir)
            processed_message = await self._process_incoming_message(message)
            
            # Llamar al manejador registrado
            if message.type in self.message_handlers:
                await self.message_handlers[message.type](processed_message)
            
            # Enviar confirmación si es necesario
            if message.priority >= 3:
                await self._send_confirmation(message.message_id)
                
        except Exception as e:
            logger.error(f"Error manejando mensaje entrante: {e}")
    
    def register_message_handler(self, message_type: MessageType, handler: Callable):
        """Registra un manejador para un tipo de mensaje"""
        self.message_handlers[message_type] = handler