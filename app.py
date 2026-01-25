"""Hytale Server Dashboard – FastAPI Backend."""

import os
import json
import secrets
import asyncio
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# ---------------------------------------------------------------------------
# Configuration (via environment variables)
# ---------------------------------------------------------------------------
DASH_USER = os.environ.get("DASH_USER", "admin")
DASH_PASS = os.environ.get("DASH_PASS", "changeme")
ALLOW_CONTROL = os.environ.get("ALLOW_CONTROL", "false").lower() == "true"

SERVICE_NAME = "hytale.service"
BACKUP_DIR = Path("/opt/hytale-server/backups")
SERVER_DIR = Path("/opt/hytale-server")
LOG_LINES = 150

UPDATE_SCRIPT = "/usr/local/sbin/hytale-update.sh"
VERSION_FILE = SERVER_DIR / "last_version.txt"
LATEST_VERSION_FILE = SERVER_DIR / ".latest_version"
UPDATE_AFTER_BACKUP_FLAG = SERVER_DIR / ".update_after_backup"

# ---------------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Hytale Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = secrets.compare_digest(credentials.username, DASH_USER)
    correct_pass = secrets.compare_digest(credentials.password, DASH_PASS)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def run_cmd(cmd: list[str], timeout: int = 10) -> tuple[str, int]:
    """Run a subprocess and return (stdout+stderr, returncode)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return output.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out", 1
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}", 1
    except Exception as e:
        return str(e), 1


def human_size(size_bytes: float) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def get_service_status() -> dict:
    """Query systemd for hytale.service status."""
    props = ["ActiveState", "SubState", "MainPID", "ActiveEnterTimestamp"]
    cmd = ["systemctl", "show", SERVICE_NAME, "--property=" + ",".join(props)]
    output, rc = run_cmd(cmd)
    if rc != 0:
        return {"error": output}

    data = {}
    for line in output.splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            data[key.strip()] = val.strip()

    data["StartTime"] = data.get("ActiveEnterTimestamp", "n/a") or "n/a"
    return data


def get_logs() -> list[str]:
    """Fetch journal logs for hytale unit."""
    cmd = ["journalctl", "-u", "hytale", f"-n{LOG_LINES}", "--no-pager"]
    output, rc = run_cmd(cmd, timeout=15)
    if rc != 0:
        return [f"[Error fetching logs: {output}]"]
    return output.splitlines()


def get_backups() -> dict:
    """List backup files sorted by mtime desc."""
    try:
        if not BACKUP_DIR.exists():
            return {"error": f"Backup-Verzeichnis nicht gefunden: {BACKUP_DIR}", "files": [], "count": 0, "last_backup": "n/a"}

        backup_files = list(BACKUP_DIR.glob("hytale_*.tar.gz")) + list(BACKUP_DIR.glob("*.zip"))
        files = sorted(
            backup_files,
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
    except PermissionError:
        return {"error": "Keine Berechtigung auf Backup-Verzeichnis", "files": [], "count": 0, "last_backup": "n/a"}

    result = []
    for f in files:
        st = f.stat()
        result.append({
            "name": f.name,
            "size": human_size(st.st_size),
            "size_bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                      .strftime("%Y-%m-%d %H:%M:%S UTC"),
        })

    last_backup = result[0]["mtime"] if result else "n/a"
    return {"files": result, "count": len(result), "last_backup": last_backup}


def get_disk_usage() -> dict:
    """Disk usage for /opt/hytale-server."""
    try:
        if not SERVER_DIR.exists():
            return {"error": f"Pfad nicht gefunden: {SERVER_DIR}"}
        usage = shutil.disk_usage(str(SERVER_DIR))
        return {
            "total": human_size(usage.total),
            "used": human_size(usage.used),
            "free": human_size(usage.free),
            "percent_used": round(usage.used / usage.total * 100, 1),
        }
    except Exception as e:
        return {"error": str(e)}


def get_version_info() -> dict:
    """Read current and latest version from state files."""
    current = "unknown"
    latest = "unknown"
    try:
        if VERSION_FILE.exists():
            current = VERSION_FILE.read_text().strip()
    except (PermissionError, OSError):
        pass
    try:
        if LATEST_VERSION_FILE.exists():
            latest = LATEST_VERSION_FILE.read_text().strip()
    except (PermissionError, OSError):
        pass

    update_available = (
        latest != "unknown"
        and current != latest
    )
    update_after_backup = UPDATE_AFTER_BACKUP_FLAG.exists()

    return {
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "update_after_backup": update_after_backup,
    }


def get_backup_count() -> int:
    """Return the current number of backup files."""
    try:
        if not BACKUP_DIR.exists():
            return 0
        files = list(BACKUP_DIR.glob("hytale_*.tar.gz")) + list(BACKUP_DIR.glob("*.zip"))
        return len(files)
    except (PermissionError, OSError):
        return 0


def check_auto_update() -> None:
    """If update-after-backup flag is set and a new backup appeared, trigger update."""
    if not UPDATE_AFTER_BACKUP_FLAG.exists():
        return
    if not ALLOW_CONTROL:
        return
    try:
        stored_count = int(UPDATE_AFTER_BACKUP_FLAG.read_text().strip())
    except (ValueError, OSError):
        return
    current_count = get_backup_count()
    if current_count > stored_count:
        # New backup detected, trigger update
        run_cmd(["sudo", UPDATE_SCRIPT, "update"], timeout=300)
        # Flag is removed by the update script


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: str = Depends(verify_credentials)):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "allow_control": ALLOW_CONTROL,
        "user": user,
        "backup_dir": str(BACKUP_DIR),
        "service": SERVICE_NAME,
    })


@app.get("/manage", response_class=HTMLResponse)
async def manage(request: Request, user: str = Depends(verify_credentials)):
    return templates.TemplateResponse("manage.html", {
        "request": request,
        "allow_control": ALLOW_CONTROL,
        "user": user,
        "server_dir": str(SERVER_DIR),
        "service": SERVICE_NAME,
    })


@app.get("/api/status")
async def api_status(user: str = Depends(verify_credentials)):
    check_auto_update()
    return JSONResponse({
        "service": get_service_status(),
        "backups": get_backups(),
        "disk": get_disk_usage(),
        "version": get_version_info(),
        "allow_control": ALLOW_CONTROL,
    })


@app.get("/api/logs")
async def api_logs(user: str = Depends(verify_credentials)):
    return JSONResponse({"lines": get_logs()})


# ---------------------------------------------------------------------------
# Control Endpoints (only when ALLOW_CONTROL=true)
# ---------------------------------------------------------------------------
@app.post("/api/server/{action}")
async def api_server_action(action: str, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert. ALLOW_CONTROL=true setzen.")

    allowed = {
        "start": ["sudo", "/bin/systemctl", "start", SERVICE_NAME],
        "stop": ["sudo", "/bin/systemctl", "stop", SERVICE_NAME],
        "restart": ["sudo", "/bin/systemctl", "restart", SERVICE_NAME],
    }
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {action}")

    output, rc = run_cmd(allowed[action], timeout=30)
    if rc != 0:
        raise HTTPException(status_code=500, detail=output)
    return {"ok": True, "action": action}


@app.post("/api/backup/run")
async def api_backup_run(user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert. ALLOW_CONTROL=true setzen.")

    output, rc = run_cmd(["sudo", "/usr/local/sbin/hytale-backup.sh"], timeout=120)
    if rc != 0:
        raise HTTPException(status_code=500, detail=output)
    return {"ok": True, "output": output}


# ---------------------------------------------------------------------------
# Configuration Endpoints
# ---------------------------------------------------------------------------
HYTALE_SERVICE_FILE = Path("/etc/systemd/system/hytale.service")
HYTALE_OVERRIDE_DIR = Path("/etc/systemd/system/hytale.service.d")
HYTALE_OVERRIDE_FILE = HYTALE_OVERRIDE_DIR / "override.conf"
ALLOWED_FREQUENCIES = [0, 30, 60, 120, 360]  # 0 = deaktiviert


def get_backup_frequency() -> int:
    """Read current backup frequency from hytale.service (or override)."""
    # Check override first
    try:
        if HYTALE_OVERRIDE_FILE.exists():
            content = HYTALE_OVERRIDE_FILE.read_text()
            for line in content.splitlines():
                # Skip empty ExecStart= (systemd clear directive)
                stripped = line.strip()
                if stripped == "ExecStart=" or not stripped.startswith("ExecStart="):
                    continue
                if "--backup-frequency" in line:
                    parts = line.split("--backup-frequency")
                    if len(parts) > 1:
                        val = parts[1].strip().split()[0]
                        return int(val)
                # ExecStart with content but no --backup flag means backup is off
                return 0
    except (PermissionError, ValueError):
        pass

    # Fall back to main service file
    try:
        content = HYTALE_SERVICE_FILE.read_text()
        for line in content.splitlines():
            if "--backup-frequency" in line:
                parts = line.split("--backup-frequency")
                if len(parts) > 1:
                    val = parts[1].strip().split()[0]
                    return int(val)
    except (PermissionError, ValueError):
        pass

    return 0


def build_exec_start(frequency: int) -> str:
    """Build ExecStart line for hytale.service with given backup frequency."""
    base = "/usr/bin/java -Xms2G -Xmx4G -jar Server/HytaleServer.jar --assets Assets.zip --bind 0.0.0.0:5520"
    if frequency > 0:
        return f"{base} --backup --backup-frequency {frequency} --backup-dir backups"
    return base


@app.get("/api/config")
async def api_config(user: str = Depends(verify_credentials)):
    return JSONResponse({
        "backup_frequency": get_backup_frequency(),
        "allowed_frequencies": ALLOWED_FREQUENCIES,
    })


@app.post("/api/config/backup-frequency")
async def api_set_backup_frequency(request: Request, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")

    body = await request.json()
    freq = body.get("frequency")
    if freq is None or freq not in ALLOWED_FREQUENCIES:
        raise HTTPException(status_code=400, detail=f"Ungueltige Frequenz. Erlaubt: {ALLOWED_FREQUENCIES}")

    # Build override content
    override_content = f"""[Service]
ExecStart=
ExecStart={build_exec_start(freq)}
"""

    # Create override directory
    output, rc = run_cmd(["sudo", "/bin/mkdir", "-p", str(HYTALE_OVERRIDE_DIR)])
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Fehler beim Erstellen des Override-Verzeichnisses: {output}")

    # Write override file via sudo tee
    try:
        proc = subprocess.run(
            ["sudo", "/usr/bin/tee", str(HYTALE_OVERRIDE_FILE)],
            input=override_content, capture_output=True, text=True, timeout=10
        )
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Fehler beim Schreiben der Override-Datei: {proc.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Reload systemd and restart hytale
    output, rc = run_cmd(["sudo", "/bin/systemctl", "daemon-reload"], timeout=10)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"daemon-reload fehlgeschlagen: {output}")

    output, rc = run_cmd(["sudo", "/bin/systemctl", "restart", SERVICE_NAME], timeout=60)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"Server-Neustart fehlgeschlagen: {output}")

    return {"ok": True, "frequency": freq}


# ---------------------------------------------------------------------------
# Version / Update Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/version")
async def api_version(user: str = Depends(verify_credentials)):
    return JSONResponse(get_version_info())


@app.get("/api/update/log")
async def api_update_log(user: str = Depends(verify_credentials)):
    """Return current content of the downloader log and process status."""
    log_file = SERVER_DIR / ".downloader" / "download.log"
    log_content = ""
    try:
        if log_file.exists():
            log_content = log_file.read_text()
    except (PermissionError, OSError):
        pass

    # Check if update/downloader process is currently running
    running = False
    try:
        result = subprocess.run(
            ["pgrep", "-f", "hytale-update.sh|hytale-downloader"],
            capture_output=True, text=True, timeout=5
        )
        running = result.returncode == 0
    except Exception:
        pass

    return JSONResponse({
        "log": log_content,
        "running": running,
    })


@app.post("/api/version/check")
async def api_version_check(user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert. ALLOW_CONTROL=true setzen.")

    output, rc = await asyncio.to_thread(run_cmd, ["sudo", UPDATE_SCRIPT, "check"], 300)
    if rc != 0:
        raise HTTPException(status_code=500, detail=output)

    try:
        result = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=500, detail=f"Unerwartete Ausgabe: {output}")

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return JSONResponse(result)


@app.post("/api/update/run")
async def api_update_run(user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert. ALLOW_CONTROL=true setzen.")

    output, rc = await asyncio.to_thread(run_cmd, ["sudo", UPDATE_SCRIPT, "update"], 600)
    if rc != 0:
        raise HTTPException(status_code=500, detail=output)

    try:
        result = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=500, detail=f"Unerwartete Ausgabe: {output}")

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return JSONResponse(result)


@app.post("/api/update/auto")
async def api_update_auto(user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert. ALLOW_CONTROL=true setzen.")

    if UPDATE_AFTER_BACKUP_FLAG.exists():
        # Toggle off
        UPDATE_AFTER_BACKUP_FLAG.unlink(missing_ok=True)
        return {"ok": True, "update_after_backup": False}
    else:
        # Toggle on: store current backup count
        count = get_backup_count()
        UPDATE_AFTER_BACKUP_FLAG.write_text(str(count))
        return {"ok": True, "update_after_backup": True}


# ---------------------------------------------------------------------------
# Management Endpoints
# ---------------------------------------------------------------------------
import re

CONSOLE_PIPE = SERVER_DIR / ".console_pipe"
MODS_DIR = SERVER_DIR / "mods"
WORLD_CONFIG_FILE = SERVER_DIR / "universe" / "worlds" / "default" / "config.json"
SERVER_CONFIG_FILE = SERVER_DIR / "config.json"


@app.get("/api/players")
async def api_players(user: str = Depends(verify_credentials)):
    """Parse journalctl for player join/leave events."""
    output, rc = run_cmd(
        ["journalctl", "-u", "hytale", "--no-pager", "-o", "short-iso"],
        timeout=15
    )
    if rc != 0:
        return JSONResponse({"players": [], "error": output})

    players = {}
    join_re = re.compile(
        r"(\S+T\S+).*Adding player '([^']+)' to world '([^']+)' at location .+\(([a-f0-9-]+)\)"
    )
    leave_re = re.compile(
        r"(\S+T\S+).*Removing player '([^']+?)(?:\s*\([^)]+\))?'.*\(([a-f0-9-]+)\)\s*$"
    )

    for line in output.splitlines():
        m = join_re.search(line)
        if m:
            ts, name, world, uuid = m.group(1), m.group(2), m.group(3), m.group(4)
            players[uuid] = {
                "name": name, "uuid": uuid,
                "online": True, "last_login": ts,
                "last_logout": None, "world": world, "position": None,
            }
            continue
        m = leave_re.search(line)
        if m:
            ts, name, uuid = m.group(1), m.group(2), m.group(3)
            if uuid in players:
                players[uuid]["online"] = False
                players[uuid]["last_logout"] = ts

    return JSONResponse({"players": list(players.values())})


@app.post("/api/console/send")
async def api_console_send(request: Request, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")

    body = await request.json()
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Kein Befehl angegeben.")

    if not CONSOLE_PIPE.exists():
        raise HTTPException(status_code=500, detail="Konsolen-Pipe nicht gefunden. Server laeuft nicht mit Wrapper.")

    try:
        fd = os.open(str(CONSOLE_PIPE), os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, (command + "\n").encode())
        os.close(fd)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Fehler beim Senden: {e}")

    return {"ok": True, "command": command}


@app.get("/api/console/output")
async def api_console_output(user: str = Depends(verify_credentials), since: str = ""):
    """Return recent log lines from journalctl."""
    cmd = ["journalctl", "-u", "hytale", "-n50", "--no-pager"]
    if since:
        cmd.extend(["--since", since])
    output, rc = run_cmd(cmd, timeout=10)
    lines = output.splitlines() if rc == 0 else [f"[Fehler: {output}]"]
    return JSONResponse({"lines": lines})


@app.get("/api/config/server")
async def api_config_server_get(user: str = Depends(verify_credentials)):
    try:
        content = SERVER_CONFIG_FILE.read_text()
        return JSONResponse({"content": content})
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/server")
async def api_config_server_set(request: Request, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")
    body = await request.json()
    content = body.get("content", "")
    try:
        json.loads(content)  # validate JSON
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Ungueltiges JSON: {e}")
    try:
        SERVER_CONFIG_FILE.write_text(content)
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.get("/api/config/world")
async def api_config_world_get(user: str = Depends(verify_credentials)):
    try:
        content = WORLD_CONFIG_FILE.read_text()
        return JSONResponse({"content": content})
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/world")
async def api_config_world_set(request: Request, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")
    body = await request.json()
    content = body.get("content", "")
    try:
        json.loads(content)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Ungueltiges JSON: {e}")
    try:
        WORLD_CONFIG_FILE.write_text(content)
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.get("/api/backups/list")
async def api_backups_list(user: str = Depends(verify_credentials)):
    result = []
    # Regular backups
    try:
        if BACKUP_DIR.exists():
            for f in sorted(BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file() and (f.suffix in (".gz", ".zip")):
                    st = f.stat()
                    result.append({
                        "name": f.name, "size": human_size(st.st_size),
                        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "type": "backup", "path": str(f),
                    })
    except (PermissionError, OSError):
        pass
    # Update backups
    try:
        for d in sorted(SERVER_DIR.glob(".update_backup_*"), reverse=True):
            if d.is_dir():
                st = d.stat()
                result.append({
                    "name": d.name, "size": "-",
                    "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "type": "update-backup", "path": str(d),
                })
    except (PermissionError, OSError):
        pass
    return JSONResponse({"backups": result})


@app.delete("/api/backups/{filename:path}")
async def api_backup_delete(filename: str, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")
    # Check in backup dir
    target = BACKUP_DIR / filename
    if not target.exists():
        target = SERVER_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.get("/api/mods")
async def api_mods(user: str = Depends(verify_credentials)):
    mods = []
    try:
        if MODS_DIR.exists():
            for d in sorted(MODS_DIR.iterdir()):
                if d.is_dir():
                    enabled = not d.name.endswith(".disabled")
                    display_name = d.name.removesuffix(".disabled")
                    has_manifest = (d / "manifest.json").exists()
                    total_size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                    mods.append({
                        "name": display_name, "dir_name": d.name,
                        "enabled": enabled, "has_manifest": has_manifest,
                        "size": human_size(total_size),
                    })
    except (PermissionError, OSError):
        pass
    return JSONResponse({"mods": mods})


@app.post("/api/mods/{name}/toggle")
async def api_mod_toggle(name: str, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")
    enabled_path = MODS_DIR / name
    disabled_path = MODS_DIR / f"{name}.disabled"
    try:
        if enabled_path.exists() and enabled_path.is_dir():
            enabled_path.rename(disabled_path)
            return {"ok": True, "enabled": False}
        elif disabled_path.exists() and disabled_path.is_dir():
            disabled_path.rename(enabled_path)
            return {"ok": True, "enabled": True}
        else:
            raise HTTPException(status_code=404, detail="Mod nicht gefunden.")
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/mods/{name}")
async def api_mod_delete(name: str, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")
    target = MODS_DIR / name
    if not target.exists():
        target = MODS_DIR / f"{name}.disabled"
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Mod nicht gefunden.")
    try:
        shutil.rmtree(target)
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.post("/api/mods/upload")
async def api_mod_upload(request: Request, user: str = Depends(verify_credentials)):
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")

    from fastapi import UploadFile, File
    import tempfile
    import zipfile

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="Keine Datei hochgeladen.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Leere Datei.")

    filename = file.filename or "mod"
    is_jar = filename.lower().endswith(".jar")

    if is_jar:
        # JAR file: create directory with mod name and put JAR inside
        mod_name = Path(filename).stem
        mod_dir = MODS_DIR / mod_name
        mod_dir.mkdir(parents=True, exist_ok=True)
        jar_path = mod_dir / filename
        jar_path.write_bytes(content)
        return {"ok": True, "mod_name": mod_name}

    # ZIP file handling
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            # Determine mod name from zip content
            names = zf.namelist()
            top_dirs = set()
            for n in names:
                parts = n.split("/")
                if len(parts) > 1 and parts[0]:
                    top_dirs.add(parts[0])

            if len(top_dirs) == 1:
                mod_name = top_dirs.pop()
                extract_to = MODS_DIR
            else:
                mod_name = Path(filename).stem
                extract_to = MODS_DIR / mod_name
                extract_to.mkdir(parents=True, exist_ok=True)

            zf.extractall(str(extract_to))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Ungueltige ZIP-Datei.")
    finally:
        os.unlink(tmp_path)

    return {"ok": True, "mod_name": mod_name}


# ---------------------------------------------------------------------------
# Plugin Store
# ---------------------------------------------------------------------------
PLUGIN_STORE = [
    {
        "id": "nitrado-webserver",
        "name": "Nitrado:WebServer",
        "description": "Base plugin for web applications and APIs. Required by Query and PrometheusExporter.",
        "version": "1.0.0",
        "author": "Nitrado",
        "url": "https://github.com/nitrado/hytale-plugin-webserver/releases/download/v1.0.0/nitrado-webserver-1.0.0.jar",
        "dir_name": "Nitrado_WebServer",
        "config_port": 5523,
    },
    {
        "id": "nitrado-query",
        "name": "Nitrado:Query",
        "description": "Exposes server status (player counts, TPS, etc.) via HTTP API.",
        "version": "1.0.1",
        "author": "Nitrado",
        "url": "https://github.com/nitrado/hytale-plugin-query/releases/download/v1.0.1/nitrado-query-1.0.1.jar",
        "dir_name": "Nitrado_Query",
        "depends": ["nitrado-webserver"],
    },
    {
        "id": "nitrado-performance-saver",
        "name": "Nitrado:PerformanceSaver",
        "description": "Dynamically limits view distance based on resource usage.",
        "version": "1.1.0",
        "author": "Nitrado",
        "url": "https://github.com/nitrado/hytale-plugin-performance-saver/releases/download/v1.1.0/nitrado-performance-saver-1.1.0.jar",
        "dir_name": "Nitrado_PerformanceSaver",
    },
    {
        "id": "apexhosting-prometheus",
        "name": "ApexHosting:PrometheusExporter",
        "description": "Exposes detailed server and JVM metrics for Prometheus monitoring.",
        "version": "1.0.0",
        "author": "ApexHosting",
        "url": "https://github.com/apexhosting/hytale-plugin-prometheus/releases/download/v1.0.0/apexhosting-prometheusexporter-1.0.0.jar",
        "dir_name": "ApexHosting_PrometheusExporter",
        "depends": ["nitrado-webserver"],
    },
]


@app.get("/api/plugins")
async def api_plugins(user: str = Depends(verify_credentials)):
    """List available plugins from the store with install status."""
    result = []
    for plugin in PLUGIN_STORE:
        installed = False
        enabled = False
        dir_name = plugin["dir_name"]
        if (MODS_DIR / dir_name).exists():
            installed = True
            enabled = True
        elif (MODS_DIR / f"{dir_name}.disabled").exists():
            installed = True
            enabled = False
        result.append({
            **plugin,
            "installed": installed,
            "enabled": enabled,
        })
    return JSONResponse({"plugins": result})


@app.post("/api/plugins/{plugin_id}/install")
async def api_plugin_install(plugin_id: str, user: str = Depends(verify_credentials)):
    """Download and install a plugin from the store."""
    if not ALLOW_CONTROL:
        raise HTTPException(status_code=403, detail="Control-Aktionen deaktiviert.")

    plugin = next((p for p in PLUGIN_STORE if p["id"] == plugin_id), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin nicht gefunden.")

    # Check dependencies
    depends = plugin.get("depends", [])
    for dep_id in depends:
        dep = next((p for p in PLUGIN_STORE if p["id"] == dep_id), None)
        if dep:
            dep_dir = MODS_DIR / dep["dir_name"]
            if not dep_dir.exists() and not (MODS_DIR / f"{dep['dir_name']}.disabled").exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"Abhaengigkeit fehlt: {dep['name']}. Bitte zuerst installieren."
                )

    import urllib.request

    dir_name = plugin["dir_name"]
    mod_dir = MODS_DIR / dir_name

    if mod_dir.exists() or (MODS_DIR / f"{dir_name}.disabled").exists():
        raise HTTPException(status_code=400, detail="Plugin bereits installiert.")

    try:
        jar_name = plugin["url"].split("/")[-1]
        mod_dir.mkdir(parents=True, exist_ok=True)
        jar_path = mod_dir / jar_name

        def download():
            urllib.request.urlretrieve(plugin["url"], str(jar_path))

        await asyncio.to_thread(download)
    except Exception as e:
        if mod_dir.exists():
            shutil.rmtree(mod_dir)
        raise HTTPException(status_code=500, detail=f"Download fehlgeschlagen: {e}")

    return {"ok": True, "plugin": plugin["name"]}


@app.get("/api/server/query")
async def api_server_query(user: str = Depends(verify_credentials)):
    """Get server status from Nitrado Query API (if installed)."""
    query_dir = MODS_DIR / "Nitrado_Query"
    webserver_dir = MODS_DIR / "Nitrado_WebServer"

    if not query_dir.exists() or not webserver_dir.exists():
        return JSONResponse({"available": False, "reason": "Nitrado:Query oder Nitrado:WebServer nicht installiert."})

    # Read WebServer config to get port
    config_path = webserver_dir / "config.json"
    port = 5523  # default: game port (5520) + 3
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            port = cfg.get("port", port)
        except Exception:
            pass

    try:
        import urllib.request
        import ssl

        # Skip SSL verification for self-signed cert
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        url = f"https://127.0.0.1:{port}/Nitrado/Query"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        def fetch():
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                return json.loads(resp.read().decode())

        data = await asyncio.to_thread(fetch)
        return JSONResponse({"available": True, "data": data})
    except Exception as e:
        return JSONResponse({"available": False, "reason": str(e)})
