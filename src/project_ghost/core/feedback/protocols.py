"""Protocol estructural de la capa de feedback (ADR-0026).

``CalibrationAdjustmentPolicy``: pure function shape mapping
``(BeliefSelfAssessment, CalibrationHistory) → CalibratedSelfAssessment``.

``@runtime_checkable`` para detección por ``isinstance``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )

    from .types import CalibratedSelfAssessment, CalibrationHistory


@runtime_checkable
class CalibrationAdjustmentPolicy(Protocol):
    """Pure function shape para producir ``CalibratedSelfAssessment``
    a partir de un assessment crudo + evidencia de outcomes.

    Contratos:

    - ``policy_id`` es estable durante la vida del objeto. Identifica
      qué policy produjo el ajuste (queda en
      ``CalibratedSelfAssessment.adjustment_policy_id``).
    - ``adjust(raw, history)`` es pure: mismo input → mismo output.
      Sin reloj, sin random, sin estado mutable visible.
    - El record retornado debe satisfacer
      ``record.raw_assessment is raw`` y
      ``record.calibration_history is history`` — no se permite
      reemplazar las entradas, sólo derivar el ajuste y los metadatos.
      (Enforced por la signature del Protocol + tests.)
    - La policy es libre de upgrade o downgrade el level; el contrato
      no lo restringe direccionalmente.
    """

    @property
    def policy_id(self) -> str: ...

    def adjust(
        self,
        raw: BeliefSelfAssessment,
        history: CalibrationHistory,
    ) -> CalibratedSelfAssessment: ...


__all__ = ["CalibrationAdjustmentPolicy"]
