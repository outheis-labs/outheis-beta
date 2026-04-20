"""
Transport layer for outheis.

Transports handle I/O with the outside world:
- CLI (stdin/stdout)
- Signal (via signal-cli JSON-RPC)
- Future: Matrix, Telegram, etc.

Each transport:
1. Receives messages from external source
2. Writes to messages.jsonl (to="dispatcher")
3. Watches for responses (to="transport")
4. Sends responses back to external source
"""

from outheis.transport.base import Transport
from outheis.transport.cli import CLITransport

__all__ = ["Transport", "CLITransport"]

# Signal transport is optional (requires signal-cli)
try:
    from outheis.transport.signal import SignalTransport  # noqa: F401
    __all__.append("SignalTransport")
except ImportError:
    pass
