# xrouter-container

A multi-arch Docker image that packages [XRouter](https://wiki.oarc.uk/packet:xrouter),
the closed-source AX.25 / NetRom packet-radio node by Paula Dowie (G8PZT). The
image is published to **`ghcr.io/packethacking/xrouter`** with every released
binary version tagged, and a `:latest` multi-arch manifest list that resolves
on `linux/amd64`, `linux/arm64`, and `linux/arm/v7`.

## Why

XRouter's upstream distribution is a wiki page, a groups.io files area behind a
login, ad-hoc per-platform zips named in two different conventions, and a
support-files bundle that is versioned independently of the binary. Standing it
up reproducibly — for an integration test, a CI job, a fresh sysop install, or
an x86 VM rehearsing a Pi deployment — is fiddly and error-prone.

This repo turns all of that into:

- A canonical mirror of the binaries on OARC compute object storage, named
  predictably (`xrouter-<version>-<arch>`).
- A single Docker image per `(version, arch)` combination, with the support
  tree, sample configs, and HELP / MAN docs already laid out as XRouter
  expects.
- A multi-arch image so `docker pull ghcr.io/packethacking/xrouter:latest` does
  the right thing on any of the three platforms above.
- A headless wrapper that turns XRouter's curses status TUI into a structured
  log stream on `docker logs`, so testcontainers' `WaitForLogMessage` and
  similar strategies work against real boot lines.

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
prepended for the static-binary case — see [Caveats](#caveats)) is shipped at
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

## Image tags

| Tag                              | Refers to                                             |
| -------------------------------- | ----------------------------------------------------- |
| `:latest`                        | Multi-arch manifest list of the per-arch latests      |
| `:latest-amd64`                  | The newest published x86-64 build                     |
| `:latest-arm64`                  | The newest published aarch64 build                    |
| `:latest-armv7`                  | The newest published 32-bit ARM build                 |
| `:<version>` e.g. `:505c`        | Multi-arch manifest list of every arch built for that version |
| `:<version>-<arch>` e.g. `:505c-arm64` | A specific (version, arch) build                |

XRouter's release scheme is a numeric prefix plus a letter suffix (`504v`,
`504z`, `505a`, `505b`, …). Letters increment until the prefix rolls. Because
the registry doesn't know that `504z < 505a`, the per-arch `latest_<arch>`
pointers in [`versions.json`](versions.json) are explicit, not derived from
sorting. The author publishes builds for arches inconsistently — some releases
ship only amd64 — so each arch tracks its own latest and a stalled arch
doesn't hold back the others.

## Output modes

By default the entrypoint runs in **headless mode**: XRouter's curses TUI is
silenced and `/data/LOG/*.TXT` (the structured boot log + the day-stamped
activity log) is `tail -F`'d to PID 1 stdout. This is what you want for
`docker run -d`, testcontainers, log aggregation, anything programmatic.
Signals propagate cleanly — `docker stop` triggers `--- Closedown via SIGTERM
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
  `*.SYS` / `*.ACL` files with `cp -n` semantics — your edits are not
  clobbered. The XROUTER.CFG dummy is renamed to `XROUTER.CFG.example` and
  not auto-copied; bring your own.
- **Outbound traffic.** With a stock loopback config the container makes zero
  outbound IP connections. Hosts XRouter is wired to talk to (`rotate.aprs2.net`,
  `node-api.packet.oarc.uk`, `*.ampr.org`, the DynDNS endpoint) only fire
  when the matching directive is present in `XROUTER.CFG`.

## testcontainers (Python) example

Spins the container up against an in-memory loopback config, waits for the
boot announcement in the log, and asserts the HTTP API port is reachable.

```python
# pip install testcontainers
import pathlib, socket, textwrap
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

XROUTER_CFG = textwrap.dedent("""\
    NODECALL=TEST-1
    NODEALIAS=TEST
    CONSOLECALL=TEST
    INTERFACE=1
        TYPE=LOOPBACK
        PROTOCOL=KISS
        MTU=256
    ENDINTERFACE
    PORT=1
        ID="Loopback port"
        INTERFACENUM=1
    ENDPORT
""")


def test_xrouter_boots(tmp_path: pathlib.Path) -> None:
    data = tmp_path / "xr"
    data.mkdir()
    (data / "XROUTER.CFG").write_text(XROUTER_CFG)

    with (
        DockerContainer("ghcr.io/packethacking/xrouter:latest")
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
for .NET](https://dotnet.testcontainers.org/) — replace `wait_for_logs` with
`WithWaitStrategy(Wait.ForUnixContainer().UntilMessageIsLogged("version .* started"))`.

For multi-version test fixtures, parameterise on the tag:

```python
import pytest

@pytest.fixture(params=["504v", "505a", "505c"])
def xrouter_image(request):
    return f"ghcr.io/packethacking/xrouter:{request.param}"
```

## Adding a new version

1. Download the new binary from the [groups.io files
   area](https://groups.io/g/xrouter/files) (login required) — typically
   `xrlin64v<NEW>-static`, `xrpi64v<NEW>-static`, `xrpi32v<NEW>-static`.
2. Upload each to OARC compute folder 4851 under the canonical name
   `xrouter-<NEW>-<arch>`:

   ```sh
   for arch in amd64 arm64 armv7; do
       python3 ~/object-storage-cli/object_storage_cli.py \
           --upload xrouter-<NEW>-$arch --folder 4851 --json --overwrite
   done
   ```
3. Add a block to [`versions.json`](versions.json) with the sha256 of each
   binary, and bump `latest_<arch>` (and `latest`) to `<NEW>` for each arch
   that ships in this release.
4. Push. The workflow rebuilds, re-verifies all 28 (version, arch) cells,
   reassembles the per-version multi-arch lists, and updates the latest
   pointers.

If only some arches got a build (it happens), omit the missing arch entries —
the workflow only builds what's in the manifest, and the per-arch latest
pointers stay where they are unless you explicitly bump them.

## Building locally

```sh
bash scripts/build.sh                  # latest version, all arches, --load
bash scripts/build.sh 505c             # specific version, all arches
bash scripts/build.sh 505c amd64       # one arch only
```

Multi-arch builds need QEMU registered for binfmt; Docker Desktop does this
automatically.

## Repo layout

```
docker/
    Dockerfile        # 2-stage, native fetch + target-arch runtime
    entrypoint.sh     # docs/config seeding + headless wrapper
scripts/
    build.sh          # local multi-arch driver, reads versions.json
.github/workflows/
    build-and-publish.yml   # discover -> build -> smoke-test ->
                            # manifest-per-version -> latest-pointers
versions.json         # per-(version, arch) URL + sha256 manifest;
                      # the source of truth for the build matrix
```
