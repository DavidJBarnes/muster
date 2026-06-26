"""The ingress adapter contract every chat connector implements.

A connector (Slack now, Teams later) translates a specific chat platform to and
from Muster's normalized ingress types. The control plane depends only on this
abstract interface, never on a concrete platform SDK — which is what lets a new
connector slot in without touching the hub or the agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from muster_contracts.messages import Origin


class IncomingInstruction(BaseModel):
    """A normalized inbound instruction lifted from any chat platform."""

    text: str = Field(description="The user's message text.")
    origin: Origin = Field(description="Where the message came from, for reply routing.")


class OutgoingUpdate(BaseModel):
    """A normalized outbound message (result or status) to post back to chat."""

    origin: Origin = Field(description="Destination thread/channel for the update.")
    content: str = Field(description="Text to post back to the chat platform.")


InstructionHandler = Callable[[IncomingInstruction], Awaitable[None]]
"""Async callback the control plane supplies to receive inbound instructions."""


class Ingress(ABC):
    """Abstract base class for a chat ingress connector.

    Concrete connectors hold the platform connection, forward inbound messages to
    the supplied handler via :meth:`dispatch`, and implement :meth:`send` to post
    updates back to the originating thread.
    """

    def __init__(self, handler: InstructionHandler) -> None:
        """Store the control-plane callback used for inbound instructions."""
        self._handler = handler

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable connector name, e.g. 'slack' — also used as ``Origin.connector``."""

    @abstractmethod
    async def start(self) -> None:
        """Begin listening for inbound messages from the chat platform."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and release the platform connection."""

    @abstractmethod
    async def send(self, update: OutgoingUpdate) -> None:
        """Post an outgoing update back to the originating thread/channel."""

    async def dispatch(self, instruction: IncomingInstruction) -> None:
        """Forward an inbound instruction to the control-plane handler.

        Connectors call this from their platform event loop; it exists so the
        handler-invocation path is shared and testable rather than reimplemented
        per connector.
        """
        await self._handler(instruction)
