"""`NoisyGroundTruthEstimator` — perturbación determinista de GT (ADR-0015).

**Honestidad framing.** Este "estimator" NO estima. Perturba
``GroundTruth`` con ruido Gaussiano determinista y empaqueta el
resultado en un ``VehicleState`` con la covarianza que el caller
declaró. Es el primer artefacto del proyecto que produce **creencia**
en vez de verdad (``covariance_15x15 is not None``), y existe para
ejercitar consumidores aguas abajo de creencia no-trivial — NO para
sustituir un estimador real.

Modelo de perturbación (ADR-0015 §3):

- Posición ENU, velocidad lineal world, velocidad angular body,
  aceleración body: ruido Gaussiano aditivo, per-eje, std del config.
- Orientación: perturbación tangente pequeña-rotación. Se muestrea
  ``δθ ∈ R³`` con std ``orientation_noise_std_rad`` per-eje, se forma
  ``δq = [1, δθ_x/2, δθ_y/2, δθ_z/2]``, se compone con la GT vía
  multiplicación Hamilton (``q' = δq ⊗ q``) y se renormaliza.

Coherencia interna (ADR-0015 §4): el twist publicado usa la pose
**ruidosa** para R_body_to_world y R_world_to_body, NO la GT. La
creencia publicada es internamente coherente — coherente consigo
misma, NO con la verdad.

Determinismo (ADR-0015 §6): el estimador deriva un único hijo
``RandomSource`` en construcción y lo reusa. Mismo ``(seed parent,
label parent, config, secuencia de inputs)`` -> bytes idénticos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from project_ghost.state.messages import (
    IMUBiases,
    NavigationState,
    Pose,
    Twist,
    VehicleState,
)
from project_ghost.state.transforms import R_body_to_world, R_world_to_body

if TYPE_CHECKING:
    from project_ghost.core.clock.types import RandomSource
    from project_ghost.hal.messages import GroundTruth
    from project_ghost.state.messages import (
        FlightStatus,
        MissionStatus,
        SensorHealthMap,
    )

    from .config import NoisyGroundTruthConfig


def _hamilton_multiply(q_left: np.ndarray, q_right: np.ndarray) -> np.ndarray:
    """Composición Hamilton ``q_left ⊗ q_right`` para ``[w, x, y, z]``.

    Convención: aplicar la rotación ``q_right`` primero y luego
    ``q_left`` (igual que matrices: ``R_left @ R_right @ v``).
    """
    w1, x1, y1, z1 = q_left
    w2, x2, y2, z2 = q_right
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=np.float64,
    )


class NoisyGroundTruthEstimator:
    """Perturbador determinista de ``GroundTruth`` -> ``VehicleState``.

    **Posture honesto** (ADR-0015): este no es un estimador en el
    sentido epistemológico. Es un perturbador de verdad que empaqueta
    el resultado como si fuera creencia, atado a una covarianza
    declarada por el caller. Existe para ejercitar consumidores de
    creencia no-trivial.

    Construcción: se toma una vez el child ``RandomSource`` derivado
    de ``random_source.child(config.random_source_label)``. El parent
    no se vuelve a leer; el child es el único productor de aleatoriedad
    del estimador.

    Cada ``estimate(...)`` muestrea cinco bloques de Gaussianas (uno
    por campo perturbado) del numpy.random.Generator interno del
    child. La covarianza publicada es una **copia fresca** de
    ``config.declared_covariance_15x15`` — el estimador no comparte
    vistas selladas con el config.
    """

    def __init__(
        self,
        *,
        config: NoisyGroundTruthConfig,
        random_source: RandomSource,
    ) -> None:
        self._config: NoisyGroundTruthConfig = config
        # Un solo child, derivado una vez. ADR-0002: cadena de child()
        # determinista; replay con misma parent seed + mismo label
        # produce la misma secuencia.
        self._rs: RandomSource = random_source.child(config.random_source_label)
        self._rng: np.random.Generator = self._rs.numpy_rng()

    @property
    def config(self) -> NoisyGroundTruthConfig:
        return self._config

    @property
    def random_source_label(self) -> str:
        return self._rs.label

    def estimate(
        self,
        *,
        gt: GroundTruth,
        sensors_health: SensorHealthMap,
        flight: FlightStatus,
        mission: MissionStatus,
        stamp_wall_ns: int,
    ) -> VehicleState:
        """Perturba ``gt`` y empaqueta como ``VehicleState`` con creencia.

        ``covariance_15x15`` queda en una **copia** de la cov declarada
        en el config — no se comparte vista sellada con el config.

        ``stamp_sim_ns`` se toma de ``gt.stamp_sim_ns``;
        ``stamp_wall_ns`` se pasa como parámetro (ADR-0002: el
        estimador no lee reloj).

        El twist publicado usa la quaternion **ruidosa** para
        R_body_to_world / R_world_to_body, garantizando que
        ``twist_world`` y ``twist_body`` son coherentes con la pose
        publicada.
        """
        cfg = self._config

        # ----- Muestreo de ruido (orden estable: position, orientation,
        # linear_vel_world, angular_vel_body, accel_body). Cambiar este
        # orden rompería determinismo replay.
        delta_position = self._sample_vec3(cfg.position_noise_std_m)
        delta_theta = self._sample_vec3(cfg.orientation_noise_std_rad)
        delta_v_world = self._sample_vec3(cfg.linear_velocity_noise_std_mps)
        delta_omega_body = self._sample_vec3(
            cfg.angular_velocity_noise_std_rps
        )
        delta_accel_body = self._sample_vec3(cfg.accel_body_noise_std_mps2)

        # ----- Pose perturbada.
        noisy_position = np.ascontiguousarray(
            gt.position_enu_m + delta_position, dtype=np.float64
        )
        noisy_q = _perturb_quaternion(gt.orientation_q, delta_theta)

        # ----- Velocidades perturbadas en sus frames nativos.
        noisy_v_world = np.ascontiguousarray(
            gt.linear_velocity_world_mps + delta_v_world, dtype=np.float64
        )
        noisy_omega_body = np.ascontiguousarray(
            gt.angular_velocity_body_rps + delta_omega_body, dtype=np.float64
        )
        noisy_accel_body = np.ascontiguousarray(
            gt.accel_body_mps2 + delta_accel_body, dtype=np.float64
        )

        # ----- Twists coherentes con la POSE RUIDOSA (ADR-0015 §4):
        # se usa noisy_q (no gt.orientation_q) para que el VehicleState
        # publicado sea internamente coherente.
        r_body_to_world = R_body_to_world(noisy_q)
        r_world_to_body = R_world_to_body(noisy_q)
        noisy_omega_world = np.ascontiguousarray(
            r_body_to_world @ noisy_omega_body, dtype=np.float64
        )
        noisy_v_body = np.ascontiguousarray(
            r_world_to_body @ noisy_v_world, dtype=np.float64
        )

        pose = Pose(
            position_enu_m=noisy_position,
            orientation_q=noisy_q,
        )
        twist_world = Twist(
            linear_mps=noisy_v_world.copy(),
            angular_rps=noisy_omega_world,
            frame="world",
        )
        twist_body = Twist(
            linear_mps=noisy_v_body,
            angular_rps=noisy_omega_body.copy(),
            frame="body",
        )

        # ----- Biases cero (ADR-0015 §5): este estimador no infiere
        # biases; los publica como cero por honestidad explícita.
        biases = IMUBiases(
            accel_bias_mps2=np.zeros(3, dtype=np.float64),
            gyro_bias_rps=np.zeros(3, dtype=np.float64),
        )

        # ----- Covarianza: copia fresca de la declarada en el config.
        # NavigationState la valida (forma/simetría/PSD) y la sella;
        # pasar copia evita compartir vista sellada del config.
        declared_cov_copy = np.ascontiguousarray(
            cfg.declared_covariance_15x15, dtype=np.float64
        ).copy()

        nav = NavigationState(
            pose=pose,
            twist_world=twist_world,
            twist_body=twist_body,
            accel_body_mps2=noisy_accel_body,
            imu_biases=biases,
            covariance_15x15=declared_cov_copy,
        )

        return VehicleState(
            stamp_sim_ns=gt.stamp_sim_ns,
            stamp_wall_ns=stamp_wall_ns,
            nav=nav,
            sensors=sensors_health,
            flight=flight,
            mission=mission,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _sample_vec3(self, std: float) -> np.ndarray:
        """Muestrea N(0, std²)³. Si ``std == 0`` devuelve ceros sin
        consumir el generator — preserva la invariante de "ruido cero
        no perturba" y evita un draw espurio (que cambiaría el estado
        del Generator y por tanto las muestras subsiguientes)."""
        if std == 0.0:
            return np.zeros(3, dtype=np.float64)
        sample = self._rng.normal(loc=0.0, scale=std, size=3)
        return np.ascontiguousarray(sample, dtype=np.float64)


def _perturb_quaternion(
    q_gt: np.ndarray, delta_theta: np.ndarray
) -> np.ndarray:
    """Compose small-angle ``δq`` with ``q_gt`` via Hamilton multiply.

    ``δq = [1, δθ_x/2, δθ_y/2, δθ_z/2]``, normalizado pre-composición
    para que el producto resulte cerca de unit; el resultado final se
    renormaliza explícitamente para satisfacer la tolerancia
    ``_QUAT_NORM_TOLERANCE`` de ``Pose._validate_unit_quaternion``.
    """
    half_theta = delta_theta * 0.5
    dq = np.array(
        [1.0, half_theta[0], half_theta[1], half_theta[2]],
        dtype=np.float64,
    )
    dq /= float(np.linalg.norm(dq))
    composed = _hamilton_multiply(dq, q_gt)
    norm = float(np.linalg.norm(composed))
    composed /= norm
    return np.ascontiguousarray(composed, dtype=np.float64)


__all__ = ["NoisyGroundTruthEstimator"]
