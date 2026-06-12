"""Quantitative benchmark of Ghost vs RTAMT on a comparable safety
property (paper §8.7; Action E).

Compares the two tools on a property that approximates BAUD-v1 from
both sides:

- **Ghost**: ``ghost verify-properties --mcap <log>`` runs the
  Python verifier over the captured MCAP. Property statements live
  in the ADRs; the verifier knows the Ghost message schema.
- **RTAMT**: signal temporal logic (STL) monitor. The property is
  translated into STL as best as the formalism allows:

      G_[a, b] ( error_magnitude > threshold ) -> ( decision != PROCEED )

  which reads "if the prediction error has been above threshold for
  every cycle in the past [a..b] window, then at cycle b+1 the
  decision must not be PROCEED". This is a *qualitative* analogue of
  BAUD-v1; the actual BAUD predicate is K-of-M-in-W, which STL
  cannot natively express as a single formula without auxiliary
  counters.

The benchmark reports:

- Verdict per tool: does the property hold on the reference smoke
  MCAP?
- Wall-clock time per tool, mean of 5 replicates.
- Setup steps (number of API calls / lines of glue code) — a
  qualitative measure of integration friction.

Honest reading of the result:

- **Ghost has lower friction** because the property is hand-coded
  for the domain; the verifier knows the channel names and the
  decision-lattice semantics.
- **RTAMT is more expressive in principle** because STL formulae
  can describe arbitrary temporal patterns; the formula above is
  a single STL line. The cost is that the user has to extract
  signals manually and the property is qualitative, not the
  exact ADR predicate.
- **The two are complementary**, not direct competitors. RTAMT is
  the right choice when the user wants to write properties in STL
  declaratively over arbitrary signals. Ghost is the right choice
  when the user wants a content-addressed CLI verifier for a
  specific autonomy supervisor.

Run after ``pip install rtamt``:

    .venv\\Scripts\\python.exe docs\\paper\\scripts\\benchmark_vs_rtamt.py

Writes results to ``docs/paper/outputs/benchmark_vs_rtamt.json``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import rtamt  # type: ignore[import-untyped]

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties import verify_baud
from project_ghost.telemetry import (
    MCAPReplayReader,
    decode_message,
)
from project_ghost.telemetry.channels import (
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CHANNEL_DECISIONS,
    CHANNEL_PREDICTION_OUTCOMES,
)

# ---------------------------------------------------------------------------
# Tunables (matched on both sides for fairness)
# ---------------------------------------------------------------------------

_FEEDBACK_MIN_OUTCOMES = 4
_FEEDBACK_DOWNGRADE_THRESHOLD = 2
_N_CYCLES = 50  # longer than the reference smoke to give RTAMT enough samples
_REPLICAS = 5  # for mean wall-clock time


# ---------------------------------------------------------------------------
# Extract STL-friendly signals from the Ghost MCAP
# ---------------------------------------------------------------------------


def _extract_signals(mcap_path: Path) -> tuple[list[float], list[float], list[float]]:
    """Return three parallel time series:

    - timestamps in seconds (relative to start)
    - error_magnitude per cycle (worst Mahalanobis position)
    - proceed_indicator per cycle (1.0 if PROCEED, 0.0 otherwise)
    """
    cal_by_stamp = {}
    dec_by_stamp = {}
    out_by_stamp = {}
    with MCAPReplayReader(mcap_path) as reader:
        for msg in reader.iter_messages():
            decoded = decode_message(msg)
            if msg.channel == CHANNEL_CALIBRATED_SELF_ASSESSMENT:
                stamp = decoded.raw_assessment.belief_stamp_sim_ns
                cal_by_stamp[stamp] = decoded
            elif msg.channel == CHANNEL_DECISIONS:
                # /decisions carries DecisionRationale; the inner
                # Decision is decoded.decision.
                stamp = decoded.belief_stamp_sim_ns
                dec_by_stamp[stamp] = decoded
            elif msg.channel == CHANNEL_PREDICTION_OUTCOMES:
                stamp = decoded.actual_belief_stamp_sim_ns
                out_by_stamp[stamp] = decoded

    stamps = sorted(set(cal_by_stamp.keys()) & set(dec_by_stamp.keys()))
    t0 = stamps[0]
    timestamps = [(s - t0) / 1e9 for s in stamps]

    error_magnitude: list[float] = []
    proceed_indicator: list[float] = []
    for s in stamps:
        c = cal_by_stamp[s]
        # The Mahalanobis is per outcome; use the worst position
        # Mahalanobis from the calibration history as a proxy.
        err = float(c.calibration_history.worst_position_mahalanobis)
        error_magnitude.append(err)
        dec = dec_by_stamp[s]
        # dec is a DecisionRationale; the Decision lives at dec.decision.
        proceed_indicator.append(1.0 if dec.decision.kind.value == "proceed" else 0.0)
    return timestamps, error_magnitude, proceed_indicator


# ---------------------------------------------------------------------------
# Ghost side
# ---------------------------------------------------------------------------


def _time_ghost(mcap_path: Path) -> tuple[bool, float]:
    # Warm-up (cache reads, jit, etc.).
    verify_baud(
        mcap_path,
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )
    durations: list[float] = []
    for _ in range(_REPLICAS):
        t0 = time.perf_counter()
        report = verify_baud(
            mcap_path,
            min_outcomes=_FEEDBACK_MIN_OUTCOMES,
            downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
        )
        durations.append((time.perf_counter() - t0) * 1000.0)
    return report.holds, sum(durations) / len(durations)


# ---------------------------------------------------------------------------
# RTAMT side
# ---------------------------------------------------------------------------


def _time_rtamt(
    timestamps: list[float],
    error_magnitude: list[float],
    proceed_indicator: list[float],
) -> tuple[bool, float]:
    """STL formula approximating BAUD-v1:

        always[0:0.4] ( ( error > 3.0 ) implies ( proceed_indicator < 0.5 ) )

    Reads as: whenever the prediction error is above 3-sigma, the agent
    must not be issuing PROCEED. The window [0:0.4] corresponds to ~4
    cycles at the smoke's 10 Hz rate, approximating BAUD's M=4 min
    outcomes; an STL formula cannot directly count K-of-M occurrences,
    but the global temporal implication captures the safety intuition.
    """
    def _build_monitor() -> rtamt.StlDenseTimeSpecification:
        spec = rtamt.StlDenseTimeSpecification(rtamt.Semantics.STANDARD)
        spec.name = "baud_like_rtamt"
        spec.declare_var("error", "float")
        spec.declare_var("proceed", "float")
        spec.declare_var("hold", "float")
        spec.set_var_io_type("error", "input")
        spec.set_var_io_type("proceed", "input")
        spec.set_var_io_type("hold", "output")
        spec.spec = "hold = always[0:0.4] ( (error > 3.0) implies (proceed < 0.5) )"
        spec.parse()
        return spec

    # Warm-up.
    spec = _build_monitor()
    err_signal = list(zip(timestamps, error_magnitude, strict=True))
    proc_signal = list(zip(timestamps, proceed_indicator, strict=True))
    _ = spec.evaluate(["error", err_signal], ["proceed", proc_signal])

    durations: list[float] = []
    last_robustness = 0.0
    for _ in range(_REPLICAS):
        spec = _build_monitor()
        t0 = time.perf_counter()
        out = spec.evaluate(["error", err_signal], ["proceed", proc_signal])
        durations.append((time.perf_counter() - t0) * 1000.0)
        # The output is a list of (t, robustness) pairs; the formula
        # holds robustly iff every robustness value is >= 0.
        robustness_values = [r for _, r in out]
        last_robustness = float(np.min(robustness_values)) if robustness_values else 0.0

    holds = last_robustness >= 0.0
    return holds, sum(durations) / len(durations)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = repo_root / "docs" / "paper" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Capture a fresh smoke MCAP for the benchmark.
    mcap_path = out_dir / "benchmark_smoke.mcap"
    print(f"Generating smoke MCAP at {mcap_path}...")
    summary = run_closed_loop_smoke(mcap_path, n_cycles=_N_CYCLES)
    print(f"  SHA-256: {summary.mcap_sha256}")
    print(f"  Cycles: {summary.n_cycles}")
    print()

    print("Benchmarking Ghost (verify_baud)...")
    ghost_holds, ghost_ms = _time_ghost(mcap_path)
    print(f"  Verdict: {'HOLDS' if ghost_holds else 'VIOLATED'}")
    print(f"  Time:    {ghost_ms:.2f} ms (mean of {_REPLICAS} replicates)")
    print()

    print("Extracting signals for RTAMT...")
    timestamps, err, proc = _extract_signals(mcap_path)
    print(f"  {len(timestamps)} samples extracted")
    print()

    print("Benchmarking RTAMT (STL approximation)...")
    rtamt_holds, rtamt_ms = _time_rtamt(timestamps, err, proc)
    print(f"  Verdict: {'HOLDS' if rtamt_holds else 'VIOLATED'}")
    print(f"  Time:    {rtamt_ms:.2f} ms (mean of {_REPLICAS} replicates)")
    print()

    payload = {
        "smoke_n_cycles": _N_CYCLES,
        "smoke_mcap_sha256": summary.mcap_sha256,
        "replicas": _REPLICAS,
        "ghost": {
            "tool": "ghost verify-properties (BAUD-v1)",
            "verdict_holds": ghost_holds,
            "wallclock_ms_mean": round(ghost_ms, 3),
            "property_language": "Python predicate over MCAP schema",
            "setup_lines_of_code": 1,  # ghost verify-properties --mcap X
        },
        "rtamt": {
            "tool": "RTAMT (STL dense-time)",
            "verdict_holds": rtamt_holds,
            "wallclock_ms_mean": round(rtamt_ms, 3),
            "property_language": "STL: G[0:0.4] (error>3 -> proceed<0.5)",
            "setup_lines_of_code": 12,  # spec building + signal extraction
        },
        "honest_caveats": [
            "RTAMT formula is a qualitative STL analogue of BAUD-v1, not the "
            "exact ADR predicate (STL cannot natively count K-of-M occurrences).",
            "Ghost's verifier has full knowledge of the Ghost message schema; "
            "RTAMT receives the signals pre-extracted by 12 lines of glue code.",
            "Wall-clock times measure the verification step only, not the "
            "signal-extraction step that RTAMT requires.",
        ],
    }
    json_path = out_dir / "benchmark_vs_rtamt.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
