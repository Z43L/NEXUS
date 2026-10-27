"""Protocolo P2P experimental de NEXUS (H3).

EXPERIMENTAL. No importar desde la ruta H0/H1 (router ni worker). Solo se
activa con config["experimental_p2p"] = True o NEXUS_EXPERIMENTAL_P2P=1.

Partes reales y stand-ins:
- Firma: Ed25519 real (paquete `cryptography`). node_id = clave publica en hex.
  Cada mensaje de red se firma y se verifica en recepcion.
- Transporte: `LocalTcpTransport` es un stand-in: TCP con framing de longitud,
  limitado a loopback. NO es libp2p.
- libp2p: no esta instalado en el entorno. El interfaz `P2PTransport` permite
  sustituir el transporte por uno libp2p; esa implementacion no existe aqui.

Limitaciones: sin ACK de aplicacion (solo reintento ante error de conexion),
sin anti-replay, sin lista de confianza (cualquier clave puede unirse), y las
entradas de sincronizacion no estan verificadas hasta que su nodo firme algo.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

logger = logging.getLogger(__name__)

FLAG_CONFIG_KEY = "experimental_p2p"
FLAG_ENV_VAR = "NEXUS_EXPERIMENTAL_P2P"
MAX_FRAME_BYTES = 1 << 20
DISCOVERY_TYPE = "discovery"
SYNC_TYPE = "sync"


class P2PDisabledError(RuntimeError):
    """El P2P experimental esta desactivado (falta la bandera explicita)."""


class MessageVerificationError(ValueError):
    """Mensaje con firma invalida o formato no valido."""


def p2p_enabled(config: Dict) -> bool:
    """True solo si la bandera explicita esta activada."""
    return config.get(FLAG_CONFIG_KEY) is True or os.environ.get(FLAG_ENV_VAR) == "1"


def parse_listen_addr(addr: str) -> Tuple[str, int]:
    """Parsea '/ip4/<host>/tcp/<port>'. Solo loopback en esta version."""
    parts = addr.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "ip4" or parts[2] != "tcp":
        raise ValueError(f"Direccion no soportada: {addr}")
    host = parts[1]
    port = int(parts[3])
    _require_loopback(host)
    return host, port


def _require_loopback(host: str) -> None:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Solo se permite loopback en el P2P experimental")


def _canonical(body: Dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _to_wire(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dict):
        return {k: _to_wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_wire(v) for v in value]
    return value


def _from_wire(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value.keys()) == {"__bytes_b64__"}:
            return base64.b64decode(value["__bytes_b64__"])
        return {k: _from_wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_wire(v) for v in value]
    return value


class P2PTransport(ABC):
    """Interfaz minima de transporte. Las implementaciones entregan frames a on_frame."""

    @abstractmethod
    async def start(self, host: str, port: int) -> Tuple[str, int]:
        """Escucha en host:port (port 0 = automatico). Devuelve la direccion real."""

    @abstractmethod
    async def stop(self) -> None:
        """Cierra la escucha."""

    @abstractmethod
    async def send(self, host: str, port: int, data: bytes) -> None:
        """Envia un frame. Lanza OSError si no se puede entregar."""


class LocalTcpTransport(P2PTransport):
    """Stand-in: TCP en loopback con framing de 4 bytes de longitud."""

    def __init__(self, on_frame: Callable[[bytes], Awaitable[None]]):
        self._on_frame = on_frame
        self._server: Optional[asyncio.AbstractServer] = None

    async def start(self, host: str, port: int) -> Tuple[str, int]:
        _require_loopback(host)
        self._server = await asyncio.start_server(self._handle_conn, host, port)
        real_host, real_port = self._server.sockets[0].getsockname()[:2]
        return real_host, real_port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def send(self, host: str, port: int, data: bytes) -> None:
        _require_loopback(host)
        if len(data) > MAX_FRAME_BYTES:
            raise ValueError("Frame demasiado grande")
        _, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(len(data).to_bytes(4, "big") + data)
            await writer.drain()
        finally:
            await _close_writer(writer)

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size > MAX_FRAME_BYTES:
                logger.warning("Frame rechazado por tamano")
                return
            data = await reader.readexactly(size)
            await self._on_frame(data)
        except asyncio.IncompleteReadError:
            logger.debug("Conexion cerrada antes de completar el frame")
        except Exception as exc:  # no tumbar el servidor por un frame malo
            logger.warning("Error procesando frame: %s", exc)
        finally:
            await _close_writer(writer)


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionError, OSError):
        pass


@dataclass
class PeerRecord:
    node_id: str
    host: str
    port: int
    roles: List[str] = field(default_factory=list)
    region: str = ""

    @property
    def addr(self) -> str:
        return f"/ip4/{self.host}/tcp/{self.port}"


class NexusP2PProtocol:
    """Protocolo P2P experimental (H3) con mensajes firmados Ed25519."""

    def __init__(self, config: Dict):
        self.config = config
        self._signing_key: Ed25519PrivateKey = config.get("signing_key") or Ed25519PrivateKey.generate()
        pub = self._signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.node_id: str = pub.hex()
        self.transport: Optional[P2PTransport] = None
        self.known_peers: Dict[str, PeerRecord] = {}
        self.message_handlers: Dict[str, Callable] = {}
        self.listen_addr: str = ""
        self._host: str = ""
        self._port: int = 0
        self._initialized = False

    async def initialize(self) -> None:
        """Arranca el transporte y el descubrimiento. Requiere la bandera explicita."""
        if not p2p_enabled(self.config):
            raise P2PDisabledError(
                f"P2P experimental desactivado: config['{FLAG_CONFIG_KEY}']=True o {FLAG_ENV_VAR}=1"
            )
        host, port = parse_listen_addr(self.config.get("listen_addr", "/ip4/127.0.0.1/tcp/0"))
        factory = self.config.get("transport_factory", LocalTcpTransport)
        self.transport = factory(self._on_frame)
        self._host, self._port = await self.transport.start(host, port)
        self.listen_addr = f"/ip4/{self._host}/tcp/{self._port}"
        self._initialized = True
        await self._start_peer_discovery()
        logger.info("Nodo P2P %s escuchando en %s", self.node_id[:12], self.listen_addr)

    async def shutdown(self) -> None:
        if self.transport is not None and self._initialized:
            await self.transport.stop()
        self._initialized = False

    def register_message_handler(self, message_type: str, handler: Callable) -> None:
        self.message_handlers[message_type] = handler

    # ----- descubrimiento y sincronizacion -----

    async def _start_peer_discovery(self) -> None:
        """Envia un anuncio de descubrimiento a cada nodo bootstrap configurado."""
        for addr in self.config.get("bootstrap_nodes", []):
            host, port = parse_listen_addr(addr)
            raw = self._encode_message(self._discovery_message())
            await self._send_raw(host, port, raw)

    def _discovery_message(self) -> Dict:
        return {
            "type": DISCOVERY_TYPE,
            "payload": {
                "roles": list(self.config.get("roles", [])),
                "region": self.config.get("region", ""),
            },
        }

    async def _handle_discovery(self, message: Dict) -> None:
        """Registra al emisor (ya verificado) y le responde con nuestra tabla de peers."""
        sender = message["sender_id"]
        if sender == self.node_id:
            return
        payload = message.get("payload") or {}
        self._upsert_peer(sender, message.get("sender_addr", ""), payload.get("roles"), payload.get("region", ""))
        if sender not in self.known_peers:
            return
        reply = {"type": SYNC_TYPE, "payload": {"peers": self._peer_table()}}
        await self.send_message(reply, target=sender)

    async def _handle_sync(self, message: Dict) -> None:
        """Incorpora las entradas de la tabla recibida. Son informativas hasta que su nodo firme."""
        for entry in (message.get("payload") or {}).get("peers", []):
            try:
                if not _valid_node_id(entry["node_id"]):
                    continue
                self._upsert_peer(entry["node_id"], entry["addr"], entry.get("roles"), entry.get("region", ""))
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("Entrada de sync descartada: %s", exc)

    def _peer_table(self) -> List[Dict]:
        table = [{"node_id": self.node_id, "addr": self.listen_addr,
                  "roles": list(self.config.get("roles", [])), "region": self.config.get("region", "")}]
        for rec in self.known_peers.values():
            table.append({"node_id": rec.node_id, "addr": rec.addr, "roles": rec.roles, "region": rec.region})
        return table

    def _upsert_peer(self, node_id: str, addr: str, roles=None, region: str = "") -> None:
        if node_id == self.node_id or not addr:
            return
        host, port = parse_listen_addr(addr)
        self.known_peers[node_id] = PeerRecord(
            node_id=node_id, host=host, port=port, roles=list(roles or []), region=region or ""
        )

    # ----- mensajeria -----

    async def send_message(self, message: Dict, target: Optional[str] = None) -> int:
        """Envia a un peer concreto (node_id) o a todos los conocidos. Devuelve los envios correctos.

        Con requires_ack=True reintenta hasta 3 veces ante error de conexion (sin ACK de aplicacion).
        """
        if not self._initialized:
            raise RuntimeError("P2P no inicializado")
        raw = self._encode_message(message)
        if target is not None:
            if target not in self.known_peers:
                raise KeyError(f"Peer desconocido: {target}")
            recipients = [self.known_peers[target]]
        else:
            recipients = list(self.known_peers.values())
        attempts = 3 if message.get("requires_ack") else 1
        sent = 0
        for rec in recipients:
            if await self._send_raw(rec.host, rec.port, raw, attempts=attempts):
                sent += 1
        return sent

    async def broadcast_message(self, message_type: str, payload: Any) -> int:
        return await self.send_message({"type": message_type, "payload": payload})

    async def _send_raw(self, host: str, port: int, raw: bytes, attempts: int = 1) -> bool:
        for attempt in range(attempts):
            try:
                await self.transport.send(host, port, raw)
                return True
            except OSError as exc:
                logger.warning("Envio a %s:%s fallo (intento %d): %s", host, port, attempt + 1, exc)
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.05 * (attempt + 1))
        return False

    async def _on_frame(self, data: bytes) -> None:
        try:
            message = self._decode_message(data)
        except MessageVerificationError as exc:
            logger.warning("Mensaje descartado: %s", exc)
            return
        await self.handle_incoming_message(message)

    async def handle_incoming_message(self, message: Dict) -> None:
        """Despacha un mensaje ya verificado (o in-process, sin firma)."""
        mtype = message.get("type")
        if mtype == DISCOVERY_TYPE:
            await self._handle_discovery(message)
        elif mtype == SYNC_TYPE:
            await self._handle_sync(message)
        elif mtype in self.message_handlers:
            result = self.message_handlers[mtype](message)
            if asyncio.iscoroutine(result):
                await result
        else:
            logger.info("Tipo de mensaje no manejado: %s", mtype)

    def _encode_message(self, message: Dict) -> bytes:
        """Serializa y firma el mensaje con la clave Ed25519 del nodo."""
        body = {
            "type": message["type"],
            "payload": _to_wire(message.get("payload")),
            "message_id": message.get("message_id") or uuid.uuid4().hex,
            "timestamp": time.time(),
            "sender_id": self.node_id,
            "sender_addr": self.listen_addr,
        }
        signature = self._signing_key.sign(_canonical(body))
        return json.dumps({"body": body, "sig": signature.hex()}, separators=(",", ":")).encode("utf-8")

    def _decode_message(self, data: bytes) -> Dict:
        """Verifica la firma con la clave publica del emisor (node_id) y devuelve el mensaje."""
        try:
            envelope = json.loads(data.decode("utf-8"))
            body = envelope["body"]
            signature = bytes.fromhex(envelope["sig"])
            if not _valid_node_id(body["sender_id"]):
                raise ValueError("sender_id no es una clave Ed25519")
            public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(body["sender_id"]))
            public_key.verify(signature, _canonical(body))
        except (KeyError, ValueError, TypeError, InvalidSignature, UnicodeDecodeError) as exc:
            raise MessageVerificationError(f"firma o formato invalido: {exc}") from exc
        message = dict(body)
        message["payload"] = _from_wire(body["payload"])
        return message


def _valid_node_id(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True
