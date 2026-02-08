#!/bin/bash
# Hytale Backup Restore Script
# Usage: hytale-restore.sh <backup.tar.gz|.update_backup_dir> [world|full]
# - world: restore only Server/universe
# - full: restore universe + auth/config/bans/whitelist/mods

set -euo pipefail
umask 027

SERVER_DIR="/opt/hytale-server"
BACKUP_DIR="${SERVER_DIR}/backups"
SERVICE_NAME="hytale.service"
HYTALE_USER="hytale"
HYTALE_GROUP="hytale"

SOURCE_INPUT="${1:-}"
MODE="${2:-world}"

usage() {
  echo "Usage: $0 <backup.tar.gz|backup.tgz|.update_backup_dir> [world|full]" >&2
  exit 1
}

json_error() {
  printf '{"ok":false,"error":"%s"}\n' "$1"
  exit 1
}

if [[ -z "$SOURCE_INPUT" ]]; then
  usage
fi

case "$MODE" in
  world|full) ;;
  *) usage ;;
esac

source_path="$(readlink -f "$SOURCE_INPUT" 2>/dev/null || true)"
backup_root="$(readlink -f "$BACKUP_DIR" 2>/dev/null || true)"
server_root="$(readlink -f "$SERVER_DIR" 2>/dev/null || true)"

if [[ -z "$source_path" || -z "$backup_root" || -z "$server_root" || ! -e "$source_path" ]]; then
  json_error "Quelle nicht gefunden"
fi

source_type=""
if [[ -f "$source_path" ]]; then
  if [[ "${source_path#${backup_root}/}" == "$source_path" ]]; then
    json_error "Backup-Datei muss unter ${BACKUP_DIR} liegen"
  fi
  case "$source_path" in
    *.tar.gz|*.tgz) ;;
    *) json_error "Nur .tar.gz/.tgz Backups werden als Datei unterstuetzt" ;;
  esac
  if ! tar -tzf "$source_path" universe/worlds/default/config.json >/dev/null 2>&1; then
    json_error "Backup enthaelt keine gueltige universe/worlds/default/config.json"
  fi
  source_type="archive"
elif [[ -d "$source_path" ]]; then
  if [[ "${source_path#${server_root}/}" == "$source_path" ]]; then
    json_error "Update-Backup muss unter ${SERVER_DIR} liegen"
  fi
  if [[ "$(basename "$source_path")" != .update_backup_* ]]; then
    json_error "Nur .update_backup_* Verzeichnisse werden unterstuetzt"
  fi
  if [[ ! -f "${source_path}/Server/universe/worlds/default/config.json" && ! -f "${source_path}/universe/worlds/default/config.json" ]]; then
    json_error "Update-Backup enthaelt keine gueltige universe/worlds/default/config.json"
  fi
  source_type="update-dir"
else
  json_error "Ungueltige Quelle"
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
pre_dir="${SERVER_DIR}/.restore_pre_${timestamp}"
extract_dir="$(mktemp -d "${SERVER_DIR}/.restore_extract_XXXXXX")"
restore_ok=false

cleanup() {
  rm -rf "$extract_dir"
}
trap cleanup EXIT

recover_service_on_error() {
  if [[ "$restore_ok" != true ]]; then
    systemctl start "$SERVICE_NAME" >/dev/null 2>&1 || true
  fi
}
trap recover_service_on_error ERR

systemctl stop "$SERVICE_NAME" 2>/dev/null || true

mkdir -p "$pre_dir"

if [[ -d "${SERVER_DIR}/Server/universe" ]]; then
  mv "${SERVER_DIR}/Server/universe" "${pre_dir}/Server.universe.before"
fi

if [[ "$MODE" == "full" ]]; then
  for item in auth.enc config.json bans.json whitelist.json; do
    if [[ -f "${SERVER_DIR}/${item}" ]]; then
      cp -a "${SERVER_DIR}/${item}" "${pre_dir}/${item}.before"
    fi
  done
  if [[ -d "${SERVER_DIR}/mods" ]]; then
    mv "${SERVER_DIR}/mods" "${pre_dir}/mods.before"
  fi
fi

if [[ "$source_type" == "archive" ]]; then
  tar -xzf "$source_path" -C "$extract_dir" universe
elif [[ -d "${source_path}/Server/universe" ]]; then
  cp -a "${source_path}/Server/universe" "${extract_dir}/universe"
else
  cp -a "${source_path}/universe" "${extract_dir}/universe"
fi

if [[ "$MODE" == "full" ]]; then
  if [[ "$source_type" == "archive" ]]; then
    for optional in auth.enc config.json bans.json whitelist.json mods; do
      if tar -tzf "$source_path" "$optional" >/dev/null 2>&1; then
        tar -xzf "$source_path" -C "$extract_dir" "$optional"
      fi
    done
  else
    for optional in auth.enc config.json bans.json whitelist.json mods; do
      if [[ -e "${source_path}/${optional}" ]]; then
        cp -a "${source_path}/${optional}" "${extract_dir}/${optional}"
      fi
    done
  fi
fi

mkdir -p "${SERVER_DIR}/Server"
rm -rf "${SERVER_DIR}/Server/universe"
cp -a "${extract_dir}/universe" "${SERVER_DIR}/Server/universe"

if [[ "$MODE" == "full" ]]; then
  for cfg in auth.enc config.json bans.json whitelist.json; do
    if [[ -e "${extract_dir}/${cfg}" ]]; then
      cp -a "${extract_dir}/${cfg}" "${SERVER_DIR}/${cfg}"
    fi
  done

  if [[ -d "${extract_dir}/mods" ]]; then
    rm -rf "${SERVER_DIR}/mods"
    cp -a "${extract_dir}/mods" "${SERVER_DIR}/mods"
  fi
fi

# Normalize ownership and permissions
chown -R "${HYTALE_USER}:${HYTALE_GROUP}" "${SERVER_DIR}/Server/universe"
find "${SERVER_DIR}/Server/universe" -type d -exec chmod 750 {} +
find "${SERVER_DIR}/Server/universe" -type f -exec chmod 640 {} +
if [[ -f "${SERVER_DIR}/Server/universe/worlds/default/config.json" ]]; then
  chmod 664 "${SERVER_DIR}/Server/universe/worlds/default/config.json"
fi

if [[ "$MODE" == "full" ]]; then
  if [[ -f "${SERVER_DIR}/auth.enc" ]]; then
    chown "${HYTALE_USER}:${HYTALE_GROUP}" "${SERVER_DIR}/auth.enc"
    chmod 600 "${SERVER_DIR}/auth.enc"
  fi
  for cfg in config.json bans.json whitelist.json; do
    if [[ -f "${SERVER_DIR}/${cfg}" ]]; then
      chown "${HYTALE_USER}:${HYTALE_GROUP}" "${SERVER_DIR}/${cfg}"
      chmod 664 "${SERVER_DIR}/${cfg}"
    fi
  done
  if [[ -d "${SERVER_DIR}/mods" ]]; then
    chown -R "${HYTALE_USER}:${HYTALE_GROUP}" "${SERVER_DIR}/mods"
    chmod 770 "${SERVER_DIR}/mods"
  fi
fi

systemctl start "$SERVICE_NAME"
restore_ok=true

printf '{"ok":true,"mode":"%s","source_type":"%s","backup":"%s","snapshot":"%s"}\n' "$MODE" "$source_type" "$(basename "$source_path")" "$pre_dir"
