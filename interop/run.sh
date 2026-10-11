#!/usr/bin/env bash
# Run the XRouter <-> LinBPQ interop suite against one or more XRouter tags.
#
#   interop/run.sh                 # latest
#   interop/run.sh 505o 505c 505a  # each in turn, results in interop/out/<tag>/
#
# Extra pytest arguments go after "--", e.g. interop/run.sh 505o -- -k inp3
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

tags=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do tags+=("$1"); shift; done
[ "${1:-}" = "--" ] && shift
[ ${#tags[@]} -eq 0 ] && tags=(latest)

if ! python3 -c 'import pytest' 2>/dev/null; then
    python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 2
    py=.venv/bin/python
else
    py=python3
fi

rc=0
for tag in "${tags[@]}"; do
    echo "=== XRouter $tag ==="
    XROUTER_TAG="$tag" XRI_OUT="$here/out/$tag" \
        "$py" -m pytest tests -v -rxX -p no:cacheprovider --junitxml="$here/out/$tag/junit.xml" "$@" || rc=1
done
exit $rc
