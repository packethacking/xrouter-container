#!/usr/bin/env bash
# Boot a clean xrouter target and run the AXUDP fuzzer against it.
#
# Usage:
#   fuzz/run-demo.sh                       # default: 505c-amd64, 5 min
#   fuzz/run-demo.sh 504v-amd64            # specific version
#   fuzz/run-demo.sh 504u-arm64 600        # specific version, 10 min
#
# Requires a running Docker daemon and python3 (stdlib only).

set -euo pipefail

TAG="${1:-505c-amd64}"
DURATION="${2:-300}"
IMG="ghcr.io/packethacking/xrouter:${TAG}"

# Fixed host ports so `docker restart` (used by the fuzzer's --replay
# bisector) keeps the same mappings across the container lifecycle.
PORT_HTTP="${PORT_HTTP:-18080}"
PORT_UDP="${PORT_UDP:-10093}"

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d -t xr-fuzz-XXXXXX)"
cp "$HERE/XROUTER.CFG" "$WORK/XROUTER.CFG"

CNAME="xr-fuzz-target"
cleanup() {
    docker rm -f "$CNAME" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "[+] starting target: $IMG"
docker rm -f "$CNAME" >/dev/null 2>&1 || true
docker run -d --name "$CNAME" \
    -v "$WORK":/data \
    -p "$PORT_HTTP":80/tcp \
    -p "$PORT_UDP":10093/udp \
    "$IMG" >/dev/null

echo "[+] http=$PORT_HTTP  axudp=$PORT_UDP/udp  duration=${DURATION}s"

# Wait for HTTP to come up (xrouter takes a few seconds to bind)
for _ in $(seq 1 30); do
    if curl -fsS -m 1 "http://127.0.0.1:$PORT_HTTP/" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

python3 "$HERE/axudp-fuzz.py" \
    --target "127.0.0.1:$PORT_UDP" \
    --health "http://127.0.0.1:$PORT_HTTP/" \
    --duration "$DURATION" \
    --corpus "$HERE/crashes" \
    --restart-cmd "docker restart $CNAME" || true

# Print a hint for follow-up bisection of any crash batches produced.
latest=$(ls -t "$HERE/crashes"/batch-*.txt 2>/dev/null | head -1 || true)
if [ -n "$latest" ]; then
    echo
    echo "[+] crash batch saved: $latest"
    echo "    to find the minimum trigger frame:"
    echo "      python3 $HERE/axudp-fuzz.py \\"
    echo "          --target 127.0.0.1:$PORT_UDP \\"
    echo "          --health http://127.0.0.1:$PORT_HTTP/ \\"
    echo "          --replay $latest \\"
    echo "          --restart-cmd 'docker restart $CNAME'"
fi
