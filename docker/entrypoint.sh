#!/bin/sh
# XRouter Docker entrypoint.
#
# Refreshes docs (HELP/MAN/INFO/MISC) from the image so they track the
# binary, seeds sample .SYS/.ACL/.CFG files into /data on first run
# (without clobbering subsequent sysop edits), creates the runtime
# subdirs XRouter expects to exist, then runs xrouter from /data so
# cwd-relative state lands in the volume.
#
# Output mode is controlled by XROUTER_TUI (default 0, headless):
#
#   XROUTER_TUI=0   (default) — xrouter runs in the background with
#                   stdout discarded; the entrypoint tails the
#                   /data/LOG/*.TXT files to PID 1 stdout so
#                   `docker logs` is a structured log stream and
#                   testcontainers `WaitForLogMessage` works against
#                   real boot lines. SIGTERM is forwarded to xrouter
#                   for clean shutdown.
#
#   XROUTER_TUI=1   xrouter runs in the foreground and emits its
#                   curses status TUI to stdout. Useful for
#                   `docker run -it` interactive inspection.
#
# Usage:
#   docker run --rm -it \
#       -v "$PWD/myxrouter:/data" \
#       -p 23:23 -p 80:80 -p 2323:2323 \
#       <image>:latest
#
# A dummy XROUTER.CFG ships at /opt/xrouter/skel/XROUTER.CFG.example;
# copy it into your mounted dir and edit it for your callsign:
#
#   cp /opt/xrouter/skel/XROUTER.CFG.example /data/XROUTER.CFG
#
# For non-loopback ports (real AX25/AXIP/AXUDP) the container will
# likely need --cap-add=NET_RAW. The dummy cfg uses pure loopback so
# the smoke test runs without extra caps.

set -e

SKEL=/opt/xrouter/skel

# Docs: refresh from image on every run (lock-step with binary).
for d in HELP MAN INFO MISC; do
    if [ -d "$SKEL/$d" ]; then
        rm -rf "/data/$d"
        cp -rf "$SKEL/$d" "/data/$d"
    fi
done

# Sample config files: cp -n equivalent (only if missing — don't
# overwrite sysop edits). XROUTER.CFG.example lets sysops bootstrap
# their own XROUTER.CFG.
for f in ACCESS.SYS BOOTCMDS.SYS CRONTAB.SYS HTTP.ACL HTTP.SYS \
         HTTPBAN.SYS IGATE.CFG IPROUTE.SYS LANGS.SYS PASSWORD.SYS \
         TELGUEST.ACL TELPROXY.ACL USERPASS.SYS \
         ESPANOL.SYS FRANCAIS.SYS NEDERLANDS.SYS \
         XROUTER.CFG.example; do
    if [ -f "$SKEL/$f" ] && [ ! -f "/data/$f" ]; then
        cp -p "$SKEL/$f" "/data/$f"
    fi
done

# Sample FINGER files: same don't-clobber rule, file by file.
if [ -d "$SKEL/FINGER" ]; then
    mkdir -p /data/FINGER
    for f in "$SKEL/FINGER/"*; do
        [ -f "$f" ] || continue
        name=$(basename "$f")
        [ -f "/data/FINGER/$name" ] || cp -p "$f" "/data/FINGER/$name"
    done
fi

# Subdirs XRouter needs to exist (it'll create others on demand).
mkdir -p /data/LOG /data/CHAT /data/PMS /data/FINGER

cd /data

if [ ! -f XROUTER.CFG ]; then
    cat >&2 <<EOF
ERROR: /data/XROUTER.CFG not found.

Mount a host directory containing your XROUTER.CFG as /data, e.g.:

    docker run --rm -it \\
        -v "\$PWD/myxrouter:/data" \\
        -p 23:23 -p 80:80 -p 2323:2323 \\
        <image>:latest

A starter config ships at /opt/xrouter/skel/XROUTER.CFG.example — copy
it into your mounted dir and edit it for your callsign:

    cp /opt/xrouter/skel/XROUTER.CFG.example /data/XROUTER.CFG
EOF
    exit 1
fi

# TUI mode — preserve original behaviour for interactive sessions.
if [ "${XROUTER_TUI:-0}" = "1" ]; then
    exec /usr/local/bin/xrouter "$@"
fi

# Headless mode (default): xrouter in background with stdout silenced,
# log files tailed to PID 1 stdout, signals forwarded.
/usr/local/bin/xrouter "$@" >/dev/null 2>&1 &
XR_PID=$!

forward_term() {
    kill -TERM "$XR_PID" 2>/dev/null || true
}
trap forward_term TERM INT

# xrouter writes BOOTLOG.TXT plus a day-stamped log within ~1s of
# starting; poll briefly so `tail -F` has files to follow.
i=0
while [ $i -lt 20 ] && [ -z "$(ls -A /data/LOG 2>/dev/null)" ]; do
    sleep 0.25
    i=$((i + 1))
done

if [ -n "$(ls -A /data/LOG 2>/dev/null)" ]; then
    tail -n +1 -F /data/LOG/*.TXT 2>/dev/null &
    TAIL_PID=$!
else
    echo "warning: /data/LOG is still empty after startup grace period" >&2
    TAIL_PID=
fi

# `wait` returns 128+signo when interrupted; the trap re-fires kill,
# xrouter then exits, and the next wait yields its real status.
set +e
wait "$XR_PID"
RC=$?
while kill -0 "$XR_PID" 2>/dev/null; do
    wait "$XR_PID"
    RC=$?
done
set -e

if [ -n "$TAIL_PID" ]; then
    kill -TERM "$TAIL_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
fi

exit "$RC"
