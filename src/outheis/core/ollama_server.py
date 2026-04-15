"""
Ollama server lifecycle management.

Starts and monitors the ollama serve process, injecting environment variables
from the outheis config (ollama.local provider).

Policy:
- If Ollama is already responsive when outheis starts, leave it untouched.
- If not responsive, start it and take ownership.
- On outheis shutdown, stop only if we own the process.
- Cloud-only setups (no ollama.local provider) skip this module entirely.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 11434
_STARTUP_TIMEOUT = 15.0  # seconds to wait for ollama to become responsive


class OllamaServer:
    """Manages a single ollama serve subprocess."""

    def __init__(self, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self._proc: subprocess.Popen | None = None  # None = not owned by us

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_responsive(self) -> bool:
        """Return True if an Ollama server is accepting connections on the port."""
        try:
            with socket.create_connection((self._host, self._port), timeout=1.0):
                return True
        except OSError:
            return False

    def owns_process(self) -> bool:
        """Return True if outheis started the server in this session."""
        return self._proc is not None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def ensure_running(self, env_vars: dict[str, str] | None = None) -> bool:
        """Start Ollama if not already responsive. Returns True when server is ready."""
        if self.is_responsive():
            return True
        return self._start(env_vars)

    def stop(self) -> None:
        """Stop the server if we own the process. No-op otherwise."""
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start(self, env_vars: dict[str, str] | None = None) -> bool:
        binary = shutil.which("ollama")
        if not binary:
            print("[ollama] binary not found — cannot start server", file=sys.stderr)
            return False

        env = os.environ.copy()
        if env_vars:
            env.update({k: str(v) for k, v in env_vars.items()})

        self._proc = subprocess.Popen(
            [binary, "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.is_responsive():
                return True
            if self._proc.poll() is not None:
                print("[ollama] server process exited unexpectedly", file=sys.stderr)
                self._proc = None
                return False
            time.sleep(0.25)

        print("[ollama] server did not become ready within timeout", file=sys.stderr)
        return False


# Module-level singleton — shared across the dispatcher session
_server: OllamaServer | None = None


def get_server() -> OllamaServer:
    """Return the module-level OllamaServer instance (created on first call)."""
    global _server
    if _server is None:
        _server = OllamaServer()
    return _server
