#!/usr/bin/env bash
# Build XRouter Docker images for one or all architectures, locally.
#
# Reads versions.json, picks the URLs/shas for the requested version,
# and drives `docker buildx build`. Each arch yields tags of the form
# packethacking/xrouter:<version>-<arch> and <version>-<arch>-<sha8>,
# plus <version>-<arch>-<sha8> for each replaced "previous" binary;
# with --multi the function instead pushes a multi-arch manifest list,
# which requires a registry.
#
# Usage:
#   scripts/build.sh                     # latest version, all arches, --load
#   scripts/build.sh 504v                # specific version, all arches
#   scripts/build.sh 504v amd64          # one arch only
#   scripts/build.sh 504v all --multi    # build all arches into a single
#                                        # manifest list (requires --push;
#                                        # not used in local-only mode)
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${1:-}"
ARCH_FILTER="${2:-all}"

# Tiny python helper instead of jq so we avoid an extra dep on dev / CI.
mf() { python3 -c "import json,sys; d=json.load(open('versions.json')); print(eval(sys.argv[1]) or '')" "$1"; }

if [ -z "$VERSION" ]; then
    VERSION=$(mf 'd["latest"]')
fi

SUPPORT_URL=$(mf 'd["support"]["url"]')
SUPPORT_SHA=$(mf 'd["support"]["sha256"]')

if [ -z "$(mf "d['versions'].get('$VERSION')")" ]; then
    echo "ERROR: version '$VERSION' not in versions.json" >&2
    exit 1
fi

# One docker buildx build. Extra arguments are -t tags.
build_one() {
    local platform="$1" bin_url="$2" bin_sha="$3" pkgs="$4"
    shift 4
    docker buildx build \
        --platform "$platform" \
        --build-arg SUPPORT_URL="$SUPPORT_URL" \
        --build-arg SUPPORT_SHA256="$SUPPORT_SHA" \
        --build-arg BIN_URL="$bin_url" \
        --build-arg BIN_SHA256="$bin_sha" \
        --build-arg XROUTER_VERSION="$VERSION" \
        --build-arg RUNTIME_PACKAGES="$pkgs" \
        -f docker/Dockerfile \
        "$@" \
        --load \
        .
}

# Builds the current binary as <version>-<arch> and <version>-<arch>-<sha8>,
# then any binaries upstream later replaced ("previous" in versions.json)
# as <version>-<arch>-<sha8> only.
build_arch() {
    local arch="$1" platform="$2"
    local bin_url bin_sha pkgs
    bin_url=$(mf "d['versions']['$VERSION'].get('$arch',{}).get('url','')")
    bin_sha=$(mf "d['versions']['$VERSION'].get('$arch',{}).get('sha256','')")
    pkgs=$(mf "d['versions']['$VERSION'].get('$arch',{}).get('packages','')")
    if [ -z "$bin_url" ]; then
        echo "skip: $VERSION has no $arch build" >&2
        return 0
    fi
    echo "==> building packethacking/xrouter:$VERSION-$arch ($platform)"
    build_one "$platform" "$bin_url" "$bin_sha" "$pkgs" \
        -t "packethacking/xrouter:$VERSION-$arch" \
        -t "packethacking/xrouter:$VERSION-$arch-${bin_sha:0:8}"
    local prev
    prev=$(python3 -c "import json; d=json.load(open('versions.json'))
for p in d['versions']['$VERSION']['$arch'].get('previous', []):
    print(p['url'], p['sha256'], p.get('packages', '').replace(' ', ','))")
    while read -r p_url p_sha p_pkgs; do
        [ -n "$p_url" ] || continue
        echo "==> building packethacking/xrouter:$VERSION-$arch-${p_sha:0:8} (previous, $platform)"
        build_one "$platform" "$p_url" "$p_sha" "${p_pkgs//,/ }" \
            -t "packethacking/xrouter:$VERSION-$arch-${p_sha:0:8}"
    done <<<"$prev"
}

case "$ARCH_FILTER" in
    all)   for a in amd64 arm64 armv7; do
               case $a in
                 amd64) build_arch amd64 linux/amd64 ;;
                 arm64) build_arch arm64 linux/arm64 ;;
                 armv7) build_arch armv7 linux/arm/v7 ;;
               esac
           done ;;
    amd64) build_arch amd64 linux/amd64 ;;
    arm64) build_arch arm64 linux/arm64 ;;
    armv7) build_arch armv7 linux/arm/v7 ;;
    *)     echo "unknown arch: $ARCH_FILTER" >&2; exit 1 ;;
esac
