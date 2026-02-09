# Release Checklist (Docker + Native Compatibility)

This checklist is mandatory before merging Docker adapter changes to `master`.

## 1. Branch and Scope

- [ ] Work is on a feature branch (not `master`)
- [ ] Scope is documented in PR summary
- [ ] Rollback path is documented

## 2. Compatibility Contract

- [ ] `COMPATIBILITY.md` reviewed and still accurate
- [ ] Contract check passes:
  - `bash scripts/contract_check.sh`
- [ ] Docker integration simulation CI is green

## 3. Runtime Preflight (Target Host / Container)

- [ ] Preflight passes:
  - `bash scripts/preflight_compat.sh --server-dir /opt/hytale-server`
- [ ] Wrapper and startup scripts are executable
- [ ] Runtime files exist:
  - `/opt/hytale-server/Server/HytaleServer.jar`
  - `/opt/hytale-server/Assets.zip`
- [ ] At least one command adapter exists:
  - `/opt/hytale-server/.server_command` or `/opt/hytale-server/.console_pipe`

## 4. API Smoke Test

- [ ] Status endpoint:
  - `GET /api/status`
- [ ] Logs endpoint:
  - `GET /api/logs`
- [ ] Console output endpoint:
  - `GET /api/console/output`
- [ ] Console send endpoint:
  - `POST /api/console/send`
- [ ] Backup list endpoint:
  - `GET /api/backups/list`
- [ ] Smoke script passes:
  - `BASE_URL=http://<host>:<port> DASH_USER=<user> DASH_PASS=<pass> bash scripts/release_smoke.sh`
- [ ] In Docker adapter rollout, console send uses `server_command` channel

## 5. Persistence and Restart Safety

- [ ] Persistent mounts validated:
  - `Server`, `Server/universe`, `mods`, `backups`, `.downloader`, `logs`
- [ ] Container recreate test completed
- [ ] Post-recreate smoke test still passes

## 6. Finalization

- [ ] Changelog updated (if behavior changed)
- [ ] PR checklist fully checked
- [ ] Merge approved
