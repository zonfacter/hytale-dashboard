#!/usr/bin/env bash

set -euo pipefail

APP_FILE="${1:-app.py}"

if [[ ! -f "$APP_FILE" ]]; then
  echo "ERROR: app file not found: $APP_FILE" >&2
  exit 1
fi

required=(
  '@app.get("/api/status")'
  '@app.get("/api/logs")'
  '@app.get("/api/console/output")'
  '@app.post("/api/console/send")'
  '@app.get("/api/backups/list")'
  '@app.post("/api/backups/restore")'
  '@app.post("/api/backups/create")'
  'def get_logs() -> list[str]'
  'def _get_console_output('
  'def send_console_command('
  'DOCKER_MODE'
  'HYTALE_CONTAINER'
)

echo "[contract] Checking required tokens in ${APP_FILE}"
for token in "${required[@]}"; do
  if ! grep -F "$token" "$APP_FILE" >/dev/null; then
    echo "ERROR: Missing contract token: $token" >&2
    exit 1
  fi
done

echo "[contract] OK"
