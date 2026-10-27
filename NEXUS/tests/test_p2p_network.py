"""Pruebas del P2P experimental (H3). Solo loopback, claves Ed25519 efimeras."""
import asyncio
import json
import socket

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from nexus.network.p2p_protocol import (
    MessageVerificationError,
    NexusP2PProtocol,
    P2PDisabledError,
    PeerRecord,
)


def make_config(**extra):
    config = {
        "listen_addr": "/ip4/127.0.0.1/tcp/0",
        "bootstrap_nodes": [],
        "experimental_p2p": True,
        "signing_key": Ed25519PrivateKey.generate(),
    }
    config.update(extra)
    return config


async def wait_until(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("tiempo agotado esperando condicion")
        await asyncio.sleep(0.02)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestP2PNetwork:
    """Suite de pruebas para el P2P experimental de NEXUS"""

    def test_disabled_without_flag(self, monkeypatch):
        monkeypatch.delenv("NEXUS_EXPERIMENTAL_P2P", raising=False)

        async def scenario():
            protocol = NexusP2PProtocol({"listen_addr": "/ip4/127.0.0.1/tcp/0",
                                         "signing_key": Ed25519PrivateKey.generate()})
            with pytest.raises(P2PDisabledError):
                await protocol.initialize()
            assert protocol.transport is None

        asyncio.run(scenario())

    def test_peer_discovery(self):
        """Dos peers en localhost se descubren mediante bootstrap y sincronizacion"""

        async def scenario():
            b = NexusP2PProtocol(make_config(roles=["storage"], region="eu-central"))
            await b.initialize()
            a = NexusP2PProtocol(make_config(roles=["validation"], region="us-west",
                                             bootstrap_nodes=[b.listen_addr]))
            await a.initialize()
            try:
                await wait_until(lambda: a.node_id in b.known_peers and b.node_id in a.known_peers)
                assert len(a.known_peers) == 1
                peer_b = a.known_peers[b.node_id]
                assert isinstance(peer_b, PeerRecord)
                assert peer_b.roles == ["storage"]
                assert peer_b.region == "eu-central"
                assert b.known_peers[a.node_id].roles == ["validation"]
            finally:
                await a.shutdown()
                await b.shutdown()

        asyncio.run(scenario())

    def test_signed_message_exchange(self):
        """Un mensaje firmado viaja entre dos peers y se verifica en recepcion"""

        async def scenario():
            b = NexusP2PProtocol(make_config())
            await b.initialize()
            a = NexusP2PProtocol(make_config(bootstrap_nodes=[b.listen_addr]))
            await a.initialize()
            received = []
            b.register_message_handler("test_message", received.append)
            try:
                await wait_until(lambda: b.node_id in a.known_peers and a.node_id in b.known_peers)
                sent = await a.send_message(
                    {"type": "test_message", "payload": b"signed-payload"}, target=b.node_id
                )
                assert sent == 1
                await wait_until(lambda: len(received) == 1)
                assert received[0]["payload"] == b"signed-payload"
                assert received[0]["sender_id"] == a.node_id
            finally:
                await a.shutdown()
                await b.shutdown()

        asyncio.run(scenario())

    def test_tampered_and_forged_messages_rejected(self):
        protocol = NexusP2PProtocol(make_config())
        raw = protocol._encode_message({"type": "x", "payload": b"orig"})

        envelope = json.loads(raw)
        envelope["body"]["type"] = "evil"
        with pytest.raises(MessageVerificationError):
            protocol._decode_message(json.dumps(envelope).encode())

        forged = json.loads(raw)
        other = Ed25519PrivateKey.generate().public_key()
        forged["body"]["sender_id"] = other.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        with pytest.raises(MessageVerificationError):
            protocol._decode_message(json.dumps(forged).encode())

        ok = protocol._decode_message(raw)
        assert ok["payload"] == b"orig"
        assert ok["sender_id"] == protocol.node_id

    def test_message_reliability(self):
        async def scenario():
            protocol = NexusP2PProtocol(make_config())
            await protocol.initialize()
            try:
                test_messages = []
                protocol.register_message_handler("test_message", test_messages.append)
                await protocol.handle_incoming_message(
                    {"type": "test_message", "payload": b"test_payload"}
                )
                assert len(test_messages) == 1
                assert test_messages[0]["payload"] == b"test_payload"

                # Peer inalcanzable: con requires_ack se reintenta 3 veces
                attempts = 0
                original_send = protocol.transport.send

                async def counting_send(host, port, data):
                    nonlocal attempts
                    attempts += 1
                    return await original_send(host, port, data)

                protocol.transport.send = counting_send
                dead_port = free_port()
                protocol.known_peers["dead"] = PeerRecord("dead", "127.0.0.1", dead_port)
                sent = await protocol.send_message(
                    {"type": "important_message", "payload": b"important_data",
                     "priority": 5, "requires_ack": True},
                    target="dead",
                )
                assert sent == 0
                assert attempts == 3
            finally:
                await protocol.shutdown()

        asyncio.run(scenario())
