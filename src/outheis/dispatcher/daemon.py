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
            # Already ran this slot today?
            if self.last_run is not None and self.last_run.date() == now.date() and self.last_run.hour == h:
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
        if sched.data_migrate.enabled:
            self.scheduler.add("data_migrate", self._run_data_migrate, time=sched.data_migrate.time)
        if sched.action_tasks.enabled:
            self.scheduler.add("action_tasks", self._run_action_tasks, interval_minutes=15)
        if sched.agenda_review.enabled:
            self.scheduler.add("agenda_review", self._run_agenda_review, time=sched.agenda_review.time)

    def _execute_task(
        self,
        task_name: str,
        runner: "Callable[[], None]",
        conversation_id: str | None = None,
    ) -> bool:
        """
        Execute a task in a background thread if not already running.

        Returns True if started, False if skipped (already running).
        Writes started/completed/failed events when conversation_id is given (WebUI-triggered runs).
        """
        with self._task_lock:
            if task_name in self._running_tasks:
                print(f"[dispatcher] run_task:{task_name} skipped (already running)")
                if conversation_id:
                    self._write_task_event(task_name, "skipped: already running", conversation_id)
                return False
            self._running_tasks.add(task_name)

        def _run() -> None:
            try:
                if conversation_id:
                    self._write_task_event(task_name, "started", conversation_id)
                runner()
                if conversation_id:
                    self._write_task_event(task_name, "completed", conversation_id)
            except Exception as e:
                print(f"[dispatcher] run_task:{task_name} failed: {e}")
                if conversation_id:
                    self._write_task_event(task_name, f"failed: {e}", conversation_id)
            finally:
                with self._task_lock:
                    self._running_tasks.discard(task_name)

        t = threading.Thread(target=_run, daemon=True, name=f"task-{task_name}")
        t.start()
        return True

    def _write_task_event(self, task_name: str, status: str, conversation_id: str) -> None:
        """Write a task lifecycle event to the message queue (for WebUI tracking)."""
        from outheis.core.message import create_agent_message
        msg = create_agent_message(
            from_agent="scheduler",
            to="webui",
            type="event",
            payload={"task": task_name, "status": status},
            conversation_id=conversation_id,
        )
        append(self.queue_path, msg)

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

    def _warmup_persistent_models(self) -> None:
        """Send a minimal call to each persistent local model to load it into memory."""
        import sys
        for alias, model_cfg in self.config.llm.models.items():
            if model_cfg.provider == "ollama" and model_cfg.run_mode == "persistent":
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
                    print(f"  \033[31m✗\033[0m {alias} warmup failed: {e}", file=sys.stderr)

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

    def _run_agenda_review(self) -> None:
        """
        Review of Agenda files at configured times.

        - First and last scheduled run of the day: force=True
        - All other runs: force=False (hash-based skip)
        """
        time = self.config.schedule.agenda_review.time
        hours = [int(t.split(":")[0]) for t in time if ":" in t]
        hour = datetime.now().hour
        force = bool(hours) and (hour == hours[0] or hour == hours[-1])
        
        agent = self.get_agent("agenda")
        if agent and hasattr(agent, 'run_hourly_review'):
            try:
                agent.run_hourly_review(force=force)
            except Exception as e:
                print(f"Agenda review failed: {e}")

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
        """Insert content into Daily.md."""
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
                self._agents[name] = create_agenda_agent(model_alias=model_alias)
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

    def process_message(self, msg: Message) -> None:
        """Process a single message."""
        # Skip messages not addressed to dispatcher
        if msg.to != "dispatcher":
            return

        # Handle internal task triggers (e.g. from WebUI "Run now")
        if msg.intent == "internal":
            text = msg.payload.get("text", "")
            if text.startswith("run_task:"):
                task_name = text[len("run_task:"):]
                task_map = {
                    "pattern_infer": self._run_pattern_agent,
                    "pattern_nightly": self._run_pattern_agent,  # migration alias
                    "index_rebuild": self._run_index_rebuild,
                    "shadow_scan": self._run_shadow_scan,
                    "archive_rotation": self._run_archive_rotation,
                    "agenda_review": self._run_agenda_review,
                    "tag_scan": self._run_tag_scan,
                    "data_migrate": self._run_data_migrate,
                }
                runner = task_map.get(task_name)
                if runner:
                    print(f"[dispatcher] run_task:{task_name} triggered")
                    self._execute_task(task_name, runner, conversation_id=msg.conversation_id)
                else:
                    print(f"[dispatcher] unknown task: {task_name}")
                return

        # Route to appropriate agent
        target = get_dispatch_target(msg)

        # Get agent and handle
        agent = self.get_agent(target)
        if agent:
            try:
                agent.handle(msg)
            except Exception as e:
                # Log error, send error response
                self._handle_agent_error(msg, target, e)

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
        """Process all pending messages. Returns count processed."""
        count = 0
        for msg in read_from(self.queue_path, after_id=self.last_processed_id):
            self.process_message(msg)
            self.last_processed_id = msg.id
            count += 1
        return count

    def run(self) -> None:
        """Run the dispatcher daemon."""
        from outheis.core.queue import recover_pending
        from outheis.core.llm import init_llm
        from outheis.dispatcher.lock import LockManager

        init_directories()
        write_pid()
        self.running = True
        
        # Initialize LLM with config (once, at startup)
        init_llm(self.config.llm)

        # Warmup persistent local models
        self._warmup_persistent_models()

        # Set up scheduled tasks
        self._setup_scheduled_tasks()

        print(f"Dispatcher started (PID {os.getpid()})")
        print(f"Watching: {self.queue_path}")
        print(f"Scheduled tasks: {[t.name for t in self.scheduler.tasks]}")

        # Recover any pending messages from crashed processes
        recovered = recover_pending(self.queue_path)
        if recovered:
            print(f"Recovered {recovered} pending message(s)")

        # Process any unanswered requests (crashed before response)
        unanswered = get_unanswered_requests(self.queue_path)
        if unanswered:
            print(f"Processing {len(unanswered)} unanswered request(s)...")
            for msg in unanswered:
                self.process_message(msg)

        # Start from last message for new ones
        self.last_processed_id = get_last_id(self.queue_path)

        # Start lock manager
        lock_manager = LockManager()
        lock_manager.start()
        print(f"Lock manager listening on: {lock_manager.socket_path}")

        # Start Signal transport if enabled
        signal_transport = None
        if self.config.signal.enabled:
            try:
                from outheis.transport.signal import SignalTransport
                signal_transport = SignalTransport(self.config)
                self._signal_thread = threading.Thread(
                    target=signal_transport.run,
                    daemon=True,
                    name="signal-transport",
                )
                self._signal_thread.start()
                print("Signal transport started")
            except Exception as e:
                print(f"Signal transport failed to start: {e}")

        # Start Web UI if enabled
        if self.config.webui.enabled:
            try:
                import uvicorn
                from outheis.webui.server import app as webui_app

                # uvicorn.run() in a non-main thread tries to install signal handlers
                # and raises ValueError. Use Config+Server instead, which skips that.
                webui_config = uvicorn.Config(
                    webui_app,
                    host=self.config.webui.host,
                    port=self.config.webui.port,
                    log_level="error",
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

        # Set up file watcher
        watcher = QueueWatcher(
            queue_path=self.queue_path,
            on_message=self._on_queue_change,
        )
        watcher.start()

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
    print(f"\n{GRAY}𝐎{RESET}{BOLD}  οὐθείς{RESET}")
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
                print(f"  {GREEN}✓{RESET} Web UI: http://{config.webui.host}:{config.webui.port}")
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
                "Daily.md": f"""# {today}

## 🧘 Daily

## 🔴 Today

## 🟠 This Week

## Notes

""",
                "Inbox.md": """# Inbox

*Quick capture — items are processed hourly.*

---

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
        
        elif provider_name == "ollama":
            # Ollama doesn't need API key, just check if reachable
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
    print(f"\n{GRAY}𝐎{RESET}{BOLD}  οὐθείς{RESET}")
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
