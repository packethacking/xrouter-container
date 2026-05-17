#!/usr/bin/env bash
# run-all.sh -- launch every fuzzer in parallel against its own xrouter
# instance, write per-fuzzer logs to /work/xr/logs/, and (when DURATION
# is reached) summarise unique crash signatures across all instances.
#
# Usage: run-all.sh [duration_seconds]

set -u

DURATION="${1:-300}"
HERE="$(cd "$(dirname "$0")" && pwd)"
LOGS=/work/xr/logs
mkdir -p "$LOGS"

# (name, http, udp, fuzz-script, fuzzer-args)
# Port allocations: http_base + 10*i, udp_base + 10*i
declare -a JOBS=(
    "axudp  18200 20200  axudp-fuzz.py  --target 127.0.0.1:20200 --health http://127.0.0.1:18200/ --restart-cmd ${HERE}/restart-target.sh\\ axudp\\ 18200\\ 20200 --probe-every 300 --duration ${DURATION} --corpus /work/xr/run-axudp/bugs/"
    "agw    18210 20210  agw-fuzz.py    --name agw --http-port 18210 --udp-port 20210 --agw-port 18212 --probe-every 500 --duration ${DURATION}"
    "http   18220 20220  http-fuzz.py   --name http --http-port 18220 --udp-port 20220 --probe-every 300 --duration ${DURATION}"
    "mqtt   18230 20230  mqtt-fuzz.py   --name mqtt --http-port 18230 --udp-port 20230 --mqtt-port 18231 --probe-every 400 --duration ${DURATION}"
    "aprs   18240 20240  aprs-fuzz.py   --name aprs --http-port 18240 --udp-port 20240 --aprs-port 18243 --probe-every 400 --duration ${DURATION}"
)

# Start an instance for each
for spec in "${JOBS[@]}"; do
    eval "set -- $spec"
    name=$1; http=$2; udp=$3
    "$HERE/restart-target.sh" "$name" "$http" "$udp"
done

# Wait for all to be up
sleep 6
for spec in "${JOBS[@]}"; do
    eval "set -- $spec"
    name=$1; http=$2
    if curl -m 3 -o /dev/null -s "http://127.0.0.1:$http/"; then
        echo "[+] $name up on $http"
    else
        echo "[!] $name FAILED to come up on $http"
    fi
done

# Kick off each fuzzer
pids=()
for spec in "${JOBS[@]}"; do
    eval "set -- $spec"
    name=$1; http=$2; udp=$3; script=$4; shift 4
    log="$LOGS/${name}.log"
    echo "[+] starting $name -> $log"
    nohup python3 "$HERE/$script" "$@" >"$log" 2>&1 &
    pids+=($!)
done

echo "[+] all fuzzers started; waiting ${DURATION}s..."
echo "[+] PIDs: ${pids[*]}"

# Wait for all to finish
for p in "${pids[@]}"; do wait "$p" 2>/dev/null || true; done

echo
echo "=== summary ==="
for spec in "${JOBS[@]}"; do
    eval "set -- $spec"
    name=$1
    log="$LOGS/${name}.log"
    if [ -f "$log" ]; then
        n=$(grep -c 'NEW BUG' "$log" 2>/dev/null || echo 0)
        printf "%-6s  new bugs: %s  log: %s\n" "$name" "$n" "$log"
    fi
done
echo
echo "=== unique signatures across all instances ==="
for inst in axudp agw http mqtt aprs; do
    f=/work/xr/run-$inst/findings.jsonl
    [ -f "$f" ] || continue
    python3 -c "
import json, sys
sigs = {}
for line in open('$f'):
    try:
        d = json.loads(line)
    except: continue
    s = d.get('signature')
    if not s: continue
    if s not in sigs:
        sigs[s] = (d.get('signal'), d.get('rip'), d.get('insn'), 1)
    else:
        sig, rip, insn, n = sigs[s]
        sigs[s] = (sig, rip, insn, n+1)
for s, (sig, rip, insn, n) in sigs.items():
    print(f'  [$inst] {s}  hits={n}  {sig:7} rip={rip}  {insn}')
"
done
