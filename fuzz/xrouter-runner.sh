#!/usr/bin/env bash
# xrouter-runner.sh -- one-shot launcher for an xrouter instance with a
# distinct port set, used as a fuzzing target.
#
# Usage: xrouter-runner.sh <name> <http-port> <udp-port> [bin] [skel]
#
# Sets up /work/xr/run-<name>/data with a fresh XROUTER.CFG that pins the
# ports, copies the support files in, runs xrouter from that directory,
# and (on crash) leaves the core in /work/xr/run-<name>/cores/. Exits
# with the same exit code xrouter did.

set -u

NAME="${1:?name}"
HTTP="${2:?http port}"
UDP="${3:?udp port}"
BIN="${4:-/work/xr/xrouter}"
SKEL="${5:-/work/xr/skel}"

ROOT="/work/xr/run-$NAME"
DATA="$ROOT/data"
CORES="$ROOT/cores"
mkdir -p "$DATA" "$CORES"

# Per-process core_pattern is set globally to /work/xr/cores/core.%p;
# the harness moves them into the per-instance dir after exit.

# Seed support files (skip if already present so we don't clobber state
# the previous run might have written that we want to keep).
for d in HELP MAN INFO MISC FINGER; do
    [ -d "$SKEL/$d" ] && [ ! -d "$DATA/$d" ] && cp -r "$SKEL/$d" "$DATA/"
done
for f in "$SKEL"/*.SYS "$SKEL"/*.ACL; do
    [ -f "$f" ] && [ ! -f "$DATA/$(basename "$f")" ] && cp "$f" "$DATA/"
done
mkdir -p "$DATA/LOG" "$DATA/CHAT" "$DATA/PMS" "$DATA/FINGER"

cat > "$DATA/XROUTER.CFG" << EOF
DNS=8.8.8.8
NODECALL=G9DUM-1
NODEALIAS=DUMMY
CONSOLECALL=G9DUM
CHATCALL=G9DUM-8
CHATALIAS=DUMCHT
LOCATOR=IO92
IPADDRESS=44.128.128.128
CTEXT
fuzz target
***
INFOTEXT
fuzz target
***
IDTEXT
fuzz target
***

HTTPPORT=$HTTP $HTTP
TELNETPORT=0
FTPPORT=0
RLOGINPORT=0
MQTTPORT=$((HTTP+1)) $((HTTP+1))
AGWPORT=$((HTTP+2)) $((HTTP+2))
TELPROXYPORT=0
APRSPORT=$((HTTP+3)) $((HTTP+3))
FINGERPORT=$((HTTP+4)) $((HTTP+4))
TTYLINKPORT=$((HTTP+5)) $((HTTP+5))

INTERFACE=1
	TYPE=LOOPBACK
	PROTOCOL=KISS
	MTU=256
ENDINTERFACE

PORT=1
	ID="Loopback port"
	INTERFACENUM=1
ENDPORT

INTERFACE=2
	TYPE=AXUDP
	MTU=256
ENDINTERFACE

PORT=2
	ID="AXUDP fuzz target"
	INTERFACENUM=2
	IPLINK=0.0.0.0
	UDPLOCAL=$UDP
	LEARN=1
ENDPORT
EOF

cd "$DATA"
ulimit -c unlimited
# Run xrouter; on crash the kernel writes the core to /work/xr/cores/core.<pid>
exec "$BIN"
