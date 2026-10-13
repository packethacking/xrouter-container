"""The stack is up and the harness can see both nodes."""

from __future__ import annotations

import time

from ax25 import Frame
from conftest import DUT_CALL, NBR_CALL, VERSION


def test_dut_reports_its_version(dut):
    out = dut.cmd("V")
    assert VERSION in out, out


def test_dut_lists_its_ports(dut):
    out = dut.cmd("P")
    for name in ("Probe A", "Probe B", "Neighbour XRouter", "Neighbour XRouter"):
        assert name in out, out


def test_probe_a_hears_dut(probe_a):
    """Anything at all from the DUT on port 1 (NODES, ID, L3RTT...)."""
    f = probe_a.wait(lambda f: f.src.startswith(DUT_CALL), timeout=90)
    assert f is not None, "nothing heard from the DUT on port 1 in 90 s"


def test_probe_c_hears_nbr(probe_c):
    f = probe_c.wait(lambda f: f.src.startswith(NBR_CALL), timeout=90)
    assert f is not None, "nothing heard from the neighbour on its port 2 in 90 s"
