"""`core.feedback` — closed-loop feedback (ADR-0026).

Primera composición explícita entre ADRs: el stream de
``PredictionOutcome`` (ADR-0025) influye el siguiente
``BeliefSelfAssessment`` (ADR-0020). Sin esta pieza, un agente puede
emitir cinco predicciones overconfident seguidas y seguir
declarándose KNOWN en la sexta — la auditoría existe en MCAP pero el
agente no la usa.

- ``CalibrationHistory`` (snapshot agregado de outcomes recientes).
- ``CalibratedSelfAssessment`` (envelope raw assessment + history +
  level ajustado + identifiers).
- ``CalibrationAdjustmentPolicy`` (Protocol pure function).
- ``MahalanobisDowngradePolicy`` (reference mínima: downgrade un nivel
  si los outcomes muestran overconfidence consistente).
- ``build_calibration_history`` + ``assess_with_feedback``
  (orquestación canónica).

Cero modificación de ADR-0020. El envelope wrapping respeta la
inmutabilidad del assessment crudo. Policies futuras (per-axis,
recency-weighted, hysteresis) implementan el mismo Protocol sin
reabrir el envelope.
"""

from __future__ import annotations

from .orchestration import assess_with_feedback, build_calibration_history
from .protocols import CalibrationAdjustmentPolicy
from .reference_policy import MahalanobisDowngradePolicy
from .types import (
    FEEDBACK_PROTOCOL_VERSION,
    CalibratedSelfAssessment,
    CalibrationHistory,
)

__all__ = [
    "FEEDBACK_PROTOCOL_VERSION",
    "CalibratedSelfAssessment",
    "CalibrationAdjustmentPolicy",
    "CalibrationHistory",
    "MahalanobisDowngradePolicy",
    "assess_with_feedback",
    "build_calibration_history",
]
