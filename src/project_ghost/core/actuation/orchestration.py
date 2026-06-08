"""Orquestación canónica de la capa de actuación (ADR-0023).

``actuate_and_publish``: one-shot canónico — ejecuta el policy, publica
el directive, devuelve el directive (por si el caller lo necesita
aguas abajo).

Pure function (asumiendo policy y sink puros).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project_ghost.core.decisions.types import Decision

    from .protocols import ActuationPolicy, ActuationSink
    from .types import ActuationDirective


def actuate_and_publish(
    policy: ActuationPolicy,
    decision: Decision,
    sink: ActuationSink,
) -> ActuationDirective:
    """Ejecuta ``policy.actuate(decision)`` y publica al sink.

    Devuelve el directive — útil cuando el caller necesita el
    ``actuator_command`` aguas abajo (e.g. para enviarlo a hardware
    además de persistirlo en MCAP).
    """
    directive = policy.actuate(decision)
    sink.publish(directive)
    return directive


__all__ = ["actuate_and_publish"]
