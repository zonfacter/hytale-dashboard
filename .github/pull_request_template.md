## Summary
- What changed?
- Why?

## Validation
- [ ] Local tests/smoke checks executed
- [ ] CI relevant jobs passed

## Compatibility
- [ ] `COMPATIBILITY.md` reviewed
- [ ] No breaking change to required endpoints/symbols
- [ ] If breaking: changelog + versioning updated

## Docker Impact
- `docker_impact`: <!-- none | low | medium | high -->
- [ ] `hytale-docker` compatibility considered
- [ ] Patch pipeline (`apply_docker_patches.py`) still valid
- [ ] No new `sudo` dependency in Docker runtime path
- [ ] Service control in Docker remains `supervisorctl`-based

## Rollout Notes
- Required migration steps:
- Rollback path:
