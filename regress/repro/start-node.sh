#!/bin/sh
# Start a fresh XRouter for the reproductions, straight from a published
# binary (no Docker):
#
#   regress/repro/start-node.sh ./xrlin64v505o-static [workdir]
#
# Makes a clean working directory (default ./xrrepro-node, emptied first)
# with the config files from regress/repro/node/, starts the binary there
# in the background with its console output discarded, and waits for
# "version ... started" in LOG/BOOTLOG.TXT. A node left over from a
# previous run in the same workdir is killed first. Stop it with:
#
#   kill -9 $(cat xrrepro-node/xrouter.pid)
#
# (-9 because a node hung by the #12 reproduction ignores SIGTERM.)
#
# The node uses only unprivileged ports on 127.0.0.1: telnet 8023, AGW 8000,
# and an AXUDP port that sends to 127.0.0.1:9999.
set -e
bin=${1:?usage: start-node.sh <xrouter binary> [workdir]}
dir=${2:-./xrrepro-node}
here=$(cd "$(dirname "$0")" && pwd)
case $bin in /*) ;; *) bin=$(pwd)/$bin ;; esac
chmod +x "$bin"
if [ -f "$dir/xrouter.pid" ]; then kill -9 "$(cat "$dir/xrouter.pid")" 2>/dev/null || true; sleep 1; fi
rm -rf "$dir"
mkdir -p "$dir/LOG" "$dir/PMS" "$dir/CHAT"
cp "$here/node/XROUTER.CFG" "$here/node/ACCESS.SYS" "$here/node/PASSWORD.SYS" "$dir/"
cp "$here/node/PMS/DISTRIB.SYS" "$here/node/PMS/FWD.SYS" "$dir/PMS/"
cd "$dir"
nohup "$bin" >/dev/null 2>&1 &
echo $! > xrouter.pid
i=0
until grep -q "version .* started" LOG/BOOTLOG.TXT 2>/dev/null; do
    i=$((i+1))
    if [ $i -gt 30 ]; then echo "XRouter did not start:"; cat LOG/BOOTLOG.TXT 2>/dev/null; exit 1; fi
    sleep 1
done
sleep 2
grep "started" LOG/BOOTLOG.TXT | tail -1
