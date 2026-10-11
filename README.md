# xrouter-container

A multi-arch Docker image that packages [XRouter](https://wiki.oarc.uk/packet:xrouter),
the closed-source AX.25 / NetRom packet-radio node by Paula Dowie (G8PZT). The
image is published to **`ghcr.io/packethacking/xrouter`** with every released
binary version tagged, and a `:latest` multi-arch manifest list that resolves
on `linux/amd64`, `linux/arm64`, and `linux/arm/v7`.

## Why

XRouter is distributed upstream via the [wiki](https://wiki.oarc.uk/packet:xrouter)
and the [groups.io files area](https://groups.io/g/xrouter/files): the
canonical sources, and the right place to go for the binary, the support
package, and sysop discussion. This repo is a downstream convenience for
people who want a containerised build: a single `docker pull` for an
integration test, a CI job, or an x86 VM rehearsing a Pi deployment.

What the image adds on top of the upstream zips:

- A pinned `(version, arch)` per tag, with the support tree, sample configs,
  and HELP / MAN docs already in the right place.
- A multi-arch `:latest` manifest list so `docker pull` resolves correctly
  on `linux/amd64`, `linux/arm64`, and `linux/arm/v7`.
- An optional headless mode that forwards XRouter's boot log to stdout so
  `docker logs` / testcontainers' `WaitForLogMessage` work; the curses TUI
  is still available via `XROUTER_TUI=1`.

## Quick start

```sh
mkdir myxrouter
cp /path/to/your/XROUTER.CFG myxrouter/

docker run --rm -d \
    --name xrouter \
    -v "$PWD/myxrouter:/data" \
    -p 23:23 -p 80:80 -p 2323:2323 -p 8086:8086 \
    ghcr.io/packethacking/xrouter:latest

docker logs -f xrouter
```

The container will refuse to start without `/data/XROUTER.CFG`. A starter
config (XRouter's "dummy" loopback-only one, with a `DNS=8.8.8.8` directive
prepended for the static-binary case; see [Caveats](#caveats)) is shipped at
`/opt/xrouter/skel/XROUTER.CFG.example`. Copy it into your data dir to get
something that boots while you write a real config:

```sh
docker run --rm --entrypoint /bin/sh ghcr.io/packethacking/xrouter:latest \
    -c 'cat /opt/xrouter/skel/XROUTER.CFG.example' > myxrouter/XROUTER.CFG
```

## What's in the image

```
/usr/local/bin/xrouter                           # the binary, renamed from
                                                 # xr{lin,pi}{32,64}-static
/opt/xrouter/skel/                               # template tree
    HELP/  MAN/  INFO/  MISC/                    # docs (refreshed every run)
    XROUTER.CFG.example                          # dummy cfg with DNS prefix
    *.SYS  *.ACL  *.CFG                          # sample config files
                                                 # (seeded only if missing)
/data                                            # VOLUME: working dir at runtime
                                                 # XROUTER.CFG lives here, plus
                                                 # state files (XRNODES, LOG/,
                                                 # CHAT/, PMS/, etc.)
```

Base layer: `debian:bookworm-slim`. The XRouter binary itself is statically
linked, so the runtime image carries no shared-library surface to update.
The exception is 504x, which upstream only released as a dynamically linked
x86-64 build; its image also carries libasound2 and libx11-6.

## Support files

XRouter ships a *support package* (currently `xrouter-504k-support-files.zip`)
separate from the binary, containing the HELP / MAN / INFO docs that the
binary serves to connected users via packet console commands like `?`, `MAN`,
and `INFO`, plus skeleton `.SYS` / `.ACL` / `.CFG` files that XRouter reads
optionally for things like access control, IP routes, and user passwords.
Upstream, sysops download this zip alongside the binary and unzip it into
their working directory.

The image bakes this tree at `/opt/xrouter/skel/` and the entrypoint stages
it into `/data` on every start:

- **Docs** (`HELP/`, `MAN/`, `INFO/`, `MISC/`) are *refreshed* every run via
  `cp -rf`; they should track the binary, not be edited.
- **Sample config files** (`ACCESS.SYS`, `BOOTCMDS.SYS`, `CRONTAB.SYS`,
  `HTTP.ACL`, `HTTP.SYS`, `HTTPBAN.SYS`, `IGATE.CFG`, `IPROUTE.SYS`,
  `LANGS.SYS`, `PASSWORD.SYS`, `TELGUEST.ACL`, `TELPROXY.ACL`,
  `USERPASS.SYS`, language packs, plus the `XROUTER.CFG.example` we ship)
  are seeded `cp -n` style, only copied if `/data/<name>` doesn't already
  exist. Sysop edits survive container restarts.
- `XROUTER.CFG` itself is *never* auto-created. The container refuses to
  start if `/data/XROUTER.CFG` is missing.
- Empty subdirs that XRouter expects (`LOG/`, `CHAT/`, `PMS/`, `FINGER/`)
  get `mkdir -p`'d.

**Do you need to know about the support tree?** Mostly no. For a typical
testcontainers / CI / single-sysop use case, mount `/data`, drop your
`XROUTER.CFG` in, and ignore everything else. The relevant exception is if
you want to customise things like the `ACCESS.SYS` rules or the language pack:
edit them inside `/data` (you'll find the seeded copies there after first
boot) and they'll persist.

The support package's version is independent from the binary's version (the
binary has changed several times since the support tree was last refreshed
upstream); the manifest tracks them separately.

## Image tags

| Tag                              | Refers to                                             |
| -------------------------------- | ----------------------------------------------------- |
| `:latest`                        | Multi-arch manifest list of the per-arch latests      |
| `:latest-amd64`                  | The newest published x86-64 build                     |
| `:latest-arm64`                  | The newest published aarch64 build                    |
| `:latest-armv7`                  | The newest published 32-bit ARM build                 |
| `:<version>` e.g. `:505o`        | Multi-arch manifest list of every arch built for that version |
| `:<version>-<arch>` e.g. `:505o-arm64` | A specific (version, arch) build                |
| `:<version>-<arch>-<sha8>` e.g. `:505o-arm64-6ef2d3bb` | One exact upstream binary, by the first 8 hex digits of its sha256 |

Upstream occasionally replaces a binary without changing its version number. When that happens, `:<version>-<arch>` (and the lists and latests built from it) moves to the new binary, while every binary we have ever published keeps its own `:<version>-<arch>-<sha8>` tag. Pin the sha8 tag if you need a result to be reproducible later. [`versions.json`](versions.json) lists replaced binaries under `previous` on the arch entry.

XRouter's release scheme is a numeric prefix plus a letter suffix (`504v`,
`504z`, `505a`, `505b`, ...). Letters increment until the prefix rolls. Because
the registry doesn't know that `504z < 505a`, the per-arch `latest_<arch>`
pointers in [`versions.json`](versions.json) are explicit, not derived from
sorting. Each arch tracks its own latest, so a release that only ships some
architectures doesn't hold the others back.

## Output modes

By default the entrypoint runs in **headless mode**: XRouter's curses TUI is
silenced and `/data/LOG/*.TXT` (the structured boot log + the day-stamped
activity log) is `tail -F`'d to PID 1 stdout. This is what you want for
`docker run -d`, testcontainers, log aggregation, anything programmatic.
Signals propagate cleanly: `docker stop` triggers `--- Closedown via SIGTERM
---` in the log and a graceful exit.

For an interactive sysop session at the curses TUI, set `XROUTER_TUI=1`:

```sh
docker run --rm -it \
    -e XROUTER_TUI=1 \
    -v "$PWD/myxrouter:/data" \
    ghcr.io/packethacking/xrouter:latest
```

## Caveats

- **DNS for hostname lookups.** The XRouter binary is statically linked; glibc's
  NSS modules are dynamic, so the system resolver doesn't work. Any hostname
  resolution XRouter does (IGATE, DynDNS, AMPR routing, etc.) requires a
  `DNS=8.8.8.8` (or your preferred resolver) directive in `XROUTER.CFG`. The
  example we ship has this prepended; if you started from groups.io's
  annotated example, uncomment line ~339.
- **`NET_RAW` for non-loopback ports.** The dummy / loopback config runs with
  no extra capabilities. Any real radio interface (AXIP/AXUDP, raw Ethernet,
  the kernel AX.25 stack) wants `--cap-add=NET_RAW`. Telnet on 23 and HTTP on
  80 work via the default `NET_BIND_SERVICE` cap; if you remap to high ports
  you don't need either.
- **First-run seeding.** The entrypoint refreshes HELP/MAN/INFO/MISC into
  `/data` on every start (so docs track the binary), but seeds sample
  `*.SYS` / `*.ACL` files with `cp -n` semantics, so your edits are not
  clobbered. The XROUTER.CFG dummy is renamed to `XROUTER.CFG.example` and
  not auto-copied; bring your own.
- **Outbound traffic.** Hosts XRouter is wired to talk to
  (`rotate.aprs2.net`, `node-api.packet.oarc.uk`, `*.ampr.org`, a DynDNS
  endpoint) are only contacted when the matching directive is configured in
  `XROUTER.CFG`. With a loopback-only config it's quiet; if you want hard
  guarantees, attach to a `docker network create --internal` network.

## testcontainers (Python) example

Spins the container up using the dummy XROUTER.CFG that ships in the image,
waits for the boot announcement in the log, and asserts the HTTP API port is
reachable.

```python
# pip install testcontainers
import pathlib, socket, subprocess
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

IMAGE = "ghcr.io/packethacking/xrouter:latest"


def test_xrouter_boots(tmp_path: pathlib.Path) -> None:
    data = tmp_path / "xr"
    data.mkdir()
    # Bootstrap config from the in-image example so the test
    # doesn't need to track XRouter's evolving validation rules
    # (callsign format, mandatory directives, etc.). The example
    # is loopback-only, fine for a smoke check.
    cfg = subprocess.check_output([
        "docker", "run", "--rm", "--entrypoint", "/bin/sh", IMAGE,
        "-c", "cat /opt/xrouter/skel/XROUTER.CFG.example",
    ])
    (data / "XROUTER.CFG").write_bytes(cfg)

    with (
        DockerContainer(IMAGE)
        .with_volume_mapping(str(data), "/data", "rw")
        .with_exposed_ports(8086)  # XRouter's /api/v1/* listener
    ) as xr:
        # The headless entrypoint forwards XRouter's BOOTLOG.TXT to
        # PID 1 stdout, so docker logs sees the structured boot line
        # before the curses TUI would have done its first redraw.
        wait_for_logs(xr, r"version \w+ started", timeout=30)

        host = xr.get_container_host_ip()
        port = int(xr.get_exposed_port(8086))
        with socket.create_connection((host, port), timeout=5):
            pass  # port open => API listener up
```

The same pattern works in [Testcontainers
for .NET](https://dotnet.testcontainers.org/): replace `wait_for_logs` with
`WithWaitStrategy(Wait.ForUnixContainer().UntilMessageIsLogged("version .* started"))`.

For multi-version test fixtures, parameterise on the tag:

```python
import pytest

@pytest.fixture(params=["504v", "505c", "505o"])
def xrouter_image(request):
    return f"ghcr.io/packethacking/xrouter:{request.param}"
```

## Tracking upstream

Upstream releases appear in the [groups.io files area](https://groups.io/g/xrouter/files) (login required), in four folders: `00-XrLin64-static` (amd64), `00-XrPi64-static` (arm64), `00-XrPi32-static` (armv7) and `00-XrLin64-vanessa` (dynamically linked amd64, used only for versions with no static amd64 build, so far just 504x).

[`upstream.json`](upstream.json) records a fingerprint of every upstream file we mirror: its groups.io id, size, upload and update times, sha256, and the version and arch it maps to. A scheduled Claude session checks groups.io once a day by following [`scripts/UPSTREAM-CHECK.md`](scripts/UPSTREAM-CHECK.md): it lists the folders, runs [`scripts/upstream_diff.py`](scripts/upstream_diff.py) to compare the listing with `upstream.json`, ingests anything new or changed, and pushes to `main` so the images build and the interop suite runs. The groups.io API is only reachable through Claude's groups.io tools, which is why this is not a plain GitHub Actions cron job.

## Adding a new version

Use [`scripts/ingest.sh`](scripts/ingest.sh) with a fresh download link for the upstream file (groups.io links expire within minutes):

```sh
scripts/ingest.sh 505p amd64 "<download url>"
scripts/ingest.sh 504x amd64 "<download url>" --dynamic   # a vanessa build
```

It downloads the binary, checks it is an ELF for that arch and contains the version string, works out the runtime packages for a dynamic build, boots it in the current image and waits for `version <ver> started`, uploads it to OARC folder 4851 as `xrouter-<ver>-<arch>` (or `xrouter-<ver>-<arch>-<sha8>` if it replaces an existing binary), checks the public copy's sha256, and updates `versions.json` (and `upstream.json` when given `--meta`). It moves `latest` and `latest_<arch>` only if the new version is newer. `--dry-run` does everything except the upload and writes to scratch copies of the manifests. It does not commit; review the diff and push. The workflow then rebuilds every cell, smoke-tests it, reassembles the per-version multi-arch lists and updates the latest pointers.

To do it by hand instead: upload each binary to OARC folder 4851 as `xrouter-<NEW>-<arch>`, add a block to [`versions.json`](versions.json) with each binary's sha256, bump `latest_<arch>` (and `latest`) where this release is newest, and push. A dynamically linked build also needs a `"packages"` field listing the Debian packages it needs (`ldd` on `debian:bookworm-slim` tells you), for example `"packages": "libasound2 libx11-6"`.

If only some arches got a build (it happens), omit the missing arch entries. The workflow only builds what is in the manifest, and the per-arch latest pointers stay where they are.

## Building locally

```sh
bash scripts/build.sh                  # latest version, all arches, --load
bash scripts/build.sh 505o             # specific version, all arches
bash scripts/build.sh 505o amd64       # one arch only
```

Each build is tagged `<version>-<arch>` and `<version>-<arch>-<sha8>`; a replaced binary listed under `previous` is built too, tagged only with its sha8 tag.

Multi-arch builds need QEMU registered for binfmt; Docker Desktop does this
automatically.

## Repo layout

```
docker/
    Dockerfile        # 2-stage, native fetch + target-arch runtime
    entrypoint.sh     # docs/config seeding + headless wrapper
scripts/
    build.sh          # local multi-arch driver, reads versions.json
    ingest.sh         # download, verify, boot-test, mirror and record
                      # one upstream binary
    upstream_diff.py  # compare a groups.io listing with upstream.json
    xrouter_manifest.py   # shared versions.json / upstream.json helpers
    UPSTREAM-CHECK.md # the daily upstream check, for the scheduled session
    tests/            # unit tests: python3 -m unittest discover -s scripts/tests
.github/workflows/
    build-and-publish.yml   # discover -> build -> smoke-test ->
                            # manifest-per-version -> latest-pointers
versions.json         # per-(version, arch) URL + sha256 manifest;
                      # the source of truth for the build matrix
upstream.json         # fingerprint of each upstream groups.io file
```
