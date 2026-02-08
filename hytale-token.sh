#!/bin/bash
# Hytale auth token backup/restore helper
# Usage:
#   hytale-token.sh backup
#   hytale-token.sh restore <filename.enc>

set -euo pipefail
umask 027

SERVER_DIR="/opt/hytale-server"
BACKUP_DIR="${SERVER_DIR}/backups/auth_tokens"
AUTH_FILE="${SERVER_DIR}/auth.enc"
SERVICE_NAME="hytale.service"
HYTALE_USER="hytale"
HYTALE_GROUP="hytale"

cmd="${1:-}"

json_error() {
  printf '{"ok":false,"error":"%s"}\n' "$1"
  exit 1
}

case "$cmd" in
  backup)
    [[ -f "$AUTH_FILE" ]] || json_error "auth.enc nicht gefunden"
    mkdir -p "$BACKUP_DIR"
    ts="$(date +%Y%m%d_%H%M%S)"
    target="${BACKUP_DIR}/auth_${ts}.enc"
    cp -a "$AUTH_FILE" "$target"
    chown "${HYTALE_USER}:${HYTALE_GROUP}" "$target"
    chmod 600 "$target"
    printf '{"ok":true,"file":"%s"}\n' "$(basename "$target")"
    ;;
  restore)
    name="${2:-}"
    [[ -n "$name" ]] || json_error "Dateiname fehlt"
    [[ "$(basename "$name")" == "$name" ]] || json_error "Ungueltiger Dateiname"
    [[ "$name" == *.enc ]] || json_error "Nur .enc Dateien erlaubt"
    source_file="${BACKUP_DIR}/${name}"
    [[ -f "$source_file" ]] || json_error "Token-Backup nicht gefunden"

    cp -a "$AUTH_FILE" "${AUTH_FILE}.pre_restore_$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
    cp -a "$source_file" "$AUTH_FILE"
    chown "${HYTALE_USER}:${HYTALE_GROUP}" "$AUTH_FILE"
    chmod 600 "$AUTH_FILE"
    systemctl restart "$SERVICE_NAME"

    printf '{"ok":true,"restored":"%s"}\n' "$name"
    ;;
  *)
    json_error "Usage: $0 {backup|restore <file.enc>}"
    ;;
esac
