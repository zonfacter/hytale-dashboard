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
- `GET /api/backups/list`
- `POST /api/backups/restore`
- `POST /api/backups/create`

## Required Functions / Symbols in `app.py`

- `def get_logs() -> list[str]`
- `def _get_console_output(`
- `DOCKER_MODE`
- `HYTALE_CONTAINER`

These are used by Docker compatibility patching and runtime behavior.

## Change Rules

1. Breaking changes to required endpoints must be released with a major/minor version bump and changelog note.
2. Any change touching log retrieval, console output, backup APIs, or Docker mode detection requires a compatibility CI pass against `hytale-docker`.
3. When in doubt, add an alias route instead of removing/renaming a route.

## CI Gate

The workflow `.github/workflows/compatibility.yml` verifies contract symbols and runs a Docker integration patch simulation using `hytale-docker` patch scripts.
