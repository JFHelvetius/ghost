"""Reference predictor: ``ConstantVelocityForwardPredictor`` (ADR-0024).

Predictor mínimo documentado que demuestra que el contrato
``ForwardPredictor`` es sound.

**No usa el comando.** Propaga la creencia actual asumiendo velocidad
lineal constante en frame mundo y orientación constante (sin modelo de
torque). Eso es exactamente el predictor "no asumo efecto del
actuador" — la baseline mínima contra la que cualquier predictor con
modelo dinámico real tiene que demostrar mejora.

Propagación:

- Posición: ``p_t + v_world * (horizon_ns / 1e9)``.
- Orientación: ``q_t`` constante.
- Std posicional: derivada de ``sqrt(diag(cov[0:3, 0:3]))`` cuando
  ``covariance_15x15`` está presente; fallback ``_FALLBACK_POS_STD``.
- Std orientacional: derivada de ``sqrt(diag(cov[6:9, 6:9]))``
  cuando está presente; fallback ``_FALLBACK_ORI_STD``.

Determinista, pure, stdlib + numpy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

import numpy as np

from project_ghost.state.messages import Pose

from .types import BeliefForwardPrediction, PoseStd

if TYPE_CHECKING:
    from project_ghost.state.messages import VehicleState


_NS_PER_S: Final[float] = 1.0e9

# Fallbacks cuando covariance no está disponible. Valores deliberadamente
# conservadores: el predictor declara "no sé con qué incertidumbre"
# antes que mentir con std cero.
_FALLBACK_POS_STD_M: Final[float] = 1.0
_FALLBACK_ORI_STD_RAD: Final[float] = 1.0

_COV_POS_SLICE: Final[slice] = slice(0, 3)
_COV_ORI_SLICE: Final[slice] = slice(6, 9)


def _std_from_cov_diag(cov: np.ndarray, sl: slice) -> np.ndarray:
    """Extraer ``sqrt(diag(cov[sl, sl]))`` como vec3 float64.

    Por la invariante PSD de ``_validate_covariance``, la diagonal es
    siempre ``>= 0`` salvo ruido numérico. Aplicamos clipping a 0 para
    cubrir el caso de eigenvalor diagonal marginalmente negativo.
    """
    block_diag = np.diag(cov)[sl]
    result: np.ndarray = np.sqrt(np.clip(block_diag, 0.0, None)).astype(
        np.float64
    )
    return result


def _fallback_std(value: float) -> np.ndarray:
    return np.full(3, value, dtype=np.float64)


class ConstantVelocityForwardPredictor:
    """Predictor de referencia: constant-velocity, no usa comando.

    Existe para demostrar que el contrato ``ForwardPredictor`` es
    sound. Predictores con modelo dinámico real (que SÍ asuman efecto
    del actuador) implementan el mismo Protocol; la divergencia entre
    ellos y este será mecánicamente comparable.
    """

    PREDICTOR_ID: ClassVar[str] = "constant_velocity_v1"

    @property
    def predictor_id(self) -> str:
        return self.PREDICTOR_ID

    def predict(
        self,
        belief: VehicleState,
        horizon_ns: int,
        directive_hash: str | None = None,
    ) -> BeliefForwardPrediction:
        if horizon_ns <= 0:
            raise ValueError(
                f"horizon_ns must be > 0; got {horizon_ns}"
            )
        dt_s = float(horizon_ns) / _NS_PER_S

        pose = belief.nav.pose
        v_world = belief.nav.twist_world.linear_mps

        predicted_position = pose.position_enu_m + v_world * dt_s
        predicted_position = predicted_position.astype(np.float64, copy=True)
        predicted_orientation = pose.orientation_q.astype(
            np.float64, copy=True
        )

        cov = belief.nav.covariance_15x15
        if cov is not None:
            pos_std = _std_from_cov_diag(cov, _COV_POS_SLICE)
            ori_std = _std_from_cov_diag(cov, _COV_ORI_SLICE)
        else:
            pos_std = _fallback_std(_FALLBACK_POS_STD_M)
            ori_std = _fallback_std(_FALLBACK_ORI_STD_RAD)

        predicted_pose = Pose(
            position_enu_m=predicted_position,
            orientation_q=predicted_orientation,
        )
        predicted_pose_std = PoseStd(
            position_std_enu_m=pos_std,
            orientation_std_rad=ori_std,
        )

        return BeliefForwardPrediction(
            source_belief_stamp_sim_ns=belief.stamp_sim_ns,
            predicted_observation_stamp_sim_ns=(
                belief.stamp_sim_ns + horizon_ns
            ),
            horizon_ns=horizon_ns,
            predicted_pose=predicted_pose,
            predicted_pose_std=predicted_pose_std,
            associated_directive_hash=directive_hash,
            predictor_id=self.PREDICTOR_ID,
        )


__all__ = ["ConstantVelocityForwardPredictor"]
