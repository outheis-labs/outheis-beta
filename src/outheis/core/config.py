"""
Configuration management.

User config: ~/.outheis/human/config.json

Environment overrides:
  OUTHEIS_HUMAN_DIR — override human data directory
  OUTHEIS_VAULT — override vault path
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# =============================================================================
# PATHS
# =============================================================================

def get_outheis_dir() -> Path:
    """Get outheis system directory."""
    return Path(os.path.expanduser("~/.outheis"))


def get_status_path() -> Path:
    """Path to system_status.json — used to signal degraded/fallback mode."""
    return get_human_dir() / "system_status.json"


def get_human_dir() -> Path:
    """Get user data directory. Respects OUTHEIS_HUMAN_DIR env var."""
    override = os.environ.get("OUTHEIS_HUMAN_DIR")
    if override:
        return Path(os.path.expanduser(override))
    return get_outheis_dir() / "human"


def get_config_path() -> Path:
    """Get user config path."""
    return get_human_dir() / "config.json"


def get_messages_path() -> Path:
    """Get message queue path."""
    return get_human_dir() / "messages.jsonl"


def get_insights_path() -> Path:
    """Get insights path."""
    return get_human_dir() / "insights.jsonl"


def get_session_notes_path() -> Path:
    """Get session notes path."""
    return get_human_dir() / "session_notes.jsonl"


def get_rules_dir() -> Path:
    """Get user rules directory."""
    return get_human_dir() / "rules"


def get_skills_dir() -> Path:
    """Get user skills directory."""
    return get_human_dir() / "skills"


def get_archive_dir() -> Path:
    """Get archive directory."""
    return get_human_dir() / "archive"


# =============================================================================
# CONFIG DATACLASSES
# =============================================================================

@dataclass
class HumanConfig:
    """Human (administrator) configuration."""
    name: str = "Human"
    phone: list[str] = field(default_factory=list)  # One or more phone numbers
    language: str = "en"
    timezone: str = "Europe/Berlin"
    vault: list[str] = field(default_factory=lambda: ["~/Documents/Vault"])

    def primary_vault(self) -> Path:
        """Get primary vault path. Respects OUTHEIS_VAULT env var."""
        override = os.environ.get("OUTHEIS_VAULT")
        if override:
            return Path(os.path.expanduser(override))
        if not self.vault:
            return get_human_dir() / "vault"
        return Path(os.path.expanduser(self.vault[0]))

    def all_vaults(self) -> list[Path]:
        """Get all vault paths, expanded. Respects OUTHEIS_VAULT env var."""
        override = os.environ.get("OUTHEIS_VAULT")
        if override:
            return [Path(os.path.expanduser(override))]
        return [Path(os.path.expanduser(v)) for v in self.vault]


@dataclass
class AllowedContact:
    """An allowed Signal contact."""
    name: str
    phone: str


@dataclass
class SignalConfig:
    """Signal transport configuration."""
    enabled: bool = False
    bot_phone: str | None = None
    bot_name: str = "Ou"
    allowed: list[AllowedContact] = field(default_factory=list)  # Additional allowed contacts


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    api_key: str | None = None
    base_url: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)


@dataclass
class ModelConfig:
    """Configuration for a single model alias."""
    provider: str  # "anthropic", "ollama", "openai"
    name: str  # e.g. "claude-sonnet-4-20250514", "llama3.2:3b"
    run_mode: str = "on-demand"  # "on-demand", "persistent"


@dataclass
class LLMConfig:
    """LLM providers and model aliases."""
    providers: dict[str, ProviderConfig] = field(default_factory=lambda: {
        "anthropic": ProviderConfig(),
    })
    models: dict[str, ModelConfig] = field(default_factory=lambda: {
        "fast": ModelConfig(provider="anthropic", name="claude-haiku-4-5"),
        "capable": ModelConfig(provider="anthropic", name="claude-sonnet-4-20250514"),
    })
    local_fallback: str | None = None  # Model alias to use when cloud billing fails

    def get_model(self, alias: str) -> ModelConfig:
        """Get model config for alias. Raises KeyError if not found."""
        if alias in self.models:
            return self.models[alias]
        # Allow direct model name as fallback
        return ModelConfig(provider="anthropic", name=alias)
    
    def get_provider(self, name: str) -> ProviderConfig:
        """Get provider config. Returns empty config if not found."""
        return self.providers.get(name, ProviderConfig())


@dataclass
class AgentConfig:
    """Configuration for a single agent."""
    name: str  # Display name (e.g. "ou", "zeno")
    model: str = "capable"  # Model alias
    enabled: bool = True


@dataclass
class WebuiConfig:
    """Web UI configuration."""
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass
class UpdatesConfig:
    """Memory migration and housekeeping settings."""
    auto_migrate: bool = True
    schedule: str = "04:00"


@dataclass
class ScheduledTaskConfig:
    """Configuration for a single scheduled task."""
    enabled: bool = True
    time: list[str] = field(default_factory=list)        # ["HH:MM", ...] — for time-based tasks
    interval_minutes: int | None = None                  # for interval-based tasks


@dataclass
class ScheduleConfig:
    """Scheduled tasks configuration."""
    pattern_infer: ScheduledTaskConfig = field(default_factory=lambda: ScheduledTaskConfig(
        time=["04:00"]
    ))
    index_rebuild: ScheduledTaskConfig = field(default_factory=lambda: ScheduledTaskConfig(
        time=["04:30"]
    ))
    archive_rotation: ScheduledTaskConfig = field(default_factory=lambda: ScheduledTaskConfig(
        time=["05:00"]
    ))
    shadow_scan: ScheduledTaskConfig = field(default_factory=lambda: ScheduledTaskConfig(
        time=["03:30"]
    ))
    data_migrate: ScheduledTaskConfig = field(default_factory=lambda: ScheduledTaskConfig(
        enabled=False, time=["04:00"]
    ))
    agenda_review: ScheduledTaskConfig = field(default_factory=lambda: ScheduledTaskConfig(
        time=[f"{h:02d}:55" for h in range(4, 24)]
    ))
    action_tasks: ScheduledTaskConfig = field(default_factory=ScheduledTaskConfig)  # interval-based


@dataclass
class Config:
    """Complete configuration."""
    human: HumanConfig = field(default_factory=HumanConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    agents: dict[str, AgentConfig] = field(default_factory=lambda: {
        "relay": AgentConfig(name="ou", model="fast"),
        "data": AgentConfig(name="zeno", model="capable"),
        "agenda": AgentConfig(name="cato", model="capable"),
        "action": AgentConfig(name="hiro", model="capable", enabled=False),
        "pattern": AgentConfig(name="rumi", model="capable"),
        "code": AgentConfig(name="alan", model="capable", enabled=False),
    })
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    webui: WebuiConfig = field(default_factory=WebuiConfig)


# =============================================================================
# LOAD / SAVE
# =============================================================================

def _parse_providers(data: dict) -> dict[str, ProviderConfig]:
    """Parse providers from config data."""
    result = {}
    for name, cfg in data.items():
        if isinstance(cfg, dict):
            result[name] = ProviderConfig(
                api_key=cfg.get("api_key"),
                base_url=cfg.get("base_url"),
                env_vars=cfg.get("env_vars") or {},
            )
        else:
            result[name] = ProviderConfig()
    return result


def _parse_models(data: dict) -> dict[str, ModelConfig]:
    """Parse models from config data."""
    result = {}
    for alias, cfg in data.items():
        if isinstance(cfg, dict):
            result[alias] = ModelConfig(
                provider=cfg.get("provider", "anthropic"),
                name=cfg.get("name", alias),
                run_mode=cfg.get("run_mode", "on-demand"),
            )
    return result


def _parse_agents(data: dict) -> dict[str, AgentConfig]:
    """Parse agents from config data."""
    result = {}
    for role, cfg in data.items():
        if isinstance(cfg, dict):
            result[role] = AgentConfig(
                name=cfg.get("name", role),
                model=cfg.get("model", "capable"),
                enabled=cfg.get("enabled", True),
            )
    return result


def _parse_scheduled_task(data: dict, defaults: ScheduledTaskConfig) -> ScheduledTaskConfig:
    """Parse a single scheduled task config. Migrates old hour/minute/hourly_at_minute format."""
    enabled = data.get("enabled", defaults.enabled)
    interval_minutes = data.get("interval_minutes", defaults.interval_minutes)
    times = data.get("time")
    if times is None:
        # Migrate from old format
        if "hourly_at_minute" in data:
            m = data["hourly_at_minute"]
            start = data.get("start_hour", 0)
            end = data.get("end_hour", 23)
            times = [f"{h:02d}:{m:02d}" for h in range(start, end + 1)]
        elif "hour" in data:
            times = [f"{data['hour']:02d}:{data.get('minute', 0):02d}"]
        else:
            times = list(defaults.time)
    return ScheduledTaskConfig(enabled=enabled, time=times, interval_minutes=interval_minutes)


def _parse_schedule(data: dict) -> ScheduleConfig:
    """Parse schedule configuration."""
    defaults = ScheduleConfig()
    
    return ScheduleConfig(
        pattern_infer=_parse_scheduled_task(
            data.get("pattern_infer", data.get("pattern_nightly", {})), defaults.pattern_infer
        ),
        index_rebuild=_parse_scheduled_task(
            data.get("index_rebuild", {}), defaults.index_rebuild
        ),
        archive_rotation=_parse_scheduled_task(
            data.get("archive_rotation", {}), defaults.archive_rotation
        ),
        shadow_scan=_parse_scheduled_task(
            data.get("shadow_scan", {}), defaults.shadow_scan
        ),
        data_migrate=_parse_scheduled_task(
            data.get("data_migrate",
                {"time": [data.get("updates", {}).get("schedule", "04:00")]}
                if "updates" in data and "data_migrate" not in data else {}),
            defaults.data_migrate
        ),
        agenda_review=_parse_scheduled_task(
            data.get("agenda_review", {}), defaults.agenda_review
        ),
        action_tasks=_parse_scheduled_task(
            data.get("action_tasks", {}), defaults.action_tasks
        ),
    )


def load_config() -> Config:
    """Load configuration from file."""
    path = get_config_path()

    if not path.exists():
        return Config()

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # User
    human_data = data.get("human", {})
    # Handle phone as string or list
    phone_raw = human_data.get("phone", [])
    if isinstance(phone_raw, str):
        phone_list = [phone_raw] if phone_raw else []
    else:
        phone_list = phone_raw or []
    
    human = HumanConfig(
        name=human_data.get("name", "Human"),
        phone=phone_list,
        language=human_data.get("language", "en"),
        timezone=human_data.get("timezone", "Europe/Berlin"),
        vault=human_data.get("vault", ["~/Documents/Vault"]),
    )

    # Signal
    signal_data = data.get("signal", {})
    allowed_raw = signal_data.get("allowed", [])
    allowed = [
        AllowedContact(name=c.get("name", ""), phone=c.get("phone", ""))
        for c in allowed_raw if isinstance(c, dict)
    ]
    signal = SignalConfig(
        enabled=signal_data.get("enabled", False),
        bot_phone=signal_data.get("bot_phone"),
        bot_name=signal_data.get("bot_name", "Ou"),
        allowed=allowed,
    )

    # LLM
    llm_data = data.get("llm", {})
    llm = LLMConfig(
        providers=_parse_providers(llm_data.get("providers", {})),
        models=_parse_models(llm_data.get("models", {})),
        local_fallback=llm_data.get("local_fallback") or None,
    )
    # Use defaults if empty
    if not llm.providers:
        llm.providers = {"anthropic": ProviderConfig()}
    if not llm.models:
        llm.models = {
            "fast": ModelConfig(provider="anthropic", name="claude-haiku-4-5"),
            "capable": ModelConfig(provider="anthropic", name="claude-sonnet-4-20250514"),
        }

    # Agents
    agents = _parse_agents(data.get("agents", {}))
    # Use defaults if empty
    if not agents:
        agents = {
            "relay": AgentConfig(name="ou", model="fast"),
            "data": AgentConfig(name="zeno", model="capable"),
            "agenda": AgentConfig(name="cato", model="capable"),
            "action": AgentConfig(name="hiro", model="capable", enabled=False),
            "pattern": AgentConfig(name="rumi", model="capable"),
            "code": AgentConfig(name="alan", model="capable", enabled=False),
        }

    # Updates
    updates_data = data.get("updates", {})
    updates = UpdatesConfig(
        auto_migrate=updates_data.get("auto_migrate", True),
        schedule=updates_data.get("schedule", "04:00"),
    )

    # Schedule
    schedule_data = data.get("schedule", {})
    schedule = _parse_schedule(schedule_data)

    # Web UI
    webui_data = data.get("webui", {})
    webui = WebuiConfig(
        enabled=webui_data.get("enabled", True),
        host=webui_data.get("host", "127.0.0.1"),
        port=webui_data.get("port", 8080),
    )

    return Config(
        human=human,
        signal=signal,
        llm=llm,
        agents=agents,
        schedule=schedule,
        updates=updates,
        webui=webui,
    )


def _serialize_scheduled_task(task: ScheduledTaskConfig) -> dict:
    """Serialize a scheduled task config."""
    d: dict = {"enabled": task.enabled, "time": task.time}
    if task.interval_minutes is not None:
        d["interval_minutes"] = task.interval_minutes
    return d


def _serialize_schedule(schedule: ScheduleConfig) -> dict:
    """Serialize schedule configuration."""
    return {
        "pattern_infer": _serialize_scheduled_task(schedule.pattern_infer),
        "index_rebuild": _serialize_scheduled_task(schedule.index_rebuild),
        "archive_rotation": _serialize_scheduled_task(schedule.archive_rotation),
        "shadow_scan": _serialize_scheduled_task(schedule.shadow_scan),
        "data_migrate": _serialize_scheduled_task(schedule.data_migrate),
        "agenda_review": _serialize_scheduled_task(schedule.agenda_review),
        "action_tasks": _serialize_scheduled_task(schedule.action_tasks),
    }


def save_config(config: Config) -> None:
    """Save configuration to file."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "human": {
            "name": config.human.name,
            "language": config.human.language,
            "timezone": config.human.timezone,
            "vault": config.human.vault,
        },
        "llm": {
            "providers": {
                name: {
                    k: v for k, v in [
                        ("api_key", p.api_key),
                        ("base_url", p.base_url),
                    ] if v is not None
                }
                for name, p in config.llm.providers.items()
            },
            "models": {
                alias: {
                    "provider": m.provider,
                    "name": m.name,
                    "run_mode": m.run_mode,
                }
                for alias, m in config.llm.models.items()
            },
        },
        "agents": {
            role: {
                "name": a.name,
                "model": a.model,
                "enabled": a.enabled,
            }
            for role, a in config.agents.items()
        },
        "schedule": _serialize_schedule(config.schedule),
        "updates": {
            "auto_migrate": config.updates.auto_migrate,
            "schedule": config.updates.schedule,
        },
        "webui": {
            "enabled": config.webui.enabled,
            "host": config.webui.host,
            "port": config.webui.port,
        },
    }

    # Human phone
    if config.human.phone:
        data["human"]["phone"] = config.human.phone

    # Signal config
    if config.signal.enabled or config.signal.bot_phone:
        data["signal"] = {
            "enabled": config.signal.enabled,
            "bot_name": config.signal.bot_name,
        }
        if config.signal.bot_phone:
            data["signal"]["bot_phone"] = config.signal.bot_phone

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================================================================
# INITIALIZATION
# =============================================================================

def init_directories() -> None:
    """Create required directories if they don't exist."""
    dirs = [
        get_outheis_dir(),
        get_human_dir(),
        get_human_dir() / "memory",
        get_human_dir() / "skills",
        get_human_dir() / "rules",
        get_human_dir() / "archive",
        get_human_dir() / "cache",
        get_human_dir() / "imports",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Create default config if needed
    if not get_config_path().exists():
        save_config(Config())

    # Seed default skills and rules on first run (never overwrite)
    defaults_dir = Path(__file__).parent.parent / "agents" / "defaults"
    human_dir = get_human_dir()
    for category in ("skills", "rules"):
        src_dir = defaults_dir / category
        dst_dir = human_dir / category
        if src_dir.exists():
            for src_file in src_dir.glob("*.md"):
                dst_file = dst_dir / src_file.name
                if not dst_file.exists():
                    import shutil
                    shutil.copy2(src_file, dst_file)
