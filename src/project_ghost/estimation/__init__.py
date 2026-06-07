"""`estimation` — productores de creencia para Project Ghost.

ADR-0015 establece la dirección: un módulo cuyas salidas tienen
``covariance_15x15 is not None``. Es el contraparte explícito a
``state.aggregator.vehicle_state_from_ground_truth``, que publica
verdad.

Contenido actual:

- ``NoisyGroundTruthConfig`` + ``NoisyGroundTruthEstimator``: perturba
  ``GroundTruth`` con ruido Gaussiano determinista y empaqueta con
  una covarianza **declarada por el caller**. NO es un estimador
  Bayesiano, NO es un Kalman filter. Es un test-fixture en forma de
  producción para ejercitar consumidores de creencia.

Estimadores reales (Kalman, factor-graph, etc.) cuando lleguen vivirán
en submódulos hermanos de este (``estimation.kalman``,
``estimation.factor_graph``, ...). El perturbador toy permanece como
fixture y para ablation studies.
"""

from __future__ import annotations

from .config import NoisyGroundTruthConfig
from .noisy_gt import NoisyGroundTruthEstimator

__all__ = [
    "NoisyGroundTruthConfig",
    "NoisyGroundTruthEstimator",
]
