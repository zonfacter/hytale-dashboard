#!/usr/bin/env sh

set -eu

SERVER_DIR="/opt/hytale-server"
WRAPPER_PATH="/usr/local/bin/hytale-server-wrapper.sh"

usage() {
  cat <<'EOF'
Usage: preflight_compat.sh [options]

Options:
  --server-dir <path>  Server root path (default: /opt/hytale-server)
  --wrapper <path>     Wrapper path (default: /usr/local/bin/hytale-server-wrapper.sh)
  -h, --help           Show help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --server-dir)
      SERVER_DIR="${2:-}"
      shift 2
      ;;
    --wrapper)
      WRAPPER_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

failures=0
warnings=0

pass() { echo "PASS: $*"; }
warn() { echo "WARN: $*"; warnings=$((warnings + 1)); }
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

if [ -d "$SERVER_DIR" ]; then
  pass "server directory exists: $SERVER_DIR"
else
  fail "server directory missing: $SERVER_DIR"
fi

if [ -f "${SERVER_DIR}/Server/HytaleServer.jar" ]; then
  pass "server binary present: ${SERVER_DIR}/Server/HytaleServer.jar"
else
  fail "missing server binary: ${SERVER_DIR}/Server/HytaleServer.jar"
fi

if [ -f "${SERVER_DIR}/Assets.zip" ]; then
  pass "assets present: ${SERVER_DIR}/Assets.zip"
else
  fail "missing assets: ${SERVER_DIR}/Assets.zip"
fi

if [ -p "${SERVER_DIR}/.console_pipe" ]; then
  pass "console pipe present: ${SERVER_DIR}/.console_pipe"
else
  warn "console pipe missing: ${SERVER_DIR}/.console_pipe"
fi

if [ -e "${SERVER_DIR}/.server_command" ]; then
  pass "server command adapter present: ${SERVER_DIR}/.server_command"
else
  warn "server command adapter missing: ${SERVER_DIR}/.server_command"
fi

if [ -p "${SERVER_DIR}/.console_pipe" ] || [ -e "${SERVER_DIR}/.server_command" ]; then
  pass "at least one command adapter is available"
else
  fail "no command adapter found (.console_pipe or .server_command)"
fi

if [ -f "${SERVER_DIR}/start.sh" ] && [ -x "${SERVER_DIR}/start.sh" ]; then
  pass "start script is executable: ${SERVER_DIR}/start.sh"
elif [ -f "${SERVER_DIR}/start.sh" ]; then
  fail "start script is not executable: ${SERVER_DIR}/start.sh"
else
  warn "start script missing: ${SERVER_DIR}/start.sh"
fi

if [ -f "$WRAPPER_PATH" ] && [ -x "$WRAPPER_PATH" ]; then
  pass "wrapper is executable: ${WRAPPER_PATH}"
elif [ -f "$WRAPPER_PATH" ]; then
  fail "wrapper is not executable: ${WRAPPER_PATH}"
else
  warn "wrapper missing: ${WRAPPER_PATH}"
fi

for d in Server "Server/universe" mods backups .downloader logs; do
  if [ -d "${SERVER_DIR}/${d}" ]; then
    pass "runtime path present: ${SERVER_DIR}/${d}"
  else
    warn "runtime path missing: ${SERVER_DIR}/${d}"
  fi
done

echo
echo "Summary: failures=${failures}, warnings=${warnings}"
if [ "$failures" -gt 0 ]; then
  exit 1
fi
