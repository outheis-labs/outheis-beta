"""
outheis Web UI server.

FastAPI backend with WebSocket for live updates.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from outheis.core.config import get_human_dir

WEBUI_DIR = Path(__file__).parent
ASSETS_DIR = WEBUI_DIR / "assets"
HUMAN_DIR = get_human_dir()
CONFIG_PATH = HUMAN_DIR / "config.json"
MESSAGES_PATH = HUMAN_DIR / "messages.jsonl"


def get_vault_path() -> Path:
    """Get primary vault path from config."""
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        vaults = config.get("human", {}).get("vault", [])
        if vaults:
            return Path(vaults[0]).expanduser()
    return Path.home() / "Documents" / "Vault"


app = FastAPI(title="outheis", docs_url=None, redoc_url=None)


# Static files
@app.get("/")
async def index():
    return FileResponse(WEBUI_DIR / "index.html")


@app.get("/style.css")
async def style():
    return FileResponse(WEBUI_DIR / "style.css", media_type="text/css")


@app.get("/app.js")
async def script():
    return FileResponse(WEBUI_DIR / "app.js", media_type="application/javascript")


@app.get("/editor.js")
async def editor_script():
    return FileResponse(WEBUI_DIR / "editor.js", media_type="application/javascript")


@app.get("/assets/{filepath:path}")
async def assets(filepath: str):
    path = (ASSETS_DIR / filepath).resolve()
    if not str(path).startswith(str(ASSETS_DIR.resolve())):
        return {"error": "Access denied"}
    media_types = {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".webmanifest": "application/manifest+json",
    }
    if path.exists() and path.suffix in media_types:
        return FileResponse(path, media_type=media_types[path.suffix])
    return {"error": "Asset not found"}


# Config API
@app.get("/api/config")
async def get_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"error": "Config not found"}


@app.post("/api/config")
async def save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    return {"status": "saved"}


# Files API
def list_files(directory: Path, extension: str = ".md") -> list[dict]:
    if not directory.exists():
        return []
    return [
        {"name": str(f.relative_to(directory)), "size": f.stat().st_size, "modified": f.stat().st_mtime}
        for f in sorted(directory.rglob(f"*{extension}"))
        if f.is_file()
    ]


def list_files_multi(directory: Path, extensions: list[str]) -> list[dict]:
    if not directory.exists():
        return []
    return [
        {"name": str(f.relative_to(directory)), "size": f.stat().st_size, "modified": f.stat().st_mtime}
        for f in sorted(directory.rglob("*"))
        if f.is_file() and f.suffix in extensions
    ]


@app.get("/api/memory")
async def get_memory_files():
    return list_files_multi(HUMAN_DIR / "memory", [".md", ".json"])


@app.get("/api/memory/{filename:path}")
async def get_memory_file(filename: str):
    path = HUMAN_DIR / "memory" / filename
    if path.exists() and path.suffix in {".md", ".json"}:
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/memory/{filename:path}")
async def save_memory_file(filename: str, data: dict):
    path = HUMAN_DIR / "memory" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.delete("/api/memory/{filename:path}")
async def delete_memory_file(filename: str):
    path = HUMAN_DIR / "memory" / filename
    if not path.exists():
        return {"error": "File not found"}
    path.unlink()
    return {"status": "deleted"}


@app.get("/api/skills")
async def get_skills_files():
    return list_files(HUMAN_DIR / "skills")


@app.get("/api/skills/{filename:path}")
async def get_skill_file(filename: str):
    path = HUMAN_DIR / "skills" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/skills/{filename:path}")
async def save_skill_file(filename: str, data: dict):
    path = HUMAN_DIR / "skills" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.delete("/api/skills/{filename:path}")
async def delete_skill_file(filename: str):
    path = HUMAN_DIR / "skills" / filename
    if not path.exists():
        return {"error": "File not found"}
    path.unlink()
    return {"status": "deleted"}


@app.get("/api/rules")
async def get_rules_files():
    return list_files(HUMAN_DIR / "rules")


@app.get("/api/rules/{filename:path}")
async def get_rule_file(filename: str):
    path = HUMAN_DIR / "rules" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/rules/{filename:path}")
async def save_rule_file(filename: str, data: dict):
    path = HUMAN_DIR / "rules" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.delete("/api/rules/{filename:path}")
async def delete_rule_file(filename: str):
    path = HUMAN_DIR / "rules" / filename
    if not path.exists():
        return {"error": "File not found"}
    path.unlink()
    return {"status": "deleted"}


# Vault files
@app.get("/api/agenda")
async def get_agenda_files():
    return list_files(get_vault_path() / "Agenda")


@app.get("/api/agenda/{filename:path}")
async def get_agenda_file(filename: str):
    path = get_vault_path() / "Agenda" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/agenda/{filename:path}")
async def save_agenda_file(filename: str, data: dict):
    path = get_vault_path() / "Agenda" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.delete("/api/agenda/{filename:path}")
async def delete_agenda_file(filename: str):
    path = get_vault_path() / "Agenda" / filename
    if not path.exists():
        return {"error": "File not found"}
    path.unlink()
    return {"status": "deleted"}


@app.get("/api/codebase")
async def get_codebase_files():
    return list_files(get_vault_path() / "Codebase")


@app.get("/api/codebase/{filename:path}")
async def get_codebase_file(filename: str):
    path = get_vault_path() / "Codebase" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.get("/api/migration")
async def get_migration_files():
    migration_dir = get_vault_path() / "Migration"
    if not migration_dir.exists():
        return {"exists": False, "files": []}
    return {
        "exists": True,
        "files": list_files(migration_dir, ".py") + list_files(migration_dir, ".md"),
    }


@app.post("/api/migration/create")
async def create_migration_dir():
    migration_dir = get_vault_path() / "Migration"
    migration_dir.mkdir(parents=True, exist_ok=True)
    return {"status": "created"}


@app.post("/api/migration/upload")
async def upload_migration_file(file: UploadFile = File(...)):
    migration_dir = get_vault_path() / "Migration"
    migration_dir.mkdir(parents=True, exist_ok=True)
    if not file.filename or Path(file.filename).suffix.lower() not in (".md", ".json"):
        return {"error": "Only .md and .json files allowed"}
    dest = migration_dir / file.filename
    dest.write_bytes(await file.read())
    return {"status": "uploaded", "name": file.filename}


@app.get("/api/migration/{filename:path}")
async def get_migration_file(filename: str):
    path = get_vault_path() / "Migration" / filename
    if path.exists() and path.suffix in (".md", ".json", ".py"):
        return {"name": filename, "content": path.read_text(encoding="utf-8")}
    return {"error": "File not found"}


@app.put("/api/migration/{filename:path}")
async def save_migration_file(filename: str, data: dict):
    path = get_vault_path() / "Migration" / filename
    if not path.exists():
        return {"error": "File not found"}
    path.write_text(data.get("content", ""), encoding="utf-8")
    return {"status": "saved"}


@app.delete("/api/migration/{filename:path}")
async def delete_migration_file(filename: str):
    path = get_vault_path() / "Migration" / filename
    if not path.exists():
        return {"error": "File not found"}
    path.unlink()
    return {"status": "deleted"}


def _file_dirs() -> dict:
    vault = get_vault_path()
    return {
        "memory": HUMAN_DIR / "memory",
        "skills": HUMAN_DIR / "skills",
        "rules": HUMAN_DIR / "rules",
        "agenda": vault / "Agenda",
        "codebase": vault / "Codebase",
        "migration": vault / "Migration",
    }


@app.get("/api/mtime")
async def get_file_mtime(type: str, filename: str):
    d = _file_dirs().get(type)
    if not d:
        return {"error": "Unknown type"}
    path = d / filename
    if not path.exists():
        return {"error": "Not found"}
    return {"mtime": path.stat().st_mtime}


def _safe_relative_path(name: str) -> str | None:
    """Validate a relative path: no absolute, no traversal. Returns normalized or None."""
    from pathlib import PurePosixPath
    try:
        p = PurePosixPath(name)
        if p.is_absolute():
            return None
        if any(part == ".." for part in p.parts):
            return None
        return str(p)
    except Exception:
        return None


@app.post("/api/{type}/rename")
async def rename_file(type: str, data: dict):
    d = _file_dirs().get(type)
    if not d:
        return {"error": "Unknown type"}
    old = _safe_relative_path(data.get("from", "").strip())
    new = _safe_relative_path(data.get("to", "").strip())
    if not old or not new:
        return {"error": "Invalid path"}
    src = d / old
    if not src.exists():
        return {"error": "File not found"}
    dst = d / new
    if dst.exists():
        return {"error": "File already exists"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"status": "renamed", "name": new}


@app.post("/api/{type}/create")
async def create_file(type: str, data: dict):
    d = _file_dirs().get(type)
    if not d:
        return {"error": "Unknown type"}
    name = _safe_relative_path(data.get("name", "").strip())
    if not name:
        return {"error": "Invalid path"}
    if not name.endswith(".md"):
        name += ".md"
    path = d / name
    if path.exists():
        return {"error": "File already exists"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return {"status": "created", "name": name}


# Search API
@app.get("/api/search")
async def search_files(type: str, q: str):
    import re

    dir_map = {
        "memory": HUMAN_DIR / "memory",
        "skills": HUMAN_DIR / "skills",
        "rules": HUMAN_DIR / "rules",
        "agenda": get_vault_path() / "Agenda",
        "codebase": get_vault_path() / "Codebase",
        "migration": get_vault_path() / "Migration",
    }
    directory = dir_map.get(type)
    if not directory:
        return {"error": f"Unknown type: {type}"}
    try:
        pattern = re.compile(q, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}
    results = []
    if directory.exists():
        for f in sorted(directory.glob("*")):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            matches = []
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    matches.append({"line": i, "content": line.strip()[:200]})
            if matches:
                results.append({"file": f.name, "matches": matches})
    return {"results": results, "total": sum(len(r["matches"]) for r in results)}


# Vault file browser
_TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv",
    ".py", ".js", ".ts", ".css", ".html", ".sh", ".rb", ".go",
    ".rs", ".java", ".c", ".cpp", ".h", ".xml", ".ini", ".env",
    ".log", ".sql",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}


def get_all_vaults() -> list[Path]:
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        vaults = config.get("human", {}).get("vault", [])
        return [Path(v).expanduser() for v in vaults if Path(v).expanduser().is_dir()]
    return []


def is_vault_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
        for vault in get_all_vaults():
            try:
                resolved.relative_to(vault.resolve())
                return True
            except ValueError:
                pass
    except Exception:
        pass
    return False


def build_vault_tree(directory: Path, depth: int = 0, max_depth: int = 6) -> dict:
    node: dict = {"name": directory.name, "path": str(directory), "type": "dir", "children": []}
    if depth >= max_depth:
        return node
    try:
        entries = list(directory.iterdir())
    except PermissionError:
        return node
    dirs = sorted((e for e in entries if e.is_dir() and not e.name.startswith(".")), key=lambda e: e.name.lower())
    files = sorted(
        (e for e in entries if e.is_file() and not e.name.startswith(".")),
        key=lambda e: e.name.lower(),
    )
    for d in dirs:
        node["children"].append(build_vault_tree(d, depth + 1, max_depth))
    for f in files:
        node["children"].append({"name": f.name, "path": str(f), "type": "file", "size": f.stat().st_size, "ext": f.suffix})
    return node


@app.get("/api/vault/tree")
async def get_vault_tree():
    return {"vaults": [build_vault_tree(v) for v in get_all_vaults()]}


def _resolve_wikilink(name: str, context_dir: Path, vaults: list[Path]) -> str | None:
    """Find a file by name: context directory first, then full vault search."""
    candidate = context_dir / name
    if candidate.is_file():
        return str(candidate)
    for vault in vaults:
        for match in vault.rglob(name):
            if match.is_file():
                return str(match)
    return None


@app.get("/api/vault/raw")
async def get_vault_raw(path: str):
    """Serve a vault file as-is (for download and inline images)."""
    from fastapi.responses import FileResponse as FR
    p = Path(path)
    if not is_vault_path(p) or not p.is_file():
        return {"error": "Not found"}
    return FR(p, filename=p.name)


@app.get("/api/vault/file")
async def get_vault_file(path: str):
    import re
    p = Path(path)
    if not is_vault_path(p) or not p.is_file():
        return {"error": "Access denied or file not found"}
    ext = p.suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return {"path": str(p), "name": p.name, "kind": "image", "ext": ext}
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        return {"path": str(p), "name": p.name, "kind": "binary", "size": p.stat().st_size, "ext": ext}
    # Resolve Obsidian wikilink images ![[name.jpg]] → absolute path
    wikilinks: dict[str, str] = {}
    if ext == ".md":
        vaults = get_all_vaults()
        for m in re.finditer(r"!\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", content):
            img_name = m.group(1).strip()
            if img_name not in wikilinks:
                resolved = _resolve_wikilink(img_name, p.parent, vaults)
                if resolved:
                    wikilinks[img_name] = resolved
    return {"path": str(p), "name": p.name, "kind": "text", "content": content, "ext": ext, "wikilinks": wikilinks}


@app.put("/api/vault/file")
async def save_vault_file(data: dict):
    p = Path(data.get("path", ""))
    if not is_vault_path(p):
        return {"error": "Access denied"}
    try:
        p.write_text(data.get("content", ""), encoding="utf-8")
        return {"status": "saved"}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/api/vault/file")
async def delete_vault_file(path: str):
    p = Path(path)
    if not is_vault_path(p) or not p.exists():
        return {"error": "Access denied or file not found"}
    try:
        p.unlink()
        return {"status": "deleted"}
    except Exception as e:
        return {"error": str(e)}


# Tags API
TAG_CACHE_PATH = HUMAN_DIR / "cache" / "tags.json"
_TAG_RE = __import__("re").compile(r"(?<!\w)#([a-zA-Z\u00c0-\u017e][a-zA-Z\u00c0-\u017e0-9_-]*)")


def _scan_vault_tags() -> dict:
    import re
    from datetime import datetime

    vault = get_vault_path()
    counts: dict[str, int] = {}
    locations: dict[str, list[str]] = {}

    for md_file in sorted(vault.rglob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = str(md_file.relative_to(vault))
        found = set(_TAG_RE.findall(text))
        for tag in found:
            full = f"#{tag}"
            counts[full] = counts.get(full, 0) + text.count(full)
            locations.setdefault(full, []).append(rel)

    tags = [
        {"name": t, "count": counts[t], "files": locations[t]}
        for t in sorted(counts)
    ]
    result = {"tags": tags, "scanned_at": datetime.now().isoformat(timespec="seconds")}
    TAG_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAG_CACHE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


@app.get("/api/tags")
async def get_tags():
    if TAG_CACHE_PATH.exists():
        data = json.loads(TAG_CACHE_PATH.read_text())
        data["tags"] = sorted(
            [t for t in data.get("tags", []) if not t["name"].startswith("#outheis-")],
            key=lambda t: t["name"],
        )
        return data
    return await scan_tags()


@app.post("/api/tags/scan")
async def scan_tags():
    from outheis.core.queue import append
    from outheis.core.message import create_agent_message
    import uuid
    msg = create_agent_message(
        from_agent="webui",
        to="dispatcher",
        type="request",
        payload={"text": "run_task:tag_scan"},
        conversation_id=str(uuid.uuid4()),
        intent="internal",
    )
    append(MESSAGES_PATH, msg)
    return {"status": "queued", "task": "tag_scan", "conversation_id": msg.conversation_id}


@app.post("/api/tags/rename")
async def rename_tag(data: dict):
    old = data.get("old_name", "").strip()
    new = data.get("new_name", "").strip()
    if not old or not new or old == new:
        return {"error": "Invalid tag names"}
    if not old.startswith("#") or not new.startswith("#"):
        return {"error": "Tags must start with #"}

    import re
    vault = get_vault_path()
    changed = []
    pattern = re.compile(r"(?<!\w)" + re.escape(old) + r"(?!\w)")

    for md_file in sorted(vault.rglob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if old not in text:
            continue
        new_text = pattern.sub(new, text)
        if new_text != text:
            md_file.write_text(new_text, encoding="utf-8")
            changed.append(str(md_file.relative_to(vault)))

    # Refresh cache after rename
    _scan_vault_tags()
    return {"files_changed": len(changed), "files": changed}


@app.post("/api/tags/delete")
async def delete_tag(data: dict):
    tag = data.get("name", "").strip()
    if not tag or not tag.startswith("#"):
        return {"error": "Invalid tag name"}

    import re
    vault = get_vault_path()
    changed = []
    pattern = re.compile(r"(?<!\w)" + re.escape(tag) + r"(?!\w)")

    for md_file in sorted(vault.rglob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if tag not in text:
            continue
        new_text = pattern.sub("", text)
        # Clean up double spaces left behind
        new_text = re.sub(r"  +", " ", new_text)
        if new_text != text:
            md_file.write_text(new_text, encoding="utf-8")
            changed.append(str(md_file.relative_to(vault)))

    _scan_vault_tags()
    return {"files_changed": len(changed), "files": changed}


# Messages API
@app.post("/api/send")
async def send_message(data: dict):
    from outheis.core.queue import append
    from outheis.core.message import create_user_message
    text = data.get("text", "").strip()
    if not text:
        return {"error": "Empty message"}
    human_name = None
    human_identity = "webui"
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
        human = cfg.get("human", {})
        human_name = human.get("name")
        human_identity = human.get("phone", "webui")
    msg = create_user_message(
        text=text,
        channel="api",
        identity=human_identity,
        name=human_name,
    )
    append(MESSAGES_PATH, msg)
    return {"status": "queued", "conversation_id": msg.conversation_id}


@app.get("/api/messages")
async def get_messages(limit: int = 50):
    if not MESSAGES_PATH.exists():
        return []
    lines = MESSAGES_PATH.read_text().strip().split("\n")
    messages = []
    for line in lines[-limit:]:
        if line:
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return list(reversed(messages))


# Tokens API
@app.get("/api/tokens/stats")
async def get_token_stats():
    from outheis.core.tokens import get_stats_7days
    return get_stats_7days()


# Scheduler API
@app.get("/api/scheduler/running")
async def get_running_tasks():
    try:
        from outheis.dispatcher.daemon import get_task_registry
        registry = get_task_registry()
        running = [name for name, rec in registry.items() if rec.get("status") == "running"]
        return {"running": running, "tasks": registry}
    except Exception:
        return {"running": [], "tasks": {}}


@app.post("/api/scheduler/run/{task}")
async def run_scheduler_task(task: str):
    from outheis.core.queue import append
    from outheis.core.message import create_agent_message
    import uuid
    msg = create_agent_message(
        from_agent="webui",
        to="dispatcher",
        type="request",
        payload={"text": f"run_task:{task}"},
        conversation_id=str(uuid.uuid4()),
        intent="internal",
    )
    append(MESSAGES_PATH, msg)
    return {"status": "queued", "task": task, "conversation_id": msg.conversation_id}


# Status API
@app.get("/api/status")
async def get_status():
    try:
        from outheis.dispatcher.daemon import read_pid, get_pid_path
        _pid = read_pid()
        if _pid:
            os.kill(_pid, 0)  # raises if process is gone
            running = True
            pid = str(_pid)
        else:
            running = False
            pid = None
    except (ProcessLookupError, PermissionError, OSError):
        running = False
        pid = None

    enabled_agents = 0
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        for agent in config.get("agents", {}).values():
            if agent.get("enabled", False):
                enabled_agents += 1

    messages_today = 0
    if MESSAGES_PATH.exists():
        from datetime import datetime, timezone

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for line in MESSAGES_PATH.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                ts = json.loads(line).get("timestamp", 0)
                if ts and ts >= today_start:
                    messages_today += 1
            except (json.JSONDecodeError, AttributeError):
                pass

    # System status (fallback mode etc.)
    system_mode = "normal"
    fallback_reason = None
    fallback_model = None
    status_path = HUMAN_DIR / "system_status.json"
    if status_path.exists():
        try:
            s = json.loads(status_path.read_text())
            system_mode = s.get("mode", "normal")
            fallback_reason = s.get("reason")
            fallback_model = s.get("fallback_model")
        except Exception:
            pass

    return {
        "running": running,
        "pid": pid,
        "enabled_agents": enabled_agents,
        "total_agents": 6,
        "messages_today": messages_today,
        "system_mode": system_mode,
        "fallback_reason": fallback_reason,
        "fallback_model": fallback_model,
    }


@app.post("/api/restart")
async def restart_daemon():
    import os
    import shutil
    import subprocess
    import sys

    from outheis.dispatcher.daemon import read_pid

    current_pid = read_pid()
    if not current_pid:
        return {"status": "not_running"}

    from outheis.core.config import get_human_dir
    log_path = str(get_human_dir() / "dispatcher.log")

    # Use the actual running executable — reliable even without PATH
    outheis_cmd = shutil.which("outheis") or sys.argv[0]
    start_cmd = repr([outheis_cmd, "start"])
    env_repr = repr(dict(os.environ))

    script = f"""
import os, time, signal, subprocess

pid = {current_pid}
start_cmd = {start_cmd}
env = {env_repr}

time.sleep(1)

try:
    os.kill(pid, signal.SIGTERM)
except ProcessLookupError:
    pass

for _ in range(20):
    time.sleep(0.5)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        break

time.sleep(1)
subprocess.run(start_cmd, env=env, check=False)
"""

    subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(os.environ),
    )

    return {"status": "restarting"}


# WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    last_size = MESSAGES_PATH.stat().st_size if MESSAGES_PATH.exists() else 0
    ping_counter = 0

    try:
        while True:
            if MESSAGES_PATH.exists():
                current_size = MESSAGES_PATH.stat().st_size
                if current_size > last_size:
                    with open(MESSAGES_PATH) as f:
                        f.seek(last_size)
                        new_content = f.read()
                    for line in new_content.strip().split("\n"):
                        if line:
                            try:
                                msg = json.loads(line)
                                await websocket.send_json({"type": "message", "data": msg})
                            except json.JSONDecodeError:
                                pass
                    last_size = current_size
            # Send keepalive ping every 30s to prevent SSH tunnel idle timeout
            ping_counter += 1
            if ping_counter >= 30:
                await websocket.send_json({"type": "ping"})
                ping_counter = 0
            await asyncio.sleep(1)
    except Exception:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
