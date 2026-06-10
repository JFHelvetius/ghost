"""ADR-0035 — False Positive Bound property verifier (FPB-v1).

Fifth property of the set (BAUD, ERUR, MD, RLB, FPB). Unlike the four
qualitative pass/fail verifiers, FPB-v1 is **quantitative
observational**: it measures the empirical fraction of cycles where
BAUD-v1's precondition fires, and compares that fraction against a
caller-provided ``max_fire_fraction``.

By default (``max_fire_fraction=1.0``) FPB-v1 is purely an observer
and never fails — it just reports the rate. Useful in CI to detect
regressions in BAUD sensitivity.

Configured with a tighter bound, FPB-v1 becomes a regression gate.

The property statement, scope, and verification plan live in
``docs/adr/0035-false-positive-bound-property-v1.md``.

Stdlib only at runtime modulo the ``mcap`` extra.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.telemetry import (
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


FPB_PROPERTY_VERSION: Final[str] = "FPB-v1"

_DEFAULT_MIN_OUTCOMES: Final[int] = 4
_DEFAULT_DOWNGRADE_THRESHOLD: Final[int] = 2
_DEFAULT_MAX_FIRE_FRACTION: Final[float] = 1.0

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


class FPBViolationKind(StrEnum):
    """Closed catalogue of how a verification can violate FPB-v1."""

    FIRE_FRACTION_EXCEEDS_BOUND = "fire_fraction_exceeds_bound"


@dataclass(frozen=True)
class FPBViolation:
    """Emitted once if the observed fire fraction exceeds the bound."""

    kind: FPBViolationKind
    observed_fire_fraction: float
    max_fire_fraction: float
    cycles_baud_fires: int
    cycles_total: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FPBViolationKind):
            raise TypeError(f"kind must be FPBViolationKind; got {type(self.kind).__name__}")
        if not (0.0 <= self.observed_fire_fraction <= 1.0) or math.isnan(
            self.observed_fire_fraction
        ):
            raise ValueError(
                f"observed_fire_fraction must be in [0.0, 1.0]; got {self.observed_fire_fraction}"
            )
        if not (0.0 <= self.max_fire_fraction <= 1.0) or math.isnan(self.max_fire_fraction):
            raise ValueError(
                f"max_fire_fraction must be in [0.0, 1.0]; got {self.max_fire_fraction}"
            )
        if self.cycles_baud_fires < 0:
            raise ValueError(f"cycles_baud_fires must be >= 0; got {self.cycles_baud_fires}")
        if self.cycles_total <= 0:
            raise ValueError(f"cycles_total must be > 0 for a violation; got {self.cycles_total}")


@dataclass(frozen=True)
class FPBVerificationReport:
    """Output of :func:`verify_fpb`.

    ``fire_fraction`` is the observed rate at which BAUD-v1's
    precondition fires across the MCAP. ``holds`` is the comparison
    of that observed rate against ``max_fire_fraction``. With the
    default ``max_fire_fraction=1.0`` the report is purely
    observational and always holds.
    """

    mcap_sha256: str
    min_outcomes: int
    downgrade_threshold: int
    max_fire_fraction: float
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    fire_fraction: float
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[FPBViolation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:  # noqa: PLR0912 — invariants on
        # eight fields including a derived numeric one (fire_fraction
        # must equal cycles_fires/cycles_total); each branch is a
        # distinct dataclass invariant. Splitting them into helpers
        # would lose locality without reducing total complexity.
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
        if not (0.0 <= self.max_fire_fraction <= 1.0) or math.isnan(self.max_fire_fraction):
            raise ValueError(
                f"max_fire_fraction must be in [0.0, 1.0]; got {self.max_fire_fraction}"
            )
        if self.cycles_total < 0:
            raise ValueError(f"cycles_total must be >= 0; got {self.cycles_total}")
        if not 0 <= self.cycles_precondition_held <= self.cycles_total:
            raise ValueError(
                "cycles_precondition_held must be in "
                f"[0, cycles_total={self.cycles_total}]; got "
                f"{self.cycles_precondition_held}"
            )
        # fire_fraction must equal cycles_baud_fires/cycles_total
        # (or 0.0 when cycles_total == 0).
        if self.cycles_total == 0:
            expected = 0.0
        else:
            expected = self.cycles_precondition_held / self.cycles_total
        if not math.isclose(self.fire_fraction, expected):
            raise ValueError(
                "fire_fraction must equal cycles_precondition_held / "
                f"cycles_total = {expected}; got {self.fire_fraction}"
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
        if self.property_version != FPB_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {FPB_PROPERTY_VERSION!r}; got {self.property_version!r}"
            )

    @property
    def holds(self) -> bool:
        return self.fire_fraction <= self.max_fire_fraction


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _baud_precondition_fires(
    c: CalibratedSelfAssessment,
    *,
    min_outcomes: int,
    downgrade_threshold: int,
) -> bool:
    """Re-evaluate BAUD-v1's precondition on a single calibrated
    assessment. Identical to the calibration policy's downgrade
    condition.
    """
    h = c.calibration_history
    beyond_3_or_worse = h.count_beyond_3_std + h.count_beyond_5_std
    return h.outcomes_considered >= min_outcomes and beyond_3_or_worse >= downgrade_threshold


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_fpb(
    mcap_path: Path,
    *,
    min_outcomes: int = _DEFAULT_MIN_OUTCOMES,
    downgrade_threshold: int = _DEFAULT_DOWNGRADE_THRESHOLD,
    max_fire_fraction: float = _DEFAULT_MAX_FIRE_FRACTION,
) -> FPBVerificationReport:
    """Measure BAUD-v1's empirical fire fraction over an MCAP.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference pipeline.
    min_outcomes
        ``M`` parameter of BAUD's precondition.
    downgrade_threshold
        ``K`` parameter of BAUD's precondition.
    max_fire_fraction
        Upper bound on the observed fire fraction. Default ``1.0``
        makes the verifier purely observational (always holds).
        Tighter values turn it into a regression gate.

    Returns
    -------
    FPBVerificationReport
        ``report.holds`` is ``True`` iff
        ``report.fire_fraction <= max_fire_fraction``. The report
        carries the observed fraction unconditionally.

    Raises
    ------
    ValueError
        If parameter values are out of range.
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    """
    if min_outcomes < 0:
        raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
    if downgrade_threshold < 1:
        raise ValueError(f"downgrade_threshold must be >= 1; got {downgrade_threshold}")
    if not (0.0 <= max_fire_fraction <= 1.0) or math.isnan(max_fire_fraction):
        raise ValueError(f"max_fire_fraction must be in [0.0, 1.0]; got {max_fire_fraction}")

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

    cycles_total = len(calibrated_order)
    cycles_fires = 0
    first_fire_stamp: int | None = None

    for stamp in calibrated_order:
        c = calibrated_by_stamp[stamp]
        if _baud_precondition_fires(
            c,
            min_outcomes=min_outcomes,
            downgrade_threshold=downgrade_threshold,
        ):
            cycles_fires += 1
            if first_fire_stamp is None:
                first_fire_stamp = stamp

    fire_fraction = cycles_fires / cycles_total if cycles_total > 0 else 0.0

    violations: tuple[FPBViolation, ...] = ()
    if fire_fraction > max_fire_fraction and cycles_total > 0:
        violations = (
            FPBViolation(
                kind=FPBViolationKind.FIRE_FRACTION_EXCEEDS_BOUND,
                observed_fire_fraction=fire_fraction,
                max_fire_fraction=max_fire_fraction,
                cycles_baud_fires=cycles_fires,
                cycles_total=cycles_total,
            ),
        )

    return FPBVerificationReport(
        mcap_sha256=mcap_sha,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        max_fire_fraction=max_fire_fraction,
        property_version=FPB_PROPERTY_VERSION,
        cycles_total=cycles_total,
        cycles_precondition_held=cycles_fires,
        fire_fraction=fire_fraction,
        first_precondition_cycle_stamp_sim_ns=first_fire_stamp,
        violations=violations,
    )
