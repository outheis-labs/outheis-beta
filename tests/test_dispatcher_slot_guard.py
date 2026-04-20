"""Tests for the scheduler slot guard in dispatcher/daemon.py.

_execute_task must prevent concurrent runs of the same task name
and release the slot after completion (success or failure).
"""

import threading
import time

from outheis.core.config import AgentConfig, Config, LLMConfig
from outheis.dispatcher.daemon import Dispatcher

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def make_dispatcher() -> Dispatcher:
    cfg = Config(
        llm=LLMConfig(),
        agents={"relay": AgentConfig(name="ou", model="fast", enabled=True)},
    )
    return Dispatcher(config=cfg)


# ---------------------------------------------------------------------------
# Basic slot guard
# ---------------------------------------------------------------------------

class TestSlotGuard:
    def test_first_call_returns_true(self, monkeypatch, tmp_path):
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        done = threading.Event()
        started = threading.Event()

        def slow():
            started.set()
            done.wait()

        result = d._execute_task("shadow_scan", slow)
        started.wait(timeout=1)
        assert result is True
        done.set()

    def test_second_call_same_task_returns_false(self, monkeypatch):
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        blocked = threading.Event()
        released = threading.Event()

        def slow():
            blocked.set()
            released.wait()

        d._execute_task("shadow_scan", slow)
        blocked.wait(timeout=1)

        result = d._execute_task("shadow_scan", lambda: None)
        assert result is False

        released.set()

    def test_different_tasks_do_not_block(self, monkeypatch):
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        blocked = threading.Event()
        released = threading.Event()

        def slow():
            blocked.set()
            released.wait()

        d._execute_task("shadow_scan", slow)
        blocked.wait(timeout=1)

        result = d._execute_task("pattern_infer", lambda: None)
        assert result is True

        released.set()

    def test_slot_released_after_success(self, monkeypatch):
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        threading.Event()

        def fast():
            pass

        d._execute_task("shadow_scan", fast)
        # Wait until the thread finishes
        deadline = time.time() + 2
        while "shadow_scan" in d._running_tasks and time.time() < deadline:
            time.sleep(0.01)

        result = d._execute_task("shadow_scan", fast)
        assert result is True

    def test_slot_released_after_failure(self, monkeypatch):
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        def boom():
            raise RuntimeError("task failed")

        d._execute_task("shadow_scan", boom)

        deadline = time.time() + 2
        while "shadow_scan" in d._running_tasks and time.time() < deadline:
            time.sleep(0.01)

        result = d._execute_task("shadow_scan", lambda: None)
        assert result is True


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------

class TestRegistryState:
    def test_registry_shows_running_while_active(self, monkeypatch):
        from outheis.dispatcher.daemon import _task_registry
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        blocked = threading.Event()
        released = threading.Event()

        def slow():
            blocked.set()
            released.wait()

        d._execute_task("shadow_scan", slow)
        blocked.wait(timeout=1)

        assert _task_registry.get("shadow_scan", {}).get("status") == "running"
        released.set()

    def test_registry_shows_completed_after_success(self, monkeypatch):
        from outheis.dispatcher.daemon import _task_registry
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        d._execute_task("shadow_scan", lambda: None)

        deadline = time.time() + 2
        while _task_registry.get("shadow_scan", {}).get("status") == "running" and time.time() < deadline:
            time.sleep(0.01)

        assert _task_registry["shadow_scan"]["status"] == "completed"

    def test_registry_shows_failed_after_exception(self, monkeypatch):
        from outheis.dispatcher.daemon import _task_registry
        monkeypatch.setattr("outheis.dispatcher.daemon._persist_registry", lambda *a: None)
        d = make_dispatcher()

        d._execute_task("shadow_scan", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        deadline = time.time() + 2
        while _task_registry.get("shadow_scan", {}).get("status") == "running" and time.time() < deadline:
            time.sleep(0.01)

        assert _task_registry["shadow_scan"]["status"] == "failed"
        assert "boom" in _task_registry["shadow_scan"]["error"]
