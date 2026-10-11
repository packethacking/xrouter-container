#!/usr/bin/env bash
# Ingest one upstream XRouter binary: download, verify, boot-test, mirror to
# OARC, and record it in versions.json and upstream.json. Does not commit.
#
# Usage:
#   scripts/ingest.sh <version> <arch> <fresh-url> [--dynamic] [--meta JSON]
#                     [--dry-run] [--scratch DIR] [--no-boot-test]
#
#   <arch>        amd64, arm64 or armv7
#   <fresh-url>   a download link just fetched with the groups.io get_file
#                 tool; these expire within minutes, so run this at once
#   --dynamic     the binary is a dynamically linked (vanessa) build; work
#                 out the Debian packages it needs and record them
#   --meta JSON   the get_file (or list_files) entry for this file, so
#                 upstream.json can record its id, size and dates
#   --dry-run     do everything except the OARC upload, and write to copies
#                 of versions.json and upstream.json in the scratch dir
#   --scratch DIR where --dry-run writes its copies (default: a temp dir)
#   --no-boot-test  skip the boot test (only if this host cannot run the
#                 target arch; the CI smoke test still covers it)
#
# Naming on OARC (folder 4851):
#   first binary for a (version, arch)  xrouter-<ver>-<arch>
#   a silent replacement upstream       xrouter-<ver>-<arch>-<sha8>
# A replacement moves the old entry into that arch's "previous" list.
#
# Prints a final line "result: <added|replaced|restored|unchanged> ..." on
# success. Any failure exits non-zero and leaves the real manifests alone.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO=$PWD

die() { echo "ingest: ERROR: $*" >&2; exit 1; }
log() { echo "ingest: $*" >&2; }

[ $# -ge 3 ] || die "usage: $0 <version> <arch> <fresh-url> [--dynamic] [--meta JSON] [--dry-run] [--scratch DIR] [--no-boot-test]"
VERSION=$1 ARCH=$2 URL=$3
shift 3
DYNAMIC='' DRY='' SCRATCH='' META='' BOOT=1
while [ $# -gt 0 ]; do
    case "$1" in
        --dynamic) DYNAMIC=1 ;;
        --dry-run) DRY=1 ;;
        --scratch) SCRATCH=$2; shift ;;
        --meta) META=$2; shift ;;
        --no-boot-test) BOOT= ;;
        *) die "unknown option $1" ;;
    esac
    shift
done

[[ "$VERSION" =~ ^[0-9]+[a-z]+$ ]] || die "bad version '$VERSION'"
case "$ARCH" in
    amd64) PLATFORM=linux/amd64 ;;
    arm64) PLATFORM=linux/arm64 ;;
    armv7) PLATFORM=linux/arm/v7 ;;
    *) die "bad arch '$ARCH'" ;;
esac
[ -z "$DYNAMIC" ] || [ "$ARCH" = amd64 ] || die "--dynamic is only expected for amd64"

OARC_FOLDER=4851
OARC_BASE="https://compute.oarc.uk/storage/public/folders/$OARC_FOLDER"
OARC_CLI="$HOME/.local/share/oarc-os/object_storage_cli.py"
OARC_TOKEN_FILE="$HOME/.config/oarc/token-xrouter"
TODAY=$(date -u +%F)

WORK=$(mktemp -d)
CNAME="xrt-ingest-$$"
cleanup() {
    docker rm -f "$CNAME" >/dev/null 2>&1 || true
    # the boot test leaves root-owned files in the data dir
    if [ -d "$WORK/data" ]; then
        docker run --rm -v "$WORK:/w" debian:bookworm-slim rm -rf /w/data >/dev/null 2>&1 || true
    fi
    rm -rf "$WORK" || true
}
trap cleanup EXIT

# Manifests to write: the real ones, or scratch copies on --dry-run.
if [ -n "$DRY" ]; then
    SCRATCH=${SCRATCH:-$(mktemp -d)}
    mkdir -p "$SCRATCH"
    cp versions.json "$SCRATCH/versions.json"
    cp upstream.json "$SCRATCH/upstream.json"
    VJSON=$SCRATCH/versions.json UJSON=$SCRATCH/upstream.json
    log "dry run: writing to $SCRATCH"
else
    VJSON=$REPO/versions.json UJSON=$REPO/upstream.json
    [ -r "$OARC_TOKEN_FILE" ] || die "no OARC token at $OARC_TOKEN_FILE"
    [ -r "$OARC_CLI" ] || die "no OARC CLI at $OARC_CLI"
fi

# 1. Download straight away; the link expires within minutes.
BIN=$WORK/xrouter
log "downloading $VERSION $ARCH"
curl -fsSL --retry 2 -o "$BIN" "$URL" || die "download failed (link expired? fetch a fresh one with get_file)"
SIZE=$(stat -c %s "$BIN")
[ "$SIZE" -gt 100000 ] || die "download is only $SIZE bytes"
if [ -n "$META" ]; then
    want=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["size_bytes"])' "$META")
    [ "$want" = "$SIZE" ] || die "size $SIZE does not match groups.io size_bytes $want"
fi

# 2. ELF for the right architecture, static or dynamic as expected.
python3 - "$BIN" "$ARCH" "$DYNAMIC" <<'EOF' || die "ELF check failed"
import struct, sys
path, arch, dynamic = sys.argv[1], sys.argv[2], bool(sys.argv[3])
b = open(path, "rb").read()
if b[:4] != b"\x7fELF":
    sys.exit("not an ELF file")
cls, data = b[4], b[5]
if data != 1:
    sys.exit("not little-endian")
machine = struct.unpack_from("<H", b, 18)[0]
want = {"amd64": (2, 0x3E), "arm64": (2, 0xB7), "armv7": (1, 0x28)}[arch]
if (cls, machine) != want:
    sys.exit(f"ELF class {cls} machine {machine:#x}, expected {want[0]} {want[1]:#x} for {arch}")
if cls == 2:
    phoff, = struct.unpack_from("<Q", b, 32); phentsize, phnum = struct.unpack_from("<HH", b, 54)
else:
    phoff, = struct.unpack_from("<I", b, 28); phentsize, phnum = struct.unpack_from("<HH", b, 42)
interp = any(struct.unpack_from("<I", b, phoff + i * phentsize)[0] == 3 for i in range(phnum))
if interp and not dynamic:
    sys.exit("binary is dynamically linked but --dynamic was not given")
if dynamic and not interp:
    sys.exit("--dynamic given but the binary is statically linked")
EOF
grep -aq "$VERSION" "$BIN" || die "binary does not contain the version string '$VERSION'"

SHA=$(sha256sum "$BIN" | cut -d' ' -f1)
SHA8=${SHA:0:8}
log "sha256 $SHA"

# Where does this binary already sit in versions.json?
PLACE=$(python3 scripts/xrouter_manifest.py lookup --versions "$VJSON" --version "$VERSION" --arch "$ARCH" --sha256 "$SHA")
HAS_ENTRY=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(1 if d["versions"].get(sys.argv[2],{}).get(sys.argv[3]) else "")' "$VJSON" "$VERSION" "$ARCH")

# 3. Runtime packages for a dynamic build: ldd in the base image.
PACKAGES=""
if [ -n "$DYNAMIC" ]; then
    missing=$(docker run --rm --platform "$PLATFORM" -v "$BIN:/xrouter:ro" debian:bookworm-slim \
        sh -c 'ldd /xrouter' | awk '/not found/ {print $1}' | sort -u)
    for lib in $missing; do
        case "$lib" in
            libasound.so.2) pkg=libasound2 ;;
            libX11.so.6)    pkg=libx11-6 ;;
            libxcb.so.1)    pkg=libxcb1 ;;
            libXau.so.6)    pkg=libxau6 ;;
            libXdmcp.so.6)  pkg=libxdmcp6 ;;
            libncurses.so.6|libncursesw.so.6) pkg=libncursesw6 ;;
            libtinfo.so.6)  pkg=libtinfo6 ;;
            libpcap.so.0.8) pkg=libpcap0.8 ;;
            libssl.so.3|libcrypto.so.3) pkg=libssl3 ;;
            libz.so.1)      pkg=zlib1g ;;
            *) die "no Debian package known for $lib; add it to the table in scripts/ingest.sh" ;;
        esac
        case " $PACKAGES " in *" $pkg "*) ;; *) PACKAGES="${PACKAGES:+$PACKAGES }$pkg" ;; esac
    done
    PACKAGES=$(tr ' ' '\n' <<<"$PACKAGES" | sort | paste -sd' ')
    log "runtime packages: ${PACKAGES:-none}"
    # confirm nothing is still missing once they are installed
    still=$(docker run --rm --platform "$PLATFORM" -v "$BIN:/xrouter:ro" debian:bookworm-slim sh -c "
        { apt-get update -qq && apt-get install -y -qq --no-install-recommends $PACKAGES; } >/dev/null 2>&1
        ldd /xrouter" | awk '/not found/ {print $1}')
    [ -z "$still" ] || die "still missing after installing packages: $still"
fi

# 4. Boot test in the current image, as the README smoke test does.
if [ -n "$BOOT" ]; then
    IMG=ghcr.io/packethacking/xrouter:latest-$ARCH
    docker run --rm --platform "$PLATFORM" debian:bookworm-slim true >/dev/null 2>&1 \
        || die "this host cannot run $PLATFORM containers (no emulation?); use --no-boot-test and rely on CI"
    docker pull -q --platform "$PLATFORM" "$IMG" >/dev/null
    DATA=$WORK/data
    mkdir -p "$DATA"
    docker run --rm --platform "$PLATFORM" --entrypoint /bin/sh "$IMG" \
        -c 'cat /opt/xrouter/skel/XROUTER.CFG.example' > "$DATA/XROUTER.CFG"
    chmod 0755 "$BIN"
    if [ -n "$PACKAGES" ]; then
        docker run -d --platform "$PLATFORM" --name "$CNAME" -v "$DATA:/data" -v "$BIN:/usr/local/bin/xrouter:ro" \
            --entrypoint /bin/sh "$IMG" -c "apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends $PACKAGES >/dev/null && exec /usr/local/bin/xrouter-entrypoint.sh" >/dev/null
        limit=180
    else
        docker run -d --platform "$PLATFORM" --name "$CNAME" -v "$DATA:/data" -v "$BIN:/usr/local/bin/xrouter:ro" "$IMG" >/dev/null
        limit=60
    fi
    ok=
    for _ in $(seq 1 "$limit"); do
        if docker logs "$CNAME" 2>&1 | grep -q "version ${VERSION} started"; then ok=1; break; fi
        sleep 1
    done
    if [ -z "$ok" ]; then
        docker logs "$CNAME" 2>&1 | tail -20 >&2 || true
        die "boot line 'version $VERSION started' not seen"
    fi
    docker stop -t 5 "$CNAME" >/dev/null 2>&1 || true
    docker rm -f "$CNAME" >/dev/null 2>&1 || true
    log "boot test passed"
fi

# 5. Pick the OARC name and upload (unless it is already there).
if [ "$PLACE" = current ] || [ "$PLACE" = previous ]; then
    NAME=""   # nothing to upload; we already mirror these exact bytes
    log "binary already in versions.json ($PLACE); no upload"
elif [ -n "$HAS_ENTRY" ]; then
    NAME="xrouter-$VERSION-$ARCH-$SHA8"
else
    NAME="xrouter-$VERSION-$ARCH"
fi
PUBURL=""
if [ -n "$NAME" ]; then
    PUBURL="$OARC_BASE/$NAME"
    code=$(curl -s -o "$WORK/existing" -w '%{http_code}' "$PUBURL" || true)
    if [ "$code" = 200 ]; then
        have=$(sha256sum "$WORK/existing" | cut -d' ' -f1)
        [ "$have" = "$SHA" ] || die "$PUBURL already exists with different bytes ($have); not overwriting"
        log "$NAME already on OARC with the same bytes; no upload"
    elif [ -n "$DRY" ]; then
        log "dry run: would upload as $NAME"
    else
        cp "$BIN" "$WORK/$NAME"
        log "uploading $NAME to OARC folder $OARC_FOLDER"
        python3 "$OARC_CLI" --token "$(cat "$OARC_TOKEN_FILE")" --upload "$WORK/$NAME" \
            --folder "$OARC_FOLDER" --upload-as "$NAME" --json > "$WORK/upload.json" \
            || die "OARC upload failed"
        got=
        for _ in 1 2 3 4 5 6; do
            if curl -fsSL -o "$WORK/check" "$PUBURL" && [ "$(sha256sum "$WORK/check" | cut -d' ' -f1)" = "$SHA" ]; then
                got=1; break
            fi
            sleep 5
        done
        [ -n "$got" ] || die "public OARC copy at $PUBURL does not match sha256 $SHA"
        log "public copy verified"
    fi
else
    PUBURL=unused
fi

# 6. Record it.
LINKAGE=static; [ -z "$DYNAMIC" ] || LINKAGE=dynamic
args=(record --versions "$VJSON" --upstream "$UJSON" --version "$VERSION" --arch "$ARCH"
      --sha256 "$SHA" --url "$PUBURL" --packages "$PACKAGES" --linkage "$LINKAGE" --today "$TODAY")
[ -z "$META" ] || args+=(--meta "$META")
WHAT=$(python3 scripts/xrouter_manifest.py "${args[@]}")

echo "result: $WHAT $VERSION $ARCH sha256=$SHA${NAME:+ oarc=$NAME}${PACKAGES:+ packages=\"$PACKAGES\"}${DRY:+ (dry run, manifests in $SCRATCH)}"
