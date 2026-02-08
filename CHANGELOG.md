# Changelog

## [v1.5.0] - 2026-02-08

### Added
- Setup-Seite unter `/setup` fuer Server-Auth und Token-Verwaltung.
- API-Endpunkte fuer Auth-Status und Login-Start (`/api/auth/status`, `/api/auth/login/start`).
- Token-Backup und Token-Restore inkl. Script `hytale-token.sh`.
- Manuelle Backup-Erstellung mit Label/Kommentar (`/api/backup/create`) ueber `hytale-backup-manual.sh`.
- Backup-Metadaten (`.meta`) fuer Label/Kommentar/Quelle bei Archiv-Backups.

### Changed
- Docker-Mode: script-basierte API-Aufrufe nutzen kein `sudo` mehr; Scripts sind im Image enthalten.
- Backup-Verwaltung in `/manage` erweitert: Backup erstellen, Restore Welt/Voll und Seed-Neuscan pro Eintrag.
- Backup-UI zeigt Label und Kommentar in der Liste.
- Backup-Restore unterstuetzt jetzt auch `update-backup` neben klassischen Archiv-Backups.
- Restore-Flow erweitert fuer Quelle als Archiv oder `.update_backup_*` Verzeichnis.
- Auth-Status-Logik verbessert: neueste relevante Log-Ereignisse entscheiden den Status.
- Worker stabilisiert bei SQLite-Locks (busy timeout, robustere Interval-Steuerung).
- Zeitfilter fuer Performance-Historie und Cleanup auf epoch-basierte Vergleiche umgestellt.

### Fixed
- Seeds in der Backup-Verwaltung werden wieder konsistent aus Backup/Update-Backup ermittelt.
- Token-Status zeigt nicht mehr faelschlich "Nicht konfiguriert", wenn gueltige Auth vorhanden ist.
- Prometheus/Grafana-Datenaktualisierung verbessert durch korrigierte Zeitfenster-Abfragen.

### Docker Compatibility
- Backup-Restore und Token-Restore melden im Docker-Modus explizit "nicht unterstuetzt" statt eines intransparenten Script-Fehlers.
