#!/usr/bin/env bash
# Manual Hytale backup with optional label/comment metadata
# Usage: hytale-backup-manual.sh [label] [comment]

set -euo pipefail
umask 027

BASE="/opt/hytale-server"
DEST="${BASE}/backups"
LABEL_RAW="${1:-}"
COMMENT_RAW="${2:-}"
TS="$(date +%F_%H-%M-%S)"

slugify() {
  local s="$1"
  s="$(echo "$s" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9._-' '-')"
  s="${s#-}"
  s="${s%-}"
  echo "${s:0:40}"
}

sanitize_text() {
  local s="$1"
  s="${s//$'\n'/ }"
  s="${s//$'\r'/ }"
  # Trim and limit
  s="$(echo "$s" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  echo "${s:0:240}"
}

LABEL="$(sanitize_text "$LABEL_RAW")"
COMMENT="$(sanitize_text "$COMMENT_RAW")"
SLUG="$(slugify "$LABEL")"

if [[ -z "$SLUG" ]]; then
  ARCHIVE="${DEST}/hytale_${TS}.tar.gz"
else
  ARCHIVE="${DEST}/hytale_${TS}_${SLUG}.tar.gz"
fi
META="${ARCHIVE%.tar.gz}.meta"

mkdir -p "$DEST"

# Hot backup
TAR_RC=0
tar -czf "${ARCHIVE}" -C "${BASE}" \
  universe \
  config.json \
  auth.enc \
  whitelist.json \
  bans.json \
  mods 2>/dev/null || TAR_RC=$?

if [[ ! -f "${ARCHIVE}" ]]; then
  echo "Backup fehlgeschlagen" >&2
  exit 1
fi

{
  echo "source=manual"
  echo "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "label=$LABEL"
  echo "comment=$COMMENT"
} > "$META"

chown hytale:hytale "$ARCHIVE" "$META" 2>/dev/null || true
chmod 640 "$ARCHIVE" "$META" 2>/dev/null || true

# Retention aligned with default backup script
find "${DEST}" -type f -name "hytale_*.tar.gz" -mtime +7 -delete
find "${DEST}" -type f -name "hytale_*.meta" -mtime +7 -delete

if [[ $TAR_RC -ne 0 ]]; then
  echo "Backup erstellt mit Warnungen (tar rc=$TAR_RC): $(basename "$ARCHIVE")"
  exit 0
fi

echo "Backup erstellt: $(basename "$ARCHIVE")"
