#!/bin/bash
# Hytale Server Wrapper - Provides FIFO pipe for console commands
# Install: sudo cp start-hytale.sh /opt/hytale-server/start.sh && sudo chmod 755 /opt/hytale-server/start.sh

PIPE=/opt/hytale-server/.console_pipe

# Create FIFO if it doesn't exist
[ -p "$PIPE" ] || mkfifo "$PIPE"
chmod 660 "$PIPE"
chown hytale:hytale "$PIPE" 2>/dev/null || true

# Cleanup on exit
cleanup() {
    rm -f "$PIPE"
    kill 0 2>/dev/null
    wait
}
trap cleanup EXIT INT TERM

# tail -f keeps the FIFO open for multiple writers
# Server reads commands from it via stdin
tail -f "$PIPE" | exec java "$@"
