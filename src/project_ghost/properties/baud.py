"""ADR-0031 — Bounded Action Under Drift property verifier (BAUD-v1).

This module is the **citable surface** of ADR-0031: third parties (and
this project's own CI) feed any Project Ghost MCAP through
:func:`verify_baud` and obtain a deterministic veredicto about whether
the property holds.

The property statement, scope, and verification plan live in
``docs/adr/0031-bounded-action-under-drift-property-v1.md``. Read that
ADR before reading this module — the dataclasses below are an exact
mechanical translation of the statement, not a re-derivation of it.

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


# Stable identifier — embedded in every report so consumers can branch
# on property version without parsing the report dataclass fields.
BAUD_PROPERTY_VERSION: Final[str] = "BAUD-v1"

# Defaults match ``MahalanobisDowngradePolicy`` defaults so the obvious
# call ``verify_baud(path)`` checks the property against the reference
# policy configuration. Operators with custom params must pass them
# explicitly — there is no auto-detection from the MCAP itself, since
# the property is intentionally parametric.
_DEFAULT_MIN_OUTCOMES: Final[int] = 4
_DEFAULT_DOWNGRADE_THRESHOLD: Final[int] = 2

# SHA-256 hex digest length; mirrors the same constant used in
# ``project_ghost.core.decisions.types`` for consistency.
_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")

# Closed set of ``ActuationDirective.reason`` strings that BAUD-v1
# recognises as safe-for-non-proceed. See ADR-0031 §1.1 for the
# justification of each entry. Extending this set requires an explicit
# ADR amendment — never widen it from code without one.
_S_BAUD_V1_SAFE_REASONS: Final[frozenset[str]] = frozenset(
    {
        # ADR-0029: identity attitude + bounded thrust under HOLD.
        "attitude_hold_hold",
        # ADR-0029: zero throttle DirectMotorCommand under ENGAGE_KILL.
        "kill_zero_throttle",
    }
)


class BAUDViolationKind(StrEnum):
    """Closed catalogue of how a single cycle can violate BAUD-v1.

    Each kind corresponds to one of the three postconditions in the
    property statement, plus one structural failure (the actuation
    record expected at the cycle stamp is missing). Snake_case names so
    consumers can stably switch on the value across versions.
    """

    # Postcondition 1: ``C_t.adjusted_overall_level != KNOWN``.
    ADJUSTED_LEVEL_KNOWN = "adjusted_level_known"

    # Postcondition 2: ``A_t.decision.kind != PROCEED``.
    DECISION_KIND_PROCEED = "decision_kind_proceed"

    # Postcondition 3: when the decision is not PROCEED and the
    # actuator_command is non-None, the actuation reason must be in
    # the registered safe set ``_S_BAUD_V1_SAFE_REASONS``.
    UNSAFE_ACTUATOR_REASON = "unsafe_actuator_reason"

    # Structural: the MCAP contained a CalibratedSelfAssessment whose
    # precondition held, but no ActuationDirective at the matching
    # stamp. The property cannot be evaluated for postconditions 2/3
    # in that cycle, so the verifier reports a violation rather than
    # silently passing.
    MISSING_ACTUATION_RECORD = "missing_actuation_record"


@dataclass(frozen=True)
class BAUDViolation:
    """One cycle, one violated postcondition.

    A single cycle may produce multiple violations (e.g. both
    ``ADJUSTED_LEVEL_KNOWN`` and ``DECISION_KIND_PROCEED``). Each is
    reported separately so the cause is unambiguous.
    """

    cycle_stamp_sim_ns: int
    cycle_index: int
    kind: BAUDViolationKind
    observed: str
    precondition_outcomes_considered: int
    precondition_beyond_3_or_worse: int

    def __post_init__(self) -> None:
        if self.cycle_stamp_sim_ns < 0:
            raise ValueError(f"cycle_stamp_sim_ns must be >= 0; got {self.cycle_stamp_sim_ns}")
        if self.cycle_index < 0:
            raise ValueError(f"cycle_index must be >= 0; got {self.cycle_index}")
        if not isinstance(self.kind, BAUDViolationKind):
            raise TypeError(f"kind must be BAUDViolationKind; got {type(self.kind).__name__}")
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
class BAUDVerificationReport:
    """Output of :func:`verify_baud`.

    ``holds`` is the boolean veredicto. ``mcap_sha256`` content-addresses
    the exact bytes that were verified — quoting the report without the
    hash is meaningless because two MCAPs can structurally agree and
    disagree byte-for-byte.

    The numeric fields make the report self-describing in CI logs:
    ``cycles_total`` is the denominator, ``cycles_precondition_held`` is
    how many of those triggered evaluation, ``violations`` is the list
    that ``holds`` reduces over.
    """

    mcap_sha256: str
    min_outcomes: int
    downgrade_threshold: int
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[BAUDViolation, ...] = field(default_factory=tuple)

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
        if self.property_version != BAUD_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {BAUD_PROPERTY_VERSION!r}; got {self.property_version!r}"
            )

    @property
    def holds(self) -> bool:
        """``True`` iff BAUD-v1 holds for every cycle in the MCAP."""
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _calibrated_stamp(c: CalibratedSelfAssessment) -> int:
    """Cycle stamp used to correlate a calibrated assessment with an
    actuation. Per ADR-0027 this is the raw belief stamp.
    """
    return c.raw_assessment.belief_stamp_sim_ns


def _actuation_stamp(a: ActuationDirective) -> int:
    """Cycle stamp of an actuation. Per ADR-0023 directive stamp equals
    the embedded decision stamp.
    """
    return a.directive_stamp_sim_ns


def _precondition_holds(
    c: CalibratedSelfAssessment,
    *,
    min_outcomes: int,
    downgrade_threshold: int,
) -> bool:
    """Evaluate the BAUD-v1 precondition for one calibrated assessment.

    Mirrors :class:`MahalanobisDowngradePolicy` exactly: the precondition
    is *the same condition* the reference calibration policy uses to
    decide to downgrade. That parity is intentional — the property is
    that the reference policy actually does what the precondition
    implies.
    """
    h = c.calibration_history
    beyond_3_or_worse = h.count_beyond_3_std + h.count_beyond_5_std
    return h.outcomes_considered >= min_outcomes and beyond_3_or_worse >= downgrade_threshold


def _check_postconditions(
    c: CalibratedSelfAssessment,
    a: ActuationDirective | None,
    *,
    stamp: int,
    cycle_index: int,
) -> list[BAUDViolation]:
    """Evaluate BAUD-v1 postconditions for one cycle whose precondition
    already held. Returns one ``BAUDViolation`` per failed postcondition;
    empty list means the cycle is BAUD-clean.

    Extracted from :func:`verify_baud` so the main entry-point stays
    flat. The decision rule is exactly the four-way switch in ADR-0031
    §1: level → decision → command, plus the structural fallback when
    no actuation is at the expected stamp.
    """
    h = c.calibration_history
    beyond_3_or_worse = h.count_beyond_3_std + h.count_beyond_5_std
    base_kwargs: dict[str, int] = {
        "cycle_stamp_sim_ns": stamp,
        "cycle_index": cycle_index,
        "precondition_outcomes_considered": h.outcomes_considered,
        "precondition_beyond_3_or_worse": beyond_3_or_worse,
    }
    out: list[BAUDViolation] = []

    # Postcondition 1: adjusted level is not KNOWN.
    if c.adjusted_overall_level is SelfAssessmentLevel.KNOWN:
        out.append(
            BAUDViolation(
                kind=BAUDViolationKind.ADJUSTED_LEVEL_KNOWN,
                observed=(
                    f"adjusted_overall_level={c.adjusted_overall_level.value!r} "
                    f"under policy {c.adjustment_policy_id!r}"
                ),
                **base_kwargs,
            )
        )

    # Postconditions 2 and 3 require the actuation record.
    if a is None:
        out.append(
            BAUDViolation(
                kind=BAUDViolationKind.MISSING_ACTUATION_RECORD,
                observed=(
                    f"no ActuationDirective at stamp_sim_ns={stamp}; "
                    "cannot verify postconditions 2/3"
                ),
                **base_kwargs,
            )
        )
        return out

    # Postcondition 2: decision kind is not PROCEED. If it IS PROCEED,
    # postcondition 3 is moot (PROCEED legitimately carries any command
    # under the reference action emission contract) — skip 3 to avoid
    # double-reporting.
    if a.decision.kind is DecisionKind.PROCEED:
        out.append(
            BAUDViolation(
                kind=BAUDViolationKind.DECISION_KIND_PROCEED,
                observed=(f"decision.kind={a.decision.kind.value!r} reason={a.decision.reason!r}"),
                **base_kwargs,
            )
        )
        return out

    # Postcondition 3: if actuator_command is non-None, its reason must
    # be in the BAUD-v1 safe set (ADR-0031 §1.1). ``None`` is always
    # safe — no command, no harm.
    if a.actuator_command is not None and a.reason not in _S_BAUD_V1_SAFE_REASONS:
        out.append(
            BAUDViolation(
                kind=BAUDViolationKind.UNSAFE_ACTUATOR_REASON,
                observed=(
                    f"actuator_command={type(a.actuator_command).__name__} "
                    f"emitted while decision.kind={a.decision.kind.value!r} "
                    f"(non-PROCEED) with reason={a.reason!r} not in "
                    f"S_baud_v1={sorted(_S_BAUD_V1_SAFE_REASONS)!r}"
                ),
                **base_kwargs,
            )
        )

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_baud(
    mcap_path: Path,
    *,
    min_outcomes: int = _DEFAULT_MIN_OUTCOMES,
    downgrade_threshold: int = _DEFAULT_DOWNGRADE_THRESHOLD,
) -> BAUDVerificationReport:
    """Verify ADR-0031 (BAUD-v1) against a captured MCAP.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference pipeline.
        Channels ``/self_assessment/calibrated`` and ``/actuations`` must
        be present for the verifier to evaluate any cycle; their absence
        produces an empty (trivially-holding) report.
    min_outcomes
        The ``M`` parameter of the BAUD-v1 precondition. Default mirrors
        :class:`MahalanobisDowngradePolicy` default.
    downgrade_threshold
        The ``K`` parameter of the BAUD-v1 precondition. Default mirrors
        :class:`MahalanobisDowngradePolicy` default.

    Returns
    -------
    BAUDVerificationReport
        ``report.holds`` is ``True`` iff the property held for every
        cycle where its precondition fired. The full violation list is
        in ``report.violations``.

    Raises
    ------
    ValueError
        If ``min_outcomes < 0`` or ``downgrade_threshold < 1``. Mirrors
        :class:`MahalanobisDowngradePolicy` input validation.
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    """
    if min_outcomes < 0:
        raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
    if downgrade_threshold < 1:
        raise ValueError(f"downgrade_threshold must be >= 1; got {downgrade_threshold}")

    mcap_sha = hashlib.sha256(mcap_path.read_bytes()).hexdigest()

    # Build per-channel indexes keyed by cycle stamp. We use the
    # belief stamp as the join key (ADR-0027 invariant guarantees both
    # records share it).
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

    violations: list[BAUDViolation] = []
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

    return BAUDVerificationReport(
        mcap_sha256=mcap_sha,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        property_version=BAUD_PROPERTY_VERSION,
        cycles_total=len(calibrated_order),
        cycles_precondition_held=cycles_precondition_held,
        first_precondition_cycle_stamp_sim_ns=first_precondition_stamp,
        violations=tuple(violations),
    )
