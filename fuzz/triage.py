#!/usr/bin/env python3
"""triage.py -- extract a stable crash signature from an xrouter core dump.

Usage: triage.py <binary> <core> [--json]

Output (text mode):
    signature: <12-char hash>
    signal   : SIGSEGV
    rip      : 0x41222f
    insn     : movzwl 0x2(%rax),%eax
    rax..r15 : ...
    bt       : 0x41222f 0x...

The signature is a hash of (signal, rip, top-of-backtrace addresses
masked to 16-byte buckets). Two cores with the same signature are
considered the same bug for dedup purposes.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def gdb_extract(binary: str, core: str) -> dict:
    out = subprocess.run(
        ["gdb", "-batch",
         "-ex", "set pagination off",
         "-ex", "set print frame-arguments none",
         "-ex", "info program",
         "-ex", "bt 20",
         "-ex", "info registers",
         "-ex", "x/4i $rip"],
        check=False, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb"},
        input="", timeout=30,
        # gdb takes args differently — pass core + binary as positionals
        args=["gdb", "-batch",
              "-ex", "set pagination off",
              "-ex", "info program",
              "-ex", "bt 20",
              "-ex", "info registers",
              "-ex", "x/4i $rip",
              binary, core],
    ).stdout

    result: dict = {"raw": out}

    m = re.search(r"signal\s+(SIG\w+)", out, re.IGNORECASE)
    result["signal"] = m.group(1).upper() if m else "UNKNOWN"

    m = re.search(r"\brip\s+(0x[0-9a-f]+)", out)
    result["rip"] = m.group(1) if m else None

    insn_match = re.search(r"=>\s*0x[0-9a-f]+:\s*(.+)", out)
    result["insn"] = insn_match.group(1).strip() if insn_match else None

    bt_addrs = re.findall(r"^#\d+\s+(0x[0-9a-f]+)\s+in", out, re.MULTILINE)
    result["bt"] = bt_addrs[:10]

    regs = {}
    for reg in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
                "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"):
        m = re.search(rf"^{reg}\s+(0x[0-9a-f]+)", out, re.MULTILINE)
        if m:
            regs[reg] = m.group(1)
    result["regs"] = regs

    # Signature: bucket each bt address to 16-byte granularity to absorb
    # tiny PC-relative variations within the same call site.
    sig_parts = [result["signal"]]
    for a in [result["rip"]] + result["bt"][:5]:
        if a:
            sig_parts.append(hex(int(a, 16) & ~0xF))
    result["signature"] = hashlib.sha1(
        "|".join(sig_parts).encode()).hexdigest()[:12]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("core")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not Path(args.binary).exists():
        print(f"no such binary: {args.binary}", file=sys.stderr)
        return 2
    if not Path(args.core).exists():
        print(f"no such core: {args.core}", file=sys.stderr)
        return 2

    r = subprocess.run(
        ["gdb", "-batch",
         "-ex", "set pagination off",
         "-ex", "info program",
         "-ex", "bt 20",
         "-ex", "info registers",
         "-ex", "x/4i $rip",
         args.binary, args.core],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb"})
    out = r.stdout

    result: dict = {}
    m = re.search(r"signal\s+(SIG\w+)", out)
    result["signal"] = m.group(1).upper() if m else "UNKNOWN"
    # RIP — try register listing first, fall back to "#0 0x... in ??" frame.
    m = re.search(r"\brip\s+(0x[0-9a-f]+)", out)
    if not m:
        m = re.search(r"^#0\s+(0x[0-9a-f]+)\s+in", out, re.MULTILINE)
    result["rip"] = m.group(1) if m else None
    # Normalise RIP width so 0x41222f and 0x000000000041222f hash the same.
    if result["rip"]:
        result["rip"] = hex(int(result["rip"], 16))
    m = re.search(r"=>\s*0x[0-9a-f]+:\s*(.+)", out)
    result["insn"] = m.group(1).strip() if m else None
    # Disassemble RIP if `x/4i $rip` didn't run (e.g. process-not-attached case).
    if not result["insn"] and result["rip"]:
        rdis = subprocess.run(
            ["gdb", "-batch", "-ex", "set pagination off",
             "-ex", f"x/i {result['rip']}", str(args.binary)],
            capture_output=True, text=True, timeout=30,
            env={"PATH": "/usr/bin:/bin", "TERM": "dumb"})
        m = re.search(r"=>\s*0x[0-9a-f]+:\s*(.+)", rdis.stdout)
        if m:
            result["insn"] = m.group(1).strip()
    bt_addrs = re.findall(r"^#\d+\s+(0x[0-9a-f]+)\s+in", out, re.MULTILINE)
    result["bt"] = bt_addrs[:10]

    regs = {}
    for reg in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
                "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"):
        m = re.search(rf"^{reg}\s+(0x[0-9a-f]+)", out, re.MULTILINE)
        if m:
            regs[reg] = m.group(1)
    result["regs"] = regs

    # The xrouter binary is statically linked + fully stripped, so gdb's
    # backtrace is unreliable past the crashing frame (no DWARF, no
    # frame pointers in libc). For stable dedup we hash on (signal, RIP,
    # crashing insn) only — same crashing instruction in the same
    # function reliably means the same bug.
    sig_parts = [result["signal"] or "UNKNOWN",
                 result["rip"] or "?",
                 result["insn"] or "?"]
    result["signature"] = hashlib.sha1(
        "|".join(sig_parts).encode()).hexdigest()[:12]

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"signature: {result['signature']}")
        print(f"signal   : {result['signal']}")
        print(f"rip      : {result['rip']}")
        print(f"insn     : {result['insn']}")
        for k, v in result["regs"].items():
            print(f"{k:9}: {v}")
        print(f"bt       : {' '.join(result['bt'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
