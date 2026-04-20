"""
Task registry — stores and manages scheduled tasks.

Tasks are stored in directories:
    ~/.outheis/human/tasks/<task-id>/
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from outheis.agents.tasks.base import Task


def get_tasks_dir() -> Path:
    """Get the tasks directory."""
    from outheis.core.config import get_human_dir
    return get_human_dir() / "tasks"


@dataclass
class TaskRegistry:
    """
    Registry for scheduled tasks.

    Tasks are stored in ~/.outheis/human/tasks/<task-id>/
    """

    tasks: dict[str, Task] = field(default_factory=dict)

    def add(self, task: Task) -> None:
        """Add a task to the registry."""
        self.tasks[task.id] = task
        self._calculate_next_run(task)
        task.save()

    def remove(self, task_id: str) -> bool:
        """Remove a task from the registry."""
        import shutil

        if task_id in self.tasks:
            del self.tasks[task_id]
            # Remove task directory
            task_dir = get_tasks_dir() / task_id
            if task_dir.exists():
                shutil.rmtree(task_dir)
            return True
        return False

    def get(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    def get_due_tasks(self) -> list[Task]:
        """Get all tasks that are due to run."""
        now = datetime.now()
        due = []
        for task in self.tasks.values():
            if task.enabled and task.next_run and task.next_run <= now:
                due.append(task)
        return due

    def mark_completed(self, task: Task, result: TaskResult) -> None:  # noqa: F821
        """Mark a task as completed and calculate next run."""
        from outheis.agents.tasks.base import TaskSchedule

        task.last_run = datetime.now()
        task.run_count += 1

        # Save history and output
        task.append_history(result)
        if result.success:
            task.save_output(task.format_for_agenda(result))

        # Remove one-time tasks
        if task.schedule in (TaskSchedule.ONCE, TaskSchedule.IMMEDIATE):
            self.remove(task.id)
        else:
            self._calculate_next_run(task)
            task.save()

    def _calculate_next_run(self, task: Task) -> None:
        """Calculate the next run time for a task."""
        from outheis.agents.tasks.base import TaskSchedule

        now = datetime.now()

        if task.schedule == TaskSchedule.IMMEDIATE:
            task.next_run = now

        elif task.schedule == TaskSchedule.ONCE:
            if task.times:
                # Parse time like "14:30"
                h, m = map(int, task.times[0].split(":"))
                next_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if next_time <= now:
                    next_time += timedelta(days=1)
                task.next_run = next_time
            else:
                task.next_run = now

        elif task.schedule == TaskSchedule.DAILY:
            if task.times:
                h, m = map(int, task.times[0].split(":"))
                next_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if next_time <= now:
                    next_time += timedelta(days=1)
                task.next_run = next_time

        elif task.schedule == TaskSchedule.TWICE_DAILY:
            if len(task.times) >= 2:
                candidates = []
                for time_str in task.times[:2]:
                    h, m = map(int, time_str.split(":"))
                    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if t <= now:
                        t += timedelta(days=1)
                    candidates.append(t)
                task.next_run = min(candidates)

        elif task.schedule == TaskSchedule.HOURLY:
            task.next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    def load(self) -> None:
        """Load all tasks from disk."""
        tasks_dir = get_tasks_dir()
        if not tasks_dir.exists():
            return

        for task_dir in tasks_dir.iterdir():
            if not task_dir.is_dir():
                continue

            config_path = task_dir / "config.json"
            if not config_path.exists():
                continue

            try:
                data = json.loads(config_path.read_text())
                task = self._deserialize_task(data)
                if task:
                    self.tasks[task.id] = task
            except Exception as e:
                print(f"Warning: Failed to load task {task_dir.name}: {e}")

    def _deserialize_task(self, data: dict) -> Task | None:
        """Deserialize a task from config.json data."""
        from outheis.agents.tasks.base import TaskSchedule, TaskSource

        task_type = data.get("type")

        if task_type == "NewsHeadlinesTask":
            from outheis.agents.tasks.news import NewsHeadlinesTask

            source = None
            if data.get("source"):
                source = TaskSource.from_dict(data["source"])

            return NewsHeadlinesTask(
                id=data["id"],
                name=data["name"],
                instruction=data.get("instruction", ""),
                source=source,
                schedule=TaskSchedule(data["schedule"]),
                enabled=data.get("enabled", True),
                times=data.get("times", []),
                days=data.get("days", []),
                last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
                next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
                run_count=data.get("run_count", 0),
                target_agent=data.get("target_agent", "agenda"),
                source_url=data.get("source_url", "https://www.sz.de"),
                source_name=data.get("source_name", "SZ"),
                max_headlines=data.get("max_headlines", 5),
            )

        # Unknown task type
        return None


# Singleton registry
_registry: TaskRegistry | None = None


def get_registry() -> TaskRegistry:
    """Get the global task registry."""
    global _registry
    if _registry is None:
        _registry = TaskRegistry()
        _registry.load()
    return _registry
