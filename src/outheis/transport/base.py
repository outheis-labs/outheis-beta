"""
Base transport interface.

All transports implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from outheis.core.message import Message


class Transport(ABC):
    """
    Abstract base class for transports.

    A transport handles I/O with an external channel (CLI, Signal, etc).
    """

    name: str = "base"

    @abstractmethod
    def send(self, text: str) -> Message:
        """Send a user message. Returns the created message."""
        ...

    @abstractmethod
    def wait_for_response(self, message_id: str, timeout: float = 30.0) -> Message | None:
        """Wait for a response to a message."""
        ...

    @abstractmethod
    def run(self) -> None:
        """Run the transport's main loop."""
        ...

    def on_response(self, callback: Callable[[Message], None]) -> None:  # noqa: B027
        """Register a callback for responses (optional)."""
        pass
