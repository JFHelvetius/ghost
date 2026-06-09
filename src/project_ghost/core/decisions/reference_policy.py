"""Reference Policy: ``UncertaintyAwareReferencePolicy`` (ADR-0021;
calibration-aware via ADR-0027).

Policy mínima documentada que demuestra que el contrato ``Policy``
es sound: mapea ``SelfAssessmentLevel.{KNOWN, UNCERTAIN, UNKNOWN}``
a ``DecisionKind.{PROCEED, HOLD, ABSTAIN_UNCERTAIN}`` respectivamente.

Desde ADR-0027 lee ``context.effective_overall_level`` en lugar de
``context.self_assessment.overall_level``. Cuando el caller wirea
``calibrated_self_assessment``, el ajuste calibrado tiene prioridad.
Sin calibrated wireado, el comportamiento es idéntico al de
ADR-0021.

**No es una recomendación de control.** Es la validación más simple
posible del shape de la capa. Operadores reales usan policies más
sofisticados (tier 0/1 safety, pilot override, mission planner) que
serán ADRs futuras.

**Observacional, no actuativa.** El reference policy NO emite
``YIELD_TO_PILOT``, ``ENGAGE_RTL``, ``ENGAGE_LAND``, ``ENGAGE_KILL`` —
esos kinds del catálogo cerrado quedan reservados para policies
operativos. ``PROCEED`` = "afirmo poder navegar", ``HOLD`` = "afirmo
debo esperar", ``ABSTAIN`` = "afirmo no poder decidir".

Determinista, pure, stdlib-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from project_ghost.core.uncertainty.self_assessment import (
    SelfAssessmentLevel,
)

from .types import Decision, DecisionKind

if TYPE_CHECKING:
    from .types import DecisionContext


# Catalog of reasons used by this reference policy. Estables, snake_case.
_REASON_NO_ASSESSMENT: Final[str] = "no_assessment"
_REASON_OVERALL_UNKNOWN: Final[str] = "overall_unknown"
_REASON_OVERALL_UNCERTAIN: Final[str] = "overall_uncertain"
_REASON_OVERALL_KNOWN: Final[str] = "overall_known"


class UncertaintyAwareReferencePolicy:
    """Reference policy uncertainty-aware.

    Mapeo (frozen):

    +-------------------------------+----------------------+----------------------+
    | input                         | DecisionKind         | reason               |
    +===============================+======================+======================+
    | self_assessment is None       | ABSTAIN_UNCERTAIN    | no_assessment        |
    +-------------------------------+----------------------+----------------------+
    | overall_level == UNKNOWN      | ABSTAIN_UNCERTAIN    | overall_unknown      |
    +-------------------------------+----------------------+----------------------+
    | overall_level == UNCERTAIN    | HOLD                 | overall_uncertain    |
    +-------------------------------+----------------------+----------------------+
    | overall_level == KNOWN        | PROCEED              | overall_known        |
    +-------------------------------+----------------------+----------------------+

    No usa ``flight_status``, ``mission_status`` ni ``perception_mode``
    del context. Policies futuras (e.g. uno que respete RTL si
    battery_pct bajo) los consumirán.
    """

    POLICY_ID: ClassVar[str] = "uncertainty_aware_reference_v1"

    @property
    def policy_id(self) -> str:
        return self.POLICY_ID

    def decide(self, context: DecisionContext) -> Decision:
        stamp = context.belief_stamp_sim_ns
        level = context.effective_overall_level

        if level is None:
            return Decision(
                kind=DecisionKind.ABSTAIN_UNCERTAIN,
                decision_stamp_sim_ns=stamp,
                reason=_REASON_NO_ASSESSMENT,
            )

        if level == SelfAssessmentLevel.UNKNOWN:
            return Decision(
                kind=DecisionKind.ABSTAIN_UNCERTAIN,
                decision_stamp_sim_ns=stamp,
                reason=_REASON_OVERALL_UNKNOWN,
            )

        if level == SelfAssessmentLevel.UNCERTAIN:
            return Decision(
                kind=DecisionKind.HOLD,
                decision_stamp_sim_ns=stamp,
                reason=_REASON_OVERALL_UNCERTAIN,
            )

        # SelfAssessmentLevel.KNOWN
        return Decision(
            kind=DecisionKind.PROCEED,
            decision_stamp_sim_ns=stamp,
            reason=_REASON_OVERALL_KNOWN,
        )


__all__ = ["UncertaintyAwareReferencePolicy"]
