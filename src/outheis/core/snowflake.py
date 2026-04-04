"""
Snowflake ID generator for outheis.

64-bit layout:
  41 bits  — millisecond timestamp since EPOCH (2024-01-01 UTC)
  10 bits  — machine ID (derived from hostname)
  12 bits  — sequence number (4096 IDs per millisecond)

IDs are monotonically increasing and lexicographically sortable as strings
(zero-padded to 19 digits).  This makes ordering by ID equivalent to
ordering by creation time without storing a separate timestamp.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time


class SnowflakeGenerator:
    """Thread-safe Snowflake ID generator."""

    # 2024-01-01 00:00:00 UTC in milliseconds
    EPOCH = 1_704_067_200_000

    MACHINE_BITS = 10
    SEQUENCE_BITS = 12

    MAX_MACHINE_ID = (1 << MACHINE_BITS) - 1
    MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1

    def __init__(self, machine_id: int | None = None) -> None:
        if machine_id is None:
            hostname = socket.gethostname()
            machine_id = int(hashlib.md5(hostname.encode()).hexdigest(), 16) & self.MAX_MACHINE_ID

        if not 0 <= machine_id <= self.MAX_MACHINE_ID:
            raise ValueError(f"machine_id must be 0–{self.MAX_MACHINE_ID}")

        self.machine_id = machine_id
        self.sequence = 0
        self.last_timestamp = -1
        self._lock = threading.Lock()

    def _now_ms(self) -> int:
        return int(time.time() * 1000) - self.EPOCH

    def generate(self) -> int:
        """Return a new Snowflake ID as an integer."""
        with self._lock:
            ts = self._now_ms()

            if ts < self.last_timestamp:
                raise RuntimeError("Clock moved backwards — cannot generate Snowflake ID")

            if ts == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.MAX_SEQUENCE
                if self.sequence == 0:
                    while ts <= self.last_timestamp:
                        ts = self._now_ms()
            else:
                self.sequence = 0

            self.last_timestamp = ts

            return (
                (ts << (self.MACHINE_BITS + self.SEQUENCE_BITS))
                | (self.machine_id << self.SEQUENCE_BITS)
                | self.sequence
            )

    def generate_str(self) -> str:
        """Return a new Snowflake ID as a zero-padded 19-digit string."""
        return f"{self.generate():019d}"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_generator: SnowflakeGenerator | None = None
_generator_lock = threading.Lock()


def _get_generator() -> SnowflakeGenerator:
    global _generator
    if _generator is None:
        with _generator_lock:
            if _generator is None:
                _generator = SnowflakeGenerator()
    return _generator


def generate() -> int:
    """Generate a new Snowflake ID (integer)."""
    return _get_generator().generate()


def generate_str() -> str:
    """Generate a new Snowflake ID (zero-padded 19-digit string)."""
    return _get_generator().generate_str()


def timestamp_ms(snowflake_id: int | str) -> int:
    """Extract the millisecond timestamp embedded in a Snowflake ID."""
    n = int(snowflake_id)
    return (n >> (SnowflakeGenerator.MACHINE_BITS + SnowflakeGenerator.SEQUENCE_BITS)) + SnowflakeGenerator.EPOCH
