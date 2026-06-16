"""CLI driver: TLC parametric sweep over Rlb.tla (paper section 6.3, ADR-0038).

Runs TLC on Rlb.tla at three structurally distinct W values
(4, 8, 16) and emits a self-describing JSON artefact summarising
how many states each scale enumerated and that INV_RLB held in
all three. The sweep is the empirical-generalisation half of the
v0.2.5 unbounded RLB-v1 evidence (the other half is the hand
proof at ``docs/proofs/Rlb_unbounded_handproof.md`` and the TLAPS
outline at ``docs/proofs/Rlb_unbounded.tla``).

Exit code 0 iff TLC reports "Model checking completed. No error"
for every W. Exit code 1 if any sweep produces a counterexample
(which would falsify the bound on that W and require the paper
to retract); exit code 2 on argument or environment errors.

Usage::

    python docs/paper/scripts/run_rlb_tlc_sweep.py \\
        --java /path/to/java --tla2tools /path/to/tla2tools.jar \\
        --out-dir docs/paper/outputs/rlb_tlc_sweep
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_W_SWEEP = (4, 8, 16)


def _default_java() -> str | None:
    return shutil.which("java")


def _resolve_repo_path(relative: str) -> Path:
    return (Path(__file__).resolve().parents[3] / relative).resolve()


def _run_one(
    java: str, tla2tools: Path, proof_dir: Path, config_name: str, w: int
) -> dict:
    """Run TLC on one config; return parsed metrics."""
    cmd = [
        java,
        "-cp",
        str(tla2tools),
        "tlc2.TLC",
        "-config",
        config_name,
        "Rlb",
    ]
    start = time.perf_counter()
    proc = subprocess.run(  # noqa: S603 -- args are trusted CLI flags
        cmd,
        cwd=str(proof_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - start
    stdout = proc.stdout

    holds = "Model checking completed. No error has been found." in stdout
    m = re.search(
        r"(\d+) states generated, (\d+) distinct states found",
        stdout,
    )
    states_generated = int(m.group(1)) if m else 0
    distinct_states = int(m.group(2)) if m else 0

    return {
        "W": w,
        "config": config_name,
        "exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "states_generated": states_generated,
        "distinct_states": distinct_states,
        "invariant_holds": bool(holds),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "RLB-v1 parametric TLC sweep over W in {4, 8, 16} "
            "(paper section 6.3, ADR-0038)."
        )
    )
    parser.add_argument(
        "--java",
        default=_default_java(),
        help=(
            "Path to java executable. Defaults to the first java on PATH; "
            "fails if absent. CI uses Eclipse Temurin 17."
        ),
    )
    parser.add_argument(
        "--tla2tools",
        type=Path,
        default=_resolve_repo_path("tla2tools.jar"),
        help=(
            "Path to tla2tools.jar (TLA+ Tools). Defaults to "
            "<repo-root>/tla2tools.jar; CI downloads it before "
            "invoking this script."
        ),
    )
    parser.add_argument(
        "--proof-dir",
        type=Path,
        default=_resolve_repo_path("docs/proofs"),
        help="Directory containing Rlb.tla and Rlb_W*.cfg files.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_resolve_repo_path("docs/paper/outputs/rlb_tlc_sweep"),
        help=(
            "Directory where the sweep JSON is written. Created if "
            "missing."
        ),
    )
    args = parser.parse_args()

    if not args.java:
        print("ERROR: java not found on PATH. Pass --java explicitly.", file=sys.stderr)
        return 2
    if not args.tla2tools.exists():
        print(
            f"ERROR: tla2tools.jar not found at {args.tla2tools}. "
            "Download it from https://github.com/tlaplus/tlaplus/releases.",
            file=sys.stderr,
        )
        return 2
    if not args.proof_dir.exists():
        print(f"ERROR: proof dir not found at {args.proof_dir}.", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)

    configs = {4: "Rlb.cfg", 8: "Rlb_W8.cfg", 16: "Rlb_W16.cfg"}
    results: list[dict] = []
    for w in _W_SWEEP:
        cfg = configs[w]
        cfg_path = args.proof_dir / cfg
        if not cfg_path.exists():
            print(
                f"ERROR: config {cfg_path} missing for W={w}.", file=sys.stderr
            )
            return 2
        print(f"Running TLC W={w} (config {cfg})...")
        r = _run_one(args.java, args.tla2tools, args.proof_dir, cfg, w)
        results.append(r)
        print(
            f"  W={w}: states_generated={r['states_generated']} "
            f"distinct={r['distinct_states']} "
            f"INV_RLB={'HOLDS' if r['invariant_holds'] else 'VIOLATED'} "
            f"({r['elapsed_seconds']}s)"
        )

    all_hold = all(r["invariant_holds"] for r in results)
    payload = {
        "schema_version": 1,
        "experiment": "rlb_tlc_parametric_sweep",
        "spec": "docs/proofs/Rlb.tla",
        "constants_swept": "W (MAX_DRIFT = W per config)",
        "W_values": list(_W_SWEEP),
        "results": results,
        "all_W_INV_RLB_holds": bool(all_hold),
    }
    json_path = args.out_dir / "sweep.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    print()
    print(f"Sweep JSON: {json_path}")
    print(f"all_W_INV_RLB_holds: {all_hold}")

    # Cleanup TLC artefact dirs (states/ contains binary state files).
    states_dir = args.proof_dir / "states"
    if states_dir.exists():
        shutil.rmtree(states_dir)

    return 0 if all_hold else 1


if __name__ == "__main__":
    raise SystemExit(main())
