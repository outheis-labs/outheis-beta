"""
Message queue — append-only JSONL file with write-ahead logging.

The queue is the central communication channel. All agents
read from and write to this queue.

Write-ahead: Messages are written to .pending/ first, then
appended to the queue. If a process dies while waiting for
the lock, the Dispatcher recovers pending messages on startup.
"""

from __future__ import annotations

import fcntl
import json
import time
from collections.abc import Iterator
from pathlib import Path

from outheis.core.message import Message
from outheis.core.schema import read_message, write_message

# =============================================================================
# PENDING DIRECTORY
# =============================================================================

def get_pending_dir() -> Path:
    """Get path to pending directory."""
    from outheis.core.config import get_human_dir
    return get_human_dir() / ".pending"


def ensure_pending_dir() -> Path:
    """Ensure pending directory exists."""
    pending = get_pending_dir()
    pending.mkdir(parents=True, exist_ok=True)
    return pending


def write_pending(msg: Message) -> Path:
    """
    Write message to pending directory.

    Returns path to pending file.
    """
    pending_dir = ensure_pending_dir()
    pending_path = pending_dir / f"{msg.id}.json"

    data = {
        "msg": msg.to_dict(),
        "timestamp": time.time(),
    }

    # Atomic write
    tmp_path = pending_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    tmp_path.rename(pending_path)

    return pending_path


def delete_pending(pending_path: Path) -> None:
    """Delete pending file after successful write."""
    pending_path.unlink(missing_ok=True)


def recover_pending(queue_path: Path) -> int:
    """
    Recover pending messages to queue.

    Called by Dispatcher on startup.
    Checks for duplicates before appending.
    Returns count of recovered messages.
    """
    pending_dir = get_pending_dir()
    if not pending_dir.exists():
        return 0

    # Get recent IDs to check for duplicates
    existing_ids = set(read_last_n_ids(queue_path, 100))

    count = 0
    for pending_path in sorted(pending_dir.glob("*.json")):
        try:
            data = json.loads(pending_path.read_text(encoding="utf-8"))
            msg = Message.from_dict(data["msg"])

            # Skip if already in queue (duplicate)
            if msg.id in existing_ids:
                delete_pending(pending_path)
                continue

            # Append with lock
            line = write_message(msg.to_dict())
            with open(queue_path, "a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(line + "\n")
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

            delete_pending(pending_path)
            count += 1
        except Exception:
            # Log in production, skip corrupted
            continue

    return count


def read_last_n_ids(path: Path, n: int) -> list[str]:
    """Read the last N message IDs from the queue."""
    if not path.exists():
        return []

    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if "id" in d:
                    ids.append(d["id"])
            except Exception:
                continue

    return ids[-n:] if len(ids) > n else ids


def get_last_id(path: Path) -> str | None:
    """Get the last message ID from the queue."""
    ids = read_last_n_ids(path, 1)
    return ids[0] if ids else None


def get_unanswered_requests(path: Path) -> list[Message]:
    """
    Find request messages that have no response.

    A request is unanswered if:
    - It's addressed to "dispatcher"
    - No message has reply_to pointing to its ID

    Used on startup to process messages that crashed before response.
    """
    if not path.exists():
        return []

    # Read all messages
    requests: dict[str, Message] = {}  # id -> message
    answered_ids: set[str] = set()

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = read_message(line)
                msg = Message.from_dict(d)

                # Track requests to dispatcher
                if msg.to == "dispatcher" and msg.type == "request":
                    requests[msg.id] = msg

                # Track which requests have been answered
                if msg.reply_to:
                    answered_ids.add(msg.reply_to)

            except Exception:
                continue

    # Return unanswered requests
    return [msg for msg_id, msg in requests.items() if msg_id not in answered_ids]


# =============================================================================
# QUEUE OPERATIONS
# =============================================================================

def append(path: Path, msg: Message) -> None:
    """
    Append a message to the queue with write-ahead safety.

    1. Write to .pending/ (survives crash)
    2. flock + append to queue
    3. Delete from .pending/

    If process dies between 1-3, Dispatcher recovers on startup.
    """
    # 1. Write-ahead
    pending_path = write_pending(msg)

    try:
        # 2. Append with lock
        line = write_message(msg.to_dict())

        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        # 3. Cleanup
        delete_pending(pending_path)
    except Exception:
        # Keep pending for recovery
        raise


def read_all(path: Path) -> list[Message]:
    """
    Read all messages from the queue.

    Handles version migration transparently.
    """
    if not path.exists():
        return []

    messages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = read_message(line)
                messages.append(Message.from_dict(d))
            except Exception:
                # Skip malformed lines, log in production
                continue

    return messages


def read_from(path: Path, after_id: str | None = None) -> Iterator[Message]:
    """
    Read messages from the queue, optionally after a given ID.

    Yields messages one by one for memory efficiency.
    """
    if not path.exists():
        return

    found_marker = after_id is None

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = read_message(line)
                msg = Message.from_dict(d)

                if not found_marker:
                    if msg.id == after_id:
                        found_marker = True
                    continue

                yield msg
            except Exception:
                continue


def read_last_n(path: Path, n: int) -> list[Message]:
    """
    Read the last N messages from the queue.

    Tail-reads from the end of the file to avoid scanning the full queue.
    Falls back to forward scan if tail-read yields fewer than N messages.
    """
    if not path.exists() or n <= 0:
        return []

    CHUNK = 8192
    collected: list[bytes] = []

    with open(path, "rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        if pos == 0:
            return []

        buf = b""
        while pos > 0 and len(collected) < n:
            read_size = min(CHUNK, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            buf = chunk + buf
            lines = buf.split(b"\n")
            # Keep partial first chunk in buf for next iteration
            buf = lines[0]
            for line in reversed(lines[1:]):
                stripped = line.strip()
                if stripped:
                    collected.append(stripped)
                if len(collected) >= n:
                    break

        # Process remaining buffer (first line of file)
        if len(collected) < n and buf.strip():
            collected.append(buf.strip())

    messages: list[Message] = []
    for raw in reversed(collected[:n]):
        try:
            d = read_message(raw.decode("utf-8"))
            messages.append(Message.from_dict(d))
        except Exception:
            continue
    return messages


# Module-level cache: (path_str, mtime, size, conv_id) -> messages
_conv_cache: dict[tuple, list[Message]] = {}


def read_conversation(path: Path, conversation_id: str) -> list[Message]:
    """Read all messages belonging to a conversation, with mtime/size cache."""
    if not path.exists():
        return []

    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size, conversation_id)

    if key in _conv_cache:
        return _conv_cache[key]

    # Evict stale entries for this path+conversation
    stale = [k for k in _conv_cache if k[0] == str(path) and k[3] == conversation_id]
    for k in stale:
        del _conv_cache[k]

    result = [msg for msg in read_all(path) if msg.conversation_id == conversation_id]
    _conv_cache[key] = result
    return result


# =============================================================================
# QUEUE MANAGEMENT
# =============================================================================

def ensure_queue(path: Path) -> None:
    """Ensure queue file exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def queue_size(path: Path) -> int:
    """Get queue file size in bytes."""
    if not path.exists():
        return 0
    return path.stat().st_size


def message_count(path: Path) -> int:
    """Count messages in queue."""
    if not path.exists():
        return 0

    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count
