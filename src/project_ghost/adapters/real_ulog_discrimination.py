"""Real-data discrimination experiment (paper §8.8).

This module closes the residual critique of paper §8.7 ("all-HOLDS
is vacuous because the verifier was never given an opportunity to
reject the run"). It re-runs the **same real PX4 ULog** through the
**same closed-loop pipeline** as ``real_ulog_smoke``, but with one
buggy policy substituted, and shows that the verifier flips its
verdict from HOLDS to VIOLATED.

The single-sentence claim:

  *The verifier discriminates real flight telemetry against a known
  regression: on the same ULog, the reference produces all-HOLDS and
  a one-line buggy decision policy produces BAUD VIOLATED.*

That sentence answers the reviewer's strongest objection
("the experiment shows the pipeline runs, not that the properties
catch anything on real data").

Why this is the right experiment to address the critique:

- The synthetic violation matrix (§8.2) demonstrates the verifier
  catches six bug categories on synthetic ground truth. The question
  it does not answer is *do those detections transfer to real
  telemetry?* This module answers yes for the two bug categories
  whose precondition fires under the real ULog's drift pattern.

- The A/B is controlled: same ULog, same fusion oracle, same MCAP
  schema, same verifier — only one named component differs. The
  MCAP SHA-256 of the buggy run differs from the nominal SHA-256
  because the buggy component leaves a visible mark in the
  ``policy_id`` and ``reason`` fields.

- The buggy policies are imported verbatim from
  ``project_ghost.examples.violation_matrix`` so this module
  introduces zero new attack surface; what is tested here is the
  *same* buggy code already exercised in §8.2.

Demonstrated categories on the real PX4 sample ULog:

  - ``DECISION_PROCEEDS_ANYWAY``    → BAUD-v1 VIOLATED
  - ``ACTUATION_NON_SAFE_REASON``   → BAUD-v1 VIOLATED

Both categories trigger because the real ULog's stationary-belief
configuration causes drift to be detected on the vast majority of
cycles (paper §8.7 reports ``fire_fraction ≈ 0.94``), which means
the BAUD precondition is satisfied on most cycles, which means a
buggy decision or actuation policy is given many opportunities to
issue a non-conservative action.

Stdlib + numpy + project_ghost internals + pyulog (via adapter).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from project_ghost.adapters.px4_ulog import parse_ulog_pose_samples
from project_ghost.adapters.real_ulog_smoke import (
    RealULogSmokeSummary,
    _run_real_ulog_pipeline,
    _subsample_to_cycle_rate,
    _verify_all_and_bundle,
)
from project_ghost.core.actuation import AttitudeHoldReferencePolicy
from project_ghost.core.decisions import UncertaintyAwareReferencePolicy
from project_ghost.core.feedback import MahalanobisDowngradePolicy
from project_ghost.examples.violation_matrix import (
    _BuggyNonSafeReasonActuationPolicy,
    _BuggyProceedOnlyDecisionPolicy,
)

if TYPE_CHECKING:
    from pathlib import Path


_FEEDBACK_MIN_OUTCOMES: Final[int] = 4
_FEEDBACK_DOWNGRADE_THRESHOLD: Final[int] = 2
_MAX_REAL_CYCLES: Final[int] = 200


class RealULogBugCategory(StrEnum):
    """Closed catalogue of buggy components exercised on the real ULog.

    Each name matches the corresponding ``BugCategory`` of the
    synthetic violation matrix (§8.2).
    """

    DECISION_PROCEEDS_ANYWAY = "decision_proceeds_anyway"
    ACTUATION_NON_SAFE_REASON = "actuation_non_safe_reason"


@dataclass(frozen=True)
class RealULogDiscriminationCell:
    """One row of the real-data discrimination matrix: a
    ``(buggy_category, verdict)`` pair, plus the property whose
    flip from HOLDS to VIOLATED demonstrates discrimination on the
    real ULog.
    """

    category: RealULogBugCategory
    expected_violator: str  # "BAUD-v1" | "ERUR-v1" | etc.
    summary: RealULogSmokeSummary
    discriminates: bool  # ``not summary.<expected>_holds``


@dataclass(frozen=True)
class RealULogDiscriminationResults:
    """Bundled output of the discrimination experiment.

    ``nominal`` is the reference verdict bundle on the same real ULog
    (same as ``run_real_ulog_smoke``). ``buggy_cells`` is one entry
    per ``RealULogBugCategory``. ``all_discriminate`` is True iff
    every buggy category produced a flip on its expected property.
    """

    ulog_sha256: str
    nominal: RealULogSmokeSummary
    buggy_cells: tuple[RealULogDiscriminationCell, ...]
    all_discriminate: bool


def _expected_violator_for(category: RealULogBugCategory) -> str:
    """The property each buggy category is expected to flip.

    Mirrors the violation matrix; the same buggy class breaks the
    same property whether the ground truth is synthetic or real.
    """
    if category is RealULogBugCategory.DECISION_PROCEEDS_ANYWAY:
        return "BAUD-v1"
    if category is RealULogBugCategory.ACTUATION_NON_SAFE_REASON:
        return "BAUD-v1"
    raise ValueError(f"unhandled category: {category}")


def _holds_by_id(summary: RealULogSmokeSummary, prop_id: str) -> bool:
    if prop_id == "BAUD-v1":
        return summary.baud_holds
    if prop_id == "ERUR-v1":
        return summary.erur_holds
    if prop_id == "MD-v1":
        return summary.md_holds
    if prop_id == "RLB-v1":
        return summary.rlb_holds
    if prop_id == "FPB-v1":
        return summary.fpb_holds
    raise ValueError(f"unknown property id: {prop_id}")


def _run_buggy_case(
    category: RealULogBugCategory,
    sub_samples: list,  # type: ignore[type-arg]
    output_mcap_path: Path,
    *,
    n_pose_samples_in_ulog: int,
    ulog_sha256: str,
) -> RealULogDiscriminationCell:
    """Run one buggy category against the same real-ULog samples and
    return the discrimination cell.
    """
    feedback_policy = MahalanobisDowngradePolicy(
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )

    decision_policy: Any
    actuation_policy: Any
    if category is RealULogBugCategory.DECISION_PROCEEDS_ANYWAY:
        decision_policy = _BuggyProceedOnlyDecisionPolicy()
        actuation_policy = AttitudeHoldReferencePolicy()
    elif category is RealULogBugCategory.ACTUATION_NON_SAFE_REASON:
        decision_policy = UncertaintyAwareReferencePolicy()
        actuation_policy = _BuggyNonSafeReasonActuationPolicy()
    else:
        raise ValueError(f"unhandled category: {category}")

    n_cycles = _run_real_ulog_pipeline(
        sub_samples,
        output_mcap_path,
        feedback_policy=feedback_policy,
        decision_policy=decision_policy,
        actuation_policy=actuation_policy,
    )
    summary = _verify_all_and_bundle(
        output_mcap_path,
        n_pose_samples_in_ulog=n_pose_samples_in_ulog,
        n_cycles=n_cycles,
        ulog_sha256=ulog_sha256,
    )
    expected = _expected_violator_for(category)
    discriminates = not _holds_by_id(summary, expected)
    return RealULogDiscriminationCell(
        category=category,
        expected_violator=expected,
        summary=summary,
        discriminates=discriminates,
    )


def run_real_ulog_discrimination(
    ulog_path: Path,
    out_dir: Path,
    *,
    max_cycles: int = _MAX_REAL_CYCLES,
) -> RealULogDiscriminationResults:
    """Run the real-data discrimination experiment (paper §8.8).

    Reads ``ulog_path`` once, subsamples to the Ghost cycle rate, and
    drives the closed-loop pipeline under (1) the reference policies
    and (2) each ``RealULogBugCategory`` in turn. Returns the paired
    verdict bundle. Writes one MCAP per run to ``out_dir``:

    - ``real_ulog_nominal.mcap``
    - ``real_ulog_<category>.mcap`` per buggy category

    ``all_discriminate`` is True iff every buggy category flipped
    its expected property; in that case the verifier is shown to
    discriminate real telemetry against the same regressions caught
    on synthetic data.
    """
    samples = parse_ulog_pose_samples(ulog_path)
    if not samples:
        raise ValueError(f"ULog produced 0 pose samples: {ulog_path}")
    sub_samples = _subsample_to_cycle_rate(samples, max_cycles)
    ulog_sha = hashlib.sha256(ulog_path.read_bytes()).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Nominal run — reference policies.
    nominal_mcap = out_dir / "real_ulog_nominal.mcap"
    feedback_ref = MahalanobisDowngradePolicy(
        min_outcomes=_FEEDBACK_MIN_OUTCOMES,
        downgrade_threshold=_FEEDBACK_DOWNGRADE_THRESHOLD,
    )
    decision_ref = UncertaintyAwareReferencePolicy()
    actuation_ref = AttitudeHoldReferencePolicy()
    n_cycles = _run_real_ulog_pipeline(
        sub_samples,
        nominal_mcap,
        feedback_policy=feedback_ref,
        decision_policy=decision_ref,
        actuation_policy=actuation_ref,
    )
    nominal = _verify_all_and_bundle(
        nominal_mcap,
        n_pose_samples_in_ulog=len(samples),
        n_cycles=n_cycles,
        ulog_sha256=ulog_sha,
    )

    # Buggy runs — one per category.
    cells = []
    for category in RealULogBugCategory:
        cell_mcap = out_dir / f"real_ulog_{category.value}.mcap"
        cell = _run_buggy_case(
            category,
            sub_samples,
            cell_mcap,
            n_pose_samples_in_ulog=len(samples),
            ulog_sha256=ulog_sha,
        )
        cells.append(cell)

    all_discriminate = all(c.discriminates for c in cells)
    return RealULogDiscriminationResults(
        ulog_sha256=ulog_sha,
        nominal=nominal,
        buggy_cells=tuple(cells),
        all_discriminate=all_discriminate,
    )


__all__ = [
    "RealULogBugCategory",
    "RealULogDiscriminationCell",
    "RealULogDiscriminationResults",
    "run_real_ulog_discrimination",
]
