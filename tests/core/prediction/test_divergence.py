"""Tests del contrato de divergencia predicción↔observación (ADR-0025).

Cubre:

- ``DivergenceVerdict`` es un StrEnum cerrado.
- ``PredictionOutcome.__post_init__`` invariantes: stamp identity,
  finiteness, normas no-negativas, verdict consistente.
- ``compute_divergence`` es pure (byte-equal repeatable).
- Identity case: actual == predicted → error cero, verdict
  ``WITHIN_1_STD``.
- Verdict thresholds: 0.5σ, 1.5σ, 4σ, 10σ → cuatro verdicts.
- Mahalanobis con std=0: error=0 → 0, error!=0 → +inf.
- Quaternion error: identity → cero; 180° rotation → π norma.
- Stamp mismatch → ValueError.
"""

from __future__ import annotations

import numpy as np
import pytest

from project_ghost.core.prediction import (
    DIVERGENCE_PROTOCOL_VERSION,
    BeliefForwardPrediction,
    DivergenceVerdict,
    PoseStd,
    PredictionOutcome,
    compute_divergence,
)
from project_ghost.state.messages import Pose
from project_ghost.telemetry import encode_to_bytes

_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
# 180° rotation about x: q = (cos(90°), sin(90°)*x_axis) = (0, 1, 0, 0)
_Q_180_X = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float64)


def _pose(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Pose:
    return Pose(
        position_enu_m=np.array([x, y, z], dtype=np.float64),
        orientation_q=_Q_IDENTITY.copy(),
    )


def _std(p: float = 0.1, o: float = 0.1) -> PoseStd:
    return PoseStd(
        position_std_enu_m=np.full(3, p, dtype=np.float64),
        orientation_std_rad=np.full(3, o, dtype=np.float64),
    )


def _prediction(
    *,
    source_stamp: int = 1000,
    horizon: int = 500,
    predicted_pose: Pose | None = None,
    predicted_std: PoseStd | None = None,
) -> BeliefForwardPrediction:
    return BeliefForwardPrediction(
        source_belief_stamp_sim_ns=source_stamp,
        predicted_observation_stamp_sim_ns=source_stamp + horizon,
        horizon_ns=horizon,
        predicted_pose=predicted_pose if predicted_pose is not None else _pose(),
        predicted_pose_std=(
            predicted_std if predicted_std is not None else _std()
        ),
        associated_directive_hash=None,
        predictor_id="constant_velocity_v1",
    )


# ---------------------------------------------------------------------------
# DivergenceVerdict
# ---------------------------------------------------------------------------


def test_verdict_catalog_is_closed_and_ordered() -> None:
    assert list(DivergenceVerdict) == [
        DivergenceVerdict.WITHIN_1_STD,
        DivergenceVerdict.BEYOND_1_STD,
        DivergenceVerdict.BEYOND_3_STD,
        DivergenceVerdict.BEYOND_5_STD,
    ]


def test_verdict_values_are_snake_case() -> None:
    for v in DivergenceVerdict:
        assert v.value == v.name.lower()


# ---------------------------------------------------------------------------
# compute_divergence — identity case
# ---------------------------------------------------------------------------


def test_identity_case_yields_zero_error_within_1_std() -> None:
    pred = _prediction()
    outcome = compute_divergence(pred, _pose(), pred.predicted_observation_stamp_sim_ns)
    np.testing.assert_array_equal(
        outcome.position_error_enu_m, np.zeros(3, dtype=np.float64)
    )
    assert outcome.position_error_norm_m == 0.0
    np.testing.assert_allclose(
        outcome.orientation_error_rad,
        np.zeros(3, dtype=np.float64),
        atol=1e-12,
    )
    assert outcome.orientation_error_norm_rad == pytest.approx(0.0, abs=1e-12)
    assert outcome.position_mahalanobis_max == 0.0
    assert outcome.orientation_mahalanobis_max == 0.0
    assert outcome.verdict == DivergenceVerdict.WITHIN_1_STD


# ---------------------------------------------------------------------------
# Verdict thresholds (positional)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("multiplier", "expected"),
    [
        (0.5, DivergenceVerdict.WITHIN_1_STD),
        (1.5, DivergenceVerdict.BEYOND_1_STD),
        (4.0, DivergenceVerdict.BEYOND_3_STD),
        (10.0, DivergenceVerdict.BEYOND_5_STD),
    ],
)
def test_position_error_verdict_thresholds(
    multiplier: float, expected: DivergenceVerdict
) -> None:
    pred = _prediction(predicted_std=_std(p=0.2, o=10.0))
    # Move only in x by `multiplier * pos_std_x` → mahal_max = multiplier
    actual = Pose(
        position_enu_m=np.array(
            [multiplier * 0.2, 0.0, 0.0], dtype=np.float64
        ),
        orientation_q=_Q_IDENTITY.copy(),
    )
    outcome = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.verdict == expected
    assert outcome.position_mahalanobis_max == pytest.approx(multiplier)


# ---------------------------------------------------------------------------
# Mahalanobis with std=0
# ---------------------------------------------------------------------------


def test_mahalanobis_zero_over_zero_is_zero() -> None:
    pred = _prediction(predicted_std=_std(p=0.0, o=0.0))
    outcome = compute_divergence(
        pred, _pose(), pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.position_mahalanobis_max == 0.0
    assert outcome.orientation_mahalanobis_max == 0.0
    assert outcome.verdict == DivergenceVerdict.WITHIN_1_STD


def test_mahalanobis_nonzero_over_zero_is_inf() -> None:
    pred = _prediction(predicted_std=_std(p=0.0, o=10.0))
    actual = _pose(x=0.5)
    outcome = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.position_mahalanobis_max == float("inf")
    assert outcome.verdict == DivergenceVerdict.BEYOND_5_STD


# ---------------------------------------------------------------------------
# Quaternion error
# ---------------------------------------------------------------------------


def test_orientation_identity_yields_zero_error() -> None:
    pred = _prediction()
    outcome = compute_divergence(
        pred, _pose(), pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.orientation_error_norm_rad == pytest.approx(
        0.0, abs=1e-12
    )


def test_orientation_180_degree_rotation_yields_pi_norm() -> None:
    pred = _prediction()
    actual = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_Q_180_X.copy(),
    )
    outcome = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.orientation_error_norm_rad == pytest.approx(np.pi)


def test_orientation_negated_quaternion_is_same_rotation() -> None:
    """``q`` and ``-q`` represent the same rotation; error must be ~0."""
    pred = _prediction()
    actual = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=(-_Q_IDENTITY).copy(),
    )
    outcome = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.orientation_error_norm_rad == pytest.approx(
        0.0, abs=1e-12
    )


# ---------------------------------------------------------------------------
# Stamp identity
# ---------------------------------------------------------------------------


def test_stamp_mismatch_raises() -> None:
    pred = _prediction(source_stamp=1000, horizon=500)
    with pytest.raises(
        ValueError, match=r"must equal prediction\.predicted_observation_stamp_sim_ns"
    ):
        compute_divergence(pred, _pose(), 9999)


def test_outcome_post_init_rejects_stamp_mismatch() -> None:
    pred = _prediction()
    with pytest.raises(
        ValueError, match=r"must equal prediction\.predicted_observation_stamp_sim_ns"
    ):
        PredictionOutcome(
            prediction=pred,
            actual_belief_stamp_sim_ns=9999,
            actual_pose=_pose(),
            position_error_enu_m=np.zeros(3, dtype=np.float64),
            position_error_norm_m=0.0,
            orientation_error_rad=np.zeros(3, dtype=np.float64),
            orientation_error_norm_rad=0.0,
            position_mahalanobis_max=0.0,
            orientation_mahalanobis_max=0.0,
            verdict=DivergenceVerdict.WITHIN_1_STD,
        )


# ---------------------------------------------------------------------------
# PredictionOutcome invariants
# ---------------------------------------------------------------------------


def test_outcome_post_init_rejects_inconsistent_verdict() -> None:
    pred = _prediction()
    with pytest.raises(ValueError, match=r"verdict .* inconsistent"):
        PredictionOutcome(
            prediction=pred,
            actual_belief_stamp_sim_ns=pred.predicted_observation_stamp_sim_ns,
            actual_pose=_pose(),
            position_error_enu_m=np.zeros(3, dtype=np.float64),
            position_error_norm_m=0.0,
            orientation_error_rad=np.zeros(3, dtype=np.float64),
            orientation_error_norm_rad=0.0,
            position_mahalanobis_max=10.0,  # implies BEYOND_5_STD
            orientation_mahalanobis_max=0.0,
            verdict=DivergenceVerdict.WITHIN_1_STD,
        )


def test_outcome_post_init_rejects_negative_norm() -> None:
    pred = _prediction()
    with pytest.raises(
        ValueError, match="position_error_norm_m must be >= 0"
    ):
        PredictionOutcome(
            prediction=pred,
            actual_belief_stamp_sim_ns=pred.predicted_observation_stamp_sim_ns,
            actual_pose=_pose(),
            position_error_enu_m=np.zeros(3, dtype=np.float64),
            position_error_norm_m=-1.0,
            orientation_error_rad=np.zeros(3, dtype=np.float64),
            orientation_error_norm_rad=0.0,
            position_mahalanobis_max=0.0,
            orientation_mahalanobis_max=0.0,
            verdict=DivergenceVerdict.WITHIN_1_STD,
        )


def test_outcome_post_init_rejects_non_finite_error() -> None:
    pred = _prediction()
    with pytest.raises(ValueError, match="must be finite"):
        PredictionOutcome(
            prediction=pred,
            actual_belief_stamp_sim_ns=pred.predicted_observation_stamp_sim_ns,
            actual_pose=_pose(),
            position_error_enu_m=np.array(
                [np.nan, 0.0, 0.0], dtype=np.float64
            ),
            position_error_norm_m=0.0,
            orientation_error_rad=np.zeros(3, dtype=np.float64),
            orientation_error_norm_rad=0.0,
            position_mahalanobis_max=0.0,
            orientation_mahalanobis_max=0.0,
            verdict=DivergenceVerdict.WITHIN_1_STD,
        )


def test_outcome_post_init_rejects_nan_mahalanobis() -> None:
    pred = _prediction()
    with pytest.raises(ValueError, match="must not be NaN"):
        PredictionOutcome(
            prediction=pred,
            actual_belief_stamp_sim_ns=pred.predicted_observation_stamp_sim_ns,
            actual_pose=_pose(),
            position_error_enu_m=np.zeros(3, dtype=np.float64),
            position_error_norm_m=0.0,
            orientation_error_rad=np.zeros(3, dtype=np.float64),
            orientation_error_norm_rad=0.0,
            position_mahalanobis_max=float("nan"),
            orientation_mahalanobis_max=0.0,
            verdict=DivergenceVerdict.WITHIN_1_STD,
        )


def test_outcome_post_init_accepts_inf_mahalanobis() -> None:
    pred = _prediction()
    outcome = PredictionOutcome(
        prediction=pred,
        actual_belief_stamp_sim_ns=pred.predicted_observation_stamp_sim_ns,
        actual_pose=_pose(),
        position_error_enu_m=np.zeros(3, dtype=np.float64),
        position_error_norm_m=0.0,
        orientation_error_rad=np.zeros(3, dtype=np.float64),
        orientation_error_norm_rad=0.0,
        position_mahalanobis_max=float("inf"),
        orientation_mahalanobis_max=0.0,
        verdict=DivergenceVerdict.BEYOND_5_STD,
    )
    assert outcome.position_mahalanobis_max == float("inf")


def test_outcome_is_frozen() -> None:
    pred = _prediction()
    outcome = compute_divergence(
        pred, _pose(), pred.predicted_observation_stamp_sim_ns
    )
    with pytest.raises(AttributeError):
        outcome.verdict = DivergenceVerdict.BEYOND_5_STD  # type: ignore[misc]


def test_outcome_error_arrays_are_read_only() -> None:
    pred = _prediction()
    outcome = compute_divergence(
        pred, _pose(x=0.05), pred.predicted_observation_stamp_sim_ns
    )
    with pytest.raises(
        ValueError, match=r"read-only|assignment destination"
    ):
        outcome.position_error_enu_m[0] = 99.0


def test_outcome_schema_version() -> None:
    pred = _prediction()
    outcome = compute_divergence(
        pred, _pose(), pred.predicted_observation_stamp_sim_ns
    )
    assert outcome.schema_version == DIVERGENCE_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Pure function
# ---------------------------------------------------------------------------


def test_compute_divergence_pure_function() -> None:
    """Same input → byte-equal output via encode_to_bytes."""
    pred = _prediction(predicted_std=_std(p=0.2, o=0.1))
    actual = _pose(x=0.1, y=-0.05, z=0.02)
    o1 = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    o2 = compute_divergence(
        pred, actual, pred.predicted_observation_stamp_sim_ns
    )
    assert encode_to_bytes(o1) == encode_to_bytes(o2)


def test_compute_divergence_rejects_wrong_pose_type() -> None:
    pred = _prediction()
    with pytest.raises(TypeError, match="actual_pose must be Pose"):
        compute_divergence(
            pred,
            "not a pose",  # type: ignore[arg-type]
            pred.predicted_observation_stamp_sim_ns,
        )


def test_compute_divergence_rejects_wrong_prediction_type() -> None:
    with pytest.raises(
        TypeError, match="prediction must be BeliefForwardPrediction"
    ):
        compute_divergence(
            "not a prediction",  # type: ignore[arg-type]
            _pose(),
            1000,
        )
