"""
Dispatcher daemon.

The central process that watches the message queue,
routes messages to agents, and manages agent lifecycle.

Includes built-in scheduler for periodic tasks (Pattern agent, housekeeping).
Uses select() with timeout — no polling loop, no external dependencies.
"""

from __future__ import annotations

import os
import select
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

# Module-level task registry — shared between dispatcher and WebUI server
# (both run in the same process). Also persisted to tasks.json so CLI tools
# can query task status without HTTP or a running WebUI.
_task_registry: dict[str, dict] = {}
_task_registry_lock = threading.Lock()


def _atomic_write(path: "Path", text: str) -> None:
    """Write *text* to *path* atomically via a sibling .tmp file + rename.

    The WebUI thread reads these files while the dispatcher thread writes them.
    A plain write_text() truncates first, so a concurrent read can observe an
    empty or partial file.  rename() is POSIX-atomic on the same filesystem, so
    readers always see either the old complete file or the new complete file.
    """
    from pathlib import Path as _Path
    tmp = _Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _persist_registry(registry: dict) -> None:
    """Write registry snapshot to tasks.json. Called under _task_registry_lock."""
    import json
    try:
        from outheis.core.config import get_tasks_path
        _atomic_write(get_tasks_path(), json.dumps(registry, indent=2, ensure_ascii=False))
    except Exception:
        pass


def get_task_registry() -> dict[str, dict]:
    """Return a snapshot of all task records.

    Same-process callers (WebUI server) get the in-memory dict directly.
    External callers (CLI) should use read_task_registry() which reads tasks.json.
    """
    with _task_registry_lock:
        return dict(_task_registry)


def read_task_registry() -> dict[str, dict]:
    """Read task registry from tasks.json — works without a running dispatcher."""
    import json
    try:
        from outheis.core.config import get_tasks_path
        path = get_tasks_path()
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


from outheis.agents import (
    create_action_agent,
    create_agenda_agent,
    create_code_agent,
    create_data_agent,
    create_pattern_agent,
    create_relay_agent,
)
from outheis.core.config import (
    Config,
    get_messages_path,
    init_directories,
    load_config,
)
from outheis.core.message import Message
from outheis.core.queue import append, get_last_id, get_unanswered_requests, read_from
from outheis.dispatcher.router import get_dispatch_target
from outheis.dispatcher.watcher import QueueWatcher


# =============================================================================
# SCHEDULER
# =============================================================================

@dataclass
class ScheduledTask:
    """A task scheduled to run at specific times or on an interval."""
    name: str
    run: Callable[[], None]
    time: list[str] = field(default_factory=list)  # ["HH:MM", ...] — empty = interval-based
    interval_minutes: int | None = None
    last_run: datetime | None = None

    def _parsed_times(self) -> list[tuple[int, int]]:
        result = []
        for t in self.time:
            try:
                h, m = t.split(":")
                result.append((int(h), int(m)))
            except ValueError:
                pass
        return result

    def next_run(self, now: datetime) -> datetime:
        """Calculate next run time."""
        if self.interval_minutes:
            if self.last_run is None:
                return now
            return self.last_run + timedelta(minutes=self.interval_minutes)
        parsed = self._parsed_times()
        if not parsed:
            return now + timedelta(hours=1)
        candidates = [
            now.replace(hour=h, minute=m, second=0, microsecond=0)
            for h, m in parsed
            if now.replace(hour=h, minute=m, second=0, microsecond=0) > now
        ]
        if candidates:
            return min(candidates)
        # All times passed today — return first time tomorrow
        h, m = parsed[0]
        return now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)

    def seconds_until_next(self, now: datetime) -> float:
        """Seconds until next scheduled run."""
        diff = (self.next_run(now) - now).total_seconds()
        return max(0, diff)

    def should_run(self, now: datetime) -> bool:
        """Check if task should run now."""
        if self.interval_minutes:
            if self.last_run is None:
                return True
            elapsed = (now - self.last_run).total_seconds() / 60
            return elapsed >= self.interval_minutes
        for h, m in self._parsed_times():
            if now.hour != h:
                continue
            # Allow up to 2 minutes past the scheduled time (scheduler jitter)
            if not (0 <= now.minute - m <= 2):
                continue
            # Already ran this slot? Guard by slot start time, not just hour,
            # so two tasks in the same hour don't block each other.
            slot_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if self.last_run is not None and self.last_run >= slot_time:
                continue
            return True
        return False


@dataclass
class Scheduler:
    """
    Built-in scheduler for periodic tasks.
    
    No external dependencies. Integrates with select() timeout.
    """
    tasks: list[ScheduledTask] = field(default_factory=list)
    
    def add(
        self,
        name: str,
        run: Callable[[], None],
        time: list[str] | None = None,
        interval_minutes: int | None = None,
    ) -> None:
        """Add a scheduled task."""
        self.tasks.append(ScheduledTask(
            name=name,
            run=run,
            time=time or [],
            interval_minutes=interval_minutes,
        ))
    
    def seconds_until_next(self) -> float:
        """Seconds until next task needs to run."""
        if not self.tasks:
            return 3600.0  # No tasks, check again in an hour
        
        now = datetime.now()
        return min(task.seconds_until_next(now) for task in self.tasks)
    
    def get_due(self) -> list["ScheduledTask"]:
        """Return due tasks and mark their last_run to prevent re-firing."""
        now = datetime.now()
        due = []
        for task in self.tasks:
            if task.should_run(now):
                task.last_run = now
                due.append(task)
        return due

    def run_due(self) -> list[str]:
        """Run all due tasks. Returns names of tasks run."""
        now = datetime.now()
        ran = []
        for task in self.tasks:
            if task.should_run(now):
                try:
                    task.run()
                    task.last_run = now
                    ran.append(task.name)
                except Exception as e:
                    # Log but don't crash
                    print(f"Scheduled task {task.name} failed: {e}")
        return ran


# =============================================================================
# PID FILE
# =============================================================================

def get_pid_path() -> Path:
    """Get path to PID file."""
    from outheis.core.config import get_outheis_dir
    return get_outheis_dir() / ".dispatcher.pid"


def write_pid() -> None:
    """Write current PID to file."""
    get_pid_path().write_text(str(os.getpid()))


def read_pid() -> int | None:
    """Read PID from file, or None if not running."""
    path = get_pid_path()
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        # Invalid PID or process not running
        path.unlink(missing_ok=True)
        return None


def remove_pid() -> None:
    """Remove PID file."""
    get_pid_path().unlink(missing_ok=True)


# =============================================================================
# CONFIG WATCHER
# =============================================================================

class ConfigWatcher:
    """Monitors config.json for changes and notifies the daemon.

    Polls mtime every 2 seconds. On change, calls on_change() in the watcher
    thread. The callback is responsible for debouncing and reload.
    """

    def __init__(self, config_path: Path, on_change: Callable[[], None]) -> None:
        self._path = config_path
        self._on_change = on_change
        self._mtime: float = config_path.stat().st_mtime if config_path.exists() else 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="config-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(timeout=2.0):
            try:
                mtime = self._path.stat().st_mtime
                if mtime != self._mtime:
                    self._mtime = mtime
                    self._on_change()
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[config-watcher] error: {e}", file=sys.stderr)


# =============================================================================
# DISPATCHER
# =============================================================================

@dataclass
class Dispatcher:
    """
    The dispatcher daemon.

    Watches the message queue, routes messages to agents,
    manages responses, and runs scheduled tasks.
    
    Uses select() with timeout for efficient waiting:
    - Wakes on file changes (inotify/kqueue via watcher)
    - Wakes on scheduled task deadline
    - No busy polling
    """

    config: Config = field(default_factory=load_config)
    queue_path: Path = field(default_factory=get_messages_path)
    last_processed_id: str | None = None
    running: bool = False
    scheduler: Scheduler = field(default_factory=Scheduler)

    # Agents (loaded on demand)
    _agents: dict = field(default_factory=dict)

    # Pipe for wakeup signal
    _wakeup_read: int | None = None
    _wakeup_write: int | None = None

    # Signal transport thread
    _signal_thread: threading.Thread | None = None
    _signal_transport: any = field(default=None, repr=False)

    # Fallback mode — activated when cloud billing fails
    _fallback_mode: bool = False
    _original_models: dict = field(default_factory=dict)  # saved before fallback override

    # Task execution lock — prevents concurrent runs of the same task
    _running_tasks: set = field(default_factory=set)
    _task_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        # Create wakeup pipe
        self._wakeup_read, self._wakeup_write = os.pipe()
        os.set_blocking(self._wakeup_read, False)
        os.set_blocking(self._wakeup_write, False)

    def _enter_fallback_mode(self, reason: str, conversation_id: str | None = None) -> None:
        """Switch to local fallback models when cloud billing fails.

        - Always notifies user on all channels, regardless of fallback availability.
        - If local_fallback is configured: overrides agent models to fallback alias.
        - Writes system_status.json so WebUI can show the yellow flag.
        - Starts periodic billing probe to detect when credits are restored.
        """
        import time as _time
        from outheis.core.config import get_status_path
        from outheis.core.message import create_agent_message
        from outheis.core.queue import append

        if self._fallback_mode:
            return  # Already in fallback — don't repeat

        self._fallback_mode = True
        print(f"[fallback] Entering fallback mode: {reason}", flush=True)

        fallback = self.config.llm.local_fallback

        if fallback:
            # Override model alias for all cloud-dependent agents, saving originals
            fallback_agents = {"relay", "data", "agenda", "pattern", "code"}
            for role, agent_cfg in self.config.agents.items():
                if role in fallback_agents and agent_cfg.enabled:
                    self._original_models[role] = agent_cfg.model
                    agent_cfg.model = fallback
                    self._agents.pop(role, None)
            text = (
                f"API credit balance exhausted. "
                f"Switched to local fallback model '{fallback}'. "
                f"Some capabilities may be reduced. "
                f"Will switch back automatically when credits are restored."
            )
        else:
            text = (
                f"API credit balance exhausted. "
                f"No local fallback model configured — requests will fail until credits are restored. "
                f"Will notify you automatically when the API is available again."
            )
            print(f"[fallback] No local_fallback configured — notifications only.", flush=True)

        # Write status file for WebUI
        status = {
            "mode": "fallback",
            "reason": reason,
            "fallback_model": fallback or "none",
            "since": _time.time(),
        }
        try:
            _atomic_write(get_status_path(), __import__("json").dumps(status))
        except Exception as e:
            print(f"[fallback] Could not write status file: {e}", flush=True)

        # Broadcast notification to all transports
        notif = create_agent_message(
            from_agent="relay",
            to="transport",
            type="response",
            payload={"text": text},
            conversation_id=conversation_id or "system",
            intent="broadcast",
        )
        try:
            append(self.queue_path, notif)
        except Exception as e:
            print(f"[fallback] Could not append broadcast: {e}", flush=True)

    def _exit_fallback_mode(self) -> None:
        """Restore cloud models after billing is confirmed available again."""
        import time as _time
        from outheis.core.config import get_status_path
        from outheis.core.message import create_agent_message
        from outheis.core.queue import append

        if not self._fallback_mode:
            return

        self._fallback_mode = False
        print(f"[fallback] Exiting fallback mode — cloud billing restored.", flush=True)

        # Restore original model aliases
        for role, original_model in self._original_models.items():
            if role in self.config.agents:
                self.config.agents[role].model = original_model
                self._agents.pop(role, None)
        self._original_models.clear()

        # Clear status file
        try:
            _atomic_write(get_status_path(), __import__("json").dumps({"mode": "ok", "since": _time.time()}))
        except Exception as e:
            print(f"[fallback] Could not update status file: {e}", flush=True)

        # Broadcast recovery notification
        text = "API credits restored. Switched back to cloud models."
        notif = create_agent_message(
            from_agent="relay",
            to="transport",
            type="response",
            payload={"text": text},
            conversation_id="system",
            intent="broadcast",
        )
        try:
            append(self.queue_path, notif)
        except Exception as e:
            print(f"[fallback] Could not append recovery broadcast: {e}", flush=True)

    def _probe_billing(self) -> bool:
        """Make a minimal cloud API call. Return True if billing is now available."""
        from outheis.core.llm import call_llm, BillingError, resolve_model

        # Find a cloud alias from original models (or current config if no originals saved)
        aliases = list(self._original_models.values()) or [
            cfg.model for cfg in self.config.agents.values()
            if cfg.enabled
        ]
        test_alias = next(
            (a for a in aliases if not a.startswith("local-")),
            None,
        )
        if not test_alias:
            return False  # No cloud alias found

        try:
            call_llm(
                model=test_alias,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                agent="billing_probe",
            )
            return True
        except BillingError:
            return False
        except Exception as e:
            print(f"[fallback] Probe error (non-billing): {e}", flush=True)
            return False

    def _run_billing_probe(self) -> None:
        """Scheduled task: silently check if billing is restored. Auto-exits fallback if so."""
        if not self._fallback_mode:
            return
        print(f"[fallback] Probing cloud billing...", flush=True)
        if self._probe_billing():
            self._exit_fallback_mode()

    def _check_billing_at_startup(self) -> None:
        """Probe cloud providers at startup. Enter fallback mode if billing fails."""
        from outheis.core.llm import call_llm, BillingError, resolve_model

        # Collect unique cloud providers used by enabled agents
        cloud_aliases: set[str] = set()
        for role, agent_cfg in self.config.agents.items():
            if not agent_cfg.enabled:
                continue
            try:
                mc = resolve_model(agent_cfg.model)
                if not mc.provider.startswith("ollama"):
                    cloud_aliases.add(agent_cfg.model)
            except Exception:
                pass

        if not cloud_aliases:
            return  # All agents already on local models

        # Test with the cheapest available alias
        test_alias = next(iter(cloud_aliases))
        try:
            call_llm(
                model=test_alias,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                agent="startup_check",
            )
            print(f"[startup] Cloud provider OK (tested alias: {test_alias})")
        except BillingError as e:
            print(f"[startup] Billing error detected: {e}")
            self._enter_fallback_mode(str(e), conversation_id=None)
        except Exception as e:
            # Other errors (network, timeout) — don't enter fallback, log only
            print(f"[startup] Cloud probe warning (non-billing): {e}")

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        self.running = False
        # Wake up select()
        if self._wakeup_write:
            try:
                os.write(self._wakeup_write, b'x')
            except OSError:
                pass

    def _setup_scheduled_tasks(self) -> None:
        """Configure scheduled tasks from config."""
        sched = self.config.schedule
        
        if sched.pattern_infer.enabled:
            self.scheduler.add("pattern_infer", self._run_pattern_agent, time=sched.pattern_infer.time)
        if sched.index_rebuild.enabled:
            self.scheduler.add("index_rebuild", self._run_index_rebuild, time=sched.index_rebuild.time)
        if sched.archive_rotation.enabled:
            self.scheduler.add("archive_rotation", self._run_archive_rotation, time=sched.archive_rotation.time)
        if sched.shadow_scan.enabled:
            self.scheduler.add("shadow_scan", self._run_shadow_scan, time=sched.shadow_scan.time)
        if sched.memory_migrate.enabled:
            self.scheduler.add("memory_migrate", self._run_memory_migrate_task, time=sched.memory_migrate.time)
        if sched.action_tasks.enabled:
            self.scheduler.add("action_tasks", self._run_action_tasks, interval_minutes=15)
        if sched.agenda_review.enabled:
            self.scheduler.add("agenda_review", self._run_agenda_review, time=sched.agenda_review.time)

        # Billing probe — always active; no-ops when not in fallback mode
        self.scheduler.add("billing_probe", self._run_billing_probe, interval_minutes=15)

        # Mandatory midnight refresh — always runs if agenda agent is enabled,
        # independent of agenda_review schedule config
        agenda_agent_cfg = self.config.agents.get("agenda")
        if agenda_agent_cfg and agenda_agent_cfg.enabled:
            self.scheduler.add("agenda_midnight", self._run_agenda_midnight, time=["00:00"])

    def _execute_task(
        self,
        task_name: str,
        runner: "Callable[[], None]",
        conversation_id: str | None = None,
    ) -> bool:
        """
        Execute a task in a background thread if not already running.

        Returns True if started, False if skipped (already running).
        Task status is tracked in the module-level _task_registry; the WebUI
        server reads it directly — no message-queue events needed.
        """
        started_at = datetime.now().isoformat()

        with self._task_lock:
            if task_name in self._running_tasks:
                print(f"[dispatcher] run_task:{task_name} skipped (already running)")
                # Do NOT overwrite the registry — the running entry must stay visible.
                return False
            self._running_tasks.add(task_name)

        with _task_registry_lock:
            rec = {"name": task_name, "status": "running",
                   "started_at": started_at, "finished_at": None}
            _task_registry[task_name] = rec
            _persist_registry(dict(_task_registry))

        def _run() -> None:
            try:
                runner()
                with _task_registry_lock:
                    rec = _task_registry.get(task_name, {})
                    rec["status"] = "completed"
                    rec["finished_at"] = datetime.now().isoformat()
                    _task_registry[task_name] = rec
                    _persist_registry(dict(_task_registry))
            except Exception as e:
                print(f"[dispatcher] run_task:{task_name} failed: {e}")
                with _task_registry_lock:
                    rec = _task_registry.get(task_name, {})
                    rec["status"] = "failed"
                    rec["finished_at"] = datetime.now().isoformat()
                    rec["error"] = str(e)
                    _task_registry[task_name] = rec
                    _persist_registry(dict(_task_registry))
            finally:
                with self._task_lock:
                    self._running_tasks.discard(task_name)

        t = threading.Thread(target=_run, daemon=True, name=f"task-{task_name}")
        t.start()
        return True

    def _run_pattern_agent(self) -> None:
        """Run Pattern agent scheduled reflection."""
        agent = self.get_agent("pattern")
        if agent:
            agent.run_scheduled()

    def _run_index_rebuild(self) -> None:
        """Rebuild vault search indices (full rebuild)."""
        agent = self.get_agent("data")
        if agent and hasattr(agent, 'rebuild_indices'):
            results = agent.rebuild_indices()
            print(f"Index rebuild: {results}")

    def _agent_model_map(self, config=None) -> dict[str, str]:
        """Return {agent_name: model_alias} for all enabled agents."""
        cfg = config or self.config
        return {name: ac.model for name, ac in cfg.agents.items() if ac.enabled}

    def _active_ollama_aliases(self, config=None) -> set[str]:
        """Return model aliases that are ollama.local AND assigned to an enabled agent."""
        cfg = config or self.config
        active_aliases = set(self._agent_model_map(cfg).values())
        return {alias for alias, mc in cfg.llm.models.items()
                if mc.provider == "ollama.local" and alias in active_aliases}

    def _warmup_persistent_models(self) -> None:
        """Send a minimal call to each ollama.local model assigned to an enabled agent.

        Raises SystemExit if a required model fails to load.
        """
        import sys

        for alias in self._active_ollama_aliases():
            model_cfg = self.config.llm.models[alias]
            try:
                from outheis.core.llm import call_llm
                call_llm(
                    model=alias,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                    agent="warmup",
                )
                print(f"  \033[32m✓\033[0m {alias} ({model_cfg.name}) loaded into memory", file=sys.stderr)
            except Exception as e:
                print(f"  \033[31m✗\033[0m {alias} ({model_cfg.name}) not available: {e}", file=sys.stderr)
                print(f"\n\033[31mStartup aborted:\033[0m model '{alias}' is required by an active agent but could not be loaded.", file=sys.stderr)
                print(f"Fix: run 'ollama pull {model_cfg.name}' or disable the agent using this model.", file=sys.stderr)
                sys.exit(1)

    def _unload_ollama_model(self, model_name: str) -> None:
        """Tell Ollama to unload a model from memory (keep_alive=0)."""
        import urllib.request
        import json as _json
        provider = self.config.llm.providers.get("ollama.local")
        base = (provider.base_url if provider and provider.base_url else "http://localhost:11434").rstrip("/").removesuffix("/v1")
        url = f"{base}/api/generate"
        body = _json.dumps({"model": model_name, "keep_alive": 0}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
            print(f"  \033[33m↓\033[0m {model_name} unloaded from memory", file=sys.stderr)
        except Exception as e:
            print(f"  [warmup] could not unload {model_name}: {e}", file=sys.stderr)

    def _on_config_changed(self) -> None:
        """Reload config.json and react to relevant changes."""
        import time
        time.sleep(0.3)  # debounce — wait for write to complete
        try:
            from outheis.core.config import load_config
            new_config = load_config()
        except Exception as e:
            print(f"[config-watcher] reload failed: {e}", file=sys.stderr)
            return

        # Diff all agent model assignments
        old_map = self._agent_model_map(self.config)
        old_ollama = self._active_ollama_aliases(self.config)
        old_ollama_names = {alias: self.config.llm.models[alias].name
                            for alias in old_ollama if alias in self.config.llm.models}

        self.config = new_config

        new_map = self._agent_model_map(new_config)
        new_ollama = self._active_ollama_aliases(new_config)

        # Invalidate cached agent instances whose model assignment changed
        for agent in sorted(set(old_map) | set(new_map)):
            old_alias = old_map.get(agent)
            new_alias = new_map.get(agent)
            if old_alias != new_alias:
                print(f"[config-watcher] {agent}: {old_alias or '(none)'} → {new_alias or '(none)'}", file=sys.stderr)
                self._agents.pop(agent, None)  # force re-creation with new model on next call

        # Ollama-specific: warmup newly assigned models, unload removed ones
        to_load = new_ollama - old_ollama
        to_unload = old_ollama - new_ollama
        if to_load or to_unload:
            def _refresh():
                for alias in to_load:
                    model_cfg = new_config.llm.models.get(alias)
                    try:
                        from outheis.core.llm import call_llm
                        call_llm(model=alias, messages=[{"role": "user", "content": "hi"}],
                                 max_tokens=1, agent="warmup")
                        print(f"  \033[32m✓\033[0m {alias} ({model_cfg.name if model_cfg else alias}) loaded", file=sys.stderr)
                    except Exception as e:
                        print(f"  \033[31m✗\033[0m {alias} failed to load: {e}", file=sys.stderr)
                for alias in to_unload:
                    self._unload_ollama_model(old_ollama_names.get(alias, alias))
            threading.Thread(target=_refresh, daemon=True, name="warmup-refresh").start()

    def _ensure_ollama(self) -> None:
        """Start Ollama server if ollama.local is configured and not yet running."""
        provider = self.config.llm.providers.get("ollama.local")
        if provider is None:
            return
        from outheis.core.ollama_server import get_server
        server = get_server()
        if server.is_responsive():
            print("[ollama] server already running", file=sys.stderr)
            return
        print("[ollama] starting server...", file=sys.stderr)
        ready = server.ensure_running(env_vars=provider.env_vars or {})
        if ready:
            print("[ollama] server ready", file=sys.stderr)
        else:
            print("[ollama] server failed to start — local models unavailable", file=sys.stderr)

    def _run_archive_rotation(self) -> None:
        """Rotate old messages to archive."""
        # TODO: Implement archive rotation
        pass

    def _run_data_migrate(self) -> None:
        """Scan and apply schema migrations for messages and insights."""
        from outheis.core.config import get_insights_path, get_messages_path
        from outheis.core.schema import INSIGHTS_VERSION, MESSAGES_VERSION, scan_file
        import sys
        files = [
            (get_messages_path(), "Message", MESSAGES_VERSION),
            (get_insights_path(), "Insight", INSIGHTS_VERSION),
        ]
        total = 0
        for path, record_type, version in files:
            if not path.exists():
                continue
            report = scan_file(str(path), record_type, version)
            total += report.outdated
        if total:
            print(f"[data_migrate] {total} outdated records found — migrated on next read", file=sys.stderr)
        else:
            print("[data_migrate] all records up to date", file=sys.stderr)

    def _run_shadow_scan(self) -> None:
        """
        Nightly shadow scan: Data agent scans vault for chronological entries.
        
        Detects dates, deadlines, birthdays, appointments across all vault files.
        Writes to Agenda/Shadow.md — appends new entries, doesn't overwrite.
        """
        agent = self.get_agent("data")
        if agent and hasattr(agent, 'scan_chronological_entries'):
            try:
                count = agent.scan_chronological_entries()
                if count:
                    print(f"Shadow scan: processed {count} file(s)")
                else:
                    print("Shadow scan: no changes detected")
            except Exception as e:
                print(f"Shadow scan failed: {e}")

    def _run_agenda_review(self, force: bool | None = None) -> None:
        """
        Review of Agenda files at configured times.

        - force=True: skip hash check, always run (manual trigger or first/last scheduled run)
        - force=False: hash-based skip for intermediate scheduled runs
        - force=None (default): compute from schedule (first/last hour → True, else False)
        """
        if force is None:
            time = self.config.schedule.agenda_review.time
            hours = [int(t.split(":")[0]) for t in time if ":" in t]
            hour = datetime.now().hour
            force = bool(hours) and (hour == hours[0] or hour == hours[-1])
        
        agent = self.get_agent("agenda")
        if agent and hasattr(agent, 'run_review'):
            try:
                agent.run_review(force=force)
            except Exception as e:
                print(f"Agenda review failed: {e}")

    def _run_backlog_generate(self) -> None:
        """Generate Backlog.md — sorted view of all open Shadow.md items, on demand only."""
        agent = self.get_agent("agenda")
        if agent and hasattr(agent, "generate_backlog"):
            try:
                result = agent.generate_backlog()
                print(f"[backlog_generate] {result}")
            except Exception as e:
                print(f"[backlog_generate] failed: {e}")

    def _run_agenda_midnight(self) -> None:
        """Mandatory midnight refresh — flips Agenda.md to the new day unconditionally."""
        agent = self.get_agent("agenda")
        if agent and hasattr(agent, 'run_review'):
            try:
                agent.run_review(force=True)
            except Exception as e:
                print(f"[agenda_midnight] failed: {e}")

    def _run_memory_migrate_task(self) -> None:
        """Trigger memory migration from vault/Migration/ — callable from WebUI 'Run now'.

        Uses the pattern agent regardless of its enabled flag — migration (Phase A) does
        not require LLM and should always be available.
        """
        agent = self.get_agent("pattern")
        if agent is None:
            # Pattern agent disabled — instantiate directly for migration only
            agent = create_pattern_agent(model_alias="capable")
        if hasattr(agent, 'run_migration'):
            try:
                result = agent.run_migration()
                print(f"[memory_migrate] {result}")
            except Exception as e:
                print(f"[memory_migrate] failed: {e}")

    def _run_code_review(self) -> None:
        """Ask code agent to review codebase and write proposals to Codebase/Exchange.md."""
        agent = self.get_agent("code")
        if agent and hasattr(agent, 'handle_direct'):
            try:
                result = agent.handle_direct(
                    "Review the outheis codebase. Look for issues, improvement opportunities, "
                    "or missing functionality worth discussing. Write any findings as proposals "
                    "to vault/Codebase/Exchange.md using the write_codebase and append_codebase tools. "
                    "If there is nothing significant to report, write a brief status entry to Exchange.md."
                )
                print(f"[code_review] {result[:200] if result else 'done'}")
            except Exception as e:
                print(f"[code_review] failed: {e}")

    def _run_tag_scan(self) -> None:
        """Scan vault for #tags and update cache."""
        import re
        import json
        from datetime import datetime
        from outheis.core.config import load_config

        from outheis.core.config import get_human_dir
        config = load_config()
        vault = config.human.primary_vault()
        cache_path = get_human_dir() / "cache" / "tags.json"
        tag_re = re.compile(r"(?<!\w)#([a-zA-Z\u00c0-\u017e][a-zA-Z\u00c0-\u017e0-9_-]*)")

        counts: dict[str, int] = {}
        locations: dict[str, list[str]] = {}

        for md_file in sorted(vault.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            rel = str(md_file.relative_to(vault))
            found = set(tag_re.findall(text))
            for tag in found:
                full = f"#{tag}"
                counts[full] = counts.get(full, 0) + text.count(full)
                locations.setdefault(full, []).append(rel)

        tags = [
            {"name": t, "count": counts[t], "files": locations[t]}
            for t in sorted(counts, key=lambda x: -counts[x])
        ]
        result = {"tags": tags, "scanned_at": datetime.now().isoformat(timespec="seconds")}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"[tag_scan] {len(tags)} distinct tags found in {vault}")

    def _run_action_tasks(self) -> None:
        """Run due action tasks."""
        from outheis.agents.tasks import get_registry
        
        registry = get_registry()
        due_tasks = registry.get_due_tasks()
        
        if not due_tasks:
            return
        
        for task in due_tasks:
            try:
                result = task.execute()
                registry.mark_completed(task, result)
                
                if result.success and task.target_agent == "agenda":
                    # Send to agenda agent
                    self._insert_to_agenda(task.format_for_agenda(result))
                
                print(f"Task '{task.name}' executed: {'✓' if result.success else '✗'}")
            except Exception as e:
                print(f"Task '{task.name}' failed: {e}")

    def _insert_to_agenda(self, content: str) -> None:
        """Insert content into Agenda.md."""
        agenda_agent = self.get_agent("agenda")
        if agenda_agent and hasattr(agenda_agent, 'insert_to_daily'):
            agenda_agent.insert_to_daily(content)

    def get_agent(self, name: str):
        """Get or create an agent instance."""
        if name not in self._agents:
            # Get agent-specific config
            agent_config = self.config.agents.get(name)
            model_alias = agent_config.model if agent_config else "capable"
            
            # Check if agent is enabled
            if agent_config and not agent_config.enabled:
                return None
            
            if name == "relay":
                relay = create_relay_agent(model_alias=model_alias)
                relay._dispatcher = self
                self._agents[name] = relay
            elif name == "data":
                self._agents[name] = create_data_agent(model_alias=model_alias)
            elif name == "agenda":
                agenda = create_agenda_agent(model_alias=model_alias)
                agenda._dispatcher = self
                self._agents[name] = agenda
            elif name == "action":
                self._agents[name] = create_action_agent(model_alias=model_alias)
            elif name == "pattern":
                self._agents[name] = create_pattern_agent(model_alias=model_alias)
            elif name == "code":
                self._agents[name] = create_code_agent(model_alias=model_alias)
            else:
                return None
        return self._agents[name]

    def dispatch_sync(
        self,
        to: str,
        query: str,
        conversation_id: str,
        from_agent: str = "relay",
    ) -> str:
        """
        Synchronous inter-agent dispatch with full queue logging.

        Logs request and response to messages.jsonl so rumi can learn
        from inter-agent communication. Execution is in-process (fast).

        Used by relay to delegate to data, agenda, action, alan.
        """
        from outheis.core.message import create_agent_message, generate_id

        # Log request
        request_msg = create_agent_message(
            from_agent=from_agent,
            to=to,
            type="request",
            payload={"text": query},
            conversation_id=conversation_id,
            intent="internal",
        )
        append(self.queue_path, request_msg)

        # Execute synchronously using long-lived agent instance
        agent = self.get_agent(to)
        if agent is None:
            result = f"Agent '{to}' not available."
        else:
            try:
                result = agent.handle_direct(query)
            except Exception as e:
                from outheis.core.llm import BillingError
                if isinstance(e, BillingError):
                    self._enter_fallback_mode(str(e), conversation_id)
                    # Retry once with fallback model now active
                    try:
                        self._agents.pop(to, None)
                        agent = self.get_agent(to)
                        result = agent.handle_direct(query) if agent else f"Agent '{to}' not available."
                    except Exception as e2:
                        result = f"Agent '{to}' error after fallback: {e2}"
                else:
                    result = f"Agent '{to}' error: {e}"

        # Log response
        response_msg = create_agent_message(
            from_agent=to,
            to=from_agent,
            type="response",
            payload={"text": result},
            conversation_id=conversation_id,
            reply_to=request_msg.id,
            intent="internal",
        )
        append(self.queue_path, response_msg)

        return result

    def process_message(self, msg: Message) -> bool:
        """Process a single message. Returns True if dispatched, False if skipped."""
        # Skip messages not addressed to dispatcher
        if msg.to != "dispatcher":
            return False

        # Handle internal task triggers (e.g. from WebUI "Run now")
        if msg.intent == "internal":
            text = msg.payload.get("text", "")
            if text.startswith("run_task:"):
                task_name = text[len("run_task:"):]
                task_map = {
                    "pattern_infer": self._run_pattern_agent,
                    "pattern_nightly": self._run_pattern_agent,  # migration alias
                    "backlog_generate": self._run_backlog_generate,
                    "index_rebuild": self._run_index_rebuild,
                    "shadow_scan": self._run_shadow_scan,
                    "archive_rotation": self._run_archive_rotation,
                    "agenda_review": lambda: self._run_agenda_review(force=True),
                    "agenda_midnight": self._run_agenda_midnight,
                    "tag_scan": self._run_tag_scan,
                    "data_migrate": self._run_data_migrate,
                    "memory_migrate": self._run_memory_migrate_task,
                    "code_review": self._run_code_review,
                }
                runner = task_map.get(task_name)
                if runner:
                    print(f"[dispatcher] run_task:{task_name} triggered")
                    self._execute_task(task_name, runner, conversation_id=msg.conversation_id)
                else:
                    print(f"[dispatcher] unknown task: {task_name}")
                return True

        # Route to appropriate agent
        target = get_dispatch_target(msg)

        # Get agent and handle
        agent = self.get_agent(target)
        if agent:
            try:
                agent.handle(msg)
            except Exception as e:
                from outheis.core.llm import BillingError
                if isinstance(e, BillingError):
                    self._enter_fallback_mode(str(e), msg.conversation_id)
                    # Retry with fallback model
                    try:
                        self._agents.pop(target, None)
                        agent = self.get_agent(target)
                        if agent:
                            agent.handle(msg)
                    except Exception as e2:
                        self._handle_agent_error(msg, target, e2)
                else:
                    self._handle_agent_error(msg, target, e)
        return True

    def _handle_agent_error(self, msg: Message, agent: str, error: Exception) -> None:
        """Handle agent processing error."""
        from outheis.core.message import create_agent_message

        error_msg = create_agent_message(
            from_agent="relay",
            to="transport",
            type="response",
            payload={
                "text": f"Error processing request: {error}",
                "error": True,
            },
            conversation_id=msg.conversation_id,
            reply_to=msg.id,
        )
        append(self.queue_path, error_msg)

    def process_pending(self) -> int:
        """Process all pending messages. Returns count of dispatched messages."""
        count = 0
        for msg in read_from(self.queue_path, after_id=self.last_processed_id):
            if self.process_message(msg):
                count += 1
            self.last_processed_id = msg.id
        return count

    def run(self) -> None:
        """Run the dispatcher daemon."""
        from outheis.core.queue import recover_pending
        from outheis.core.llm import init_llm
        from outheis.dispatcher.lock import LockManager

        init_directories()
        write_pid()
        self.running = True

        # Clear stale task lockfiles from previous run
        from outheis.core.config import get_human_dir
        lock_dir = get_human_dir() / "cache" / "locks"
        if lock_dir.exists():
            for f in lock_dir.glob("*.lock"):
                f.unlink(missing_ok=True)
        
        # Initialize LLM with config (once, at startup)
        init_llm(self.config.llm)

        # Ensure Ollama server is running (if ollama.local provider is configured)
        self._ensure_ollama()

        # Warmup persistent local models
        self._warmup_persistent_models()

        # Set up scheduled tasks
        self._setup_scheduled_tasks()

        print(f"Dispatcher started (PID {os.getpid()})")
        print(f"Watching: {self.queue_path}")
        print(f"Scheduled tasks: {[t.name for t in self.scheduler.tasks]}")

        # Startup billing check — detect exhausted credits before first user message
        self._check_billing_at_startup()

        # Recover any pending messages from crashed processes
        recovered = recover_pending(self.queue_path)
        if recovered:
            print(f"Recovered {recovered} pending message(s)")

        # Snapshot last processed ID now so the watcher doesn't re-process old messages.
        # Unanswered backlog is handled in a background thread after transports are up.
        self.last_processed_id = get_last_id(self.queue_path)
        unanswered = get_unanswered_requests(self.queue_path)

        # Start lock manager
        lock_manager = LockManager()
        lock_manager.start()
        print(f"Lock manager listening on: {lock_manager.socket_path}")

        # Start Web UI first — must be reachable before slow transports initialize
        if self.config.webui.enabled:
            try:
                import socket as _socket
                import uvicorn
                from outheis.webui.server import app as webui_app

                # Check if port is already in use before starting
                _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                _s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                try:
                    _bind_host = "127.0.0.1" if self.config.webui.host == "0.0.0.0" else self.config.webui.host
                    _s.bind((_bind_host, self.config.webui.port))
                    _s.close()
                except OSError:
                    _s.close()
                    print(
                        f"[webui] Port {self.config.webui.port} is already in use — "
                        f"run 'lsof -i :{self.config.webui.port}' to find what is using it."
                    )
                    raise RuntimeError(f"port {self.config.webui.port} already in use")

                # Safety: never expose on all interfaces unless explicitly configured.
                # Empty or unset host defaults to loopback — never to 0.0.0.0.
                _host = self.config.webui.host or "127.0.0.1"
                if _host in ("", "localhost"):
                    _host = "127.0.0.1"

                # uvicorn.run() in a non-main thread tries to install signal handlers
                # and raises ValueError. Use Config+Server instead, which skips that.
                webui_config = uvicorn.Config(
                    webui_app,
                    host=_host,
                    port=self.config.webui.port,
                    log_level="info",
                )
                webui_server = uvicorn.Server(webui_config)
                webui_server.install_signal_handlers = lambda: None  # disable — main thread owns signals

                webui_thread = threading.Thread(
                    target=webui_server.run,
                    daemon=True,
                    name="webui",
                )
                webui_thread.start()
                print(f"Web UI started at http://{self.config.webui.host}:{self.config.webui.port}")
            except Exception as e:
                print(f"Web UI failed to start: {e}")

        # Start Signal transport if enabled (Whisper model loads inside run() thread)
        signal_transport = None
        if self.config.signal.enabled:
            try:
                from outheis.transport.signal import SignalTransport
                signal_transport = SignalTransport(self.config)
                self._signal_transport = signal_transport
                self._signal_thread = threading.Thread(
                    target=signal_transport.run,
                    daemon=True,
                    name="signal-transport",
                )
                self._signal_thread.start()
                print("Signal transport started")
            except Exception as e:
                print(f"Signal transport failed to start: {e}")

        # Process unanswered backlog in background — transports are now up
        # Skip internal messages (run_task:* fire-and-forget) — replaying them
        # would re-trigger tasks that were intentionally started by the user.
        unanswered_user = [m for m in unanswered if getattr(m, "intent", None) != "internal"]
        if unanswered_user:
            print(f"Processing {len(unanswered_user)} unanswered request(s) in background...")
            def _process_backlog(msgs):
                for msg in msgs:
                    try:
                        self.process_message(msg)
                    except Exception as e:
                        print(f"[backlog] skipping message {msg.id}: {e}", flush=True)
            threading.Thread(
                target=_process_backlog,
                args=(unanswered_user,),
                daemon=True,
                name="backlog",
            ).start()

        # Set up file watcher
        watcher = QueueWatcher(
            queue_path=self.queue_path,
            on_message=self._on_queue_change,
        )
        watcher.start()

        # Monitor config.json for live changes (model assignments, agent settings)
        from outheis.core.config import get_config_path
        config_watcher = ConfigWatcher(
            config_path=get_config_path(),
            on_change=self._on_config_changed,
        )
        config_watcher.start()

        try:
            while self.running:
                # Calculate timeout until next scheduled task
                timeout = min(self.scheduler.seconds_until_next(), 60.0)
                
                # Wait for wakeup signal or timeout
                ready, _, _ = select.select([self._wakeup_read], [], [], timeout)
                
                if ready:
                    # Drain wakeup pipe
                    try:
                        os.read(self._wakeup_read, 1024)
                    except OSError:
                        pass
                
                # Run any due scheduled tasks
                for task in self.scheduler.get_due():
                    started = self._execute_task(task.name, task.run)
                    if started:
                        print(f"[dispatcher] scheduled: {task.name}")
                    
        finally:
            watcher.stop()
            lock_manager.stop()

            # Stop Ollama if we started it
            from outheis.core.ollama_server import get_server
            ollama = get_server()
            if ollama.owns_process():
                print("[ollama] stopping server", file=sys.stderr)
                ollama.stop()

            # Close wakeup pipe
            if self._wakeup_read:
                os.close(self._wakeup_read)
            if self._wakeup_write:
                os.close(self._wakeup_write)

            remove_pid()
            print("Dispatcher stopped")

    def _on_queue_change(self) -> None:
        """Called when queue file changes."""
        self.process_pending()


# =============================================================================
# DAEMON CONTROL
# =============================================================================

def start_daemon(foreground: bool = False) -> bool:
    """
    Start the dispatcher daemon.

    Args:
        foreground: If True, run in foreground (blocking).
                   If False, fork to background.

    Returns:
        True if started successfully.
    """
    # Check if already running
    existing_pid = read_pid()
    if existing_pid:
        print(f"Dispatcher already running (PID {existing_pid})")
        return False

    # Load config
    config = load_config()

    GREEN = "\033[32m"
    RED   = "\033[31m"
    RESET = "\033[0m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"

    GRAY = "\033[38;5;250m"
    print(f"\n{GRAY}𝐎{RESET}{BOLD}  οὐθείς{RESET}")  # noqa: i18n — brand name in Greek
    print(f"{DIM}outheis — nobody who refuses to be captured.{RESET}")
    print("─" * 50)

    # Validate paths
    path_errors = _validate_paths(config)
    if path_errors:
        for err in path_errors:
            print(f"  {RED}✗{RESET} {err}")
        print("\nDispatcher cannot start. Fix configuration and try again.")
        return False
    print(f"  {GREEN}✓{RESET} Paths valid")

    # Validate API keys BEFORE forking
    errors = _validate_api_keys(config)
    if errors:
        for err in errors:
            print(f"  {RED}✗{RESET} {err}")
        print("\nDispatcher cannot start. Fix configuration and try again.")
        return False
    print(f"  {GREEN}✓{RESET} API keys valid")

    if foreground:
        # Run in foreground
        dispatcher = Dispatcher(config=config)
        dispatcher.run()
        return True
    else:
        # Start as subprocess (avoids macOS fork issues with CoreFoundation)
        import subprocess
        import shutil
        
        # Find outheis command
        outheis_cmd = shutil.which("outheis")
        
        # Build command
        if outheis_cmd:
            cmd = [outheis_cmd, "start", "-f"]
        else:
            # Fallback: use python -m
            cmd = [sys.executable, "-m", "outheis.cli.main", "start", "-f"]
        
        # Copy environment, including any overrides
        env = os.environ.copy()
        
        # Log file for daemon output
        from outheis.core.config import get_human_dir
        log_path = get_human_dir() / "dispatcher.log"
        
        # Start detached subprocess
        with open(log_path, 'a') as log_file, open(os.devnull, 'r') as devnull:
            process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                stdin=devnull,
                start_new_session=True,
                env=env,
            )
        
        # Wait for PID file with retries
        child_pid = None
        for _ in range(10):  # Up to 5 seconds
            time.sleep(0.5)
            child_pid = read_pid()
            if child_pid:
                break
        
        if child_pid:
            print(f"  {GREEN}✓{RESET} Dispatcher started (PID {child_pid})")
            print(f"  {GREEN}✓{RESET} Log: {log_path}")
            if config.webui.enabled:
                import socket as _socket
                host = "127.0.0.1"
                port = config.webui.port
                webui_ready = False
                for _ in range(40):  # up to 20s
                    time.sleep(0.5)
                    try:
                        with _socket.create_connection((host, port), timeout=0.5):
                            webui_ready = True
                            break
                    except OSError:
                        pass
                if webui_ready:
                    print(f"  {GREEN}✓{RESET} Web UI: http://{host}:{port}")
                else:
                    print(f"  {GREEN}✓{RESET} Web UI: http://{host}:{port} (still starting — retry in a moment)")
            if config.signal.enabled:
                print(f"  {GREEN}✓{RESET} Signal transport enabled (bot: {config.signal.bot_phone})")
                try:
                    from faster_whisper import WhisperModel  # noqa: F401
                    print(f"  {GREEN}✓{RESET} Whisper transcription available")
                except ImportError:
                    print(f"  {GREEN}✓{RESET} Signal transport (no Whisper — install faster-whisper for voice)")
            return True
        else:
            print(f"  {RED}✗{RESET} Failed to start dispatcher. Check log: {log_path}")
            return False


def _validate_paths(config: Config) -> list[str]:
    """
    Validate vault and agenda paths.
    Creates Agenda directory and files if missing.
    
    Returns list of errors for enabled agents that require paths.
    """
    errors = []
    
    # Check vault paths if data agent is enabled
    data_config = config.agents.get("data")
    if data_config and data_config.enabled:
        vaults = config.human.all_vaults()
        if not vaults:
            errors.append("Data agent enabled but no vault configured")
        else:
            missing_vaults = [v for v in vaults if not v.exists()]
            if len(missing_vaults) == len(vaults):
                # All vaults missing
                errors.append(f"Data agent enabled but vault not found: {vaults[0]}")
    
    # Check/create Agenda directory if agenda agent is enabled
    agenda_config = config.agents.get("agenda")
    if agenda_config and agenda_config.enabled:
        primary_vault = config.human.primary_vault()
        
        if not primary_vault.exists():
            errors.append(f"Agenda agent enabled but vault not found: {primary_vault}")
        else:
            agenda_dir = primary_vault / "Agenda"
            
            # Create Agenda directory if missing
            if not agenda_dir.exists():
                print(f"  ⚠ Agenda directory not found, creating: {agenda_dir}")
                agenda_dir.mkdir(parents=True, exist_ok=True)
            
            # Create required files if missing
            from datetime import datetime
            today = datetime.now().strftime("%A, %d %B %Y")
            
            agenda_files = {
                "Agenda.md": f"""# {today}

## 🧘 Daily

## 🔴 Today

## 🟠 This Week

## Notes

""",
                "Exchange.md": """# Exchange

*Asynchronous communication between you and outheis.*
*No pressure to respond — answer when it fits.*

---

""",
            }
            
            for filename, default_content in agenda_files.items():
                filepath = agenda_dir / filename
                if not filepath.exists():
                    print(f"  ⚠ Creating: {filepath}")
                    filepath.write_text(default_content, encoding="utf-8")
    
    return errors


def _validate_api_keys(config: Config) -> list[str]:
    """
    Validate API keys for configured providers.
    
    Returns list of errors, empty if all valid.
    """
    import os as _os
    errors = []
    
    # Collect which providers are actually used
    used_providers = set()
    for agent_cfg in config.agents.values():
        if agent_cfg.enabled:
            model_cfg = config.llm.get_model(agent_cfg.model)
            used_providers.add(model_cfg.provider)
    
    # Validate each used provider
    for provider_name in used_providers:
        provider_cfg = config.llm.get_provider(provider_name)
        
        if provider_name == "anthropic":
            # Check config first, then environment
            api_key = provider_cfg.api_key or _os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                errors.append("Anthropic API key not set (config or ANTHROPIC_API_KEY)")
            elif not api_key.startswith("sk-ant-"):
                errors.append("Anthropic API key has invalid format")
            else:
                # Quick validation: try a minimal API call
                try:
                    import anthropic
                    client = anthropic.Anthropic(api_key=api_key)
                    capable_model = config.llm.get_model("capable").name
                    client.messages.create(
                        model=capable_model,
                        max_tokens=1,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                except anthropic.AuthenticationError:
                    errors.append("Anthropic API key is invalid")
                except anthropic.APIError as e:
                    # Rate limit or other API error is OK - key is valid
                    if "authentication" in str(e).lower():
                        errors.append(f"Anthropic API key error: {e}")
                except Exception as e:
                    errors.append(f"API key validation failed: {e}")
        
        elif provider_name == "ollama.local":
            # Check if local Ollama is reachable
            base_url = provider_cfg.base_url or "http://localhost:11434"
            try:
                import urllib.request
                urllib.request.urlopen(f"{base_url}/api/tags", timeout=2)
            except Exception:
                errors.append(f"Ollama not reachable at {base_url}")
        
        elif provider_name == "openai":
            api_key = provider_cfg.api_key or _os.environ.get("OPENAI_API_KEY")
            if not api_key:
                errors.append("OpenAI API key not set (config or OPENAI_API_KEY)")
    
    return errors


def stop_daemon() -> bool:
    """
    Stop the dispatcher daemon.

    Returns:
        True if stopped successfully.
    """
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    RESET = "\033[0m"

    GRAY = "\033[38;5;250m"
    print(f"\n{GRAY}𝐎{RESET}{BOLD}  οὐθείς{RESET}")  # noqa: i18n — brand name in Greek
    print(f"{DIM}outheis — nobody who refuses to be captured.{RESET}")
    print("─" * 50)

    pid = read_pid()
    if not pid:
        print("Dispatcher not running")
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for process to exit
        for _ in range(50):  # 5 seconds max
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                # Process exited
                remove_pid()
                print("Dispatcher stopped")
                return True

        # Force kill
        os.kill(pid, signal.SIGKILL)
        remove_pid()
        print("Dispatcher killed")
        return True
    except OSError as e:
        print(f"Error stopping dispatcher: {e}")
        remove_pid()
        return False


def daemon_status() -> dict:
    """
    Get daemon status.

    Returns:
        Dict with status information.
    """
    pid = read_pid()
    return {
        "running": pid is not None,
        "pid": pid,
    }
