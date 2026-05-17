#!/usr/bin/env python3
"""sweep-triage.py -- walk every /work/xr/run-*/cores/ directory, triage
every core dump found, dedup by signature, and print a unified bug
inventory. Updates each instance's findings.jsonl + bugs/<sig>/ as it
goes so per-bug artefacts are in a consistent shape regardless of which
fuzzer produced the crash.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAGE = HERE / "triage.py"
DEFAULT_BIN = Path("/work/xr/xrouter")


def triage(binary: Path, core: Path) -> dict | None:
    r = subprocess.run(["python3", str(TRIAGE), "--json",
                        str(binary), str(core)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, default=DEFAULT_BIN)
    ap.add_argument("--root", type=Path, default=Path("/work/xr"))
    args = ap.parse_args()

    instances = sorted(args.root.glob("run-*"))
    print(f"[+] scanning {len(instances)} instances under {args.root}")

    # signature -> {instances, signal, rip, insn, count, first_core}
    bugs: dict[str, dict] = {}
    by_instance: dict[str, dict] = {}

    for inst in instances:
        cores = sorted(inst.glob("cores/core.*"))
        if not cores:
            continue
        bugs_dir = inst / "bugs"
        bugs_dir.mkdir(exist_ok=True)
        by_instance[inst.name] = {"cores": len(cores), "sigs": set()}

        for core in cores:
            t = triage(args.binary, core)
            if not t or not t.get("signature"):
                continue
            sig = t["signature"]
            by_instance[inst.name]["sigs"].add(sig)
            if sig not in bugs:
                bugs[sig] = {
                    "instances": set(),
                    "signal": t.get("signal"),
                    "rip": t.get("rip"),
                    "insn": t.get("insn"),
                    "regs": t.get("regs"),
                    "count": 0,
                    "first_core": str(core),
                    "first_instance": inst.name,
                }
            bugs[sig]["instances"].add(inst.name)
            bugs[sig]["count"] += 1

            # Stash artefacts (copy of core + JSON, dedup by sig).
            bdir = bugs_dir / sig
            bdir.mkdir(exist_ok=True)
            if not (bdir / "core").exists():
                subprocess.run(["cp", str(core), str(bdir / "core")],
                               check=False)
                (bdir / "triage.json").write_text(json.dumps(t, indent=2))

    print()
    print(f"=== {len(bugs)} unique bug signatures ===")
    for sig, info in sorted(bugs.items(),
                            key=lambda kv: (-kv[1]["count"], kv[0])):
        print(f"  {sig}  hits={info['count']:>4}  {info['signal']:7} "
              f"rip={info['rip']}  in {sorted(info['instances'])}")
        print(f"          insn={info['insn']}")

    print()
    print("=== per instance ===")
    for name, info in sorted(by_instance.items()):
        sigs = sorted(info['sigs'])
        print(f"  {name:8} cores={info['cores']:>4}  unique_sigs={len(sigs)}  {sigs}")

    summary_path = args.root / "summary.json"
    summary_path.write_text(json.dumps({
        "ts": time.time(),
        "bugs": {sig: {**v, "instances": sorted(v["instances"])}
                 for sig, v in bugs.items()},
        "by_instance": {n: {**v, "sigs": sorted(v["sigs"])}
                        for n, v in by_instance.items()},
    }, indent=2, default=str))
    print(f"\n[+] summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
