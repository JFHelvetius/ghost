"""Protocols estructurales de la capa de actuación (ADR-0023).

``ActuationPolicy``: pure function shape mapping ``Decision`` →
``ActuationDirective``.

``ActuationSink``: consumer shape para ``ActuationDirective``.

Ambos ``@runtime_checkable`` para detección por ``isinstance``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from project_ghost.core.decisions.types import Decision

    from .types import ActuationDirective


@runtime_checkable
class ActuationPolicy(Protocol):
    """Pure function shape para producir directives de actuación.

    Contratos:

    - ``policy_id`` es estable durante la vida del objeto. Identifica
      qué policy produjo cada directive (queda en
      ``ActuationDirective.policy_id``).
    - ``actuate(decision)`` es pure: mismo ``Decision`` → mismo
      ``ActuationDirective``. Sin reloj, sin random, sin estado
      mutable visible.
    - El directive retornado debe satisfacer
      ``directive.directive_stamp_sim_ns == decision.decision_stamp_sim_ns``
      (enforced por ``ActuationDirective.__post_init__``).
    - ``actuator_command`` puede ser ``None`` cuando la policy declara
      que para esta decisión no procede emitir comando — caso
      legítimo y explícito.
    """

    @property
    def policy_id(self) -> str: ...

    def actuate(self, decision: Decision) -> ActuationDirective: ...


@runtime_checkable
class ActuationSink(Protocol):
    """Consumer shape para ``ActuationDirective``.

    Contratos:

    - ``publish(directive)`` recibe el directive completo (contiene
      decision + comando + identificadores). No se publica por
      separado.
    - El sink puede validar consistencia interna del directive pero
      no debe modificarlo.
    - No asume reloj de pared. Si necesita timestamps, los lee del
      directive.
    """

    def publish(self, directive: ActuationDirective) -> None: ...


__all__ = [
    "ActuationPolicy",
    "ActuationSink",
]
