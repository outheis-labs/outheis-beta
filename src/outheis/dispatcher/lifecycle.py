"""
Agent lifecycle management.

Handles spawning, notification, and shutdown of agents.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from outheis.core.config import AgentConfig

# =============================================================================
# AGENT PROCESS
# =============================================================================

@dataclass
class AgentProcess:
    """Represents a running agent."""
    name: str
    config: AgentConfig
    process: subprocess.Popen | None = None

    @property
    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None


# =============================================================================
# LIFECYCLE MANAGER
# =============================================================================

@dataclass
class LifecycleManager:
    """
    Manages agent processes.

    For MVP, agents run in-process. For production,
    they would be separate processes or containers.
    """
    agents: dict[str, AgentProcess] = field(default_factory=dict)

    def register(self, name: str, config: AgentConfig) -> None:
        """Register an agent configuration."""
        self.agents[name] = AgentProcess(name=name, config=config)

    def spawn(self, name: str) -> bool:
        """
        Spawn an agent process.

        For MVP: agents are loaded as modules, not processes.
        """
        if name not in self.agents:
            return False

        agent = self.agents[name]

        if agent.config.run_mode == "daemon":
            # Daemon agents run continuously
            # For MVP, this is a no-op (in-process)
            pass
        elif agent.config.run_mode == "on-demand":
            # On-demand agents are invoked per request
            # For MVP, this is a no-op (direct function call)
            pass
        elif agent.config.run_mode == "scheduled":
            # Scheduled agents run at specific times
            # Handled by scheduler, not lifecycle
            pass

        return True

    def notify(self, name: str, message_id: str) -> bool:
        """
        Notify an agent of a new message.

        For MVP: direct function call.
        For production: IPC or message passing.
        """
        if name not in self.agents:
            return False

        # MVP: notification is synchronous
        # The dispatcher calls the agent directly
        return True

    def shutdown(self, name: str) -> bool:
        """Shutdown an agent."""
        if name not in self.agents:
            return False

        agent = self.agents[name]

        if agent.process and agent.is_running:
            agent.process.terminate()
            agent.process.wait(timeout=5.0)

        return True

    def shutdown_all(self) -> None:
        """Shutdown all agents."""
        for name in list(self.agents.keys()):
            self.shutdown(name)
