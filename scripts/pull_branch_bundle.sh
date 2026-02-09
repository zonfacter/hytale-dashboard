#!/usr/bin/env bash

set -euo pipefail

# Pull a GitHub branch snapshot without git, intended for NAS/UGREEN hosts.
# Example:
#   bash pull_branch_bundle.sh \
#     --repo zonfacter/hytale-dashboard \
#     --branch feature/docker-command-adapter-v2 \
#     --base-dir /volume2/docker \
#     --name hytale-dashboard-feature

REPO=""
BRANCH="master"
BASE_DIR="/volume2/docker"
NAME=""
KEEP_OLD=1
MAX_RETRIES=5

usage() {
  cat <<'EOF'
Usage: pull_branch_bundle.sh --repo <owner/repo> [options]

Options:
  --repo <owner/repo>   GitHub repo, e.g. zonfacter/hytale-dashboard
  --branch <name>       Branch name (default: master)
  --base-dir <path>     Target base dir (default: /volume2/docker)
  --name <dir>          Target directory name (default: <repo>-<branch>)
  --keep-old <0|1>      Move old target to .bak_<timestamp> (default: 1)
  --retries <n>         Download retries on 429/network errors (default: 5)
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --base-dir) BASE_DIR="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --keep-old) KEEP_OLD="${2:-1}"; shift 2 ;;
    --retries) MAX_RETRIES="${2:-5}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$REPO" ]] || { echo "ERROR: --repo is required" >&2; usage; exit 1; }
[[ "$REPO" == */* ]] || { echo "ERROR: --repo must be owner/repo" >&2; exit 1; }

OWNER="${REPO%%/*}"
REPO_NAME="${REPO##*/}"

if [[ -z "$NAME" ]]; then
  SAFE_BRANCH="${BRANCH//\//-}"
  NAME="${REPO_NAME}-${SAFE_BRANCH}"
fi

ZIP_FILE="${BASE_DIR}/${NAME}.zip"
WORK_DIR="${BASE_DIR}/${NAME}.tmp"
TARGET_DIR="${BASE_DIR}/${NAME}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${TARGET_DIR}.bak_${TS}"

ZIP_URL="https://codeload.github.com/${OWNER}/${REPO_NAME}/zip/refs/heads/${BRANCH}"

echo "[pull] repo=${REPO}"
echo "[pull] branch=${BRANCH}"
echo "[pull] target=${TARGET_DIR}"
echo "[pull] url=${ZIP_URL}"

mkdir -p "$BASE_DIR"
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

download_zip() {
  local attempt
  for attempt in $(seq 1 "$MAX_RETRIES"); do
    echo "[pull] download attempt ${attempt}/${MAX_RETRIES}"
    if command -v wget >/dev/null 2>&1; then
      if wget -O "$ZIP_FILE" "$ZIP_URL"; then
        return 0
      fi
    elif command -v curl >/dev/null 2>&1; then
      if curl -fL "$ZIP_URL" -o "$ZIP_FILE"; then
        return 0
      fi
    else
      echo "ERROR: neither wget nor curl is installed" >&2
      return 1
    fi

    if [[ "$attempt" -lt "$MAX_RETRIES" ]]; then
      sleep $((attempt * 2))
    fi
  done
  return 1
}

extract_zip() {
  if command -v unzip >/dev/null 2>&1; then
    unzip -o "$ZIP_FILE" -d "$WORK_DIR" >/dev/null
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$ZIP_FILE" "$WORK_DIR" <<'PY'
import sys
import zipfile

zip_path = sys.argv[1]
target = sys.argv[2]
with zipfile.ZipFile(zip_path, "r") as zf:
    zf.extractall(target)
PY
    return 0
  fi

  echo "ERROR: cannot extract ZIP (missing unzip and python3)" >&2
  return 1
}

download_zip || { echo "ERROR: download failed after retries" >&2; exit 1; }
extract_zip

EXTRACTED_TOP="$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[[ -n "$EXTRACTED_TOP" ]] || { echo "ERROR: extracted archive is empty" >&2; exit 1; }

if [[ -d "$TARGET_DIR" ]]; then
  if [[ "$KEEP_OLD" == "1" ]]; then
    echo "[pull] moving old target to ${BACKUP_DIR}"
    mv "$TARGET_DIR" "$BACKUP_DIR"
  else
    echo "[pull] removing old target ${TARGET_DIR}"
    rm -rf "$TARGET_DIR"
  fi
fi

mv "$EXTRACTED_TOP" "$TARGET_DIR"
rm -rf "$WORK_DIR"

echo "[pull] done"
echo "[pull] ready at: ${TARGET_DIR}"

