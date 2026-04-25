"""
outheis Web UI server.

FastAPI backend with WebSocket for live updates.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from outheis.core.config import get_human_dir

WEBUI_DIR = Path(__file__).parent
ASSETS_DIR = WEBUI_DIR / "assets"
HUMAN_DIR = get_human_dir()
CONFIG_PATH = HUMAN_DIR / "config.json"
MESSAGES_PATH = HUMAN_DIR / "messages.jsonl"
WEBUI_STATE_DIR = HUMAN_DIR / "webui"
SECRET_PATH = WEBUI_STATE_DIR / "secret"
_SESSION_COOKIE = "outheis_session"


def _get_secret() -> str:
    """Return the signing secret, generating it on first call."""
    WEBUI_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32))
        SECRET_PATH.chmod(0o600)
    return SECRET_PATH.read_text().strip()


def _hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", plain.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2:sha256:600000:{salt}:{h.hex()}"


def _verify_password(plain: str, stored: str) -> bool:
    if stored.startswith("pbkdf2:sha256:"):
        _, algo, iters, salt, expected = stored.split(":")
        h = hashlib.pbkdf2_hmac(algo, plain.encode(), bytes.fromhex(salt), int(iters))
        return h.hex() == expected
    return plain == stored  # plaintext fallback for migration


def _get_password() -> str:
    """Read webui.password from config. Returns empty string if not set."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        return cfg.get("webui", {}).get("password", "")
    except Exception:
        return ""


def _migrate_password(plain: str) -> None:
    """Replace plaintext password in config with a hash."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        cfg.setdefault("webui", {})["password"] = _hash_password(plain)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    except Exception:
        pass


def _get_session_hours() -> int:
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        return int(cfg.get("webui", {}).get("session_hours", 4))
    except Exception:
        return 4


def _make_session_cookie(session_hours: int) -> str:
    """Return a signed session token: '{expiry}:{hmac}'."""
    expiry = int(time.time()) + session_hours * 3600
    secret = _get_secret()
    sig = hmac.new(secret.encode(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}:{sig}"


def _verify_session_cookie(value: str) -> bool:
    """Return True if the session cookie is valid and not expired."""
    try:
        expiry_str, sig = value.split(":", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if time.time() > expiry:
        return False
    secret = _get_secret()
    expected = hmac.new(secret.encode(), expiry_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def _auth_required() -> bool:
    return bool(_get_password())


def _is_authenticated(request: Request) -> bool:
    cookie = request.cookies.get(_SESSION_COOKIE, "")
    return _verify_session_cookie(cookie)


_BRAND = "\u03bf\u1f50\u03b8\u03b5\u03af\u03c2"  # noqa: i18n — Greek brand name, intentional
_LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>outheis</title>
<style>
  @font-face {
    font-family: 'Inter';
    src: url('/assets/fonts/InterVariable.woff2') format('woff2');
    font-weight: 100 900;
    font-style: normal;
  }
  @font-face {
    font-family: 'IBM Plex Sans';
    src: url('/assets/fonts/IBMPlexSans-Variable.woff2') format('woff2');
    font-weight: 100 700;
    font-style: normal;
  }

  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #fff;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 14px;
    color: #1a1a1a;
    -webkit-font-smoothing: antialiased;
  }

  .wrap { width: 280px; }

  .logo {
    font-family: 'Inter', sans-serif;
    font-size: 40px;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 40px;
    display: inline-block;
    transition: color 0.03s ease;
  }

  label {
    display: block;
    font-size: 11px;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 6px;
  }

  input[type="password"] {
    width: 100%;
    padding: 10px 12px;
    font-family: inherit;
    font-size: 14px;
    color: #1a1a1a;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 4px;
    outline: none;
    margin-bottom: 12px;
    transition: border-color 0.15s;
  }

  input[type="password"]:focus { border-color: #1a1a1a; }

  button {
    width: 100%;
    padding: 10px 12px;
    font-family: inherit;
    font-size: 14px;
    font-weight: 500;
    color: #fff;
    background: #1a1a1a;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
  }

  button:hover { background: #333; }

  .err {
    font-size: 12px;
    color: #dc2626;
    margin-top: 10px;
    display: none;
  }

  @media (prefers-color-scheme: no-preference) {
    body { background: #1a1a1a; color: #f0f0f0; }
    input[type="password"] { background: #242424; border-color: #333; color: #f0f0f0; }
    input[type="password"]:focus { border-color: #f0f0f0; }
    button { background: #f0f0f0; color: #1a1a1a; }
    button:hover { background: #d0d0d0; }
    label { color: #707070; }
  }
</style>
</head>
<body>
<div class="wrap">
  <div class="logo" id="logo">__OUTHEIS_BRAND__</div>
  <label for="pw">Password</label>
  <input id="pw" type="password" autofocus>
  <button onclick="login()">Sign in</button>
  <div class="err" id="err">Incorrect password.</div>
</div>
<script>
const _ci = ['#FF2E00','#FFB400','#C490D1','#97EAD2','#218380'];
const _logo = document.getElementById('logo');
_logo.addEventListener('mouseover', () => { _logo.style.color = _ci[Math.floor(Math.random() * _ci.length)]; });
_logo.addEventListener('mouseout', () => { _logo.style.color = ''; });
document.getElementById('pw').addEventListener('keydown', e => { if (e.key === 'Enter') login(); });
async function login() {
  const pw = document.getElementById('pw').value;
  const r = await fetch('/api/login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
  if (r.ok) { location.href = '/'; }
  else { document.getElementById('err').style.display = 'block'; }
}
</script>
</body>
</html>
"""


def get_vault_path() -> Path:
    """Get primary vault path from config."""
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
        vaults = config.get("human", {}).get("vault", [])
        if vaults:
            return Path(vaults[0]).expanduser()
    return Path.home() / "Documents" / "Vault"


app = FastAPI(title="outheis", docs_url=None, redoc_url=None)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Handle Chromium/Brave Private Network Access preflight
    if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Private-Network"):
        return JSONResponse(
            {},
            headers={
                "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
                "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    # Static assets are always public
    if path in ("/style.css", "/app.js", "/editor.js") or path.startswith("/assets/"):
        return await call_next(request)
    # Login/logout endpoints are always public
    if path in ("/api/login", "/api/logout"):
        return await call_next(request)
    # Auth not configured → open access
    if not _auth_required():
        return await call_next(request)
    # Authenticated → proceed
    if _is_authenticated(request):
        return await call_next(request)
    # Unauthenticated browser request → login page
    if path == "/" or not path.startswith("/api"):
        return HTMLResponse(_LOGIN_PAGE.replace("__OUTHEIS_BRAND__", _BRAND))
    # Unauthenticated API/WS request → 401
    return JSONResponse({"error": "Unauthorized"}, status_code=401)


@app.post("/api/logout")
async def logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(_SESSION_COOKIE, httponly=True, samesite="strict")
    return response


@app.post("/api/login")
async def login(body: dict):
    stored = _get_password()
    plain = body.get("password", "")
    if not stored or not _verify_password(plain, stored):
        return JSONResponse({"error": "Invalid password"}, status_code=401)
    # Migrate plaintext → hash on first successful login
    if stored and not stored.startswith("pbkdf2:"):
        _migrate_password(plain)
    hours = _get_session_hours()
    cookie_value = _make_session_cookie(hours)
    response = JSONResponse({"status": "ok"})
    response.set_cookie(
        _SESSION_COOKIE,
        cookie_value,
        max_age=hours * 3600,
        httponly=True,
        samesite="strict",
    )
    return response


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


@app.get("/api/regions")
async def get_regions():
    """Return supported holiday regions derived from built-in REGIONS registry."""
    from outheis.core.holidays._builtin import REGIONS
    countries: dict[str, list[str]] = {}
    for country, state in REGIONS:
        countries.setdefault(country, [])
        if state:
            countries[country].append(state)
    return {"regions": [{"country": c, "states": sorted(s)} for c, s in sorted(countries.items())]}


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


PAGES_DIR = HUMAN_DIR / "webui" / "pages"


@app.get("/pages/{filename:path}")
async def serve_page(filename: str):
    """Serve user-defined pages from ~/.outheis/human/webui/pages/."""
    path = PAGES_DIR / filename
    if not path.exists() or not path.is_file():
        return HTMLResponse("<p>Not found</p>", status_code=404)
    suffix = path.suffix.lower()
    if suffix == ".html":
        return HTMLResponse(path.read_text(encoding="utf-8"))
    if suffix == ".json":
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))
    return FileResponse(str(path))


@app.get("/agenda")
async def serve_agenda_html():
    """Serve agenda.html from user pages directory."""
    path = PAGES_DIR / "agenda.html"
    if not path.exists():
        return HTMLResponse("<p>agenda.html not found in ~/.outheis/human/webui/pages/</p>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/agenda.json")
async def serve_agenda_json():
    """Serve agenda.json so agenda.html's fetch('agenda.json') resolves correctly."""
    path = PAGES_DIR / "agenda.json"
    if not path.exists():
        return JSONResponse({"error": "agenda.json not found"}, status_code=404)
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.put("/agenda.json")
async def save_agenda_json(data: dict):
    """Save agenda.json from the Source tab editor."""
    path = PAGES_DIR / "agenda.json"
    content = data.get("content", "")
    try:
        json.loads(content)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    path.write_text(content, encoding="utf-8")
    return {"status": "saved"}


@app.get("/webui/pages/{filename:path}")
async def serve_pages_file(filename: str):
    """Serve files from the user pages directory (agenda-ics-*.json etc.)."""
    path = PAGES_DIR / filename
    if not path.exists() or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


_ICS_CONFIG_PATH = PAGES_DIR / "agenda-ics-config.json"


def _read_ics_config() -> dict:
    if _ICS_CONFIG_PATH.exists():
        try:
            return json.loads(_ICS_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_ics_config(cfg: dict) -> None:
    _ICS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ICS_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/agenda/ics-sources")
async def list_ics_sources():
    """List all agenda-ics-*.json files and their metadata."""
    cfg = _read_ics_config()
    sources = []
    for p in sorted(PAGES_DIR.glob("agenda-ics-*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sources.append({
                "file":     p.name,
                "stem":     p.stem[len("agenda-ics-"):],
                "facet":    data.get("meta", {}).get("facet", cfg.get(p.stem, "misc")),
                "imported": data.get("meta", {}).get("imported"),
                "count":    len(data.get("items", [])),
            })
        except Exception:
            pass
    return sources


@app.put("/api/agenda/ics-config")
async def update_ics_config(data: dict):
    """Set facet for one or more ICS sources. Body: {stem: facet, ...}"""
    cfg = _read_ics_config()
    cfg.update(data)
    _write_ics_config(cfg)
    return {"status": "ok"}


@app.post("/api/agenda/upload-ics")
async def upload_ics_file(file: UploadFile = File(...)):
    """Upload an ICS file to vault/Agenda/ and immediately import it."""
    from outheis.core.ics_import import import_ics_to_json
    if not file.filename or not file.filename.endswith(".ics"):
        return JSONResponse({"error": "only .ics files accepted"}, status_code=400)
    vault = get_vault_path()
    agenda_dir = vault / "Agenda"
    agenda_dir.mkdir(parents=True, exist_ok=True)
    dest = agenda_dir / file.filename
    dest.write_bytes(await file.read())
    stem = dest.stem
    cfg = _read_ics_config()
    facet = cfg.get(stem, "misc")
    out_path = PAGES_DIR / f"agenda-ics-{stem}.json"
    count = import_ics_to_json(dest, out_path, facet=facet)
    return {"status": "ok", "stem": stem, "count": count}


@app.post("/api/agenda/scan-ics")
async def scan_ics_files():
    """
    Scan vault/Agenda/*.ics and write per-file agenda-ics-*.json.
    Facets are read from agenda-ics-config.json; unknown files default to 'misc'.
    """
    from outheis.core.ics_import import import_ics_to_json
    cfg = _read_ics_config()
    vault = get_vault_path()
    agenda_dir = vault / "Agenda"
    if not agenda_dir.exists():
        return {"status": "ok", "imported": {}}
    results = {}
    for ics_path in sorted(agenda_dir.glob("*.ics")):
        stem = ics_path.stem
        facet = cfg.get(stem, "misc")
        out_path = PAGES_DIR / f"agenda-ics-{stem}.json"
        try:
            count = import_ics_to_json(ics_path, out_path, facet=facet)
            results[stem] = {"count": count, "facet": facet}
        except Exception as e:
            results[stem] = {"error": str(e)}
    return {"status": "ok", "imported": results}


@app.put("/api/agenda-item")
async def update_agenda_item(data: dict):
    """Update a single item in agenda.json by id.

    Accepts: {id, day?, start?, end?, base_date?}
    Updates the matching item in vault/Codebase/agenda.json.
    """
    import re
    from datetime import date, timedelta

    item_id = data.get("id")
    if not item_id:
        return {"error": "id required"}

    path = PAGES_DIR / "agenda.json"
    if not path.exists():
        return {"error": "agenda.json not found"}

    agenda = json.loads(path.read_text(encoding="utf-8"))
    items = agenda.get("items", [])
    target = next((it for it in items if it.get("id") == item_id), None)
    if target is None:
        return {"error": f"item {item_id} not found"}

    if "day" in data:
        base_str = data.get("base_date", agenda.get("meta", {}).get("base_date", date.today().isoformat()))
        try:
            new_date = date.fromisoformat(base_str) + timedelta(days=int(data["day"]))
            target["day"] = int(data["day"])
        except (ValueError, TypeError):
            return {"error": "invalid day or base_date"}

    if "start" in data:
        target["start"] = data["start"]
    if "end" in data:
        target["end"] = data["end"]
    if "type" in data:
        target["type"] = data["type"]
    if "pos" in data:
        target["pos"] = data["pos"]
    target["source"] = "webui"

    path.write_text(json.dumps(agenda, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "updated", "id": item_id}


@app.post("/api/agenda/migrate-from-shadow")
async def migrate_agenda_from_shadow():
    """Import non-vault items from Shadow.md into agenda.json (one-time migration)."""
    from outheis.core.agenda_store import migrate_from_shadow
    shadow_path = get_vault_path() / "Agenda" / "Shadow.md"
    imported = migrate_from_shadow(shadow_path)
    return {"status": "ok", "imported": imported}


@app.get("/api/codebase")
async def get_codebase_files():
    return list_files(get_vault_path() / "Codebase")


@app.get("/api/codebase/{filename:path}")
async def get_codebase_file(filename: str):
    path = get_vault_path() / "Codebase" / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text()}
    return {"error": "File not found"}


@app.get("/api/files")
async def get_vault_files_flat():
    return list_files(get_vault_path())


@app.get("/api/files/{filename:path}")
async def get_vault_file_flat(filename: str):
    path = get_vault_path() / filename
    if path.exists() and path.suffix == ".md":
        return {"name": filename, "content": path.read_text(encoding="utf-8")}
    return {"error": "File not found"}


@app.put("/api/files/{filename:path}")
async def save_vault_file_flat(filename: str, data: dict):
    path = get_vault_path() / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.get("content", ""), encoding="utf-8")
    return {"status": "saved"}


@app.delete("/api/files/{filename:path}")
async def delete_vault_file_flat(filename: str):
    path = get_vault_path() / filename
    if not path.exists():
        return {"error": "File not found"}
    path.unlink()
    return {"status": "deleted"}


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
async def upload_migration_file(file: UploadFile = File(...)):  # noqa: B008
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
        "files": vault,
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
    import uuid

    from outheis.core.message import create_agent_message
    from outheis.core.queue import append
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
    from outheis.core.message import create_user_message
    from outheis.core.queue import append
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
    import uuid

    from outheis.core.message import create_agent_message
    from outheis.core.queue import append
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
        from outheis.dispatcher.daemon import read_pid
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
        from datetime import datetime

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
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
    fallback_failed_providers: list[str] = []
    status_path = HUMAN_DIR / "system_status.json"
    if status_path.exists():
        try:
            s = json.loads(status_path.read_text())
            system_mode = s.get("mode", "normal")
            fallback_reason = s.get("reason")
            fallback_failed_providers = s.get("failed_providers", [])
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
        "fallback_failed_providers": fallback_failed_providers,
        "auth_required": _auth_required(),
    }


_version_cache: dict = {"ts": 0.0, "data": None}
_VERSION_CACHE_TTL = 3600  # seconds


@app.get("/api/ollama/models")
async def get_ollama_models():
    """Return locally available Ollama models. Always fetched live so newly pulled models appear."""
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"available": True, "models": models}
    except Exception:
        pass
    return {"available": False, "models": []}


@app.get("/api/version")
async def get_version():
    import time

    from outheis import __version__

    now = time.time()
    if _version_cache["data"] and now - _version_cache["ts"] < _VERSION_CACHE_TTL:
        return _version_cache["data"]

    result: dict = {"current": __version__, "latest": None, "update_available": False, "release_date": None}

    try:
        import httpx
        resp = httpx.get("https://pypi.org/pypi/outheis/json", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            latest = data["info"]["version"]
            result["latest"] = latest
            from packaging.version import Version
            result["update_available"] = Version(latest) > Version(__version__)
            # Release date from the first wheel/sdist upload time
            artifacts = data.get("releases", {}).get(latest, [])
            if artifacts:
                upload_time = artifacts[0].get("upload_time", "")
                if upload_time:
                    result["release_date"] = upload_time[:16].replace("T", " ")  # YYYY-MM-DD HH:MM
    except Exception:
        pass

    _version_cache["ts"] = now
    _version_cache["data"] = result
    return result


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
    str(get_human_dir() / "dispatcher.log")

    # Resolve outheis executable: same bin/ dir as the running Python interpreter
    from pathlib import Path as _Path
    outheis_cmd = str(_Path(sys.executable).parent / "outheis")
    if not _Path(outheis_cmd).exists():
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


@app.post("/api/update")
async def update_package():
    import json
    import shutil
    import subprocess
    import sys
    from pathlib import Path as _Path

    from outheis.dispatcher.daemon import read_pid

    current_pid = read_pid()

    # Resolve outheis binary: prefer sibling of current interpreter, fall back to PATH
    outheis_cmd = str(_Path(sys.executable).parent / "outheis")
    if not _Path(outheis_cmd).exists():
        outheis_cmd = shutil.which("outheis") or sys.argv[0]

    pipx_bin = shutil.which("pipx")
    using_pipx = bool(pipx_bin and ("pipx" in sys.executable or (
        subprocess.run(
            [pipx_bin, "list", "--short"], capture_output=True, text=True,
        ).stdout.find("outheis") != -1
    )))
    if using_pipx:
        upgrade_cmd = [pipx_bin, "upgrade", "outheis"]
    else:
        upgrade_cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "outheis"]

    log_path = str(_Path.home() / ".outheis" / "update.log")

    # Pass data via JSON to avoid repr() serialisation issues with env values
    payload = json.dumps({
        "pid": current_pid or 0,
        "upgrade_cmd": upgrade_cmd,
        "start_cmd": [outheis_cmd, "start"],
        "log_path": log_path,
    })

    script = r"""
import json, os, sys, time, signal, subprocess
from pathlib import Path

data = json.loads(sys.argv[1])
pid          = data["pid"]
upgrade_cmd  = data["upgrade_cmd"]
start_cmd    = data["start_cmd"]
log_path     = data["log_path"]

Path(log_path).parent.mkdir(parents=True, exist_ok=True)

def log(msg):
    with open(log_path, "a") as f:
        f.write(msg + "\n")

log(f"=== update started ===")
time.sleep(1)

if pid:
    log(f"stopping daemon (pid {pid})")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        log("daemon already gone")
    for _ in range(20):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            log("daemon stopped")
            break

log(f"running: {upgrade_cmd}")
r = subprocess.run(upgrade_cmd, capture_output=True, text=True)
log(r.stdout[-2000:] if r.stdout else "(no stdout)")
if r.returncode != 0:
    log(f"upgrade failed (rc={r.returncode}): {r.stderr[-1000:]}")
    sys.exit(1)
log("upgrade ok")

time.sleep(1)
log(f"running: {start_cmd}")
r2 = subprocess.run(start_cmd, capture_output=True, text=True)
if r2.returncode != 0:
    log(f"start failed (rc={r2.returncode}): {r2.stderr[-1000:]}")
else:
    log("start ok")
"""

    subprocess.Popen(
        [sys.executable, "-c", script, payload],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Invalidate version cache so next check reflects new version
    _version_cache["ts"] = 0.0
    _version_cache["data"] = None

    return {"status": "updating", "log": log_path}


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
    if _auth_required() and not _verify_session_cookie(websocket.cookies.get(_SESSION_COOKIE, "")):
        await websocket.close(code=1008)
        return
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
