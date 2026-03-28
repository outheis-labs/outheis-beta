"""
Base classes for tasks.

Each task is stored in its own directory:
    ~/.outheis/human/tasks/<task-id>/
    ├── directive.md     # Human-readable description + metadata
    ├── config.json      # Machine-readable configuration
    ├── output.md        # Last execution output
    └── history.jsonl    # Execution history
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class TaskSchedule(Enum):
    """When a task should run."""
    ONCE = "once"           # Run once, then delete
    IMMEDIATE = "immediate" # Run now, then delete
    HOURLY = "hourly"
    DAILY = "daily"         # Run once per day at specified time
    TWICE_DAILY = "twice_daily"  # Run at two specified times
    WEEKLY = "weekly"
    CUSTOM = "custom"       # Cron-like schedule


@dataclass
class TaskSource:
    """Metadata about who created the task and how."""
    timestamp: datetime
    interface: str  # "signal", "cli", "web"
    
    # Signal-specific
    name: str | None = None
    phone: str | None = None
    uuid: str | None = None
    
    # CLI/local-specific  
    user: str | None = None
    host: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "interface": self.interface,
            "name": self.name,
            "phone": self.phone,
            "uuid": self.uuid,
            "user": self.user,
            "host": self.host,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TaskSource":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            interface=data["interface"],
            name=data.get("name"),
            phone=data.get("phone"),
            uuid=data.get("uuid"),
            user=data.get("user"),
            host=data.get("host"),
        )
    
    def to_markdown(self) -> str:
        """Format source info for directive.md."""
        lines = [
            "## Source",
            "",
            f"- **Timestamp:** {self.timestamp.isoformat()}",
            f"- **Interface:** {self.interface}",
        ]
        if self.name:
            lines.append(f"- **Name:** {self.name}")
        if self.phone:
            lines.append(f"- **Phone:** {self.phone}")
        if self.uuid:
            lines.append(f"- **UUID:** {self.uuid}")
        if self.user:
            lines.append(f"- **User:** {self.user}")
        if self.host:
            lines.append(f"- **Host:** {self.host}")
        return "\n".join(lines)


@dataclass
class TaskResult:
    """Result of a task execution."""
    success: bool
    data: Any = None
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Task(ABC):
    """
    Base class for executable tasks.
    
    Tasks are created by the user (via Relay) and executed by Action Agent.
    Each task has its own directory with directive.md, config.json, etc.
    """
    
    id: str
    name: str
    schedule: TaskSchedule
    enabled: bool = True
    
    # Original instruction (human language)
    instruction: str = ""
    
    # Who created this task
    source: TaskSource | None = None
    
    # Schedule details
    times: list[str] = field(default_factory=list)  # ["08:00", "18:00"]
    days: list[int] = field(default_factory=list)   # [0, 2, 4] = Mon, Wed, Fri
    
    # Execution tracking
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    
    # Target agent for output (usually "agenda")
    target_agent: str = "agenda"
    
    @abstractmethod
    def execute(self) -> TaskResult:
        """Execute the task and return result."""
        pass
    
    @abstractmethod
    def format_for_agenda(self, result: TaskResult) -> str:
        """Format the result for insertion into Agenda."""
        pass
    
    def get_task_dir(self) -> Path:
        """Get the directory for this task."""
        from outheis.core.config import get_human_dir
        return get_human_dir() / "tasks" / self.id
    
    def save(self) -> None:
        """Save task to its directory."""
        import json
        
        task_dir = self.get_task_dir()
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # Save config.json
        config_path = task_dir / "config.json"
        config_path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        
        # Save/update directive.md
        directive_path = task_dir / "directive.md"
        directive_path.write_text(self.to_directive_md())
    
    def to_directive_md(self) -> str:
        """Generate directive.md content."""
        lines = [
            f"# {self.name}",
            "",
            "## Anweisung",
            "",
            self.instruction or "(no instruction)",
            "",
        ]
        
        if self.source:
            lines.append(self.source.to_markdown())
            lines.append("")
        
        lines.extend([
            "## Configuration",
            "",
            f"- **Schedule:** {self.schedule.value}",
            f"- **Times:** {', '.join(self.times) if self.times else 'not set'}",
            f"- **Target:** {self.target_agent}",
            f"- **Active:** {'yes' if self.enabled else 'no'}",
            "",
            "## History",
            "",
            f"- Created: {self.source.timestamp.isoformat() if self.source else 'unknown'}",
            f"- Executions: {self.run_count}",
        ])
        
        if self.last_run:
            lines.append(f"- Last run: {self.last_run.isoformat()}")
        
        return "\n".join(lines) + "\n"
    
    def append_history(self, result: TaskResult) -> None:
        """Append execution result to history.jsonl."""
        import json
        
        task_dir = self.get_task_dir()
        history_path = task_dir / "history.jsonl"
        
        entry = {
            "timestamp": result.timestamp.isoformat(),
            "success": result.success,
            "error": result.error,
        }
        
        with open(history_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def save_output(self, content: str) -> None:
        """Save last output to output.md."""
        task_dir = self.get_task_dir()
        output_path = task_dir / "output.md"
        output_path.write_text(content)
    
    def to_dict(self) -> dict:
        """Serialize task to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.__class__.__name__,
            "instruction": self.instruction,
            "source": self.source.to_dict() if self.source else None,
            "schedule": self.schedule.value,
            "enabled": self.enabled,
            "times": self.times,
            "days": self.days,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "target_agent": self.target_agent,
        }
