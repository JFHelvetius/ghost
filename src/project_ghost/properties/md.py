"""ADR-0033 — Monotonic Degradation property verifier (MD-v1).

Third of the property trio (BAUD, ERUR, MD). Where BAUD and ERUR are
conditional behavioural properties of the policy pair, MD is an
**unconditional structural** property of the reference calibration
policy alone: the adjusted overall level is never strictly more
confident than the raw overall level.

The property statement, scope, and verification plan live in
``docs/adr/0033-monotonic-degradation-property-v1.md``. Read the ADR
before reading this module.

Stdlib only at runtime modulo the ``mcap`` extra. Pure, deterministic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.uncertainty.self_assessment import (
    SelfAssessmentLevel,
)
from project_ghost.telemetry import (
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


MD_PROPERTY_VERSION: Final[str] = "MD-v1"

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")

# Numerification of ``SelfAssessmentLevel`` for the monotonicity test.
# KNOWN < UNCERTAIN < UNKNOWN under the ADR-0020 lattice; higher number
# means less confidence. MD-v1 asserts ``adjusted_num >= raw_num``.
_LEVEL_NUM: Final[dict[SelfAssessmentLevel, int]] = {
    SelfAssessmentLevel.KNOWN: 0,
    SelfAssessmentLevel.UNCERTAIN: 1,
    SelfAssessmentLevel.UNKNOWN: 2,
}


class MDViolationKind(StrEnum):
    """Closed catalogue of how a single cycle can violate MD-v1."""

    # The only postcondition. Named to mirror BAUD/ERUR violation kinds
    # in structure: action verb at the end describes what was wrong.
    ADJUSTED_LEVEL_MORE_CONFIDENT_THAN_RAW = "adjusted_level_more_confident_than_raw"


@dataclass(frozen=True)
class MDViolation:
    """One cycle, one violated postcondition.

    ``raw_level`` and ``adjusted_level`` are the observed strings so the
    violation report self-describes the lattice direction that failed.
    """

    cycle_stamp_sim_ns: int
    cycle_index: int
    kind: MDViolationKind
    raw_level: str
    adjusted_level: str
    adjustment_policy_id: str

    def __post_init__(self) -> None:
        if self.cycle_stamp_sim_ns < 0:
            raise ValueError(f"cycle_stamp_sim_ns must be >= 0; got {self.cycle_stamp_sim_ns}")
        if self.cycle_index < 0:
            raise ValueError(f"cycle_index must be >= 0; got {self.cycle_index}")
        if not isinstance(self.kind, MDViolationKind):
            raise TypeError(f"kind must be MDViolationKind; got {type(self.kind).__name__}")
        for f, name in (
            (self.raw_level, "raw_level"),
            (self.adjusted_level, "adjusted_level"),
            (self.adjustment_policy_id, "adjustment_policy_id"),
        ):
            if not isinstance(f, str):
                raise TypeError(f"{name} must be str; got {type(f).__name__}")


@dataclass(frozen=True)
class MDVerificationReport:
    """Output of :func:`verify_md`.

    Field shape is structurally parallel to BAUD and ERUR reports so
    consumers can build symmetric code paths. ``cycles_precondition_held``
    is always equal to ``cycles_total`` for MD-v1 because the property
    has no precondition — kept for shape parity.
    """

    mcap_sha256: str
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[MDViolation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.mcap_sha256) != _SHA256_HEX_LEN or not all(
            c in _HEX_CHARS for c in self.mcap_sha256
        ):
            raise ValueError(
                f"mcap_sha256 must be {_SHA256_HEX_LEN} lowercase hex "
                f"chars; got {self.mcap_sha256!r}"
            )
        if self.cycles_total < 0:
            raise ValueError(f"cycles_total must be >= 0; got {self.cycles_total}")
        if self.cycles_precondition_held != self.cycles_total:
            raise ValueError(
                "MD-v1 has no precondition: cycles_precondition_held "
                f"must equal cycles_total ({self.cycles_total}); got "
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
        if self.cycles_total == 0:
            if self.first_precondition_cycle_stamp_sim_ns is not None:
                raise ValueError(
                    "first_precondition_cycle_stamp_sim_ns must be None when cycles_total == 0"
                )
        elif self.first_precondition_cycle_stamp_sim_ns is None:
            raise ValueError(
                "first_precondition_cycle_stamp_sim_ns must be set when cycles_total > 0"
            )
        if not isinstance(self.violations, tuple):
            raise TypeError(f"violations must be tuple; got {type(self.violations).__name__}")
        if self.property_version != MD_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {MD_PROPERTY_VERSION!r}; got {self.property_version!r}"
            )

    @property
    def holds(self) -> bool:
        """``True`` iff MD-v1 holds for every cycle in the MCAP."""
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_md(mcap_path: Path) -> MDVerificationReport:
    """Verify ADR-0033 (MD-v1) against a captured MCAP.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference pipeline.
        Only ``/self_assessment/calibrated`` is needed — MD-v1 is
        structural, no actuations consulted.

    Returns
    -------
    MDVerificationReport
        ``report.holds`` is ``True`` iff the property held for every
        cycle. A violation indicates the calibration policy emitted an
        ``adjusted_overall_level`` strictly more confident than the
        raw — i.e. it *created* confidence. For the reference policy
        ``MahalanobisDowngradePolicy`` this never happens by
        construction; a violation would mean either a bug in the
        reference or that the MCAP was produced by a non-reference
        policy.

    Raises
    ------
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    """
    mcap_sha = hashlib.sha256(mcap_path.read_bytes()).hexdigest()

    calibrated_by_stamp: dict[int, CalibratedSelfAssessment] = {}
    calibrated_order: list[int] = []

    with MCAPReplayReader(mcap_path) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_CALIBRATED_SELF_ASSESSMENT:
                continue
            c = decode_message(msg)
            if not isinstance(c, CalibratedSelfAssessment):
                continue
            stamp = c.raw_assessment.belief_stamp_sim_ns
            if stamp not in calibrated_by_stamp:
                calibrated_order.append(stamp)
            calibrated_by_stamp[stamp] = c

    violations: list[MDViolation] = []
    first_stamp: int | None = calibrated_order[0] if calibrated_order else None

    for cycle_index, stamp in enumerate(calibrated_order):
        c = calibrated_by_stamp[stamp]
        raw_num = _LEVEL_NUM[c.raw_assessment.overall_level]
        adj_num = _LEVEL_NUM[c.adjusted_overall_level]
        if adj_num < raw_num:
            violations.append(
                MDViolation(
                    cycle_stamp_sim_ns=stamp,
                    cycle_index=cycle_index,
                    kind=MDViolationKind.ADJUSTED_LEVEL_MORE_CONFIDENT_THAN_RAW,
                    raw_level=c.raw_assessment.overall_level.value,
                    adjusted_level=c.adjusted_overall_level.value,
                    adjustment_policy_id=c.adjustment_policy_id,
                )
            )

    return MDVerificationReport(
        mcap_sha256=mcap_sha,
        property_version=MD_PROPERTY_VERSION,
        cycles_total=len(calibrated_order),
        cycles_precondition_held=len(calibrated_order),
        first_precondition_cycle_stamp_sim_ns=first_stamp,
        violations=tuple(violations),
    )
