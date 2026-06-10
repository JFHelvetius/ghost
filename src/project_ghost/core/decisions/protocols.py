"""Decision Protocols — los contratos estructurales (ADR-0021).

``Policy``: pure function shape mapping ``DecisionContext`` → ``Decision``.
``DecisionSink``: consumer shape para records `(decision, rationale)`.

Ambos ``@runtime_checkable`` para que ``isinstance`` lo detecte (útil
para tests y validación de wiring).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .types import Decision, DecisionContext, DecisionRationale


@runtime_checkable
class Policy(Protocol):
    """Pure function shape para producir decisiones.

    Contratos:

    - ``policy_id`` es estable durante la vida del objeto. Identifica
      qué policy produjo cada decisión (usado en
      ``DecisionRationale.policy_id``).
    - ``decide(context)`` es pure: mismo context → mismo Decision.
      Sin reloj, sin random, sin estado mutable visible.
    - El Decision retornado debe satisfacer
      ``decision.decision_stamp_sim_ns == context.belief_stamp_sim_ns``
      (v1 reactivo síncrono — enforced por ``DecisionRationale.__post_init__``).
    - Las decisiones deben venir del catálogo cerrado ``DecisionKind``.
    """

    @property
    def policy_id(self) -> str: ...

    def decide(self, context: DecisionContext) -> Decision: ...


@runtime_checkable
class DecisionSink(Protocol):
    """Consumer shape para records `(decision, rationale)` justificados.

    Contratos:

    - ``publish`` recibe SIEMPRE los dos. No se puede publicar una
      decisión sin su rationale — este es el enforcement contractual
      de "ninguna decisión sin justificación".
    - El sink puede validar consistencia (e.g. ``rationale.decision ==
      decision``) pero no debe modificar ninguno de los inputs.
    - El sink no asume reloj de pared. Si necesita timestamps, los
      lee del ``decision``.
    - El sink debe ser tolerante a publish() repetido con los mismos
      objetos (no requerido por el Protocol, pero recomendado para
      replay y testing).
    """

    def publish(self, decision: Decision, rationale: DecisionRationale) -> None: ...


__all__ = [
    "DecisionSink",
    "Policy",
]
