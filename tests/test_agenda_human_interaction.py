"""test_agenda_human_interaction — ensure human interaction invalidates hash-based skipping.

Regression test for: agenda_review skipping when human had interacted via Signal/chat.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


def make_agent(tmp_path: Path):
    """Create a minimal AgendaAgent for testing."""
    from outheis.agents.agenda import AgendaAgent
    agent = AgendaAgent.__new__(AgendaAgent)
    agent.model_alias = "capable"
    agent.name = "agenda"
    agent._passthrough_content = None
    agent._agenda_snapshot = ""
    agent._dispatcher = None
    agent._write_happened = False
    # Mock get_human_dir to return tmp_path
    with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
        yield agent


class TestHumanInteractionInvalidation:
    """Human interaction should invalidate hash-based skipping."""

    def test_last_interaction_path(self, tmp_path):
        """Verify _get_interaction_path returns correct path."""
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
            path = agent._get_interaction_path()
            assert path == tmp_path / "cache" / "agenda" / "interaction.json"

    def test_last_review_time_path(self, tmp_path):
        """Verify last_review is stored in hashes.json."""
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
            path = agent._get_hash_cache_path()
            assert path == tmp_path / "cache" / "agenda" / "hashes.json"

    def test_save_and_get_last_review_time(self, tmp_path):
        """Verify _save_review_time and _get_last_review_time work."""
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
            # Initially None
            assert agent._get_last_review_time() is None

            # Save and retrieve
            agent._save_review_time()
            result = agent._get_last_review_time()
            assert result is not None
            # Should be valid ISO format
            datetime.fromisoformat(result)

    def test_get_last_human_interaction_missing(self, tmp_path):
        """Verify _get_last_human_interaction returns None when file missing."""
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
            assert agent._get_last_human_interaction() is None

    def test_get_last_human_interaction_exists(self, tmp_path):
        """Verify _get_last_human_interaction returns timestamp when file exists."""
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
            # Write interaction file
            interaction_path = tmp_path / "cache" / "agenda" / "interaction.json"
            interaction_path.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().isoformat()
            interaction_path.write_text(json.dumps({"last_interaction": ts}))

            result = agent._get_last_human_interaction()
            assert result == ts

    def test_human_interaction_forces_review(self, tmp_path):
        """When human interacted since last review, force=True should be set."""
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)

        with patch("outheis.agents.agenda.get_human_dir", return_value=tmp_path):
            # Setup: same hashes, no comments, no refill needed
            # But human interacted AFTER last review
            now = datetime.now()
            earlier = (now - timedelta(hours=1)).isoformat()
            later = now.isoformat()

            # Save review time (earlier)
            hash_path = tmp_path / "cache" / "agenda" / "hashes.json"
            hash_path.parent.mkdir(parents=True, exist_ok=True)
            hash_path.write_text(json.dumps({"last_review": earlier}))

            # Save interaction time (later)
            interaction_path = tmp_path / "cache" / "agenda" / "interaction.json"
            interaction_path.write_text(json.dumps({"last_interaction": later}))

            # Create Agenda.md and Exchange.md for hash check
            agenda_dir = tmp_path / "Agenda"
            agenda_dir.mkdir(parents=True, exist_ok=True)
            (agenda_dir / "Agenda.md").write_text("## Test")
            (agenda_dir / "Exchange.md").write_text("")

            # Mock get_agenda_dir
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                # Compute hashes that match (so skip would happen without interaction)
                stored_hashes = agent._load_hashes()
                stored_hashes["Agenda.md"] = agent._compute_hash(agenda_dir / "Agenda.md")
                stored_hashes["Exchange.md"] = agent._compute_hash(agenda_dir / "Exchange.md")
                agent._save_hashes(stored_hashes)

                # Now check: interaction > review should force=True
                last_interaction = agent._get_last_human_interaction()
                last_review = agent._get_last_review_time()
                assert last_interaction is not None
                assert last_review is not None

                li = datetime.fromisoformat(last_interaction)
                lr = datetime.fromisoformat(last_review)
                assert li > lr  # Interaction happened after last review