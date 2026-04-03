"""Tests for Data agent."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outheis.agents.data import DataAgent, create_data_agent
from outheis.core.message import Message


@pytest.fixture
def temp_vault():
    """Create a temporary vault with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)
        
        (vault / "projects").mkdir()
        
        (vault / "projects" / "alpha.md").write_text("""---
title: Project Alpha
tags: [active]
---

# Project Alpha

Client: Acme Corp
Status: In progress
Budget: $50,000
""")
        
        (vault / "projects" / "beta.md").write_text("""---
title: Project Beta
tags: [planning]
---

# Project Beta

Early planning stage.
""")
        
        yield vault


@pytest.fixture
def mock_config(temp_vault):
    """Mock config to use temp vault."""
    mock_cfg = MagicMock()
    mock_cfg.user.all_vaults.return_value = [temp_vault]
    
    with patch("outheis.agents.data.load_config", return_value=mock_cfg):
        yield mock_cfg


class TestDataAgentSearch:
    def test_search_returns_results(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        results = agent.search("alpha")
        assert len(results) >= 1
        
        paths = [entry.path for _, entry in results]
        assert "projects/alpha.md" in paths
    
    def test_search_by_tag(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        results = agent.search_by_tag("active")
        assert len(results) == 1
        assert results[0][1].path == "projects/alpha.md"
    
    def test_get_file_content(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        # Build index first
        indices = agent._get_indices()
        assert len(indices) == 1
        
        index = indices[0]
        index.rebuild()
        
        vf = agent.get_file_content(index, "projects/alpha.md")
        assert vf is not None
        assert "Acme Corp" in vf.body
    
    def test_get_stats(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        # Trigger index build
        agent._get_indices()[0].rebuild()
        
        stats = agent.get_stats()
        assert stats["total_files"] == 2
        assert stats["vaults"] == 1


class TestDataAgentContext:
    def test_build_context(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        context = agent._build_context("alpha budget")
        
        assert "Project Alpha" in context
        assert "$50,000" in context
    
    def test_build_context_no_results(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        context = agent._build_context("nonexistent xyz")
        
        assert "No relevant documents" in context


@pytest.mark.integration
class TestDataAgentLLM:
    """Integration tests requiring API key."""
    
    def test_handle_direct(self, temp_vault, mock_config):
        agent = create_data_agent()
        
        answer = agent.handle_direct("What is Project Alpha's budget?")
        
        # Should mention the budget from the file
        assert "$50,000" in answer or "50,000" in answer or "fifty thousand" in answer.lower()
    
    def test_handle_message(self, temp_vault, mock_config):
        from uuid import uuid4
        
        agent = create_data_agent()
        
        msg = Message(
            id=str(uuid4()),
            conversation_id=str(uuid4()),
            to="data",
            type="request",
            payload={"text": "Tell me about Project Alpha"},
            from_agent="relay",
        )
        
        response = agent.handle(msg)
        
        assert response is not None
        assert "answer" in response.payload
        assert "Acme" in response.payload["answer"] or "Alpha" in response.payload["answer"]
