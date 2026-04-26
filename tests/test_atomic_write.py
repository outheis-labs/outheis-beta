"""Tests for atomic file writes in the dispatcher.

Covers _atomic_write, _persist_registry, and the status-file paths used by
the WebUI thread while the dispatcher thread writes them.
"""

import json
import threading

from outheis.dispatcher.daemon import (
    _atomic_write,
    _persist_registry,
    _task_registry_lock,
)


class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        p = tmp_path / "file.json"
        _atomic_write(p, '{"ok": true}')
        assert json.loads(p.read_text()) == {"ok": True}

    def test_replaces_existing(self, tmp_path):
        p = tmp_path / "file.json"
        p.write_text("old")
        _atomic_write(p, "new")
        assert p.read_text() == "new"

    def test_no_tmp_file_left_behind(self, tmp_path):
        p = tmp_path / "file.json"
        _atomic_write(p, "{}")
        assert not (tmp_path / "file.json.tmp").exists()

    def test_reader_never_sees_empty_file(self, tmp_path):
        """Concurrent reader should never observe an empty or partial file."""
        p = tmp_path / "status.json"
        p.write_text('{"mode": "ok"}')

        observed_empty = []

        def writer():
            for _ in range(200):
                _atomic_write(p, json.dumps({"mode": "fallback", "x": "y" * 100}))
                _atomic_write(p, json.dumps({"mode": "ok"}))

        def reader():
            for _ in range(200):
                try:
                    content = p.read_text()
                    if not content:
                        observed_empty.append(True)
                    else:
                        json.loads(content)  # must be valid JSON
                except (json.JSONDecodeError, OSError):
                    observed_empty.append(True)

        t_write = threading.Thread(target=writer)
        t_read = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        assert not observed_empty, "Reader observed empty or invalid file during concurrent writes"


class TestPersistRegistry:
    def test_writes_json(self, tmp_path, monkeypatch):
        from outheis.core import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "get_tasks_path", lambda: tmp_path / "tasks.json")

        registry = {"vault_scan": {"status": "completed", "last_run": 1234567890.0}}
        with _task_registry_lock:
            _persist_registry(registry)

        written = json.loads((tmp_path / "tasks.json").read_text())
        assert written == registry

    def test_no_tmp_left_behind(self, tmp_path, monkeypatch):
        from outheis.core import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "get_tasks_path", lambda: tmp_path / "tasks.json")

        with _task_registry_lock:
            _persist_registry({"a": {"status": "ok"}})

        assert not (tmp_path / "tasks.json.tmp").exists()

    def test_swallows_write_error(self, tmp_path, monkeypatch):
        """_persist_registry must not raise even if the path is unwritable."""
        monkeypatch.setattr(
            "outheis.dispatcher.daemon._atomic_write",
            lambda path, text: (_ for _ in ()).throw(OSError("disk full")),
        )
        # Should not raise
        with _task_registry_lock:
            _persist_registry({"x": {}})
