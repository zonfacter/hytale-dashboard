#!/usr/bin/env python3
"""
Hytale Dashboard Background Worker

Collects metrics and player events, stores in SQLite for fast dashboard access.
Run as systemd service: hytale-dashboard-worker.service
"""

import sqlite3
import subprocess
import time
import re
import os
import signal
import sys
from pathlib import Path
from datetime import datetime, timezone

# Configuration
DB_PATH = Path(__file__).parent / "data" / "dashboard.db"
SERVICE_NAME = "hytale"
PERF_INTERVAL = 5      # Collect performance every 5 seconds
PLAYER_INTERVAL = 10   # Check player events every 10 seconds
CLEANUP_INTERVAL = 3600  # Cleanup old data every hour
PERF_RETENTION_HOURS = 24  # Keep 24h of performance history

# Docker mode detection
DOCKER_MODE = os.environ.get("DOCKER_MODE", "false").lower() == "true"
HYTALE_CONTAINER = os.environ.get("HYTALE_CONTAINER", "")
if HYTALE_CONTAINER:
    DOCKER_MODE = True
if not DOCKER_MODE and Path("/.dockerenv").exists():
    DOCKER_MODE = True

# Globals
running = True
last_log_position = ""


def signal_handler(sig, frame):
    global running
    print(f"[Worker] Received signal {sig}, shutting down...")
    running = False


def init_db():
    """Initialize SQLite database with schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Players table
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            online INTEGER DEFAULT 0,
            last_login TEXT,
            last_logout TEXT,
            world TEXT,
            total_playtime_seconds INTEGER DEFAULT 0
        )
    """)

    # Performance history
    c.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tps INTEGER,
            cpu_percent REAL,
            ram_mb REAL,
            ram_percent REAL,
            view_radius INTEGER,
            players_online INTEGER DEFAULT 0
        )
    """)

    # Add view_radius column if missing (migration)
    try:
        c.execute("ALTER TABLE performance ADD COLUMN view_radius INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Create index for faster queries
    c.execute("CREATE INDEX IF NOT EXISTS idx_perf_ts ON performance(timestamp)")

    # Player events log
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            uuid TEXT NOT NULL,
            name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            world TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON player_events(timestamp)")

    # Metadata table for tracking state
    c.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()
    print(f"[Worker] Database initialized: {DB_PATH}")


def run_cmd(cmd: list, timeout: int = 10) -> tuple:
    """Run subprocess and return (output, returncode)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), 1


def get_logs(lines: int = 200) -> str:
    """Get recent logs from journalctl or docker logs."""
    if DOCKER_MODE and HYTALE_CONTAINER:
        cmd = ["docker", "logs", "--tail", str(lines), HYTALE_CONTAINER]
    else:
        cmd = ["journalctl", "-u", SERVICE_NAME, f"-n{lines}", "--no-pager", "-q"]
    output, rc = run_cmd(cmd)
    return output if rc == 0 else ""


def get_java_pid() -> str | None:
    """Find the Java process PID for Hytale server."""
    if DOCKER_MODE and HYTALE_CONTAINER:
        # Docker mode: get PID from docker inspect
        cmd = ["docker", "inspect", "--format", "{{.State.Pid}}", HYTALE_CONTAINER]
        output, rc = run_cmd(cmd)
        if rc == 0 and output.strip() and output.strip() != "0":
            return output.strip()
        return None

    # Native mode: Get wrapper PID from systemd
    output, rc = run_cmd(["systemctl", "show", SERVICE_NAME, "--property=MainPID", "--value"])
    if rc != 0 or not output or output == "0":
        return None

    wrapper_pid = output.strip()

    # Find Java child process
    output, rc = run_cmd(["pgrep", "-P", wrapper_pid, "java"])
    if rc == 0 and output:
        return output.split()[0]

    # Fallback: search for HytaleServer.jar
    output, rc = run_cmd(["pgrep", "-f", "HytaleServer.jar"])
    if rc == 0 and output:
        return output.split()[0]

    return None


def get_docker_stats() -> dict:
    """Get CPU/RAM stats from docker stats."""
    if not HYTALE_CONTAINER:
        return {}
    cmd = ["docker", "stats", "--no-stream", "--format",
           "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}", HYTALE_CONTAINER]
    output, rc = run_cmd(cmd, timeout=10)
    if rc != 0 or not output.strip():
        return {}

    try:
        parts = output.strip().split("|")
        cpu_str = parts[0].replace("%", "").strip()
        mem_usage = parts[1].split("/")[0].strip()
        mem_pct = parts[2].replace("%", "").strip()

        result = {
            "cpu_percent": float(cpu_str),
            "ram_percent": float(mem_pct),
        }

        # Parse memory (e.g., "1.5GiB" or "512MiB")
        if "GiB" in mem_usage:
            result["ram_mb"] = float(mem_usage.replace("GiB", "")) * 1024
        elif "MiB" in mem_usage:
            result["ram_mb"] = float(mem_usage.replace("MiB", ""))
        elif "GB" in mem_usage:
            result["ram_mb"] = float(mem_usage.replace("GB", "")) * 1024
        elif "MB" in mem_usage:
            result["ram_mb"] = float(mem_usage.replace("MB", ""))

        return result
    except (ValueError, IndexError):
        return {}


def collect_performance() -> dict:
    """Collect current performance metrics."""
    result = {
        "tps": None,
        "cpu_percent": None,
        "ram_mb": None,
        "ram_percent": None,
        "view_radius": None,
    }

    # Get TPS and view_radius from recent logs
    output = get_logs(200)
    if output:
        tps_re = re.compile(r"Setting TPS of world \w+ to (\d+)")
        vr_re = re.compile(r"(?:Initial view radius is|View radius.*?to) (\d+)")
        for line in reversed(output.splitlines()):
            if result["tps"] is None:
                match = tps_re.search(line)
                if match:
                    result["tps"] = int(match.group(1))
            if result["view_radius"] is None:
                match = vr_re.search(line)
                if match:
                    result["view_radius"] = int(match.group(1))
            if result["tps"] is not None and result["view_radius"] is not None:
                break

    # Get CPU/RAM - different methods for Docker vs native
    if DOCKER_MODE and HYTALE_CONTAINER:
        # Docker mode: use docker stats
        stats = get_docker_stats()
        if stats:
            result["cpu_percent"] = stats.get("cpu_percent")
            result["ram_percent"] = stats.get("ram_percent")
            result["ram_mb"] = stats.get("ram_mb")
    else:
        # Native mode: use ps with Java PID
        java_pid = get_java_pid()
        if java_pid:
            output, rc = run_cmd(["ps", "-p", java_pid, "-o", "%cpu,%mem,rss", "--no-headers"])
            if rc == 0 and output:
                try:
                    parts = output.split()
                    result["cpu_percent"] = float(parts[0])
                    result["ram_percent"] = float(parts[1])
                    result["ram_mb"] = int(parts[2]) / 1024  # KB to MB
                except (ValueError, IndexError):
                    pass

    return result


def get_online_player_count(conn) -> int:
    """Get count of online players from DB."""
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM players WHERE online = 1")
    return c.fetchone()[0]


def save_performance(conn, perf: dict):
    """Save performance metrics to database."""
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    players_online = get_online_player_count(conn)

    c.execute("""
        INSERT INTO performance (timestamp, tps, cpu_percent, ram_mb, ram_percent, view_radius, players_online)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (now, perf["tps"], perf["cpu_percent"], perf["ram_mb"], perf["ram_percent"], perf.get("view_radius"), players_online))
    conn.commit()


def parse_player_events(output: str) -> list:
    """Parse player join/leave events from log output."""
    events = []

    join_re = re.compile(
        r"(\d{4}-\d{2}-\d{2}T\S+).*Adding player '([^']+)' to world '([^']+)' at location .+\(([a-f0-9-]+)\)"
    )
    leave_re = re.compile(
        r"(\d{4}-\d{2}-\d{2}T\S+).*Removing player '([^']+?)(?:\s*\([^)]+\))?'.*\(([a-f0-9-]+)\)\s*$"
    )

    for line in output.splitlines():
        m = join_re.search(line)
        if m:
            events.append({
                "timestamp": m.group(1),
                "name": m.group(2),
                "world": m.group(3),
                "uuid": m.group(4),
                "type": "join"
            })
            continue

        m = leave_re.search(line)
        if m:
            events.append({
                "timestamp": m.group(1),
                "name": m.group(2),
                "uuid": m.group(3),
                "type": "leave",
                "world": None
            })

    return events


def check_player_events(conn):
    """Check for new player events and update database."""
    global last_log_position

    c = conn.cursor()

    # Get last processed timestamp
    c.execute("SELECT value FROM metadata WHERE key = 'last_event_ts'")
    row = c.fetchone()
    since_ts = row[0] if row else "3 days ago"

    # Query logs since last check
    if DOCKER_MODE and HYTALE_CONTAINER:
        # Docker mode: get recent logs (no --since support, get more lines)
        cmd = ["docker", "logs", "--tail", "1000", HYTALE_CONTAINER]
        output, rc = run_cmd(cmd, timeout=30)
    else:
        # Native mode: use journalctl with --since
        cmd = ["journalctl", "-u", SERVICE_NAME, "--no-pager", "-o", "short-iso", "--since", since_ts]
        output, rc = run_cmd(cmd, timeout=30)

    if rc != 0:
        return

    events = parse_player_events(output)

    if not events:
        return

    for event in events:
        # Update players table
        if event["type"] == "join":
            c.execute("""
                INSERT INTO players (uuid, name, online, last_login, world)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    name = excluded.name,
                    online = 1,
                    last_login = excluded.last_login,
                    world = excluded.world
            """, (event["uuid"], event["name"], event["timestamp"], event["world"]))
        else:  # leave
            c.execute("""
                UPDATE players SET online = 0, last_logout = ?
                WHERE uuid = ?
            """, (event["timestamp"], event["uuid"]))

        # Log event
        c.execute("""
            INSERT INTO player_events (timestamp, uuid, name, event_type, world)
            VALUES (?, ?, ?, ?, ?)
        """, (event["timestamp"], event["uuid"], event["name"], event["type"], event["world"]))

    # Update last processed timestamp
    latest_ts = events[-1]["timestamp"] if events else since_ts
    c.execute("""
        INSERT INTO metadata (key, value) VALUES ('last_event_ts', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (latest_ts,))

    conn.commit()
    print(f"[Worker] Processed {len(events)} player events")


def cleanup_old_data(conn):
    """Remove old performance data to keep DB size manageable."""
    c = conn.cursor()

    # Delete performance data older than retention period
    c.execute(f"""
        DELETE FROM performance
        WHERE strftime(
            '%s',
            replace(substr(timestamp, 1, 19), 'T', ' ')
        ) < strftime('%s', 'now', '-{PERF_RETENTION_HOURS} hours')
    """)
    deleted_perf = c.rowcount

    # Delete player events older than 7 days
    c.execute("""
        DELETE FROM player_events
        WHERE timestamp < datetime('now', '-7 days')
    """)
    deleted_events = c.rowcount

    if deleted_perf > 0 or deleted_events > 0:
        conn.commit()
        print(f"[Worker] Cleanup: removed {deleted_perf} perf records, {deleted_events} events")

    # Vacuum periodically to reclaim space
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def initial_player_sync(conn):
    """Initial sync of player data from logs on startup."""
    print("[Worker] Initial player sync from logs...")

    # Get logs for initial sync
    if DOCKER_MODE and HYTALE_CONTAINER:
        # Docker mode: get all available logs
        cmd = ["docker", "logs", HYTALE_CONTAINER]
        output, rc = run_cmd(cmd, timeout=60)
    else:
        # Native mode: get last 7 days
        cmd = ["journalctl", "-u", SERVICE_NAME, "--no-pager", "-o", "short-iso", "--since", "7 days ago"]
        output, rc = run_cmd(cmd, timeout=60)

    if rc != 0:
        print(f"[Worker] Failed to get logs: {output}")
        return

    events = parse_player_events(output)

    # Process events to build current player state
    players = {}
    for event in events:
        uuid = event["uuid"]
        if uuid not in players:
            players[uuid] = {
                "uuid": uuid,
                "name": event["name"],
                "online": False,
                "last_login": None,
                "last_logout": None,
                "world": None
            }

        if event["type"] == "join":
            players[uuid]["online"] = True
            players[uuid]["last_login"] = event["timestamp"]
            players[uuid]["world"] = event["world"]
            players[uuid]["name"] = event["name"]
        else:
            players[uuid]["online"] = False
            players[uuid]["last_logout"] = event["timestamp"]

    # Save to database
    c = conn.cursor()
    for p in players.values():
        c.execute("""
            INSERT INTO players (uuid, name, online, last_login, last_logout, world)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uuid) DO UPDATE SET
                name = excluded.name,
                online = excluded.online,
                last_login = COALESCE(excluded.last_login, players.last_login),
                last_logout = COALESCE(excluded.last_logout, players.last_logout),
                world = COALESCE(excluded.world, players.world)
        """, (p["uuid"], p["name"], 1 if p["online"] else 0, p["last_login"], p["last_logout"], p["world"]))

    conn.commit()
    print(f"[Worker] Synced {len(players)} players")


def main():
    global running

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print("[Worker] Starting Hytale Dashboard Worker...")

    # Initialize database
    init_db()

    # Connect to database
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
    conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
    conn.execute("PRAGMA busy_timeout=10000")  # Wait up to 10s when DB is busy

    # Initial player sync
    initial_player_sync(conn)

    last_perf = 0
    last_player = 0
    last_cleanup = 0

    print("[Worker] Entering main loop...")

    while running:
        now = time.time()

        # Collect performance metrics
        if now - last_perf >= PERF_INTERVAL:
            try:
                perf = collect_performance()
                save_performance(conn, perf)
            except Exception as e:
                print(f"[Worker] Performance error: {e}")
            finally:
                # Advance timer even on errors to avoid tight error loops.
                last_perf = now

        # Check player events
        if now - last_player >= PLAYER_INTERVAL:
            try:
                check_player_events(conn)
            except Exception as e:
                print(f"[Worker] Player sync error: {e}")
            finally:
                # Advance timer even on errors to avoid hammering journal/db.
                last_player = now

        # Cleanup old data
        if now - last_cleanup >= CLEANUP_INTERVAL:
            try:
                cleanup_old_data(conn)
            except Exception as e:
                print(f"[Worker] Cleanup error: {e}")
            finally:
                last_cleanup = now

        # Sleep briefly to avoid busy loop
        time.sleep(1)

    conn.close()
    print("[Worker] Shutdown complete")


if __name__ == "__main__":
    main()
