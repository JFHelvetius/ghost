"""PX4 ULog → Ghost pipeline adapter (skeleton — paper §10 + venues/dataset_integration.md).

Concrete, runnable skeleton of the integration path documented in
``docs/paper/venues/dataset_integration.md``. This is **NOT** a
production adapter and is deliberately NOT installed as part of the
``project_ghost`` package — putting it inside ``src/`` would require
a test suite, CI coverage, and a stable contract that the v0.2.x
honest-scope clause (paper §9 "Sim, not hardware") explicitly defers.

What this skeleton demonstrates:

1. **The shape of the conversion** from a real PX4 flight log
   (``.ulg`` format) to the message types Ghost's pipeline ingests.
2. **The specific fields** the adapter must extract: vehicle position
   estimate, covariance, IMU samples, attitude, GPS fix status.
3. **The honest-truth source policy**: if no independent ground-truth
   is available (the common case in unattended flight logs), the
   adapter must explicitly fall back to ``USE_EKF2_AS_GROUND_TRUTH``,
   which gives a vacuous evaluation. Real-flight validation requires
   pairing the ULog with motion-capture truth.

What this skeleton does **not** do:

- It does not actually run. The two lines that would parse the ULog
  (``ULog(path)``) and write the MCAP (``MCAPFileSink``) are present,
  but ``pyulog`` is not a project dependency, the converter loop is
  ``raise NotImplementedError``, and the policy parameter tuning
  needed at production noise levels is out of scope.

Run the doctest with ``python -m doctest`` to confirm the skeleton's
shape compiles; do not expect it to produce a valid MCAP.

Reference: a full implementation would close the
``ADR-0037 (candidate): real-flight data integration`` candidate in
docs/paper/project_ghost_v0_2.md §10.

Usage (planned):

    pip install pyulog
    python docs/paper/scripts/px4_ulog_adapter_skeleton.py \
        --ulog flight.ulg --mcap-out flight.mcap

The output ``flight.mcap`` would then be verifiable by
``ghost verify-properties --mcap flight.mcap``, closing the loop
between real flight telemetry and the Ghost property set.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class GroundTruthSource(StrEnum):
    """How the adapter sources the truth pose for divergence
    computation. Documents an honest-scope decision the operator
    must make explicitly per dataset.
    """

    # External motion-capture truth time-aligned with the ULog.
    # Honest evaluation possible. Requires the operator to provide
    # the truth source explicitly.
    MOTION_CAPTURE = "motion_capture"

    # External RTK GPS with cm-level accuracy.
    RTK_GPS = "rtk_gps"

    # The ULog's own early EKF2 estimate. Vacuous evaluation —
    # BAUD will never fire because the agent agrees with itself.
    # Documented as the default for unattended flight logs where no
    # independent truth exists.
    USE_EKF2_AS_GROUND_TRUTH = "use_ekf2_as_ground_truth_vacuous"


@dataclass(frozen=True)
class AdapterConfig:
    """Adapter configuration. Most fields default to values matching
    the reference smoke; production deployments would re-tune.
    """

    ulog_path: Path
    mcap_out_path: Path
    ground_truth_source: GroundTruthSource = (
        GroundTruthSource.USE_EKF2_AS_GROUND_TRUTH
    )

    # Pipeline frequency. PX4 EKF2 publishes at 250 Hz; Ghost's
    # reference smoke runs at 10 Hz. Subsample by default.
    subsample_to_hz: float = 10.0

    # Calibration policy parameters. Defaults match the smoke;
    # production noise levels likely require re-tuning per platform
    # (see docs/paper/venues/dataset_integration.md §What an
    # integration ADR would specify, item 5).
    calibration_min_outcomes: int = 4
    calibration_downgrade_threshold: int = 2
    calibration_max_history: int = 32


def convert_ulog_to_ghost_mcap(cfg: AdapterConfig) -> Path:
    """Convert one PX4 ULog file to a Ghost-pipeline-compatible MCAP.

    NOT IMPLEMENTED — the function declares its contract for
    documentation purposes only. A future contributor would:

    1. ``ulog = pyulog.ULog(cfg.ulog_path)``
    2. Extract topics:
       - ``vehicle_local_position`` (xyz + covariance)
       - ``vehicle_attitude`` (quaternion)
       - ``sensor_combined`` (IMU)
       - ``vehicle_gps_position`` (fix status)
    3. Time-align to ``cfg.subsample_to_hz``.
    4. For each cycle, construct a ``VehicleState`` from the EKF2
       fields and pass it through the Ghost pipeline
       (``fuse_and_publish`` → ``assess_belief`` → ...).
    5. Source ground truth per ``cfg.ground_truth_source``.
    6. Write the resulting messages to ``cfg.mcap_out_path``
       through ``MCAPFileSink``.

    Returns the path to the written MCAP, which is then verifiable
    by ``ghost verify-properties --mcap <mcap_out_path>``.

    >>> # Doctest just confirms the function signature compiles.
    >>> import inspect
    >>> sig = inspect.signature(convert_ulog_to_ghost_mcap)
    >>> list(sig.parameters)
    ['cfg']
    """
    raise NotImplementedError(
        "PX4 ULog adapter is a documentation-only skeleton. "
        "Implementing it is the candidate ADR-0037 (paper §10). "
        "See docs/paper/venues/dataset_integration.md for the "
        "discharge plan."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Skeleton converter from PX4 ULog (.ulg) to a "
            "Ghost-pipeline-compatible MCAP. NOT IMPLEMENTED — runs "
            "raise NotImplementedError. Demonstrates the integration "
            "path documented at "
            "docs/paper/venues/dataset_integration.md."
        )
    )
    parser.add_argument(
        "--ulog", type=Path, required=True, help="Path to .ulg file"
    )
    parser.add_argument(
        "--mcap-out", type=Path, required=True, help="Where to write the MCAP"
    )
    parser.add_argument(
        "--ground-truth-source",
        default=GroundTruthSource.USE_EKF2_AS_GROUND_TRUTH.value,
        choices=[g.value for g in GroundTruthSource],
        help=(
            "Ground-truth policy. "
            "use_ekf2_as_ground_truth_vacuous (default) yields a "
            "vacuous evaluation; use motion_capture or rtk_gps for "
            "honest evaluation."
        ),
    )
    parser.add_argument(
        "--subsample-to-hz", type=float, default=10.0,
        help="Subsample PX4's 250 Hz EKF2 to Ghost's cycle rate.",
    )
    args = parser.parse_args()

    cfg = AdapterConfig(
        ulog_path=args.ulog,
        mcap_out_path=args.mcap_out,
        ground_truth_source=GroundTruthSource(args.ground_truth_source),
        subsample_to_hz=args.subsample_to_hz,
    )
    out = convert_ulog_to_ghost_mcap(cfg)
    print(f"Wrote {out}")
    print(
        "Verify with: ghost verify-properties --mcap "
        f"{cfg.mcap_out_path}"
    )


if __name__ == "__main__":
    main()


__all__ = [
    "AdapterConfig",
    "GroundTruthSource",
    "convert_ulog_to_ghost_mcap",
]
