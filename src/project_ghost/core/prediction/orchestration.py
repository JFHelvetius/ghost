"""Orquestación canónica de la capa de forward-prediction (ADR-0024).

``forward_predict_and_publish``: one-shot canónico — ejecuta el
predictor, publica la predicción, devuelve la predicción (por si el
caller la necesita aguas abajo).

Pure function (asumiendo predictor y sink puros). Mismo posture que
``decide_and_publish`` (ADR-0021) y ``actuate_and_publish`` (ADR-0023).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_ghost.state.messages import VehicleState

    from .protocols import ForwardPredictionSink, ForwardPredictor
    from .types import BeliefForwardPrediction


def forward_predict_and_publish(
    predictor: ForwardPredictor,
    belief: VehicleState,
    horizon_ns: int,
    sink: ForwardPredictionSink,
    directive_hash: str | None = None,
) -> BeliefForwardPrediction:
    """Ejecuta ``predictor.predict(...)`` y publica al sink.

    Devuelve la predicción — útil cuando el caller necesita el record
    aguas abajo (e.g. para enviarla a un consumer adicional además de
    persistirla en MCAP).
    """
    prediction = predictor.predict(belief, horizon_ns, directive_hash)
    sink.publish(prediction)
    return prediction


__all__ = ["forward_predict_and_publish"]
