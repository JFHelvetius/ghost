"""ADR-0032 — Eventual Reactivation Under Recovery property verifier (ERUR-v1).

Symmetric counterpart of :mod:`project_ghost.properties.baud`. Where
BAUD-v1 asserts "no PROCEED when drift is detected," ERUR-v1 asserts
"PROCEED is emitted when raw is KNOWN and drift is absent." Together
they close the policy-pair claim against the trivial degenerate
solution ``always_hold``.

The property statement, scope, and verification plan live in
``docs/adr/0032-eventual-reactivation-under-recovery-property-v1.md``.
Read the ADR before reading this module — the dataclasses below are an
exact mechanical translation of the statement.

Stdlib only at runtime modulo the ``mcap`` extra (already required for
replay). Pure, deterministic, no clock, no random.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from project_ghost.core.actuation.types import ActuationDirective
from project_ghost.core.decisions.types import DecisionKind
from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.uncertainty.self_assessment import (
    SelfAssessmentLevel,
)
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


ERUR_PROPERTY_VERSION: Final[str] = "ERUR-v1"

# Defaults mirror BAUD-v1 (and `MahalanobisDowngradePolicy`) so the
# property pair is queried against the same wiring by default.
_DEFAULT_MIN_OUTCOMES: Final[int] = 4
_DEFAULT_DOWNGRADE_THRESHOLD: Final[int] = 2

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


class ERURViolationKind(StrEnum):
    """Closed catalogue of how a single cycle can violate ERUR-v1.

    Two postconditions and one structural failure; same posture as
    :class:`BAUDViolationKind` so consumers can build symmetric
    handlers.
    """

    # Postcondition 1: ``C_t.adjusted_overall_level == KNOWN``.
    ADJUSTED_LEVEL_NOT_KNOWN = "adjusted_level_not_known"

    # Postcondition 2: ``A_t.decision.kind == PROCEED``.
    DECISION_KIND_NOT_PROCEED = "decision_kind_not_proceed"

    # Structural: the MCAP contained a CalibratedSelfAssessment whose
    # precondition held, but no ActuationDirective at the matching
    # stamp. Postcondition 2 cannot be evaluated; the verifier reports
    # a violation rather than silently passing.
    MISSING_ACTUATION_RECORD = "missing_actuation_record"


@dataclass(frozen=True)
class ERURViolation:
    """One cycle, one violated postcondition.

    A single cycle may produce multiple violations (e.g. both
    ``ADJUSTED_LEVEL_NOT_KNOWN`` and ``DECISION_KIND_NOT_PROCEED``).
    Each is reported separately so the cause is unambiguous.
    """

    cycle_stamp_sim_ns: int
    cycle_index: int
    kind: ERURViolationKind
    observed: str
    precondition_outcomes_considered: int
    precondition_beyond_3_or_worse: int

    def __post_init__(self) -> None:
        if self.cycle_stamp_sim_ns < 0:
            raise ValueError(f"cycle_stamp_sim_ns must be >= 0; got {self.cycle_stamp_sim_ns}")
        if self.cycle_index < 0:
            raise ValueError(f"cycle_index must be >= 0; got {self.cycle_index}")
        if not isinstance(self.kind, ERURViolationKind):
            raise TypeError(f"kind must be ERURViolationKind; got {type(self.kind).__name__}")
        if not isinstance(self.observed, str):
            raise TypeError(f"observed must be str; got {type(self.observed).__name__}")
        if self.precondition_outcomes_considered < 0:
            raise ValueError(
                "precondition_outcomes_considered must be >= 0; got "
                f"{self.precondition_outcomes_considered}"
            )
        if self.precondition_beyond_3_or_worse < 0:
            raise ValueError(
                "precondition_beyond_3_or_worse must be >= 0; got "
                f"{self.precondition_beyond_3_or_worse}"
            )


@dataclass(frozen=True)
class ERURVerificationReport:
    """Output of :func:`verify_erur`.

    Field shape is structurally parallel to
    :class:`BAUDVerificationReport` so consumers can build symmetric
    code paths.
    """

    mcap_sha256: str
    min_outcomes: int
    downgrade_threshold: int
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[ERURViolation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.mcap_sha256) != _SHA256_HEX_LEN or not all(
            c in _HEX_CHARS for c in self.mcap_sha256
        ):
            raise ValueError(
                f"mcap_sha256 must be {_SHA256_HEX_LEN} lowercase hex "
                f"chars; got {self.mcap_sha256!r}"
            )
        if self.min_outcomes < 0:
            raise ValueError(f"min_outcomes must be >= 0; got {self.min_outcomes}")
        if self.downgrade_threshold < 1:
            raise ValueError(f"downgrade_threshold must be >= 1; got {self.downgrade_threshold}")
        if self.cycles_total < 0:
            raise ValueError(f"cycles_total must be >= 0; got {self.cycles_total}")
        if not 0 <= self.cycles_precondition_held <= self.cycles_total:
            raise ValueError(
                "cycles_precondition_held must be in "
                f"[0, cycles_total={self.cycles_total}]; got "
                f"{self.cycles_precondition_held}"
            )
        if (
            self.first_precondition_cycle_stamp_sim_ns is not None
            and self.first_precondition_cycle_stamp_sim_ns < 0
        ):
            raise ValueError(
                "first_precondition_cycle_stamp_sim_ns must be >= 0 or "
                "None; got "
                f"{self.first_precondition_cycle_stamp_sim_ns}"
            )
        if self.cycles_precondition_held == 0:
            if self.first_precondition_cycle_stamp_sim_ns is not None:
                raise ValueError(
                    "first_precondition_cycle_stamp_sim_ns must be None "
                    "when cycles_precondition_held == 0"
                )
        elif self.first_precondition_cycle_stamp_sim_ns is None:
            raise ValueError(
                "first_precondition_cycle_stamp_sim_ns must be set "
                "when cycles_precondition_held > 0"
            )
        if not isinstance(self.violations, tuple):
            raise TypeError(f"violations must be tuple; got {type(self.violations).__name__}")
        if self.property_version != ERUR_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {ERUR_PROPERTY_VERSION!r}; got {self.property_version!r}"
            )

    @property
    def holds(self) -> bool:
        """``True`` iff ERUR-v1 holds for every cycle in the MCAP."""
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _calibrated_stamp(c: CalibratedSelfAssessment) -> int:
    return c.raw_assessment.belief_stamp_sim_ns


def _actuation_stamp(a: ActuationDirective) -> int:
    return a.directive_stamp_sim_ns


def _precondition_holds(
    c: CalibratedSelfAssessment,
    *,
    min_outcomes: int,
    downgrade_threshold: int,
) -> bool:
    """Evaluate ERUR-v1's precondition for one calibrated assessment.

    Two-conjunct AND: ``H_t`` is drift-clean AND ``raw_t.overall_level
    == KNOWN``. ``drift_clean`` is the literal negation of BAUD-v1's
    precondition expanded by De Morgan: the calibrator's downgrade
    condition does NOT fire on ``H_t``, i.e.
    ``outcomes_considered < M  OR  count_beyond_3_or_worse < K``.

    Including the ``outcomes_considered < M`` disjunct closes the
    semantic gap where the K threshold is reached before the M-guard
    is satisfied: in those cycles the calibrator passes through (no
    downgrade), so ERUR's claim must fire even though
    ``count_beyond_3_or_worse >= K``.
    """
    h = c.calibration_history
    beyond_3_or_worse = h.count_beyond_3_std + h.count_beyond_5_std
    drift_clean = h.outcomes_considered < min_outcomes or beyond_3_or_worse < downgrade_threshold
    raw_known = c.raw_assessment.overall_level is SelfAssessmentLevel.KNOWN
    return drift_clean and raw_known


def _check_postconditions(
    c: CalibratedSelfAssessment,
    a: ActuationDirective | None,
    *,
    stamp: int,
    cycle_index: int,
) -> list[ERURViolation]:
    """Evaluate ERUR-v1 postconditions for one cycle whose precondition
    already held. Returns one ``ERURViolation`` per failed postcondition.
    """
    h = c.calibration_history
    beyond_3_or_worse = h.count_beyond_3_std + h.count_beyond_5_std
    base_kwargs: dict[str, int] = {
        "cycle_stamp_sim_ns": stamp,
        "cycle_index": cycle_index,
        "precondition_outcomes_considered": h.outcomes_considered,
        "precondition_beyond_3_or_worse": beyond_3_or_worse,
    }
    out: list[ERURViolation] = []

    # Postcondition 1: adjusted level is exactly KNOWN.
    if c.adjusted_overall_level is not SelfAssessmentLevel.KNOWN:
        out.append(
            ERURViolation(
                kind=ERURViolationKind.ADJUSTED_LEVEL_NOT_KNOWN,
                observed=(
                    f"adjusted_overall_level={c.adjusted_overall_level.value!r} "
                    f"under policy {c.adjustment_policy_id!r}; expected KNOWN"
                ),
                **base_kwargs,
            )
        )

    # Postcondition 2 requires the actuation record.
    if a is None:
        out.append(
            ERURViolation(
                kind=ERURViolationKind.MISSING_ACTUATION_RECORD,
                observed=(
                    f"no ActuationDirective at stamp_sim_ns={stamp}; cannot verify postcondition 2"
                ),
                **base_kwargs,
            )
        )
        return out

    # Postcondition 2: decision kind is exactly PROCEED.
    if a.decision.kind is not DecisionKind.PROCEED:
        out.append(
            ERURViolation(
                kind=ERURViolationKind.DECISION_KIND_NOT_PROCEED,
                observed=(
                    f"decision.kind={a.decision.kind.value!r} "
                    f"reason={a.decision.reason!r}; expected PROCEED"
                ),
                **base_kwargs,
            )
        )

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_erur(
    mcap_path: Path,
    *,
    min_outcomes: int = _DEFAULT_MIN_OUTCOMES,
    downgrade_threshold: int = _DEFAULT_DOWNGRADE_THRESHOLD,
) -> ERURVerificationReport:
    """Verify ADR-0032 (ERUR-v1) against a captured MCAP.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference pipeline.
        Channels ``/self_assessment/calibrated`` and ``/actuations`` must
        be present for the verifier to evaluate any cycle.
    min_outcomes
        ``M`` parameter. Drift-clean is the literal De Morgan negation
        of BAUD-v1's precondition: ``outcomes_considered < M  OR
        count_beyond_3_or_worse < K``. Both M and K appear in ERUR's
        precondition so that cycles where K is reached before M's
        sample-size guard kicks in remain covered. Default mirrors
        :class:`MahalanobisDowngradePolicy` default.
    downgrade_threshold
        ``K`` parameter; see ``min_outcomes`` above for the full
        drift-clean condition.

    Returns
    -------
    ERURVerificationReport
        ``report.holds`` is ``True`` iff the property held for every
        cycle where its precondition fired.

    Raises
    ------
    ValueError
        If ``min_outcomes < 0`` or ``downgrade_threshold < 1``.
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    """
    if min_outcomes < 0:
        raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
    if downgrade_threshold < 1:
        raise ValueError(f"downgrade_threshold must be >= 1; got {downgrade_threshold}")

    mcap_sha = hashlib.sha256(mcap_path.read_bytes()).hexdigest()

    calibrated_by_stamp: dict[int, CalibratedSelfAssessment] = {}
    calibrated_order: list[int] = []
    actuation_by_stamp: dict[int, ActuationDirective] = {}

    with MCAPReplayReader(mcap_path) as reader:
        for msg in reader.iter_messages():
            if msg.channel == CHANNEL_CALIBRATED_SELF_ASSESSMENT:
                c = decode_message(msg)
                if not isinstance(c, CalibratedSelfAssessment):
                    continue
                stamp = _calibrated_stamp(c)
                if stamp not in calibrated_by_stamp:
                    calibrated_order.append(stamp)
                calibrated_by_stamp[stamp] = c
            elif msg.channel == CHANNEL_ACTUATIONS:
                a = decode_message(msg)
                if not isinstance(a, ActuationDirective):
                    continue
                actuation_by_stamp[_actuation_stamp(a)] = a

    violations: list[ERURViolation] = []
    cycles_precondition_held = 0
    first_precondition_stamp: int | None = None

    for cycle_index, stamp in enumerate(calibrated_order):
        c = calibrated_by_stamp[stamp]
        if not _precondition_holds(
            c,
            min_outcomes=min_outcomes,
            downgrade_threshold=downgrade_threshold,
        ):
            continue

        cycles_precondition_held += 1
        if first_precondition_stamp is None:
            first_precondition_stamp = stamp

        violations.extend(
            _check_postconditions(
                c,
                actuation_by_stamp.get(stamp),
                stamp=stamp,
                cycle_index=cycle_index,
            )
        )

    return ERURVerificationReport(
        mcap_sha256=mcap_sha,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        property_version=ERUR_PROPERTY_VERSION,
        cycles_total=len(calibrated_order),
        cycles_precondition_held=cycles_precondition_held,
        first_precondition_cycle_stamp_sim_ns=first_precondition_stamp,
        violations=tuple(violations),
    )
