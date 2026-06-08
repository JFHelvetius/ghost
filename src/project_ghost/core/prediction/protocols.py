"""Protocols estructurales de la capa de forward-prediction (ADR-0024).

``ForwardPredictor``: pure function shape mapping
``(belief, horizon_ns, directive_hash) → BeliefForwardPrediction``.

``ForwardPredictionSink``: consumer shape para
``BeliefForwardPrediction``.

Ambos ``@runtime_checkable`` para detección por ``isinstance``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from project_ghost.state.messages import VehicleState

    from .types import BeliefForwardPrediction


@runtime_checkable
class ForwardPredictor(Protocol):
    """Pure function shape para producir predicciones forward.

    Contratos:

    - ``predictor_id`` es estable durante la vida del objeto. Identifica
      qué predictor produjo cada record (queda en
      ``BeliefForwardPrediction.predictor_id``).
    - ``predict(belief, horizon_ns, directive_hash)`` es pure: misma
      entrada → misma ``BeliefForwardPrediction``. Sin reloj, sin
      random, sin estado mutable visible.
    - El record retornado debe satisfacer
      ``record.source_belief_stamp_sim_ns == belief.stamp_sim_ns`` y
      ``record.horizon_ns == horizon_ns`` (enforced por
      ``BeliefForwardPrediction.__post_init__``).
    - ``directive_hash`` opcional: si se pasa, viaja en
      ``record.associated_directive_hash``; si es ``None``, el record
      lo refleja también como ``None`` (forecasting standalone).
    """

    @property
    def predictor_id(self) -> str: ...

    def predict(
        self,
        belief: VehicleState,
        horizon_ns: int,
        directive_hash: str | None = None,
    ) -> BeliefForwardPrediction: ...


@runtime_checkable
class ForwardPredictionSink(Protocol):
    """Consumer shape para ``BeliefForwardPrediction``.

    Contratos:

    - ``publish(prediction)`` recibe el record completo. No se publica
      por separado.
    - El sink puede validar consistencia interna pero no debe modificar
      el record.
    - No asume reloj de pared. Si necesita timestamps, los lee del
      record (``source_belief_stamp_sim_ns``).
    """

    def publish(self, prediction: BeliefForwardPrediction) -> None: ...


__all__ = [
    "ForwardPredictionSink",
    "ForwardPredictor",
]
