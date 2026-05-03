"""Verifies the testcontainers-Python example shipped in README.md
boots an XRouter container from ghcr.io/packethacking/xrouter:latest
and reaches a known-good state.

The body of test_xrouter_boots is intentionally identical to the
README snippet so that running pytest against this file is the
same thing as running the example as a copy-paste."""

from __future__ import annotations
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
