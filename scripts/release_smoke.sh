#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8088}"
DASH_USER="${DASH_USER:-admin}"
DASH_PASS="${DASH_PASS:-change-me}"
EXPECTED_CHANNEL="${EXPECTED_CHANNEL:-}"
ALLOW_CONTROL_REQUIRED="${ALLOW_CONTROL_REQUIRED:-true}"

auth=(-u "${DASH_USER}:${DASH_PASS}")

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required tool missing: $1" >&2
    exit 1
  fi
}

require_tool curl
require_tool python3

get_json() {
  local route="$1"
  curl -fsS "${auth[@]}" "${BASE_URL}${route}"
}

post_json() {
  local route="$1"
  local payload="$2"
  curl -fsS "${auth[@]}" -H "Content-Type: application/json" -d "$payload" "${BASE_URL}${route}"
}

check_status() {
  local payload
  payload="$(get_json "/api/status")"
  python3 - "$payload" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
service = data.get("service", {})
if "ActiveState" not in service:
    raise SystemExit("missing service.ActiveState")
if "allow_control" not in data:
    raise SystemExit("missing allow_control")
print("PASS: /api/status")
PY
}

check_logs() {
  local payload
  payload="$(get_json "/api/logs")"
  python3 - "$payload" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
if "lines" not in data or not isinstance(data["lines"], list):
    raise SystemExit("missing logs.lines")
print("PASS: /api/logs")
PY
}

check_console_output() {
  local payload
  payload="$(get_json "/api/console/output")"
  python3 - "$payload" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
if "lines" not in data or not isinstance(data["lines"], list):
    raise SystemExit("missing console output lines")
print("PASS: /api/console/output")
PY
}

check_backups_list() {
  local payload
  payload="$(get_json "/api/backups/list")"
  python3 - "$payload" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
if "files" in data and "count" in data:
    print("PASS: /api/backups/list")
    raise SystemExit(0)
if "backups" in data and isinstance(data["backups"], dict):
    nested = data["backups"]
    if "files" in nested and "count" in nested:
        print("PASS: /api/backups/list")
        raise SystemExit(0)
if "backups" in data and isinstance(data["backups"], list):
    print("PASS: /api/backups/list")
    raise SystemExit(0)
raise SystemExit("missing backup list keys")
PY
}

check_console_send() {
  local payload
  local cmd="say release-smoke $(date +%s)"
  payload="$(post_json "/api/console/send" "{\"command\":\"${cmd}\"}")"
  python3 - "$payload" "$EXPECTED_CHANNEL" "$ALLOW_CONTROL_REQUIRED" <<'PY'
import json
import sys
data = json.loads(sys.argv[1])
expected_channel = sys.argv[2].strip()
allow_control_required = sys.argv[3].strip().lower() == "true"

if allow_control_required and not data.get("ok"):
    raise SystemExit("console send failed")

if expected_channel:
    channel = data.get("channel")
    if channel != expected_channel:
        raise SystemExit(f"unexpected channel: {channel!r}, expected {expected_channel!r}")

print("PASS: /api/console/send")
PY
}

echo "[smoke] BASE_URL=${BASE_URL}"
echo "[smoke] checking required endpoints..."
check_status
check_logs
check_console_output
check_backups_list
check_console_send
echo "[smoke] OK"
