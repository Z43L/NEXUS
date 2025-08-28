from typing import Dict, List, Optional
import asyncio
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class ConsensusMessageType(Enum):
    """Tipos de mensajes para consenso"""
    PROPOSAL = "proposal"
    VOTE = "vote"
    COMMIT = "commit"
    VIEW_CHANGE = "view_change"
    RECOVERY = "recovery"

@dataclass
class ConsensusMessage:
    """Mensaje específico para protocolos de consenso"""
    message_id: str
    type: ConsensusMessageType
    round_number: int
    sender_id: str
    payload: Dict
    signature: Optional[bytes] = None

class ConsensusCommunication:
    """Comunicación especializada para protocolos de consenso"""
    
    def __init__(self, network_protocol, node_id: str):
        self.network = network_protocol
        self.node_id = node_id
        self.current_round = 0
        self.pending_messages: Dict[int, List[ConsensusMessage]] = {}
        
    async def broadcast_proposal(self, proposal: Dict, round_number: int):
        """Transmite una propuesta de consenso"""
        message = ConsensusMessage(
            message_id=self._generate_message_id(),
            type=ConsensusMessageType.PROPOSAL,
            round_number=round_number,
            sender_id=self.node_id,
            payload=proposal
        )
        
        signed_message = await self._sign_message(message)
        await self.network.broadcast_message(signed_message)
    
    async def send_vote(self, vote: Dict, round_number: int, target_node: Optional[str] = None):
        """Envía un voto de consenso"""
        message = ConsensusMessage(
            message_id=self._generate_message_id(),
            type=ConsensusMessageType.VOTE,
            round_number=round_number,
            sender_id=self.node_id,
            payload=vote
        )
        
        signed_message = await self._sign_message(message)
        
        if target_node:
            await self.network.send_directed_message(target_node, signed_message)
        else:
            await self.network.broadcast_message(signed_message)
    
    async def handle_consensus_message(self, message: ConsensusMessage):
        """Maneja un mensaje de consenso entrante"""
        # Verificar firma si existe
        if message.signature and not await self._verify_signature(message):
            logger.warning(f"Mensaje de consenso con firma inválida de {message.sender_id}")
            return
        
        # Verificar round number
        if message.round_number < self.current_round:
            logger.debug(f"Mensaje de round antiguo {message.round_number}, current: {self.current_round}")
            return
        
        # Almacenar mensaje para procesamiento
        if message.round_number not in self.pending_messages:
            self.pending_messages[message.round_number] = []
        
        self.pending_messages[message.round_number].append(message)
        
        # Procesar si tenemos suficientes mensajes para este round
        if len(self.pending_messages[message.round_number]) >= self._quorum_size():
            await self._process_round_messages(message.round_number)
    
    async def _process_round_messages(self, round_number: int):
        """Procesa todos los mensajes de un round de consenso"""
        messages = self.pending_messages.get(round_number, [])
        
        # Agrupar por tipo
        proposals = [m for m in messages if m.type == ConsensusMessageType.PROPOSAL]
        votes = [m for m in messages if m.type == ConsensusMessageType.VOTE]
        commits = [m for m in messages if m.type == ConsensusMessageType.COMMIT]
        
        # Lógica específica de procesamiento según el protocolo de consenso
        await self._handle_proposals(proposals)
        await self._handle_votes(votes)
        await self._handle_commits(commits)
        
        # Limpiar mensajes procesados
        if round_number in self.pending_messages:
            del self.pending_messages[round_number]
