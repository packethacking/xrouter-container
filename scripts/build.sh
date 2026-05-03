#!/usr/bin/env bash
# Build XRouter Docker images for one or all architectures, locally.
#
# Reads versions.json, picks the URLs/shas for the requested version,
# and drives `docker buildx build`. Each arch yields a tag of the form
# packethacking/xrouter:<version>-<arch>; with --multi the function
# instead pushes a multi-arch manifest list, which requires a registry.
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

build_arch() {
    local arch="$1" platform="$2"
    local bin_url bin_sha
    bin_url=$(mf "d['versions']['$VERSION'].get('$arch',{}).get('url','')")
    bin_sha=$(mf "d['versions']['$VERSION'].get('$arch',{}).get('sha256','')")
    if [ -z "$bin_url" ]; then
        echo "skip: $VERSION has no $arch build" >&2
        return 0
    fi
    echo "==> building packethacking/xrouter:$VERSION-$arch ($platform)"
    docker buildx build \
        --platform "$platform" \
        --build-arg SUPPORT_URL="$SUPPORT_URL" \
        --build-arg SUPPORT_SHA256="$SUPPORT_SHA" \
        --build-arg BIN_URL="$bin_url" \
        --build-arg BIN_SHA256="$bin_sha" \
        --build-arg XROUTER_VERSION="$VERSION" \
        -f docker/Dockerfile \
        -t "packethacking/xrouter:$VERSION-$arch" \
        --load \
        .
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
