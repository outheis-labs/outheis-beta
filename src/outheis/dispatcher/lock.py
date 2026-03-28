"""
Lock manager for queue access.

Dispatcher owns the lock. Clients request access via Unix socket.
Priority-based scheduling with FIFO within priority class.
"""

from __future__ import annotations

import heapq
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

# =============================================================================
# PRIORITY
# =============================================================================

class Priority(IntEnum):
    """
    Lock request priorities.

    Lower number = higher priority.
    Defined in architecture, not configurable.
    """
    HIGH = 0      # transport (user waiting)
    NORMAL = 1    # relay, data, agenda, action
    LOW = 2       # pattern (background)


# Priority mapping by requester
PRIORITY_MAP = {
    "transport": Priority.HIGH,
    "relay": Priority.NORMAL,
    "data": Priority.NORMAL,
    "agenda": Priority.NORMAL,
    "action": Priority.NORMAL,
    "pattern": Priority.LOW,
}


def get_priority(requester: str) -> Priority:
    """Get priority for a requester."""
    return PRIORITY_MAP.get(requester, Priority.NORMAL)


# =============================================================================
# LOCK REQUEST
# =============================================================================

@dataclass(order=True)
class LockRequest:
    """A request for queue lock."""
    priority: Priority
    timestamp: float = field(compare=True)
    requester: str = field(compare=False)
    client_id: str = field(compare=False)

    def to_tuple(self) -> tuple:
        """For heap ordering: (priority, timestamp)."""
        return (self.priority, self.timestamp)


# =============================================================================
# LOCK MANAGER
# =============================================================================

class LockManager:
    """
    Manages queue lock requests.

    - Receives requests via Unix socket
    - Grants locks by priority (FIFO within class)
    - Tracks lock holder
    - Cleans up on client disconnect
    """

    def __init__(self, socket_path: Path | None = None):
        if socket_path is None:
            from outheis.core.config import get_outheis_dir
            socket_path = get_outheis_dir() / ".dispatcher.sock"

        self.socket_path = socket_path
        self.server: socket.socket | None = None

        # Lock state
        self._lock = threading.Lock()
        self._queue: list[LockRequest] = []  # heap
        self._holder: str | None = None   # client_id of lock holder
        self._clients: dict[str, socket.socket] = {}  # client_id -> socket

        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the lock manager server."""
        if self._running:
            return

        # Remove stale socket
        self.socket_path.unlink(missing_ok=True)

        # Create server socket
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.socket_path))
        self.server.listen(10)
        self.server.settimeout(0.5)  # For clean shutdown

        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the lock manager server."""
        self._running = False

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self.server:
            self.server.close()
            self.server = None

        self.socket_path.unlink(missing_ok=True)

        # Close all client connections
        for sock in self._clients.values():
            try:
                sock.close()
            except Exception:
                pass
        self._clients.clear()

    def _accept_loop(self) -> None:
        """Accept incoming connections."""
        while self._running:
            try:
                client, _ = self.server.accept()
                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client,),
                    daemon=True,
                )
                thread.start()
            except TimeoutError:
                continue
            except Exception:
                if self._running:
                    raise

    def _handle_client(self, client: socket.socket) -> None:
        """Handle a client connection."""
        client_id = f"client_{id(client)}"
        self._clients[client_id] = client

        try:
            while self._running:
                data = client.recv(4096)
                if not data:
                    break

                try:
                    msg = json.loads(data.decode())
                    response = self._handle_message(client_id, msg)
                    client.sendall(json.dumps(response).encode() + b"\n")
                except json.JSONDecodeError:
                    client.sendall(b'{"error": "invalid json"}\n')
        finally:
            # Client disconnected — release any held lock
            self._cleanup_client(client_id)
            client.close()
            self._clients.pop(client_id, None)

    def _handle_message(self, client_id: str, msg: dict) -> dict:
        """Handle a message from a client."""
        cmd = msg.get("cmd")

        if cmd == "request":
            return self._handle_request(client_id, msg)
        elif cmd == "release":
            return self._handle_release(client_id)
        elif cmd == "status":
            return self._handle_status()
        else:
            return {"error": f"unknown command: {cmd}"}

    def _handle_request(self, client_id: str, msg: dict) -> dict:
        """Handle lock request."""
        requester = msg.get("requester", "unknown")
        priority = get_priority(requester)

        with self._lock:
            # If no one holds the lock, grant immediately
            if self._holder is None:
                self._holder = client_id
                return {"status": "granted"}

            # If this client already holds it
            if self._holder == client_id:
                return {"status": "granted"}

            # Add to queue
            request = LockRequest(
                priority=priority,
                timestamp=time.time(),
                requester=requester,
                client_id=client_id,
            )
            heapq.heappush(self._queue, request)
            position = sum(1 for r in self._queue if r.client_id != client_id)

            return {"status": "queued", "position": position}

    def _handle_release(self, client_id: str) -> dict:
        """Handle lock release."""
        with self._lock:
            if self._holder != client_id:
                return {"error": "not holder"}

            self._holder = None

            # Grant to next in queue
            if self._queue:
                next_request = heapq.heappop(self._queue)
                self._holder = next_request.client_id

                # Notify next client
                if next_request.client_id in self._clients:
                    try:
                        sock = self._clients[next_request.client_id]
                        sock.sendall(b'{"status": "granted"}\n')
                    except Exception:
                        # Client gone, try next
                        self._holder = None
                        return self._handle_release(client_id)

            return {"status": "released"}

    def _handle_status(self) -> dict:
        """Handle status request."""
        with self._lock:
            return {
                "holder": self._holder,
                "queue_length": len(self._queue),
                "queue": [
                    {"requester": r.requester, "priority": r.priority}
                    for r in sorted(self._queue)
                ],
            }

    def _cleanup_client(self, client_id: str) -> None:
        """Clean up when client disconnects."""
        with self._lock:
            # Release lock if held
            if self._holder == client_id:
                self._holder = None

                # Grant to next
                while self._queue:
                    next_request = heapq.heappop(self._queue)
                    if next_request.client_id in self._clients:
                        self._holder = next_request.client_id
                        try:
                            sock = self._clients[next_request.client_id]
                            sock.sendall(b'{"status": "granted"}\n')
                        except Exception:
                            self._holder = None
                            continue
                        break

            # Remove from queue
            self._queue = [r for r in self._queue if r.client_id != client_id]
            heapq.heapify(self._queue)


# =============================================================================
# CLIENT
# =============================================================================

class LockClient:
    """Client for requesting queue lock."""

    def __init__(self, requester: str, socket_path: Path | None = None):
        self.requester = requester

        if socket_path is None:
            from outheis.core.config import get_outheis_dir
            socket_path = get_outheis_dir() / ".dispatcher.sock"

        self.socket_path = socket_path
        self.sock: socket.socket | None = None

    def connect(self) -> bool:
        """Connect to lock manager."""
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(str(self.socket_path))
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close connection."""
        if self.sock:
            self.sock.close()
            self.sock = None

    def request(self, timeout: float = 30.0) -> bool:
        """
        Request lock. Blocks until granted or timeout.

        Returns True if lock granted.
        """
        if not self.sock:
            if not self.connect():
                return False

        msg = {"cmd": "request", "requester": self.requester}
        self.sock.sendall(json.dumps(msg).encode())

        self.sock.settimeout(timeout)
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    return False

                response = json.loads(data.decode().strip())

                if response.get("status") == "granted":
                    return True
                elif response.get("status") == "queued":
                    # Wait for grant notification
                    continue
                else:
                    return False
        except TimeoutError:
            return False

    def release(self) -> bool:
        """Release lock."""
        if not self.sock:
            return False

        msg = {"cmd": "release"}
        self.sock.sendall(json.dumps(msg).encode())

        data = self.sock.recv(4096)
        response = json.loads(data.decode().strip())

        return response.get("status") == "released"

    def __enter__(self):
        """Context manager: request lock."""
        if not self.request():
            raise RuntimeError("Failed to acquire lock")
        return self

    def __exit__(self, *args):
        """Context manager: release lock."""
        self.release()
        self.close()
