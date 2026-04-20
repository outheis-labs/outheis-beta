"""test_code_review_diff — unit tests for CodeAgent file and diff operations."""

import tempfile
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    from outheis.agents.code import CodeAgent
    agent = CodeAgent.__new__(CodeAgent)
    agent.model_alias = "capable"
    agent.name = "code"
    return agent


# ---------------------------------------------------------------------------
# write_codebase — security boundary
# ---------------------------------------------------------------------------

class TestWriteCodebaseSecurity:

    def test_write_within_codebase_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase), \
                 patch.object(agent, "_ensure_exchange_entry"):
                result = agent._tool_write_codebase("proposal.md", "fix suggestion")
            assert "Written" in result
            assert (codebase / "proposal.md").exists()

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_write_codebase("../../etc/passwd", "evil")
        assert "rejected" in result.lower()

    def test_absolute_path_outside_codebase_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_write_codebase("/tmp/evil.md", "evil")
        assert "rejected" in result.lower()

    def test_empty_path_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_write_codebase("", "content")
        assert "no path" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# write_codebase — proposal behavior
# ---------------------------------------------------------------------------

class TestWriteCodebaseProposal:

    def test_proposal_gets_timestamp_prepended(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase), \
                 patch.object(agent, "_ensure_exchange_entry"):
                agent._tool_write_codebase("fix.md", "here is the fix")
            content = (codebase / "fix.md").read_text()
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", content)
        assert "here is the fix" in content

    def test_exchange_md_no_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                agent._tool_write_codebase("Exchange.md", "## Entry\npending")
            content = (codebase / "Exchange.md").read_text()
        assert content.startswith("## Entry")

    def test_proposal_creates_exchange_entry(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase), \
                 patch("outheis.core.config.load_config") as mock_cfg:
                mock_cfg.return_value.human.language = "en"
                agent._tool_write_codebase("my-proposal.md", "suggestion")
            exchange = (codebase / "Exchange.md").read_text()
        assert "my-proposal.md" in exchange

    def test_existing_exchange_entry_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            (codebase / "Exchange.md").write_text("## my-proposal.md\nexisting", encoding="utf-8")
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase), \
                 patch("outheis.core.config.load_config") as mock_cfg:
                mock_cfg.return_value.human.language = "en"
                agent._tool_write_codebase("my-proposal.md", "updated")
            exchange = (codebase / "Exchange.md").read_text()
        assert exchange.count("## my-proposal.md") == 1


# ---------------------------------------------------------------------------
# append_codebase
# ---------------------------------------------------------------------------

class TestAppendCodebase:

    def test_append_to_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            target = codebase / "Exchange.md"
            target.write_text("## existing\npending", encoding="utf-8")
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_append_codebase("Exchange.md", "new entry")
            assert "Appended" in result
            assert "new entry" in target.read_text()
            assert "existing" in target.read_text()

    def test_append_creates_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                agent._tool_append_codebase("new.md", "first content")
            assert (codebase / "new.md").exists()

    def test_append_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            codebase = Path(d) / "Codebase"
            codebase.mkdir()
            agent = make_agent()
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_append_codebase("../../secret.md", "evil")
        assert "rejected" in result.lower()


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------

class TestListFiles:

    def test_list_files_returns_filenames(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "alpha.py").write_text("x=1")
            (Path(d) / "beta.py").write_text("y=2")
            agent = make_agent()
            result = agent._tool_list_files(d)  # absolute path
        assert "alpha.py" in result
        assert "beta.py" in result

    def test_list_files_skips_dotfiles(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".hidden").write_text("secret")
            (Path(d) / "visible.py").write_text("code")
            agent = make_agent()
            result = agent._tool_list_files(d)
        assert ".hidden" not in result
        assert "visible.py" in result

    def test_list_files_nonexistent_returns_error(self):
        agent = make_agent()
        result = agent._tool_list_files("/nonexistent/path/xyz")
        assert "not found" in result.lower()
