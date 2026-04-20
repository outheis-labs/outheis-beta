"""
CLI application.

Entry point for outheis command-line interface.
"""

from __future__ import annotations

import typer

from outheis import __version__

app = typer.Typer(
    name="outheis",
    help="Multi-agent personal assistant",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
    ),
) -> None:
    """outheis — Multi-agent personal assistant."""
    if version:
        typer.echo(f"outheis {__version__}")
        raise typer.Exit()


@app.command()
def init() -> None:
    """Interactive setup wizard for outheis."""
    import os
    import shutil
    import subprocess
    from datetime import date, timedelta

    from outheis.core.config import (
        Config,
        HumanConfig,
        SignalConfig,
        AllowedContact,
        LLMConfig,
        ProviderConfig,
        ModelConfig,
        AgentConfig,
        UpdatesConfig,
        get_config_path,
        get_human_dir,
        load_config,
        save_config,
        init_directories,
    )

    typer.echo("\n" + "=" * 50)
    typer.echo("Welcome to outheis!")
    typer.echo("=" * 50)
    typer.echo("\nThis wizard will guide you through the setup.")
    typer.echo("Press Enter to keep existing values shown in [brackets].\n")

    # === PREREQUISITE CHECK: signal-cli ===
    signal_cli_path = shutil.which("signal-cli")
    if not signal_cli_path:
        typer.echo("─" * 50)
        typer.echo("Optional: signal-cli")
        typer.echo("─" * 50)
        typer.echo("\nsignal-cli enables Signal Messenger integration (optional).")
        typer.echo("Without it, outheis is fully usable via the WebUI and CLI.")
        typer.echo("\n  macOS:  brew install signal-cli")
        typer.echo("  Linux:  apt install signal-cli")
        typer.echo("  Other:  https://github.com/AsamK/signal-cli\n")
        if not typer.confirm("Continue without signal-cli?", default=True):
            raise typer.Exit(0)
        typer.echo("")
    else:
        typer.echo(f"✓ signal-cli found: {signal_cli_path}\n")

    # Load existing config or create new
    init_directories()
    try:
        config = load_config()
    except Exception:
        config = Config()

    # === HUMAN SECTION ===
    typer.echo("─" * 50)
    typer.echo("Human (Administrator)")
    typer.echo("─" * 50 + "\n")

    default_name = config.human.name or "Human"
    name = typer.prompt("Your name", default=default_name)

    default_lang = config.human.language or "en"
    language = typer.prompt("Language (en/de/fr/es/it)", default=default_lang)

    default_tz = config.human.timezone or "Europe/Berlin"
    timezone = typer.prompt("Timezone", default=default_tz)

    default_phones = ", ".join(config.human.phone) if config.human.phone else ""
    phones_str = typer.prompt("Your phone number(s), comma-separated", default=default_phones or "")
    phones = [p.strip() for p in phones_str.split(",") if p.strip()]

    default_vault = config.human.vault[0] if config.human.vault else "~/Documents/Vault"
    vault_path = typer.prompt("Vault path", default=default_vault)

    config.human = HumanConfig(
        name=name,
        phone=phones,
        language=language,
        timezone=timezone,
        vault=[vault_path],
    )

    # === LLM SECTION ===
    typer.echo("\n" + "─" * 50)
    typer.echo("LLM Configuration")
    typer.echo("─" * 50 + "\n")
    typer.echo("outheis uses Anthropic Claude by default.")
    typer.echo("Local models (Ollama) are also supported — see https://ollama.com\n")

    existing_key = config.llm.providers.get("anthropic", ProviderConfig()).api_key
    masked = f"{existing_key[:10]}...{existing_key[-4:]}" if existing_key else ""

    api_key_input = typer.prompt(
        "Anthropic API key (leave blank to use Ollama only)",
        default=masked or "",
        hide_input=False,
    )

    if api_key_input and api_key_input != masked:
        api_key = api_key_input
    else:
        api_key = existing_key

    if api_key:
        typer.echo("Validating API key...", nl=False)
        if _validate_anthropic_key(api_key):
            typer.echo(" ✓")
        else:
            typer.echo(" ✗ invalid")
            if not typer.confirm("Continue anyway?"):
                raise typer.Exit(1)
    else:
        typer.echo("No Anthropic key — configure Ollama in config.json after setup.")
        typer.echo("See https://ollama.com for installation instructions.\n")

    config.llm.providers["anthropic"] = ProviderConfig(api_key=api_key)

    # === SIGNAL SECTION ===
    typer.echo("\n" + "─" * 50)
    typer.echo("Signal Messenger (optional)")
    typer.echo("─" * 50 + "\n")

    if signal_cli_path:
        enable_signal = typer.confirm("Enable Signal?", default=config.signal.enabled)

        if enable_signal:
            default_bot_phone = config.signal.bot_phone or ""
            bot_phone = typer.prompt("Bot phone number", default=default_bot_phone)

            if bot_phone:
                typer.echo(f"Checking registration for {bot_phone}...", nl=False)
                registered = _check_signal_registration(bot_phone)
                if registered:
                    typer.echo(" ✓ registered")
                else:
                    typer.echo(" ✗ not registered")
                    if typer.confirm("Register now?"):
                        _register_signal(bot_phone)

            default_bot_name = config.signal.bot_name or "Ou"
            bot_name = typer.prompt("Bot display name", default=default_bot_name)

            config.signal = SignalConfig(
                enabled=True,
                bot_phone=bot_phone,
                bot_name=bot_name,
                allowed=config.signal.allowed,
            )
        else:
            config.signal.enabled = False
    else:
        typer.echo("signal-cli not found — skipping Signal setup.")
        typer.echo("Install it and re-run 'outheis init' to enable Signal.\n")

    # === WEBUI SECTION ===
    typer.echo("\n" + "─" * 50)
    typer.echo("Web UI")
    typer.echo("─" * 50 + "\n")
    typer.echo("The Web UI runs as a local HTTP server accessible via browser.")
    typer.echo("Use 127.0.0.1 (localhost only) or 0.0.0.0 (all interfaces, e.g. for remote access).\n")

    default_host = config.webui.host or "127.0.0.1"
    config.webui.host = typer.prompt("Bind address", default=default_host)

    default_port = config.webui.port or 8080
    config.webui.port = typer.prompt("Port", default=default_port)

    typer.echo()
    typer.echo("Set a password to protect the Web UI (recommended when using remote access).\n")

    existing_pw = config.webui.password or ""
    masked_pw = "****" if existing_pw else ""
    pw_input = typer.prompt(
        "Web UI password (leave blank for no authentication)",
        default=masked_pw or "",
        hide_input=True,
    )
    if pw_input and pw_input != masked_pw:
        config.webui.password = pw_input
    elif pw_input == "":
        config.webui.password = ""
    # else: keep existing

    if config.webui.password:
        default_hours = config.webui.session_hours or 4
        config.webui.session_hours = typer.prompt("Session duration (hours)", default=default_hours)
        typer.echo("✓ Password set.")
    else:
        typer.echo("No password — Web UI is open to anyone with access to the host.")

    # === SAVE CONFIG ===
    save_config(config)
    typer.echo("\n" + "─" * 50)
    typer.echo("Setup complete!")
    typer.echo("─" * 50 + "\n")
    typer.echo(f"✓ Config saved to {get_config_path()}")

    # === VAULT + AGENDA SCAFFOLD ===
    vault_expanded = os.path.expanduser(vault_path)
    agenda_dir_path = os.path.join(vault_expanded, "Agenda")

    os.makedirs(agenda_dir_path, exist_ok=True)
    if not os.path.exists(vault_expanded):
        typer.echo(f"✓ Created vault directory: {vault_expanded}")

    agenda_path = os.path.join(agenda_dir_path, "Agenda.md")
    if not os.path.exists(agenda_path):
        scaffold = _build_agenda_scaffold(language)
        with open(agenda_path, "w", encoding="utf-8") as f:
            f.write(scaffold)
        typer.echo(f"✓ Created {agenda_path}")
    else:
        typer.echo(f"⏭ {agenda_path} exists, skipping")

    typer.echo(f"\nRun 'outheis start' to begin.\n")


def _validate_anthropic_key(api_key: str) -> bool:
    """Validate Anthropic API key with a minimal request."""
    if not api_key or not api_key.startswith("sk-ant-"):
        return False
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return True
    except Exception:
        return False


def _build_agenda_scaffold(language: str) -> str:
    """Build a correctly structured empty Agenda.md for the given language."""
    from datetime import date, timedelta
    from outheis.core.i18n import AGENDA_LABELS, WEEKDAYS

    lang = language[:2].lower()
    lbl = AGENDA_LABELS.get(lang, AGENDA_LABELS["en"])
    wdays = WEEKDAYS.get(lang, WEEKDAYS["en"])

    today = date.today()
    week_num = today.isocalendar()[1]
    weekday = wdays[today.weekday()]
    date_str = today.strftime("%d.%m.%Y")

    lines = [
        f"## ⛅ {weekday}, {date_str}",
        f"*{lbl['week']} {week_num} / {lbl['generated']}: —*",
        "",
        "---",
        "",
        f"## 🧘 {lbl['personal']}",
        "",
        "- [ ] ",
        "",
        "---",
        "",
        f"## 📅 {lbl['today_hdr']}",
        "",
        lbl["empty_today"],
        "",
        "---",
        "",
        f"## 🗓️ {lbl['week_hdr']}",
        "",
        lbl["empty_week"],
        "",
        "---",
        "",
        "## 💶 Cashflow",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _check_signal_registration(phone: str) -> bool:
    """Check if a phone number is registered with signal-cli."""
    import subprocess
    try:
        result = subprocess.run(
            ["signal-cli", "-a", phone, "listAccounts"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return phone in result.stdout
    except Exception:
        return False


def _register_signal(phone: str) -> bool:
    """Register a phone number with signal-cli."""
    import subprocess
    
    typer.echo(f"\nRegistering {phone} with Signal...")
    typer.echo("Signal will send an SMS with a verification code.\n")
    
    use_voice = typer.confirm("Use voice call instead of SMS?", default=False)
    
    try:
        # Request verification
        cmd = ["signal-cli", "-a", phone, "register"]
        if use_voice:
            cmd.append("--voice")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            typer.echo(f"Error: {result.stderr}")
            return False
        
        # Get code from user
        code = typer.prompt("Enter verification code")
        
        # Verify
        result = subprocess.run(
            ["signal-cli", "-a", phone, "verify", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode == 0:
            typer.echo("✓ Registration successful!")
            return True
        else:
            typer.echo(f"Error: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        typer.echo("Timeout — try again later")
        return False
    except Exception as e:
        typer.echo(f"Error: {e}")
        return False


@app.command()
def update(
    source: str = typer.Option(
        None,
        "--from",
        help="Install from a specific .whl path or URL instead of the default index",
    ),
) -> None:
    """Update outheis to the latest version."""
    import shutil
    import subprocess
    import sys

    from outheis.dispatcher.daemon import read_pid, start_daemon, stop_daemon

    was_running = read_pid() is not None

    # Fetch version info from PyPI before doing anything
    latest_version = None
    release_date = None
    skipped_versions: list[str] = []
    if not source:
        try:
            import urllib.request as _urllib
            import json as _json
            with _urllib.urlopen("https://pypi.org/pypi/outheis/json", timeout=5) as r:
                data = _json.loads(r.read())
            latest_version = data["info"]["version"]
            releases = data.get("releases", {}).get(latest_version, [])
            if releases:
                upload_time = releases[0].get("upload_time", "")
                release_date = upload_time[:10] if upload_time else None
            # Collect intermediate versions using simple tuple comparison (no packaging needed)
            def _ver_tuple(v: str) -> tuple[int, ...]:
                try:
                    return tuple(int(x) for x in v.split(".") if x.isdigit())
                except Exception:
                    return (0,)
            current_t = _ver_tuple(__version__)
            latest_t = _ver_tuple(latest_version)
            all_versions = sorted(
                (v for v in data.get("releases", {})),
                key=_ver_tuple,
            )
            skipped_versions = [
                v for v in all_versions
                if current_t < _ver_tuple(v) < latest_t
            ]
        except Exception:
            pass

    if latest_version and latest_version == __version__:
        typer.echo(f"outheis {__version__} is already the latest release.")
        raise typer.Exit()

    typer.echo(f"Updating outheis {__version__} → latest...")
    if skipped_versions:
        typer.echo(f"  {len(skipped_versions)} intermediate release(s) skipped: {', '.join(skipped_versions)}")

    if was_running:
        typer.echo("Stopping daemon...")
        stop_daemon()

    if source:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", source]
    else:
        # Prefer pipx if outheis was installed that way
        exe = sys.executable
        pipx_bin = shutil.which("pipx")
        using_pipx = pipx_bin and ("pipx" in exe or (
            pipx_bin and subprocess.run(
                [pipx_bin, "list", "--short"], capture_output=True, text=True,
            ).stdout.find("outheis") != -1
        ))
        if using_pipx:
            cmd = [pipx_bin, "upgrade", "outheis"]
        else:
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "outheis"]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        typer.echo(f"Update failed:\n{result.stderr or result.stdout}", err=True)
        if was_running:
            typer.echo("Restarting daemon with current version...")
            start_daemon()
        raise typer.Exit(1)

    # Determine the actually installed version by querying pip directly.
    # importlib.metadata reads the running process — still shows old version.
    installed_version: str | None = None
    try:
        show = subprocess.run(
            [sys.executable, "-m", "pip", "show", "outheis"],
            capture_output=True, text=True,
        )
        import re as _re
        m = _re.search(r"^Version:\s*(\S+)", show.stdout, _re.MULTILINE)
        if m:
            installed_version = m.group(1)
    except Exception:
        pass

    if installed_version and installed_version == __version__:
        typer.echo(f"outheis {__version__} — already up to date.")
        raise typer.Exit()

    date_str = f", released {release_date}" if release_date else ""
    if installed_version:
        typer.echo(f"Updated to outheis {installed_version}{date_str}.")
    elif latest_version:
        typer.echo(f"Updated to outheis {latest_version}{date_str}.")
    else:
        typer.echo("outheis updated.")

    if was_running:
        typer.echo("Restarting daemon...")
        start_daemon()


@app.command()
def start(
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help="Run in foreground (don't daemonize)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug output (routing, delegation)",
    ),
    human_dir: str = typer.Option(
        None,
        "--human",
        help="Override human data directory (default: ~/.outheis/human)",
    ),
    vault_path: str = typer.Option(
        None,
        "--vault",
        help="Override vault path",
    ),
) -> None:
    """Start the outheis dispatcher daemon."""
    import os
    from outheis.core.config import init_directories
    from outheis.dispatcher.daemon import start_daemon

    # Set environment overrides
    if human_dir:
        os.environ["OUTHEIS_HUMAN_DIR"] = human_dir
    if vault_path:
        os.environ["OUTHEIS_VAULT"] = vault_path
    if verbose:
        os.environ["OUTHEIS_VERBOSE"] = "1"

    init_directories()

    if foreground:
        typer.echo("Starting dispatcher in foreground (Ctrl+C to stop)...")

    success = start_daemon(foreground=foreground)
    if not success and not foreground:
        raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop the outheis dispatcher daemon."""
    from outheis.dispatcher.daemon import stop_daemon

    success = stop_daemon()
    if not success:
        raise typer.Exit(1)


@app.command()
def send(
    message: str = typer.Argument(..., help="Message to send"),
    timeout: float = typer.Option(60.0, "--timeout", "-t", help="Response timeout in seconds"),
) -> None:
    """Send a message and wait for response."""
    import sys
    import time
    
    from outheis.dispatcher.daemon import daemon_status
    from outheis.transport.cli import CLITransport

    # Check if daemon is running
    status = daemon_status()
    if not status["running"]:
        typer.echo("Dispatcher not running. Start it with: outheis start")
        raise typer.Exit(1)

    transport = CLITransport()
    msg = transport.send(message)

    # Wait for response with progress indicator
    # Braille column animation: ⡀ → ⡄ → ⡆ → ⡇ → ⣇ → ⣧ → ⣷ → ⣿ → ⣾ → ⣼ → ⣸ → ⣰ → ⣠ → ⣀ → ⢀ → (space) → repeat
    start = time.time()
    spinner = ['⡀', '⡄', '⡆', '⡇', '⣇', '⣧', '⣷', '⣿', '⣾', '⣼', '⣸', '⣰', '⣠', '⣀', '⢀', ' ']
    spinner_idx = 0
    
    while time.time() - start < timeout:
        # Check for response
        response = transport.check_for_response(msg.id)
        if response:
            # Clear spinner line
            sys.stdout.write('\r' + ' ' * 40 + '\r')
            sys.stdout.flush()
            
            # Display response
            text = response.payload.get('text') or response.payload.get('answer', '')
            if response.payload.get('error'):
                typer.echo(f"[Error: {text}]")
            else:
                typer.echo(text)
            return
        
        # Show spinner with elapsed time
        elapsed = int(time.time() - start)
        sys.stdout.write(f'\r{spinner[spinner_idx]} Waiting for response... ({elapsed}s)')
        sys.stdout.flush()
        spinner_idx = (spinner_idx + 1) % len(spinner)
        time.sleep(0.3)
    
    # Timeout
    sys.stdout.write('\r' + ' ' * 40 + '\r')
    sys.stdout.flush()
    typer.echo("[no response within timeout]")


@app.command()
def chat() -> None:
    """Start interactive chat session (requires running dispatcher)."""
    import readline
    from outheis.dispatcher.daemon import daemon_status
    from outheis.transport.cli import CLITransport

    # Check if daemon is running
    status = daemon_status()
    if not status["running"]:
        typer.echo("Dispatcher not running. Start it with: outheis start")
        raise typer.Exit(1)

    # Configure readline for history
    readline.set_history_length(10)
    
    typer.echo("outheis CLI (type 'exit' to quit)")
    typer.echo("-" * 40)

    transport = CLITransport()

    while True:
        try:
            text = input("\n>: ").strip()

            if not text:
                continue

            if text.lower() in ("exit", "quit", "q"):
                break

            msg = transport.send(text)
            response = transport.wait_for_response(msg.id, timeout=120.0)

            if response:
                text = response.payload.get('text') or response.payload.get('answer', '')
                if response.payload.get('error'):
                    typer.echo(f"[Error: {text}]")
                else:
                    typer.echo(f"\n{text}")
            else:
                typer.echo("[no response]")

        except KeyboardInterrupt:
            typer.echo("\n[interrupted]")
            break
        except EOFError:
            break

    typer.echo("\nGoodbye.")


@app.command()
def status() -> None:
    """Show system status."""
    from outheis.core.config import (
        get_messages_path,
        load_config,
    )
    from outheis.core.queue import message_count, queue_size
    from outheis.dispatcher.daemon import daemon_status

    config = load_config()
    queue_path = get_messages_path()
    dstatus = daemon_status()

    typer.echo("outheis status")
    typer.echo("-" * 40)

    # Daemon status
    if dstatus["running"]:
        typer.echo(f"Dispatcher: running (PID {dstatus['pid']})")
    else:
        typer.echo("Dispatcher: stopped")

    typer.echo()
    typer.echo(f"User: {config.human.name}")
    typer.echo(f"Language: {config.human.language}")
    typer.echo(f"Timezone: {config.human.timezone}")
    typer.echo(f"Primary vault: {config.human.primary_vault()}")
    typer.echo()
    typer.echo(f"Messages: {message_count(queue_path)}")
    typer.echo(f"Queue size: {queue_size(queue_path)} bytes")

    # Task registry (from file — works without running dispatcher or WebUI)
    from outheis.dispatcher.daemon import read_task_registry
    tasks = read_task_registry()
    if tasks:
        typer.echo()
        typer.echo("Tasks:")
        for rec in sorted(tasks.values(), key=lambda r: r.get("started_at", "")):
            status = rec.get("status", "?")
            name = rec.get("name", "?")
            started = rec.get("started_at", "")[:19].replace("T", " ")
            finished = rec.get("finished_at", "")
            if finished:
                finished = finished[:19].replace("T", " ")
                duration = ""
                try:
                    from datetime import datetime as _dt
                    d = _dt.fromisoformat(rec["finished_at"]) - _dt.fromisoformat(rec["started_at"])
                    duration = f" ({int(d.total_seconds())}s)"
                except Exception:
                    pass
                typer.echo(f"  {name}: {status}{duration}  [{started} → {finished}]")
            else:
                typer.echo(f"  {name}: {status}  [started {started}]")
            if rec.get("error"):
                typer.echo(f"    error: {rec['error']}")


@app.command()
def migrate(
    scan: bool = typer.Option(False, "--scan", help="Scan for outdated records"),
    apply: bool = typer.Option(False, "--apply", help="Apply migrations"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Quiet mode"),
) -> None:
    """Scan for and apply schema migrations."""
    from outheis.core.config import get_insights_path, get_messages_path
    from outheis.core.schema import (
        INSIGHTS_VERSION,
        MESSAGES_VERSION,
        scan_file,
    )

    files_to_scan = [
        (get_messages_path(), "Message", MESSAGES_VERSION),
        (get_insights_path(), "Insight", INSIGHTS_VERSION),
    ]

    total_outdated = 0

    for path, record_type, current_version in files_to_scan:
        if not path.exists():
            continue

        report = scan_file(str(path), record_type, current_version)
        total_outdated += report.outdated

        if not quiet and report.outdated > 0:
            typer.echo(
                f"Found {report.outdated} {record_type}s at old version "
                f"(current: v{current_version})"
            )
            for v, count in sorted(report.versions_found.items()):
                if v < current_version:
                    typer.echo(f"  v{v}: {count} records")

    if scan and not apply:
        if total_outdated == 0:
            typer.echo("All records up to date.")
        else:
            typer.echo(f"\nTotal: {total_outdated} outdated records")
            typer.echo("Run 'outheis migrate --apply' to convert")
        return

    if apply:
        if total_outdated == 0:
            if not quiet:
                typer.echo("Nothing to migrate.")
            return

        # TODO: Implement actual migration
        typer.echo("Migration not yet implemented.")
        typer.echo("Records will be migrated on-the-fly when read.")


# =============================================================================
# PATTERN
# =============================================================================

pattern_app = typer.Typer(help="Pattern agent commands")
app.add_typer(pattern_app, name="pattern")


@pattern_app.command("run")
def pattern_run(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be done"),
) -> None:
    """Run full Pattern agent cycle (like nightly 04:00 run)."""
    from outheis.agents.pattern import create_pattern_agent

    typer.echo("Running Pattern agent (full cycle)...")

    agent = create_pattern_agent()

    if dry_run:
        typer.echo("[dry-run] Would process seed files")
        typer.echo("[dry-run] Would apply approved seeds")
        typer.echo("[dry-run] Would analyze recent conversations")
        typer.echo("[dry-run] Would consolidate memory")
        return

    agent.run_scheduled()
    typer.echo("✓ Pattern agent cycle complete.")


@pattern_app.command("seed")
def pattern_seed(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be done"),
) -> None:
    """Process seed files only (stage for approval)."""
    from outheis.agents.pattern import create_pattern_agent
    from outheis.core.config import get_human_dir

    seed_dir = get_human_dir() / "memory" / "seed"
    
    if not seed_dir.exists():
        typer.echo(f"No seed directory: {seed_dir}")
        typer.echo("Create it and add .json files to migrate memory.")
        return
    
    # Count unprocessed files
    files = [f for f in seed_dir.glob("*.json") if not f.name.startswith("x-")]
    if not files:
        typer.echo("No unprocessed seed files found.")
        staging = get_human_dir() / "memory" / "seed.json"
        if staging.exists():
            typer.echo(f"Pending approvals in: {staging}")
        return

    typer.echo(f"Found {len(files)} seed file(s):")
    for f in files:
        typer.echo(f"  - {f.name}")

    if dry_run:
        typer.echo("[dry-run] Would process and stage entries")
        return

    agent = create_pattern_agent()
    agent.process_seed_files()
    typer.echo("✓ Seed files processed. Check ~/.outheis/human/memory/seed.json")


@pattern_app.command("apply")
def pattern_apply() -> None:
    """Apply approved seed entries to memory."""
    from outheis.agents.pattern import create_pattern_agent
    from outheis.core.config import get_human_dir

    staging = get_human_dir() / "memory" / "seed.json"
    
    if not staging.exists():
        typer.echo("No staging file found. Run 'outheis pattern seed' first.")
        return

    agent = create_pattern_agent()
    agent.apply_approved_seeds()
    typer.echo("✓ Approved entries applied to memory.")


@pattern_app.command("analyze")
def pattern_analyze(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be done"),
) -> None:
    """Analyze recent conversations and extract memories."""
    from outheis.agents.pattern import create_pattern_agent

    typer.echo("Analyzing recent conversations...")

    agent = create_pattern_agent()

    if dry_run:
        typer.echo("[dry-run] Would analyze recent conversations")
        typer.echo("[dry-run] Would extract memories")
        return

    count = agent.analyze_recent_conversations()
    typer.echo(f"✓ Extracted {count} new memory entries.")


@app.command("pattern-legacy", hidden=True)
def pattern(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be done"),
) -> None:
    """[Deprecated] Use 'outheis pattern run' instead."""
    typer.echo("Hint: Use 'outheis pattern run' for full cycle")
    typer.echo("      or 'outheis pattern analyze' for memory extraction only")
    pattern_analyze(dry_run=dry_run)


@app.command()
def memory(
    show: bool = typer.Option(True, "--show", "-s", help="Show current memory"),
    add: str = typer.Option(None, "--add", "-a", help="Add memory entry (format: type:content)"),
    clear: str = typer.Option(None, "--clear", "-c", help="Clear memory type (user/feedback/context)"),
) -> None:
    """View and manage persistent memory."""
    from outheis.core.memory import get_memory_store
    
    store = get_memory_store()
    
    if add:
        # Parse "type:content" format
        if ":" not in add:
            typer.echo("Format: --add 'type:content' (type = user/feedback/context)")
            raise typer.Exit(1)
        
        memory_type, content = add.split(":", 1)
        memory_type = memory_type.strip().lower()
        content = content.strip()
        
        if memory_type not in ["user", "feedback", "context"]:
            typer.echo(f"Invalid type: {memory_type}. Use user/feedback/context.")
            raise typer.Exit(1)
        
        store.add(content, memory_type)
        typer.echo(f"Added to {memory_type}: {content}")
        return
    
    if clear:
        if clear not in ["user", "feedback", "context", "all"]:
            typer.echo("Use: --clear user/feedback/context/all")
            raise typer.Exit(1)
        
        if clear == "all":
            for mt in ["user", "feedback", "context"]:
                store.clear(mt)
            typer.echo("Cleared all memory.")
        else:
            store.clear(clear)
            typer.echo(f"Cleared {clear} memory.")
        return
    
    # Show memory
    typer.echo("Memory")
    typer.echo("-" * 40)
    
    for memory_type in ["user", "feedback", "context"]:
        entries = store.get(memory_type)
        typer.echo(f"\n[{memory_type}] ({len(entries)} entries)")
        for i, entry in enumerate(entries):
            # Build status indicators
            markers = []
            if entry.is_explicit:
                markers.append("!")
            if entry.confidence < 1.0:
                markers.append(f"{entry.confidence:.0%}")
            if entry.decay_days:
                from datetime import datetime, timedelta
                expiry = entry.updated_at + timedelta(days=entry.decay_days)
                days_left = (expiry - datetime.now()).days
                if days_left > 0:
                    markers.append(f"↓{days_left}d")
                else:
                    markers.append("expired")
            
            status = f" [{', '.join(markers)}]" if markers else ""
            typer.echo(f"  {i+1}. {entry.content}{status}")
    
    typer.echo()


@app.command()
def rules(
    agent: str = typer.Argument(None, help="Agent name (relay, data, agenda, action, pattern)"),
    user_only: bool = typer.Option(False, "--user", "-u", help="Show only user rules"),
    system_only: bool = typer.Option(False, "--system", "-s", help="Show only system rules"),
) -> None:
    """View rules for agents."""
    from outheis.agents.loader import (
        get_system_rules_dir,
        get_user_rules_dir,
        list_user_rules,
    )
    
    system_dir = get_system_rules_dir()
    user_dir = get_user_rules_dir()
    
    agents = ["common", "relay", "data", "agenda", "action", "pattern"]
    
    if agent:
        if agent not in agents:
            typer.echo(f"Unknown agent: {agent}. Use: {', '.join(agents)}")
            raise typer.Exit(1)
        agents = [agent]
    
    for ag in agents:
        typer.echo(f"\n{'='*40}")
        typer.echo(f"[{ag}]")
        typer.echo('='*40)
        
        # System rules
        if not user_only:
            system_file = system_dir / f"{ag}.md"
            if system_file.exists():
                typer.echo("\n## System Rules")
                content = system_file.read_text()
                # Show first 500 chars or summary
                if len(content) > 500:
                    typer.echo(content[:500] + "\n...")
                else:
                    typer.echo(content)
            else:
                typer.echo("\n## System Rules: (none)")
        
        # User rules
        if not system_only:
            user_file = user_dir / f"{ag}.md"
            if user_file.exists():
                typer.echo("\n## User Rules (emergent)")
                typer.echo(user_file.read_text())
            else:
                typer.echo("\n## User Rules: (none yet)")
    
    typer.echo()


# =============================================================================
# TASK COMMANDS
# =============================================================================

task_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(task_app, name="task")


def _get_cli_source() -> "TaskSource":
    """Create TaskSource for CLI context."""
    import os
    import socket
    from datetime import datetime
    from outheis.agents.tasks.base import TaskSource
    
    return TaskSource(
        timestamp=datetime.now(),
        interface="cli",
        user=os.environ.get("USER", "unknown"),
        host=socket.gethostname(),
    )


@task_app.command("list")
def task_list() -> None:
    """List all registered tasks."""
    from outheis.agents.tasks import get_registry
    
    registry = get_registry()
    
    if not registry.tasks:
        typer.echo("No tasks registered.")
        typer.echo("\nAdd a task with: outheis task add <instruction>")
        return
    
    typer.echo(f"\n{'ID':<20} {'Name':<25} {'Schedule':<15} {'Next Run':<20}")
    typer.echo("-" * 80)
    
    for task in registry.tasks.values():
        next_run = task.next_run.strftime("%Y-%m-%d %H:%M") if task.next_run else "—"
        status = "✓" if task.enabled else "✗"
        typer.echo(f"{status} {task.id:<18} {task.name:<25} {task.schedule.value:<15} {next_run:<20}")
    
    typer.echo()


@task_app.command("add")
def task_add(
    instruction: str = typer.Argument(..., help="What should the task do?"),
    task_id: str = typer.Option(None, "--id", help="Task ID (auto-generated if not provided)"),
    times: str = typer.Option("08:00,18:00", "--times", "-t", help="Execution times (comma-separated)"),
) -> None:
    """Add a new task from natural language instruction."""
    from datetime import datetime
    from outheis.agents.tasks import get_registry
    from outheis.agents.tasks.news import create_sz_task
    
    # For now, only SZ headlines task is supported
    # TODO: Parse instruction and create appropriate task type
    
    if "sz" in instruction.lower() or "sueddeutsche" in instruction.lower() or "headlines" in instruction.lower():
        # Create SZ headlines task
        if not task_id:
            task_id = f"sz-headlines-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        time_list = [t.strip() for t in times.split(",")]
        source = _get_cli_source()
        
        task = create_sz_task(
            task_id=task_id,
            times=time_list,
            source=source,
            instruction=instruction,
        )
        
        registry = get_registry()
        registry.add(task)
        
        typer.echo(f"✓ Task '{task.name}' created")
        typer.echo(f"  ID: {task.id}")
        typer.echo(f"  Schedule: {task.schedule.value} at {', '.join(task.times)}")
        typer.echo(f"  Next run: {task.next_run.strftime('%Y-%m-%d %H:%M') if task.next_run else '—'}")
        typer.echo(f"  Directory: {task.get_task_dir()}")
    else:
        typer.echo("⚠ Currently only SZ headlines tasks are supported.")
        typer.echo("  Try: outheis task add 'SZ Headlines twice daily'")
        raise typer.Exit(1)


@task_app.command("run")
def task_run(
    task_id: str = typer.Argument(..., help="Task ID to run"),
) -> None:
    """Run a task immediately."""
    from outheis.agents.tasks import get_registry
    
    registry = get_registry()
    task = registry.get(task_id)
    
    if not task:
        typer.echo(f"✗ Task not found: {task_id}")
        raise typer.Exit(1)
    
    typer.echo(f"Running '{task.name}'...")
    
    result = task.execute()
    
    if result.success:
        typer.echo(f"✓ Success")
        typer.echo("\nOutput:")
        typer.echo(task.format_for_agenda(result))
        
        # Save to history
        registry.mark_completed(task, result)
    else:
        typer.echo(f"✗ Failed: {result.error}")
        raise typer.Exit(1)


@task_app.command("remove")
def task_remove(
    task_id: str = typer.Argument(..., help="Task ID to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Don't ask for confirmation"),
) -> None:
    """Remove a task."""
    from outheis.agents.tasks import get_registry
    
    registry = get_registry()
    task = registry.get(task_id)
    
    if not task:
        typer.echo(f"✗ Task not found: {task_id}")
        raise typer.Exit(1)
    
    if not force:
        confirm = typer.confirm(f"Remove task '{task.name}'?")
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)
    
    registry.remove(task_id)
    typer.echo(f"✓ Task '{task_id}' removed")


@task_app.command("show")
def task_show(
    task_id: str = typer.Argument(..., help="Task ID to show"),
) -> None:
    """Show task details."""
    from outheis.agents.tasks import get_registry
    
    registry = get_registry()
    task = registry.get(task_id)
    
    if not task:
        typer.echo(f"✗ Task not found: {task_id}")
        raise typer.Exit(1)
    
    # Print directive.md content
    directive_path = task.get_task_dir() / "directive.md"
    if directive_path.exists():
        typer.echo(directive_path.read_text())
    else:
        typer.echo(task.to_directive_md())


# =============================================================================
# MEMORY COMMANDS
# =============================================================================

memory_app = typer.Typer(help="Manage persistent memory")
app.add_typer(memory_app, name="memory")


@memory_app.command("show")
def memory_show() -> None:
    """Show all memory entries."""
    from outheis.core.memory import get_memory_store
    
    store = get_memory_store()
    all_memory = store.get_all()
    
    for memory_type in ["user", "feedback", "context"]:
        entries = all_memory.get(memory_type, [])
        typer.echo(f"\n## {memory_type.title()} ({len(entries)} entries)")
        
        if not entries:
            typer.echo("  (none)")
            continue
        
        for i, entry in enumerate(entries):
            explicit = "!" if entry.is_explicit else " "
            typer.echo(f"  {i+1}. {explicit} {entry.content}")
            if entry.decay_days:
                typer.echo(f"      (expires in {entry.decay_days} days)")
    
    typer.echo()


@memory_app.command("analyze")
def memory_analyze() -> None:
    """Analyze recent conversations and extract memory."""
    from outheis.agents.pattern import create_pattern_agent
    
    typer.echo("Analyzing recent conversations...")
    
    agent = create_pattern_agent()
    count = agent.run_scheduled()
    
    if count:
        typer.echo(f"✓ Extracted {count} new memory entries")
    else:
        typer.echo("No new information to extract")


@memory_app.command("add")
def memory_add(
    content: str = typer.Argument(..., help="Memory content"),
    memory_type: str = typer.Option("user", "--type", "-t", help="Memory type: user, feedback, context"),
) -> None:
    """Add a memory entry manually."""
    from outheis.core.memory import get_memory_store, MemoryType
    
    if memory_type not in ["user", "feedback", "context"]:
        typer.echo(f"Invalid type: {memory_type}. Use: user, feedback, context")
        raise typer.Exit(1)
    
    store = get_memory_store()
    store.add(content, memory_type, is_explicit=True)
    
    typer.echo(f"✓ Added to {memory_type}: {content}")


@memory_app.command("clear")
def memory_clear(
    memory_type: str = typer.Argument(..., help="Memory type to clear: user, feedback, context, or all"),
    force: bool = typer.Option(False, "--force", "-f", help="Don't ask for confirmation"),
) -> None:
    """Clear memory entries."""
    from outheis.core.memory import get_memory_store
    
    if memory_type not in ["user", "feedback", "context", "all"]:
        typer.echo(f"Invalid type: {memory_type}")
        raise typer.Exit(1)
    
    if not force:
        confirm = typer.confirm(f"Clear {memory_type} memory?")
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)
    
    store = get_memory_store()
    
    if memory_type == "all":
        for mt in ["user", "feedback", "context"]:
            store.clear(mt)
        typer.echo("✓ All memory cleared")
    else:
        store.clear(memory_type)
        typer.echo(f"✓ {memory_type} memory cleared")


if __name__ == "__main__":
    app()
