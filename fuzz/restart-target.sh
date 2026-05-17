#!/usr/bin/env bash
# restart-target.sh -- (re)start a managed xrouter instance for fuzzing.
#
# Usage: restart-target.sh <name> <http-port> <udp-port>
#
# Kills any existing xrouter for this instance, moves any cores into the
# instance dir for later triage, and starts a fresh xrouter in the
# background using xrouter-runner.sh. Returns immediately; the caller
# polls the HTTP port for readiness.

set -u

NAME="${1:?name}"
HTTP="${2:?http port}"
UDP="${3:?udp port}"

ROOT="/work/xr/run-$NAME"
PIDFILE="$ROOT/xrouter.pid"
mkdir -p "$ROOT/cores"

HERE="$(cd "$(dirname "$0")" && pwd)"

# Kill previous instance, if any.
if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE")
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
        kill -TERM "$OLD" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$OLD" 2>/dev/null || break
            sleep 0.1
        done
        kill -KILL "$OLD" 2>/dev/null
    fi
fi

# Stray xrouter processes in this instance's data dir (in case PID file
# is out of sync with reality).
pkill -KILL -f "/work/xr/run-$NAME/data" 2>/dev/null || true

# Sweep any pending cores into this instance's cores dir.
for f in /work/xr/cores/core.*; do
    [ -e "$f" ] && mv "$f" "$ROOT/cores/" 2>/dev/null
done

# Start a new instance. setsid + redirects detach it from this script so
# the fuzzer's restart command returns immediately.
setsid bash "$HERE/xrouter-runner.sh" "$NAME" "$HTTP" "$UDP" \
    >"$ROOT/stdout.log" 2>&1 </dev/null &
WRAPPER_PID=$!

# The wrapper exec's xrouter, so by the time we see it under the same
# PID it IS xrouter.
echo "$WRAPPER_PID" > "$PIDFILE"
