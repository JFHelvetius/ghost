"""ADR-0034 — Recovery Latency Bound property verifier (RLB-v1).

Fourth of the property set (BAUD, ERUR, MD, RLB). The first one that
is **multi-cycle**: it watches the chronological transition from
dirty cycles (history contains over-threshold outcomes) to clean
cycles (history is fully clean) and bounds the dirty-run length by
the window size ``W`` used by ``build_calibration_history``.

Stateless calibrator + windowed history builder = recovery happens
at most W cycles after the last over-threshold outcome enters the
window. RLB-v1 makes that bound explicit and verifiable.

The property statement, scope, and verification plan live in
``docs/adr/0034-recovery-latency-bound-property-v1.md``.

Stdlib only at runtime modulo the ``mcap`` extra.
"""

from __future__ import annotations

import hashlib
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


RLB_PROPERTY_VERSION: Final[str] = "RLB-v1"

# Default mirrors the smoke's `assess_with_feedback(..., max_history=32)`.
_DEFAULT_MAX_HISTORY: Final[int] = 32

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


class RLBViolationKind(StrEnum):
    """Closed catalogue of how a recovery transition can violate RLB-v1."""

    # The only postcondition: the dirty-run length preceding a recovery
    # transition exceeds W.
    DIRTY_RUN_EXCEEDS_WINDOW = "dirty_run_exceeds_window"


@dataclass(frozen=True)
class RLBViolation:
    """One recovery transition where ``L(t) > peak + W - 1``."""

    cycle_stamp_sim_ns: int  # the clean cycle (recovery)
    cycle_index: int  # its 0-based ordinal
    kind: RLBViolationKind
    dirty_run_length: int  # observed L(t)
    peak_count: int  # peak(t) observed during the run
    max_history: int  # the W parameter
    bound: int  # the bound that was violated

    def __post_init__(self) -> None:
        if self.cycle_stamp_sim_ns < 0:
            raise ValueError(f"cycle_stamp_sim_ns must be >= 0; got {self.cycle_stamp_sim_ns}")
        if self.cycle_index < 0:
            raise ValueError(f"cycle_index must be >= 0; got {self.cycle_index}")
        if not isinstance(self.kind, RLBViolationKind):
            raise TypeError(f"kind must be RLBViolationKind; got {type(self.kind).__name__}")
        if self.dirty_run_length <= 0:
            raise ValueError(f"dirty_run_length must be > 0; got {self.dirty_run_length}")
        if self.peak_count <= 0:
            raise ValueError(f"peak_count must be > 0; got {self.peak_count}")
        if self.max_history < 0:
            raise ValueError(f"max_history must be >= 0; got {self.max_history}")


@dataclass(frozen=True)
class RLBVerificationReport:
    """Output of :func:`verify_rlb`.

    ``cycles_precondition_held`` is the number of recovery transitions
    observed (dirty → clean). Under sustained-drift executions like the
    smoke baseline this is zero, and the report holds vacuously.
    """

    mcap_sha256: str
    max_history: int
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[RLBViolation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.mcap_sha256) != _SHA256_HEX_LEN or not all(
            c in _HEX_CHARS for c in self.mcap_sha256
        ):
            raise ValueError(
                f"mcap_sha256 must be {_SHA256_HEX_LEN} lowercase hex "
                f"chars; got {self.mcap_sha256!r}"
            )
        if self.max_history < 0:
            raise ValueError(f"max_history must be >= 0; got {self.max_history}")
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
        if self.property_version != RLB_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {RLB_PROPERTY_VERSION!r}; got {self.property_version!r}"
            )

    @property
    def holds(self) -> bool:
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dirty_count(c: CalibratedSelfAssessment) -> int:
    """Return the dirty count of one cycle: ``count_beyond_3 +
    count_beyond_5``. A cycle is *dirty* when this is > 0, *clean*
    when 0.
    """
    h = c.calibration_history
    return h.count_beyond_3_std + h.count_beyond_5_std


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_rlb(
    mcap_path: Path,
    *,
    max_history: int = _DEFAULT_MAX_HISTORY,
) -> RLBVerificationReport:
    """Verify ADR-0034 (RLB-v1) against a captured MCAP.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference pipeline.
    max_history
        ``W`` parameter — the window size used by
        ``build_calibration_history`` at capture time. Default matches
        the smoke (``W=32``). Passing the wrong W produces a
        mathematically invalid bound; callers must know their pipeline's
        wiring.

    Returns
    -------
    RLBVerificationReport
        ``report.holds`` is ``True`` iff every observed recovery
        transition's pre-recovery dirty run was ``<= W``.

    Raises
    ------
    ValueError
        If ``max_history < 0``.
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    """
    if max_history < 0:
        raise ValueError(f"max_history must be >= 0; got {max_history}")

    mcap_sha = hashlib.sha256(mcap_path.read_bytes()).hexdigest()

    # Read all calibrated assessments in chronological order.
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

    violations: list[RLBViolation] = []
    recovery_transitions = 0
    first_recovery_stamp: int | None = None
    dirty_run = 0
    peak_during_run = 0

    for cycle_index, stamp in enumerate(calibrated_order):
        c = calibrated_by_stamp[stamp]
        count = _dirty_count(c)
        if count > 0:
            dirty_run += 1
            peak_during_run = max(peak_during_run, count)
            continue

        # Clean cycle. Is it a recovery transition?
        if dirty_run > 0:
            recovery_transitions += 1
            if first_recovery_stamp is None:
                first_recovery_stamp = stamp
            bound = peak_during_run + max_history - 1
            if dirty_run > bound:
                violations.append(
                    RLBViolation(
                        cycle_stamp_sim_ns=stamp,
                        cycle_index=cycle_index,
                        kind=RLBViolationKind.DIRTY_RUN_EXCEEDS_WINDOW,
                        dirty_run_length=dirty_run,
                        peak_count=peak_during_run,
                        max_history=max_history,
                        bound=bound,
                    )
                )
        dirty_run = 0
        peak_during_run = 0

    return RLBVerificationReport(
        mcap_sha256=mcap_sha,
        max_history=max_history,
        property_version=RLB_PROPERTY_VERSION,
        cycles_total=len(calibrated_order),
        cycles_precondition_held=recovery_transitions,
        first_precondition_cycle_stamp_sim_ns=first_recovery_stamp,
        violations=tuple(violations),
    )
