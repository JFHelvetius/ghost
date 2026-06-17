"""ADR-0041 -- False Positive Bound v2 (statistical), paper section 3.5.

FPB-v1 (ADR-0035) is an observational pass/fail comparison of an
**empirical** fire fraction against a caller-supplied threshold. That
contract is correct but operationally weak: a verdict on ``n = 10``
cycles is treated the same as a verdict on ``n = 10 000`` cycles,
even though the statistical authority of the two is vastly different.

FPB-v2 closes that gap by reporting an explicit **confidence upper
bound** on the *true* firing probability ``p`` given the observed
sample ``(cycles_fires, cycles_total)``. The contract reads:

  *With confidence at least ``confidence_level`` (default 0.95), the
  true firing probability is at most ``upper_bound``.*

The verifier HOLDS iff ``upper_bound <= max_fire_probability``. That
makes the small-sample regime correctly conservative (a wide
confidence interval cannot satisfy a tight bound) and lets a release
**earn** a tight regression gate by accumulating evidence.

Two estimators are shipped:

- :class:`ConfidenceMethod.HOEFFDING` (default): a closed-form,
  distribution-free upper bound

      ub = p_hat + sqrt(ln(1 / (1 - level)) / (2 * n))

  Stdlib only. Conservative. Works for any (bounded) random process
  that produces a Bernoulli-like sequence; does not assume binomial.

- :class:`ConfidenceMethod.CLOPPER_PEARSON`: the exact one-sided
  upper bound under a binomial model, computed as the
  ``(1 - level)``-quantile of a Beta distribution

      ub = BetaInv(level; cycles_fires + 1, cycles_total - cycles_fires)

  Tighter than Hoeffding when the binomial assumption holds.
  Requires SciPy; gracefully degrades to a clear error message if
  SciPy is unavailable.

The v1 verifier is *not* deprecated. v1 answers "is my observed
rate above a regression threshold?" (a CI smoke test). v2 answers
"is the *underlying* rate above a contractual bound, with the
confidence I claim?" (a statistical safety case). The paper's
section 9 caveat about "no statistical bound" is closed by FPB-v2;
section 3.5 documents the two contracts side by side.

Stdlib only at runtime by default; SciPy gated behind the
``CLOPPER_PEARSON`` method.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.properties.fpb import (
    _DEFAULT_DOWNGRADE_THRESHOLD,
    _DEFAULT_MIN_OUTCOMES,
    _baud_precondition_fires,
)
from project_ghost.telemetry import (
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


FPB_V2_PROPERTY_VERSION: Final[str] = "FPB-v2"

_DEFAULT_MAX_FIRE_PROBABILITY: Final[float] = 1.0
_DEFAULT_CONFIDENCE_LEVEL: Final[float] = 0.95

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


class ConfidenceMethod(StrEnum):
    """Closed catalogue of estimators FPB-v2 supports.

    Adding a new method requires (1) an ADR amendment documenting its
    contract and (2) a Hypothesis property test pinning its
    monotonicity in ``n`` and ``p_hat``. The verifier dispatches on
    the enum value only; the actual math lives in ``_upper_bound``.
    """

    HOEFFDING = "hoeffding"
    """Distribution-free Hoeffding inequality; stdlib only."""

    CLOPPER_PEARSON = "clopper_pearson"
    """Exact one-sided binomial upper bound via Beta inverse CDF;
    requires SciPy. Tighter than Hoeffding when observations are iid
    Bernoulli."""


class FPBv2ViolationKind(StrEnum):
    """Closed catalogue of FPB-v2 violations."""

    UPPER_BOUND_EXCEEDS_LIMIT = "upper_bound_exceeds_limit"
    """The confidence upper bound on the true firing probability
    exceeds ``max_fire_probability``. Either the observed rate is
    too high, or the sample is too small to certify the bound."""


@dataclass(frozen=True)
class FPBv2Violation:
    """Emitted once if the confidence upper bound exceeds the limit.

    Includes the observed point estimate, the computed upper bound,
    and the sample size so a maintainer can immediately tell whether
    the violation is "rate too high" or "sample too small".
    """

    kind: FPBv2ViolationKind
    observed_fire_fraction: float
    confidence_upper_bound: float
    max_fire_probability: float
    confidence_level: float
    method: ConfidenceMethod
    cycles_baud_fires: int
    cycles_total: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FPBv2ViolationKind):
            raise TypeError(
                f"kind must be FPBv2ViolationKind; got {type(self.kind).__name__}"
            )
        if not isinstance(self.method, ConfidenceMethod):
            raise TypeError(
                f"method must be ConfidenceMethod; got {type(self.method).__name__}"
            )
        for name, value in (
            ("observed_fire_fraction", self.observed_fire_fraction),
            ("confidence_upper_bound", self.confidence_upper_bound),
            ("max_fire_probability", self.max_fire_probability),
        ):
            if not (0.0 <= value <= 1.0) or math.isnan(value):
                raise ValueError(f"{name} must be in [0.0, 1.0]; got {value}")
        if not (0.0 < self.confidence_level < 1.0) or math.isnan(self.confidence_level):
            raise ValueError(
                f"confidence_level must be in (0.0, 1.0); got {self.confidence_level}"
            )
        if self.cycles_baud_fires < 0:
            raise ValueError(
                f"cycles_baud_fires must be >= 0; got {self.cycles_baud_fires}"
            )
        if self.cycles_total <= 0:
            raise ValueError(
                f"cycles_total must be > 0 for a violation; got {self.cycles_total}"
            )


@dataclass(frozen=True)
class FPBv2VerificationReport:
    """Output of :func:`verify_fpb_v2`.

    ``confidence_upper_bound`` is the statistical upper bound on the
    true firing probability given the observed ``(cycles_fires,
    cycles_total)`` under ``method`` at ``confidence_level``.
    ``holds`` is ``True`` iff that bound does not exceed
    ``max_fire_probability``.
    """

    mcap_sha256: str
    min_outcomes: int
    downgrade_threshold: int
    max_fire_probability: float
    confidence_level: float
    method: ConfidenceMethod
    property_version: str
    cycles_total: int
    cycles_precondition_held: int
    fire_fraction: float
    confidence_upper_bound: float
    first_precondition_cycle_stamp_sim_ns: int | None
    violations: tuple[FPBv2Violation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:  # noqa: PLR0912 -- one invariant per field
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
            raise ValueError(
                f"downgrade_threshold must be >= 1; got {self.downgrade_threshold}"
            )
        for name, value in (
            ("max_fire_probability", self.max_fire_probability),
            ("fire_fraction", self.fire_fraction),
            ("confidence_upper_bound", self.confidence_upper_bound),
        ):
            if not (0.0 <= value <= 1.0) or math.isnan(value):
                raise ValueError(f"{name} must be in [0.0, 1.0]; got {value}")
        if not (0.0 < self.confidence_level < 1.0) or math.isnan(self.confidence_level):
            raise ValueError(
                f"confidence_level must be in (0.0, 1.0); got {self.confidence_level}"
            )
        if not isinstance(self.method, ConfidenceMethod):
            raise TypeError(
                f"method must be ConfidenceMethod; got {type(self.method).__name__}"
            )
        if self.cycles_total < 0:
            raise ValueError(f"cycles_total must be >= 0; got {self.cycles_total}")
        if not 0 <= self.cycles_precondition_held <= self.cycles_total:
            raise ValueError(
                "cycles_precondition_held must be in "
                f"[0, cycles_total={self.cycles_total}]; got "
                f"{self.cycles_precondition_held}"
            )
        if self.cycles_total == 0:
            expected = 0.0
        else:
            expected = self.cycles_precondition_held / self.cycles_total
        if not math.isclose(self.fire_fraction, expected):
            raise ValueError(
                "fire_fraction must equal cycles_precondition_held / "
                f"cycles_total = {expected}; got {self.fire_fraction}"
            )
        # The upper bound must never be below the point estimate; that
        # would mean the bound undercounts the observation, which is
        # unsound.
        if self.confidence_upper_bound + 1e-12 < self.fire_fraction:
            raise ValueError(
                "confidence_upper_bound must be >= fire_fraction; got "
                f"ub={self.confidence_upper_bound} vs p_hat={self.fire_fraction}"
            )
        if (
            self.first_precondition_cycle_stamp_sim_ns is not None
            and self.first_precondition_cycle_stamp_sim_ns < 0
        ):
            raise ValueError(
                "first_precondition_cycle_stamp_sim_ns must be >= 0 or None; "
                f"got {self.first_precondition_cycle_stamp_sim_ns}"
            )
        if self.cycles_precondition_held == 0:
            if self.first_precondition_cycle_stamp_sim_ns is not None:
                raise ValueError(
                    "first_precondition_cycle_stamp_sim_ns must be None "
                    "when cycles_precondition_held == 0"
                )
        elif self.first_precondition_cycle_stamp_sim_ns is None:
            raise ValueError(
                "first_precondition_cycle_stamp_sim_ns must be set when "
                "cycles_precondition_held > 0"
            )
        if not isinstance(self.violations, tuple):
            raise TypeError(
                f"violations must be tuple; got {type(self.violations).__name__}"
            )
        if self.property_version != FPB_V2_PROPERTY_VERSION:
            raise ValueError(
                f"property_version must be {FPB_V2_PROPERTY_VERSION!r}; got "
                f"{self.property_version!r}"
            )

    @property
    def holds(self) -> bool:
        return self.confidence_upper_bound <= self.max_fire_probability


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hoeffding_upper_bound(
    cycles_fires: int, cycles_total: int, confidence_level: float
) -> float:
    """One-sided Hoeffding upper bound on the true firing probability.

    For ``X_i in [0, 1]`` iid with mean ``p``, Hoeffding's inequality
    gives

        P(p_hat - p <= -t) <= exp(-2 * n * t^2)

    Setting the right-hand side to ``alpha = 1 - confidence_level`` and
    solving for ``t`` yields

        ub = p_hat + sqrt(ln(1 / alpha) / (2 * n))

    Clamped to ``[0, 1]``. With ``n = 0`` the bound is the vacuous
    ``1.0`` (no observations means no certified bound).
    """
    if cycles_total <= 0:
        return 1.0
    p_hat = cycles_fires / cycles_total
    alpha = 1.0 - confidence_level
    epsilon = math.sqrt(math.log(1.0 / alpha) / (2.0 * cycles_total))
    return min(1.0, p_hat + epsilon)


def _clopper_pearson_upper_bound(
    cycles_fires: int, cycles_total: int, confidence_level: float
) -> float:
    """One-sided exact binomial upper bound (Clopper-Pearson).

    Under iid Bernoulli observations, the exact ``confidence_level``
    upper bound is the corresponding quantile of a Beta distribution:

        ub = BetaInv(confidence_level; cycles_fires + 1,
                                       cycles_total - cycles_fires)

    Requires SciPy because the inverse regularised incomplete beta
    function is not in stdlib. Raises ``ImportError`` with an
    actionable message if SciPy is unavailable; the caller can then
    fall back to ``HOEFFDING``.

    Special cases:

    - ``cycles_total == 0`` returns the vacuous bound ``1.0``.
    - ``cycles_fires == cycles_total`` returns ``1.0`` (all fires;
      bound is at the boundary).
    """
    if cycles_total <= 0:
        return 1.0
    if cycles_fires >= cycles_total:
        return 1.0
    # scipy is an optional extra; the lazy import gates the dependency
    # so the default Hoeffding path stays stdlib-only.
    try:
        from scipy.stats import beta  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "ConfidenceMethod.CLOPPER_PEARSON requires SciPy, which is "
            "not installed. Either install with "
            "`pip install 'project-ghost[stats]'` or pass "
            "method=ConfidenceMethod.HOEFFDING."
        ) from exc

    a = cycles_fires + 1
    b = cycles_total - cycles_fires
    return float(beta.ppf(confidence_level, a, b))


def _upper_bound(
    cycles_fires: int,
    cycles_total: int,
    *,
    method: ConfidenceMethod,
    confidence_level: float,
) -> float:
    """Dispatch on ``method`` to one of the closed-form bounds.

    Returns the upper bound on the true firing probability at the
    given confidence level. Always >= the point estimate.
    """
    if method is ConfidenceMethod.HOEFFDING:
        return _hoeffding_upper_bound(cycles_fires, cycles_total, confidence_level)
    if method is ConfidenceMethod.CLOPPER_PEARSON:
        return _clopper_pearson_upper_bound(
            cycles_fires, cycles_total, confidence_level
        )
    raise ValueError(f"unhandled ConfidenceMethod: {method}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_fpb_v2(  # noqa: PLR0912 -- one branch per of seven validated parameters
    mcap_path: Path,
    *,
    min_outcomes: int = _DEFAULT_MIN_OUTCOMES,
    downgrade_threshold: int = _DEFAULT_DOWNGRADE_THRESHOLD,
    max_fire_probability: float = _DEFAULT_MAX_FIRE_PROBABILITY,
    confidence_level: float = _DEFAULT_CONFIDENCE_LEVEL,
    method: ConfidenceMethod = ConfidenceMethod.HOEFFDING,
) -> FPBv2VerificationReport:
    """Compute a confidence upper bound on the true BAUD firing rate.

    Parameters
    ----------
    mcap_path
        Path to an MCAP produced by Project Ghost's reference pipeline.
    min_outcomes, downgrade_threshold
        BAUD-v1 precondition parameters ``M`` and ``K`` (mirrored on
        the v1 verifier so the two reports are directly comparable).
    max_fire_probability
        Contractual upper bound on the *true* firing probability.
        Default ``1.0`` makes the verifier purely observational and
        always holds.
    confidence_level
        Confidence at which the upper bound is certified. Default
        ``0.95`` (i.e. ``alpha = 0.05``).
    method
        Which statistical estimator to use. Default
        :class:`ConfidenceMethod.HOEFFDING` (stdlib-only,
        distribution-free).

    Returns
    -------
    FPBv2VerificationReport
        ``report.holds`` is ``True`` iff
        ``report.confidence_upper_bound <= max_fire_probability``.
        The report always carries the observed fraction, the upper
        bound, the chosen method and confidence level so verdicts
        are auditable.

    Raises
    ------
    ValueError
        If parameters are out of range or ``method`` is not one of
        :class:`ConfidenceMethod`.
    ImportError
        If ``method = CLOPPER_PEARSON`` and SciPy is not installed.
    FileNotFoundError
        If ``mcap_path`` does not exist or is unreadable.
    """
    if min_outcomes < 0:
        raise ValueError(f"min_outcomes must be >= 0; got {min_outcomes}")
    if downgrade_threshold < 1:
        raise ValueError(f"downgrade_threshold must be >= 1; got {downgrade_threshold}")
    if not (0.0 <= max_fire_probability <= 1.0) or math.isnan(max_fire_probability):
        raise ValueError(
            f"max_fire_probability must be in [0.0, 1.0]; got {max_fire_probability}"
        )
    if not (0.0 < confidence_level < 1.0) or math.isnan(confidence_level):
        raise ValueError(
            f"confidence_level must be in (0.0, 1.0); got {confidence_level}"
        )
    if not isinstance(method, ConfidenceMethod):
        raise TypeError(
            f"method must be ConfidenceMethod; got {type(method).__name__}"
        )

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
    upper_bound = _upper_bound(
        cycles_fires,
        cycles_total,
        method=method,
        confidence_level=confidence_level,
    )

    violations: tuple[FPBv2Violation, ...] = ()
    if upper_bound > max_fire_probability and cycles_total > 0:
        violations = (
            FPBv2Violation(
                kind=FPBv2ViolationKind.UPPER_BOUND_EXCEEDS_LIMIT,
                observed_fire_fraction=fire_fraction,
                confidence_upper_bound=upper_bound,
                max_fire_probability=max_fire_probability,
                confidence_level=confidence_level,
                method=method,
                cycles_baud_fires=cycles_fires,
                cycles_total=cycles_total,
            ),
        )

    return FPBv2VerificationReport(
        mcap_sha256=mcap_sha,
        min_outcomes=min_outcomes,
        downgrade_threshold=downgrade_threshold,
        max_fire_probability=max_fire_probability,
        confidence_level=confidence_level,
        method=method,
        property_version=FPB_V2_PROPERTY_VERSION,
        cycles_total=cycles_total,
        cycles_precondition_held=cycles_fires,
        fire_fraction=fire_fraction,
        confidence_upper_bound=upper_bound,
        first_precondition_cycle_stamp_sim_ns=first_fire_stamp,
        violations=violations,
    )


__all__ = [
    "FPB_V2_PROPERTY_VERSION",
    "ConfidenceMethod",
    "FPBv2VerificationReport",
    "FPBv2Violation",
    "FPBv2ViolationKind",
    "verify_fpb_v2",
]
