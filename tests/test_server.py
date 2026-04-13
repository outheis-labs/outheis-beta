"""Tests for the WebUI FastAPI server (webui/server.py).

Skipped: WebSocket, /api/restart (subprocess), static file routes (FileResponse),
         vault tree (full filesystem traversal), tag scan/rename/delete (vault-wide writes).
"""

import json

import pytest
from fastapi.testclient import TestClient

import outheis.webui.server as server_mod
from outheis.webui.server import app, _safe_relative_path, list_files, list_files_multi


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dirs(tmp_path):
    human = tmp_path / "human"
    vault = tmp_path / "vault"
    for d in (human, vault, human / "memory", human / "skills", human / "rules",
              vault / "Agenda", vault / "Codebase", vault / "Migration"):
        d.mkdir(parents=True, exist_ok=True)
    return {"human": human, "vault": vault}


@pytest.fixture
def client(dirs, monkeypatch):
    human = dirs["human"]
    vault = dirs["vault"]
    monkeypatch.setattr(server_mod, "HUMAN_DIR", human)
    monkeypatch.setattr(server_mod, "CONFIG_PATH", human / "config.json")
    monkeypatch.setattr(server_mod, "MESSAGES_PATH", human / "messages.jsonl")
    monkeypatch.setattr(server_mod, "TAG_CACHE_PATH", human / "cache" / "tags.json")
    monkeypatch.setattr(server_mod, "get_vault_path", lambda: vault)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_relative_path_tests():
    pass  # see dedicated class below


# ---------------------------------------------------------------------------
# _safe_relative_path
# ---------------------------------------------------------------------------

class TestSafeRelativePath:
    def test_simple_name(self):
        assert _safe_relative_path("foo.md") == "foo.md"

    def test_nested_path(self):
        assert _safe_relative_path("a/b/c.md") == "a/b/c.md"

    def test_traversal_rejected(self):
        assert _safe_relative_path("../secret.md") is None

    def test_traversal_in_middle_rejected(self):
        assert _safe_relative_path("a/../../etc/passwd") is None

    def test_absolute_rejected(self):
        assert _safe_relative_path("/etc/passwd") is None

    def test_empty_string(self):
        # PurePosixPath("") has no parts → no traversal, returns ""
        result = _safe_relative_path("")
        assert result == "."  # PurePosixPath("") normalises to "."


# ---------------------------------------------------------------------------
# list_files helper
# ---------------------------------------------------------------------------

class TestListFiles:
    def test_returns_empty_for_missing_dir(self, tmp_path):
        assert list_files(tmp_path / "nonexistent") == []

    def test_finds_md_files(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        (tmp_path / "b.txt").write_text("ignored")
        result = list_files(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "a.md"

    def test_includes_size(self, tmp_path):
        (tmp_path / "x.md").write_text("abc")
        result = list_files(tmp_path)
        assert result[0]["size"] == 3

    def test_list_files_multi_extensions(self, tmp_path):
        (tmp_path / "a.md").write_text("")
        (tmp_path / "b.json").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = list_files_multi(tmp_path, [".md", ".json"])
        names = {r["name"] for r in result}
        assert "a.md" in names
        assert "b.json" in names
        assert "c.txt" not in names


# ---------------------------------------------------------------------------
# Config API
# ---------------------------------------------------------------------------

class TestConfigAPI:
    def test_get_config_missing(self, client):
        r = client.get("/api/config")
        assert r.json() == {"error": "Config not found"}

    def test_save_and_get_config(self, client):
        payload = {"human": {"name": "Test"}, "agents": {}}
        client.post("/api/config", json=payload)
        r = client.get("/api/config")
        assert r.json()["human"]["name"] == "Test"

    def test_save_config_returns_saved(self, client):
        r = client.post("/api/config", json={"x": 1})
        assert r.json() == {"status": "saved"}


# ---------------------------------------------------------------------------
# Memory API  (skills/rules share the same structure — tested via memory)
# ---------------------------------------------------------------------------

class TestMemoryAPI:
    def test_list_empty(self, client):
        r = client.get("/api/memory")
        assert r.json() == []

    def test_list_after_create(self, client, dirs):
        (dirs["human"] / "memory" / "test.md").write_text("hello")
        r = client.get("/api/memory")
        assert len(r.json()) == 1

    def test_get_file(self, client, dirs):
        (dirs["human"] / "memory" / "user.md").write_text("content here")
        r = client.get("/api/memory/user.md")
        assert r.json()["content"] == "content here"

    def test_get_missing_file(self, client):
        r = client.get("/api/memory/missing.md")
        assert "error" in r.json()

    def test_save_file(self, client):
        r = client.put("/api/memory/new.md", json={"content": "saved"})
        assert r.json() == {"status": "saved"}

    def test_save_creates_file(self, client, dirs):
        client.put("/api/memory/new.md", json={"content": "hello"})
        assert (dirs["human"] / "memory" / "new.md").read_text() == "hello"

    def test_delete_file(self, client, dirs):
        f = dirs["human"] / "memory" / "todelete.md"
        f.write_text("bye")
        r = client.delete("/api/memory/todelete.md")
        assert r.json() == {"status": "deleted"}
        assert not f.exists()

    def test_delete_missing_file(self, client):
        r = client.delete("/api/memory/ghost.md")
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# Skills API (spot check — same structure as memory)
# ---------------------------------------------------------------------------

class TestSkillsAPI:
    def test_list_and_get(self, client, dirs):
        (dirs["human"] / "skills" / "common.md").write_text("skill content")
        assert len(client.get("/api/skills").json()) == 1
        r = client.get("/api/skills/common.md")
        assert r.json()["content"] == "skill content"

    def test_save_and_delete(self, client, dirs):
        client.put("/api/skills/relay.md", json={"content": "x"})
        assert (dirs["human"] / "skills" / "relay.md").exists()
        client.delete("/api/skills/relay.md")
        assert not (dirs["human"] / "skills" / "relay.md").exists()


# ---------------------------------------------------------------------------
# Agenda API (vault-backed)
# ---------------------------------------------------------------------------

class TestAgendaAPI:
    def test_list_empty(self, client):
        assert client.get("/api/agenda").json() == []

    def test_get_file(self, client, dirs):
        (dirs["vault"] / "Agenda" / "Agenda.md").write_text("# Today")
        r = client.get("/api/agenda/Agenda.md")
        assert r.json()["content"] == "# Today"

    def test_save_file(self, client, dirs):
        client.put("/api/agenda/Agenda.md", json={"content": "new"})
        assert (dirs["vault"] / "Agenda" / "Agenda.md").read_text() == "new"

    def test_delete_missing(self, client):
        r = client.delete("/api/agenda/ghost.md")
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# Generic rename/create endpoints
# ---------------------------------------------------------------------------

class TestRenameCreateAPI:
    def test_create_file(self, client, dirs):
        r = client.post("/api/memory/create", json={"name": "mynote"})
        assert r.json()["status"] == "created"
        assert r.json()["name"] == "mynote.md"
        assert (dirs["human"] / "memory" / "mynote.md").exists()

    def test_create_adds_md_extension(self, client, dirs):
        client.post("/api/memory/create", json={"name": "noext"})
        assert (dirs["human"] / "memory" / "noext.md").exists()

    def test_create_rejects_duplicate(self, client, dirs):
        (dirs["human"] / "memory" / "dup.md").write_text("")
        r = client.post("/api/memory/create", json={"name": "dup"})
        assert "error" in r.json()

    def test_create_rejects_traversal(self, client):
        r = client.post("/api/memory/create", json={"name": "../escape"})
        assert "error" in r.json()

    def test_rename_file(self, client, dirs):
        (dirs["human"] / "memory" / "old.md").write_text("content")
        r = client.post("/api/memory/rename", json={"from": "old.md", "to": "new.md"})
        assert r.json()["status"] == "renamed"
        assert not (dirs["human"] / "memory" / "old.md").exists()
        assert (dirs["human"] / "memory" / "new.md").exists()

    def test_rename_missing_file(self, client):
        r = client.post("/api/memory/rename", json={"from": "ghost.md", "to": "new.md"})
        assert "error" in r.json()

    def test_rename_rejects_traversal(self, client, dirs):
        (dirs["human"] / "memory" / "src.md").write_text("")
        r = client.post("/api/memory/rename", json={"from": "src.md", "to": "../escape.md"})
        assert "error" in r.json()

    def test_unknown_type_returns_error(self, client):
        r = client.post("/api/unknown/create", json={"name": "x"})
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------

class TestSearchAPI:
    def test_search_finds_match(self, client, dirs):
        (dirs["human"] / "memory" / "notes.md").write_text("hello world\nsecond line")
        r = client.get("/api/search?type=memory&q=hello")
        data = r.json()
        assert data["total"] == 1
        assert data["results"][0]["file"] == "notes.md"

    def test_search_case_insensitive(self, client, dirs):
        (dirs["human"] / "memory" / "notes.md").write_text("Hello World")
        r = client.get("/api/search?type=memory&q=hello")
        assert r.json()["total"] == 1

    def test_search_no_match(self, client, dirs):
        (dirs["human"] / "memory" / "notes.md").write_text("unrelated content")
        r = client.get("/api/search?type=memory&q=xyz123")
        assert r.json()["total"] == 0

    def test_search_invalid_regex(self, client):
        r = client.get("/api/search?type=memory&q=[invalid")
        assert "error" in r.json()

    def test_search_unknown_type(self, client):
        r = client.get("/api/search?type=unknown&q=test")
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# Messages API
# ---------------------------------------------------------------------------

class TestMessagesAPI:
    def test_get_messages_empty(self, client):
        r = client.get("/api/messages")
        assert r.json() == []

    def test_get_messages_returns_list(self, client, dirs):
        msg = {"id": "1", "text": "hi", "timestamp": 1000}
        (dirs["human"] / "messages.jsonl").write_text(json.dumps(msg) + "\n")
        r = client.get("/api/messages")
        assert len(r.json()) == 1

    def test_get_messages_limit(self, client, dirs):
        lines = "\n".join(json.dumps({"id": str(i), "timestamp": i}) for i in range(10))
        (dirs["human"] / "messages.jsonl").write_text(lines + "\n")
        r = client.get("/api/messages?limit=3")
        assert len(r.json()) == 3

    def test_send_empty_message_rejected(self, client):
        r = client.post("/api/send", json={"text": "  "})
        assert "error" in r.json()

    def test_send_queues_message(self, client, dirs):
        r = client.post("/api/send", json={"text": "hello outheis"})
        assert r.json()["status"] == "queued"
        assert "conversation_id" in r.json()
        assert (dirs["human"] / "messages.jsonl").exists()


# ---------------------------------------------------------------------------
# mtime API
# ---------------------------------------------------------------------------

class TestMtimeAPI:
    def test_returns_mtime_for_existing_file(self, client, dirs):
        f = dirs["human"] / "memory" / "x.md"
        f.write_text("hi")
        r = client.get("/api/mtime?type=memory&filename=x.md")
        assert "mtime" in r.json()

    def test_unknown_type(self, client):
        r = client.get("/api/mtime?type=bogus&filename=x.md")
        assert "error" in r.json()

    def test_missing_file(self, client):
        r = client.get("/api/mtime?type=memory&filename=ghost.md")
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# Status API
# ---------------------------------------------------------------------------

class TestStatusAPI:
    def test_returns_expected_keys(self, client):
        r = client.get("/api/status")
        data = r.json()
        for key in ("running", "enabled_agents", "total_agents", "messages_today"):
            assert key in data

    def test_counts_enabled_agents(self, client, dirs):
        cfg = {"agents": {"relay": {"enabled": True}, "pattern": {"enabled": False}}}
        (dirs["human"] / "config.json").write_text(json.dumps(cfg))
        r = client.get("/api/status")
        assert r.json()["enabled_agents"] == 1

    def test_not_running_when_no_pid(self, client, monkeypatch):
        monkeypatch.setattr("outheis.webui.server.os.kill", lambda pid, sig: (_ for _ in ()).throw(OSError()))
        import outheis.dispatcher.daemon as daemon_mod
        monkeypatch.setattr(daemon_mod, "read_pid", lambda: None)
        r = client.get("/api/status")
        assert r.json()["running"] is False
