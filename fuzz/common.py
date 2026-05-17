"""common.py -- shared helpers for the xrouter fuzzers.

- TargetController: launches/kills an xrouter instance, polls liveness,
  collects core dumps from the instance dir, runs triage.py to compute
  a dedup signature, and keeps a findings.jsonl per-instance log.

All stdlib only. Lives under /home/user/xrouter-container/fuzz/ but is
designed to be importable from any sibling fuzzer script via:

    sys.path.insert(0, str(Path(__file__).parent))
    from common import TargetController
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESTART_SH = HERE / "restart-target.sh"
TRIAGE_PY = HERE / "triage.py"
DEFAULT_BIN = Path("/work/xr/xrouter")


@dataclass
class CrashInfo:
    signature: str
    signal: str
    rip: str | None
    insn: str | None
    core_path: str
    seen_at: float = field(default_factory=time.time)
    regs: dict = field(default_factory=dict)


class TargetController:
    """Manage a single xrouter instance for fuzzing.

    name      — unique label (used as a subdirectory under /work/xr/run-*)
    http_port — base HTTP port (other ports are derived: mqtt=http+1, agw=http+2, aprs=http+3)
    udp_port  — AXUDP UDPLOCAL
    """

    def __init__(self, name: str, http_port: int, udp_port: int,
                 binary: Path = DEFAULT_BIN, boot_grace: float = 15.0,
                 probe_timeout: float = 3.0):
        self.name = name
        self.http_port = http_port
        self.udp_port = udp_port
        self.binary = binary
        self.boot_grace = boot_grace
        self.probe_timeout = probe_timeout
        self.root = Path(f"/work/xr/run-{name}")
        self.cores_dir = self.root / "cores"
        self.findings = self.root / "findings.jsonl"
        self.bugs_dir = self.root / "bugs"
        self.bugs_dir.mkdir(parents=True, exist_ok=True)
        self.cores_dir.mkdir(parents=True, exist_ok=True)
        self.seen_signatures: set[str] = self._reload_signatures()

    def _reload_signatures(self) -> set[str]:
        seen = set()
        if self.findings.exists():
            for line in self.findings.read_text().splitlines():
                try:
                    seen.add(json.loads(line)["signature"])
                except (json.JSONDecodeError, KeyError):
                    pass
        return seen

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}/"

    def health_ok(self, timeout: float | None = None) -> bool:
        try:
            with urllib.request.urlopen(self.health_url,
                                        timeout=timeout or self.probe_timeout) as r:
                return 200 <= r.status < 500
        except (urllib.error.URLError, ConnectionError,
                TimeoutError, OSError):
            return False

    def restart(self) -> bool:
        """Restart the target and wait until it's serving HTTP. Returns True on success."""
        subprocess.run([str(RESTART_SH), self.name,
                        str(self.http_port), str(self.udp_port)],
                       check=False, capture_output=True)
        deadline = time.monotonic() + self.boot_grace
        while time.monotonic() < deadline:
            if self.health_ok():
                return True
            time.sleep(0.2)
        return False

    def stop(self) -> None:
        pidfile = self.root / "xrouter.pid"
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                os.kill(pid, 15)
                time.sleep(0.3)
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
            except (ValueError, ProcessLookupError):
                pass

    def collect_cores(self) -> list[Path]:
        # restart-target.sh sweeps the global /work/xr/cores into our dir,
        # but call it again here to catch ones that landed between calls.
        for f in Path("/work/xr/cores").glob("core.*"):
            target = self.cores_dir / f.name
            try:
                f.rename(target)
            except OSError:
                pass
        return sorted(self.cores_dir.glob("core.*"),
                      key=lambda p: p.stat().st_mtime)

    def triage(self, core_path: Path) -> CrashInfo | None:
        r = subprocess.run(
            ["python3", str(TRIAGE_PY), "--json",
             str(self.binary), str(core_path)],
            check=False, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return None
        return CrashInfo(
            signature=data.get("signature", "unknown"),
            signal=data.get("signal", "UNKNOWN"),
            rip=data.get("rip"),
            insn=data.get("insn"),
            core_path=str(core_path),
            regs=data.get("regs", {}),
        )

    def record_crash(self, crash: CrashInfo, trigger: bytes | None = None,
                     extra: dict | None = None) -> bool:
        """Record a crash. Returns True if it's a new (deduped) signature."""
        new = crash.signature not in self.seen_signatures
        record = {
            "ts": crash.seen_at,
            "signature": crash.signature,
            "signal": crash.signal,
            "rip": crash.rip,
            "insn": crash.insn,
            "core_path": crash.core_path,
            "trigger_hex": trigger.hex() if trigger else None,
            "new": new,
        }
        if extra:
            record.update(extra)
        with self.findings.open("a") as f:
            f.write(json.dumps(record) + "\n")
        if new:
            self.seen_signatures.add(crash.signature)
            bug_dir = self.bugs_dir / crash.signature
            bug_dir.mkdir(exist_ok=True)
            (bug_dir / "first.json").write_text(json.dumps(record, indent=2))
            if trigger:
                (bug_dir / "trigger.bin").write_bytes(trigger)
                (bug_dir / "trigger.hex").write_text(trigger.hex() + "\n")
            try:
                core_dest = bug_dir / "core"
                if not core_dest.exists():
                    subprocess.run(["cp", crash.core_path, str(core_dest)],
                                   check=False)
            except OSError:
                pass
        return new

    def udp_socket(self) -> socket.socket:
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def tcp_connect(self, port: int, timeout: float = 5.0) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        return s


def now() -> float:
    return time.monotonic()
