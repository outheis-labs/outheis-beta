"""
File watcher for message queue.

Uses watchdog for cross-platform file monitoring.
Notifies dispatcher when new messages arrive.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

try:
    from watchdog.events import FileModifiedEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


# =============================================================================
# WATCHDOG HANDLER
# =============================================================================

if WATCHDOG_AVAILABLE:
    class QueueHandler(FileSystemEventHandler):
        """Handler for queue file changes."""

        def __init__(self, callback: Callable[[], None]):
            self.callback = callback
            self._last_size = 0

        def on_modified(self, event):
            if isinstance(event, FileModifiedEvent):
                # Debounce: only trigger if file actually grew
                try:
                    new_size = Path(event.src_path).stat().st_size
                    if new_size > self._last_size:
                        self._last_size = new_size
                        self.callback()
                except OSError:
                    pass


# =============================================================================
# WATCHER CLASS
# =============================================================================

class QueueWatcher:
    """
    Watch message queue for new messages.

    Uses watchdog if available, falls back to polling.
    """

    def __init__(
        self,
        queue_path: Path,
        on_message: Callable[[], None],
        poll_interval: float = 1.0,
    ):
        self.queue_path = queue_path
        self.on_message = on_message
        self.poll_interval = poll_interval

        self._running = False
        self._thread: threading.Thread | None = None
        self._observer = None

    def start(self) -> None:
        """Start watching the queue."""
        if self._running:
            return

        self._running = True

        if WATCHDOG_AVAILABLE:
            self._start_watchdog()
        else:
            self._start_polling()

    def stop(self) -> None:
        """Stop watching the queue."""
        self._running = False

        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _start_watchdog(self) -> None:
        """Start using watchdog."""
        handler = QueueHandler(self.on_message)
        self._observer = Observer()
        self._observer.schedule(
            handler,
            str(self.queue_path.parent),
            recursive=False,
        )
        self._observer.start()

    def _start_polling(self) -> None:
        """Start using polling fallback."""
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self) -> None:
        """Polling loop for systems without watchdog."""
        last_size = 0

        while self._running:
            try:
                if self.queue_path.exists():
                    new_size = self.queue_path.stat().st_size
                    if new_size > last_size:
                        last_size = new_size
                        self.on_message()
            except OSError:
                pass

            time.sleep(self.poll_interval)
