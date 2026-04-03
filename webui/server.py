"""
outheis Web UI server.

FastAPI backend with WebSocket for live updates.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

WEBUI_DIR = Path(__file__).parent
ASSETS_DIR = WEBUI_DIR / "assets"
HUMAN_DIR = Path.home() / ".outheis" / "human"
CONFIG_PATH = HUMAN_DIR / "config.json"
MESSAGES_PATH = HUMAN_DIR / "messages.jsonl"


def get_vault_path() -> Path:
    """Get primary vault path from config."""
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        vaults = config.get("human", {}).get("vaults", [])
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


@app.get("/assets/{filename}")
async def assets(filename: str):
    path = ASSETS_DIR / filename
    if path.exists() and path.suffix in {".svg", ".png", ".ico"}:
        media_types = {".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
        return FileResponse(path, media_type=media_types.get(path.suffix, "application/octet-stream"))
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
        {"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime}
        for f in sorted(directory.glob(f"*{extension}"))
    ]


@app.get("/api/memory")
async def get_memory_files():
    return list_files(HUMAN_DIR / "memory")


@app.get("/api/memory/{filename}")
async def get_memory_file(filename: str):
    path = HUMAN_DIR / "memory" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/memory/{filename}")
async def save_memory_file(filename: str, data: dict):
    path = HUMAN_DIR / "memory" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.get("/api/skills")
async def get_skills_files():
    return list_files(HUMAN_DIR / "skills")


@app.get("/api/skills/{filename}")
async def get_skill_file(filename: str):
    path = HUMAN_DIR / "skills" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/skills/{filename}")
async def save_skill_file(filename: str, data: dict):
    path = HUMAN_DIR / "skills" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.get("/api/rules")
async def get_rules_files():
    return list_files(HUMAN_DIR / "rules")


@app.get("/api/rules/{filename}")
async def get_rule_file(filename: str):
    path = HUMAN_DIR / "rules" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/rules/{filename}")
async def save_rule_file(filename: str, data: dict):
    path = HUMAN_DIR / "rules" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.get("/api/patterns")
async def get_patterns_files():
    return list_files(HUMAN_DIR / "cache" / "patterns")


@app.get("/api/patterns/{filename}")
async def get_pattern_file(filename: str):
    path = HUMAN_DIR / "cache" / "patterns" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


# Vault files
@app.get("/api/agenda")
async def get_agenda_files():
    return list_files(get_vault_path() / "Agenda")


@app.get("/api/agenda/{filename}")
async def get_agenda_file(filename: str):
    path = get_vault_path() / "Agenda" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.put("/api/agenda/{filename}")
async def save_agenda_file(filename: str, data: dict):
    path = get_vault_path() / "Agenda" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""))
    return {"status": "saved"}


@app.get("/api/codebase")
async def get_codebase_files():
    return list_files(get_vault_path() / "Codebase")


@app.get("/api/codebase/{filename}")
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


# Messages API
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


# Status API
@app.get("/api/status")
async def get_status():
    import subprocess

    try:
        result = subprocess.run(
            ["pgrep", "-f", "outheis.*daemon"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        running = result.returncode == 0
        pid = result.stdout.strip().split("\n")[0] if running else None
    except Exception:
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
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        for line in MESSAGES_PATH.read_text().strip().split("\n"):
            if line and today in line:
                messages_today += 1

    return {
        "running": running,
        "pid": pid,
        "enabled_agents": enabled_agents,
        "total_agents": 6,
        "messages_today": messages_today,
    }


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
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
