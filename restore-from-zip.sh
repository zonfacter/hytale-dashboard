#!/bin/bash
# Restore missing Hytale server files from .downloader/game.zip
# Usage:
#   ./restore-from-zip.sh
#   ./restore-from-zip.sh --no-start
#   ./restore-from-zip.sh --zip /custom/path/game.zip --server-dir /opt/hytale-server

set -euo pipefail
umask 027

SERVER_DIR="/opt/hytale-server"
ZIP_PATH="/opt/hytale-server/.downloader/game.zip"
SERVICE_NAME="hytale-server"
OWNER_USER="hytale"
OWNER_GROUP="hytale"
START_SERVICE=true

usage() {
  cat <<'EOF'
Usage: restore-from-zip.sh [options]

Options:
  --zip <path>         Path to game.zip (default: /opt/hytale-server/.downloader/game.zip)
  --server-dir <path>  Hytale server root directory (default: /opt/hytale-server)
  --service <name>     Supervisor service name (default: hytale-server)
  --owner <user:group> Owner for restored files (default: hytale:hytale)
  --no-start           Only extract + chown, do not start service
  -h, --help           Show this help
EOF
}

log() {
  printf '[restore] %s\n' "$*"
}

err() {
  printf '[restore] ERROR: %s\n' "$*" >&2
  exit 1
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

extract_with_python() {
  local zip_file="$1"
  local target_dir="$2"

  python3 - "$zip_file" "$target_dir" <<'PYEOF'
import sys
from zipfile import ZipFile

zip_path = sys.argv[1]
target_dir = sys.argv[2]

with ZipFile(zip_path, "r") as zf:
    zf.extractall(target_dir)
PYEOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --zip)
      ZIP_PATH="${2:-}"
      shift 2
      ;;
    --server-dir)
      SERVER_DIR="${2:-}"
      shift 2
      ;;
    --service)
      SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --owner)
      owner_raw="${2:-}"
      OWNER_USER="${owner_raw%%:*}"
      OWNER_GROUP="${owner_raw##*:}"
      shift 2
      ;;
    --no-start)
      START_SERVICE=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      err "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$SERVER_DIR" ]] || err "--server-dir darf nicht leer sein"
[[ -n "$ZIP_PATH" ]] || err "--zip darf nicht leer sein"
[[ -n "$SERVICE_NAME" ]] || err "--service darf nicht leer sein"
[[ -n "$OWNER_USER" && -n "$OWNER_GROUP" ]] || err "--owner muss user:group sein"
[[ -d "$SERVER_DIR" ]] || err "Server-Verzeichnis nicht gefunden: $SERVER_DIR"
[[ -f "$ZIP_PATH" ]] || err "ZIP-Datei nicht gefunden: $ZIP_PATH"

log "Entpacke: $ZIP_PATH -> $SERVER_DIR"
if command -v unzip >/dev/null 2>&1; then
  run_privileged unzip -o "$ZIP_PATH" -d "$SERVER_DIR" >/dev/null
else
  log "unzip fehlt, nutze Python-Fallback"
  command -v python3 >/dev/null 2>&1 || err "Weder unzip noch python3 verfuegbar"
  run_privileged mkdir -p "$SERVER_DIR"
  extract_with_python "$ZIP_PATH" "$SERVER_DIR"
fi

[[ -f "$SERVER_DIR/Server/HytaleServer.jar" ]] || err "Fehlt nach Entpacken: $SERVER_DIR/Server/HytaleServer.jar"
[[ -f "$SERVER_DIR/Assets.zip" ]] || err "Fehlt nach Entpacken: $SERVER_DIR/Assets.zip"

log "Setze Owner: $OWNER_USER:$OWNER_GROUP"
run_privileged chown -R "${OWNER_USER}:${OWNER_GROUP}" "$SERVER_DIR/Server" "$SERVER_DIR/Assets.zip"

if [[ "$START_SERVICE" == true ]]; then
  command -v supervisorctl >/dev/null 2>&1 || err "supervisorctl nicht gefunden"
  log "Starte Service via supervisorctl: $SERVICE_NAME"
  run_privileged supervisorctl start "$SERVICE_NAME"
  log "Service-Status:"
  run_privileged supervisorctl status "$SERVICE_NAME"
else
  log "--no-start gesetzt, Service wird nicht gestartet"
fi

log "Restore abgeschlossen"
