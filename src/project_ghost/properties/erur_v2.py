"""ADR-0040 — ERUR-v2 (policy-parametric) property verifier.

Policy-parametric lifting of ERUR-v1
(:mod:`project_ghost.properties.erur`). Where v1 evaluates the
precondition using the *reference* count-of-K-in-W rule with fixed
``(M, K)`` parameters, v2 delegates the precondition to each
policy's own drift criterion via the
:class:`~project_ghost.core.feedback.protocols.DriftPreconditionProvider`
Protocol.

**Semantics.** A cycle's precondition holds iff (i) the raw belief
is KNOWN and (ii) the policy that produced the calibrated
assessment reports its own drift criterion as *absent* on the
recorded calibration history. The postcondition is identical to
v1: the adjusted level must be KNOWN and the emitted decision
must be PROCEED.

**Verifier-side dispatch.** v2 is a pure function over the MCAP
plus a caller-supplied ``Mapping[policy_id, drift_predicate]``.
The verifier looks up ``adjustment_policy_id`` from each MCAP
record and dispatches to the matching predicate. Unknown
``adjustment_policy_id`` is a verifier-level error
(:class:`UnknownPolicyError`) — the caller must register every
policy whose output appears in the MCAP. This dispatch design
keeps the verifier pure (the predicates are *input*, not state)
while letting the producer choose any calibrator without rewriting
``verify_erur``.

**Backward compatibility.** v1 (``verify_erur``) is unchanged.
MCAPs produced before ADR-0040 land verify identically under v1;
v2 is opt-in.

**Paper §3.2 / §8.4 (long), §4 / Appendix C.3 (short).** The
discrepancy between v1 and v2 verdicts on EWMA and PerAxis
calibrators is what makes the lifting operationally meaningful:
v1 reports VIOLATED because the alternatives do not behave like
the reference, v2 reports HOLDS because each alternative behaves
correctly under its own contract.

Stdlib only at runtime modulo the ``mcap`` extra. Pure,
deterministic, no clock, no random.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from project_ghost.core.actuation.types import ActuationDirective
from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.uncertainty.self_assessment import SelfAssessmentLevel
from project_ghost.properties.erur import (
    ERURViolation,
    _actuation_stamp,
    _calibrated_stamp,
    _check_postconditions,
)
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from project_ghost.core.feedback.types import CalibrationHistory


ERUR_V2_PROPERTY_VERSION: Final[str] = "ERUR-v2"

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


class UnknownPolicyError(LookupError):
    """Raised when an MCAP record names an ``adjustment_policy_id``
    not present in the caller-supplied predicate mapping.

    Distinguished from generic ``KeyError`` so that callers (CI
    jobs, scripts) can show an actionable message: "this MCAP was
    produced under policy X; register X's drift_precondition before
    running verify_erur_v2."
    """


@dataclass(frozen=True)
class ERURv2VerificationReport:
    """Output of :func:`verify_erur_v2`.

    Field shape mirrors :class:`ERURVerificationReport` (v1) so a
    consumer that handles v1 can handle v2 with one extra field
    (``policies_dispatched``) and the relaxed property-version
    string.

    ``policies_dispatched`` records every distinct
    ``adjustment_policy_id`` observed in the MCAP, in the order it
    first appeared. Useful both for human inspection and for
    asserting that the caller registered every policy required.
    """

    mcap_sha256: str
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    first_precondition_cycle_stamp_sim_ns: int | None
    policies_dispatched: tuple[str, ...] = field(default_factory=tuple)
    violations: tuple[ERURViolation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.mcap_sha256) != _SHA256_HEX_LEN or not all(
            c in _HEX_CHARS for c in self.mcap_sha256
        ):
            raise ValueError(
                f"mcap_sha256 must be {_SHA256_HEX_LEN} lowercase hex "
                f"chars; got {self.mcap_sha256!r}"
            )
        if self.property_version != ERUR_V2_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {ERUR_V2_PROPERTY_VERSION!r}; "
                f"got {self.property_version!r}"
            )
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
                f"None; got {self.first_precondition_cycle_stamp_sim_ns}"
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
        if not isinstance(self.policies_dispatched, tuple):
            raise TypeError(
                f"policies_dispatched must be tuple; got {type(self.policies_dispatched).__name__}"
            )
        if not isinstance(self.violations, tuple):
            raise TypeError(f"violations must be tuple; got {type(self.violations).__name__}")

    @property
    def holds(self) -> bool:
        """``True`` iff ERUR-v2 holds for every cycle in the MCAP."""
        return len(self.violations) == 0


def verify_erur_v2(
    mcap_path: Path,
    *,
    drift_predicates: Mapping[str, Callable[[CalibrationHistory], bool]],
) -> ERURv2VerificationReport:
    """Verify ADR-0040 (ERUR-v2, policy-parametric) against an MCAP.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference
        pipeline. Channels ``/self_assessment/calibrated`` and
        ``/actuations`` must be present for the verifier to evaluate
        any cycle.
    drift_predicates
        Mapping from ``adjustment_policy_id`` to a callable that
        takes a :class:`CalibrationHistory` and returns ``True`` iff
        that policy's own drift criterion fires on the history. The
        callable is typically the ``drift_precondition`` method of a
        :class:`DriftPreconditionProvider` policy instance, but any
        pure function with the right signature is acceptable.

    Returns
    -------
    ERURv2VerificationReport
        ``report.holds`` is ``True`` iff the property held for every
        cycle where its precondition fired under the caller-supplied
        predicates.

    Raises
    ------
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    UnknownPolicyError
        If any MCAP record names an ``adjustment_policy_id`` not
        present in ``drift_predicates``. The error message lists the
        unknown id and the keys that *were* registered, so the
        caller can fix the registration.
    """
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
    seen_policies: list[str] = []

    for cycle_index, stamp in enumerate(calibrated_order):
        c = calibrated_by_stamp[stamp]
        policy_id = c.adjustment_policy_id
        if policy_id not in seen_policies:
            seen_policies.append(policy_id)
        try:
            predicate = drift_predicates[policy_id]
        except KeyError as exc:
            registered = sorted(drift_predicates.keys())
            raise UnknownPolicyError(
                f"MCAP record at cycle {cycle_index} (stamp_sim_ns={stamp}) "
                f"names adjustment_policy_id={policy_id!r}, but this id is "
                f"not present in drift_predicates. Registered ids: "
                f"{registered}. Register the policy's drift_precondition "
                f"method before calling verify_erur_v2."
            ) from exc

        if not _precondition_v2_holds(c, drift_predicate=predicate):
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

    return ERURv2VerificationReport(
        mcap_sha256=mcap_sha,
        property_version=ERUR_V2_PROPERTY_VERSION,
        cycles_total=len(calibrated_order),
        cycles_precondition_held=cycles_precondition_held,
        first_precondition_cycle_stamp_sim_ns=first_precondition_stamp,
        policies_dispatched=tuple(seen_policies),
        violations=tuple(violations),
    )


def _precondition_v2_holds(
    c: CalibratedSelfAssessment,
    *,
    drift_predicate: Callable[[CalibrationHistory], bool],
) -> bool:
    """Evaluate ERUR-v2's precondition for one calibrated assessment.

    Two-conjunct AND: ``drift_predicate(H_t) is False`` AND
    ``raw_t.overall_level == KNOWN``. The drift predicate is
    supplied by the caller and represents the policy's *own*
    criterion (as opposed to v1, which evaluates the reference
    count-of-K-in-W rule with fixed parameters).
    """
    drift_present = drift_predicate(c.calibration_history)
    raw_known = c.raw_assessment.overall_level is SelfAssessmentLevel.KNOWN
    return (not drift_present) and raw_known


__all__ = [
    "ERUR_V2_PROPERTY_VERSION",
    "ERURv2VerificationReport",
    "UnknownPolicyError",
    "verify_erur_v2",
]
