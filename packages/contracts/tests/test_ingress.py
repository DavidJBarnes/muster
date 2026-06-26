"""Tests for the ingress adapter contract."""

from __future__ import annotations

import pytest

from muster_contracts.ingress import (
    IncomingInstruction,
    Ingress,
    OutgoingUpdate,
)
from muster_contracts.messages import Origin


def _origin() -> Origin:
    """Build a representative Origin for ingress tests."""
    return Origin(connector="fake", channel="C1", thread="T1")


class FakeConnector(Ingress):
    """Minimal concrete Ingress used to exercise the base class."""

    def __init__(self, handler) -> None:  # type: ignore[no-untyped-def]
        """Track lifecycle calls and sent updates for assertions."""
        super().__init__(handler)
        self.started = False
        self.stopped = False
        self.sent: list[OutgoingUpdate] = []

    @property
    def name(self) -> str:
        """Return this connector's stable name."""
        return "fake"

    async def start(self) -> None:
        """Record that listening began."""
        self.started = True

    async def stop(self) -> None:
        """Record that listening stopped."""
        self.stopped = True

    async def send(self, update: OutgoingUpdate) -> None:
        """Capture the outgoing update instead of hitting a real platform."""
        self.sent.append(update)


def test_ingress_is_abstract() -> None:
    """The base Ingress cannot be instantiated directly."""
    with pytest.raises(TypeError):
        Ingress(lambda instruction: None)  # type: ignore[abstract,arg-type]


def test_incoming_and_outgoing_models() -> None:
    """The normalized in/out models carry text and origin."""
    incoming = IncomingInstruction(text="hello", origin=_origin())
    outgoing = OutgoingUpdate(origin=_origin(), content="hi back")
    assert incoming.text == "hello"
    assert incoming.origin.connector == "fake"
    assert outgoing.content == "hi back"


async def test_connector_lifecycle_and_send() -> None:
    """A concrete connector's start/stop/send work through the base class."""
    received: list[IncomingInstruction] = []

    async def handler(instruction: IncomingInstruction) -> None:
        received.append(instruction)

    connector = FakeConnector(handler)
    assert connector.name == "fake"

    await connector.start()
    await connector.stop()
    await connector.send(OutgoingUpdate(origin=_origin(), content="done"))

    assert connector.started is True
    assert connector.stopped is True
    assert connector.sent[0].content == "done"


async def test_dispatch_forwards_to_handler() -> None:
    """dispatch hands inbound instructions to the supplied handler."""
    received: list[IncomingInstruction] = []

    async def handler(instruction: IncomingInstruction) -> None:
        received.append(instruction)

    connector = FakeConnector(handler)
    instruction = IncomingInstruction(text="do x", origin=_origin())
    await connector.dispatch(instruction)

    assert received == [instruction]
