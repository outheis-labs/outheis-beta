"""
Tests that config.example.json is complete and consistent with the Config schema.

This test is the automated guard against config.example.json drifting from
the actual schema defined in config.py. Add a new config field? This test
will fail until the example file is updated.
"""

import json
import os
import shutil
import tempfile
from dataclasses import fields
from pathlib import Path

import pytest

from outheis.core.config import (
    Config,
    ScheduleConfig,
    load_config,
)

EXAMPLE_PATH = Path(__file__).parent.parent / "config.example.json"


@pytest.fixture
def example_data():
    """Load config.example.json as raw dict."""
    assert EXAMPLE_PATH.exists(), f"config.example.json not found at {EXAMPLE_PATH}"
    with open(EXAMPLE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def config_from_example(tmp_path):
    """Load config.example.json through the real load_config() parser."""
    config_dir = tmp_path / "human"
    config_dir.mkdir()
    shutil.copy(EXAMPLE_PATH, config_dir / "config.json")

    original = os.environ.get("OUTHEIS_HUMAN_DIR")
    os.environ["OUTHEIS_HUMAN_DIR"] = str(config_dir)
    try:
        yield load_config()
    finally:
        if original is None:
            del os.environ["OUTHEIS_HUMAN_DIR"]
        else:
            os.environ["OUTHEIS_HUMAN_DIR"] = original


class TestConfigExampleComplete:
    """config.example.json contains all top-level sections."""

    def test_top_level_keys(self, example_data):
        """All Config dataclass fields are present in example file."""
        required = {f.name for f in fields(Config)}
        missing = required - set(example_data.keys())
        assert not missing, (
            f"config.example.json is missing top-level sections: {missing}\n"
            f"Add them to config.example.json."
        )

    def test_schedule_tasks(self, example_data):
        """All ScheduleConfig tasks are present in example schedule section."""
        required = {f.name for f in fields(ScheduleConfig)}
        actual = set(example_data.get("schedule", {}).keys())
        missing = required - actual
        assert not missing, (
            f"config.example.json schedule section is missing tasks: {missing}\n"
            f"Add them under the \"schedule\" key."
        )

    def test_default_agents_present(self, example_data):
        """All default agent roles are documented in the example."""
        required = {"relay", "data", "agenda", "action", "pattern"}
        actual = set(example_data.get("agents", {}).keys())
        missing = required - actual
        assert not missing, (
            f"config.example.json agents section is missing roles: {missing}"
        )

    def test_llm_models_present(self, example_data):
        """fast and capable model aliases must be documented."""
        required = {"fast", "capable"}
        actual = set(example_data.get("llm", {}).get("models", {}).keys())
        missing = required - actual
        assert not missing, (
            f"config.example.json llm.models is missing aliases: {missing}"
        )

    def test_no_unknown_agent_fields(self, example_data):
        """Agent entries must not contain fields outside AgentConfig schema."""
        from dataclasses import fields as dc_fields
        from outheis.core.config import AgentConfig
        valid_fields = {f.name for f in dc_fields(AgentConfig)}
        for role, cfg in example_data.get("agents", {}).items():
            unknown = set(cfg.keys()) - valid_fields
            assert not unknown, (
                f"agents.{role} in config.example.json has unknown fields: {unknown}\n"
                f"Valid fields: {valid_fields}"
            )


class TestConfigExampleParseable:
    """config.example.json parses without errors through load_config()."""

    def test_parses_without_error(self, config_from_example):
        """load_config() on example file raises no exceptions."""
        assert config_from_example is not None

    def test_human_section(self, config_from_example):
        assert config_from_example.human.name == "Human"
        assert config_from_example.human.language == "en"
        assert config_from_example.human.timezone == "Europe/Berlin"

    def test_signal_section(self, config_from_example):
        assert config_from_example.signal.enabled is False

    def test_llm_models(self, config_from_example):
        assert "fast" in config_from_example.llm.models
        assert "capable" in config_from_example.llm.models
        fast = config_from_example.llm.models["fast"]
        assert fast.provider == "anthropic"
        assert fast.name  # not empty

    def test_agents(self, config_from_example):
        agents = config_from_example.agents
        assert "relay" in agents
        assert "data" in agents
        assert "agenda" in agents
        assert agents["relay"].enabled is True
        assert agents["action"].enabled is False  # hiro disabled by default
        assert agents.get("code") is not None
        assert agents["code"].enabled is False  # alan (code) disabled by default (dev only)

    def test_schedule(self, config_from_example):
        sched = config_from_example.schedule
        # agenda_review uses time list (one entry per hour 04:55–23:55)
        assert any("55" in t for t in sched.agenda_review.time)
        assert sched.pattern_infer.enabled is True
        assert sched.index_rebuild.enabled is True

    def test_updates(self, config_from_example):
        assert config_from_example.updates.auto_migrate is True
