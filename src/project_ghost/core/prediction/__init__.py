"""`core.prediction` — capa contractual belief → forward-prediction
(ADR-0024).

Define los shapes mínimos para que el agente se comprometa con una
predicción sobre el futuro, de modo que una observación posterior pueda
refutarla o confirmarla mecánicamente.

- ``BeliefForwardPrediction`` (envelope creencia → predicción de pose
  futura con incertidumbre).
- ``PoseStd`` (desviación típica predicha sobre la pose).
- ``ForwardPredictor`` (Protocol pure function).
- ``ForwardPredictionSink`` (Protocol consumer).
- ``NullForwardPredictionSink`` / ``RecordingForwardPredictionSink``
  (implementaciones de referencia para tests).
- ``ConstantVelocityForwardPredictor`` (predictor mínimo que valida
  que el contrato es sound — no usa el comando).
- ``forward_predict_and_publish`` (orquestación canónica).

Cero modelo dinámico realista. Cero asumir efecto del actuador. Esos
llegan en predictores futuros componiéndose sobre estos shapes. La
divergencia entre predicción y observación llega en ADR-0025.
"""

from __future__ import annotations

from .orchestration import forward_predict_and_publish
from .protocols import ForwardPredictionSink, ForwardPredictor
from .reference_predictor import ConstantVelocityForwardPredictor
from .sinks import NullForwardPredictionSink, RecordingForwardPredictionSink
from .types import (
    PREDICTION_PROTOCOL_VERSION,
    BeliefForwardPrediction,
    PoseStd,
)

__all__ = [
    "PREDICTION_PROTOCOL_VERSION",
    "BeliefForwardPrediction",
    "ConstantVelocityForwardPredictor",
    "ForwardPredictionSink",
    "ForwardPredictor",
    "NullForwardPredictionSink",
    "PoseStd",
    "RecordingForwardPredictionSink",
    "forward_predict_and_publish",
]
