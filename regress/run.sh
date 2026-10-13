#!/usr/bin/env bash
# Run the regress suite against one or more XRouter tags.
#
#   regress/run.sh                 # latest
#   regress/run.sh 505c 505o       # each in turn, results in regress/out/<tag>/
#   regress/run.sh 505o -- -k digi # extra pytest arguments after --
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

tags=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do tags+=("$1"); shift; done
[ "${1:-}" = "--" ] && shift
[ ${#tags[@]} -eq 0 ] && tags=(latest)

if ! python3 -c 'import pytest' 2>/dev/null; then
    python3 -m venv .venv && .venv/bin/pip install -q pytest || exit 2
    py=.venv/bin/python
else
    py=python3
fi

rc=0
for tag in "${tags[@]}"; do
    echo "=== XRouter $tag ==="
    mkdir -p "$here/out/$tag"
    XROUTER_TAG="$tag" XRR_OUT="$here/out/$tag" \
        "$py" -m pytest tests -v -rxXfE -p no:cacheprovider --junitxml="$here/out/$tag/junit.xml" "$@" || rc=1
done
exit $rc
