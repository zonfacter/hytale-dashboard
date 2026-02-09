# Compatibility Contract

This document defines the minimum compatibility contract between:
- `zonfacter/hytale-dashboard` (upstream dashboard)
- `zonfacter/hytale-docker` (Docker integration layer)

## Scope

The following routes and behavior are treated as compatibility-critical.
Changes to these must be explicitly documented and coordinated with `hytale-docker`.

## Required Endpoints

- `GET /api/status`
- `GET /api/logs`
- `GET /api/console/output`
- `POST /api/console/send`
- `GET /api/backups/list`
- `POST /api/backups/restore`
- `POST /api/backups/create`

## Required Functions / Symbols in `app.py`

- `def get_logs() -> list[str]`
- `def _get_console_output(`
- `def send_console_command(`
- `DOCKER_MODE`
- `HYTALE_CONTAINER`

These are used by Docker compatibility patching and runtime behavior.

## Change Rules

1. Breaking changes to required endpoints must be released with a major/minor version bump and changelog note.
2. Any change touching log retrieval, console output, backup APIs, or Docker mode detection requires a compatibility CI pass against `hytale-docker`.
3. When in doubt, add an alias route instead of removing/renaming a route.
4. Docker command flow must keep an adapter path available (`.server_command` preferred, `.console_pipe` fallback).

## CI Gate

The workflow `.github/workflows/compatibility.yml` verifies contract symbols and runs a Docker integration patch simulation using `hytale-docker` patch scripts.

## Release Gate (Manual)

Before merge/release, run:

- `bash scripts/contract_check.sh`
- `bash scripts/preflight_compat.sh --server-dir /opt/hytale-server`
- `BASE_URL=http://<host>:<port> DASH_USER=<user> DASH_PASS=<pass> bash scripts/release_smoke.sh`

Full checklist: `RELEASE_CHECKLIST.md`
