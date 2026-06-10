"""Action emission types — el shape de "lo que el agente emite al
actuador" (ADR-0023).

Stdlib only (más ``numpy`` ya transitivamente presente vía HAL para
``ActuatorCommand``). Frozen, pure data, content-addressed por
construcción.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from project_ghost.core.decisions.types import Decision
from project_ghost.hal.messages.actuators import (
    AttitudeCommand,
    DirectMotorCommand,
)

ACTION_PROTOCOL_VERSION: Final[int] = 1

# Same format as DecisionRationale.policy_id and Decision.reason in
# ADR-0021: snake_case, starts with lowercase letter, length 1-64.
# Stable identifiers for auditing; not free text.
_TAXONOMY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_TAXONOMY_MAX_LEN: Final[int] = 64


def _validate_taxonomy(value: str, *, field: str) -> None:
    """Validar identificador snake_case taxonomizado.

    Mismo posture que ``Decision.reason`` y ``DecisionRationale.policy_id``
    en ADR-0021.
    """
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str; got {type(value).__name__}")
    if not value:
        raise ValueError(f"{field} cannot be empty")
    if len(value) > _TAXONOMY_MAX_LEN:
        raise ValueError(f"{field} must be <= {_TAXONOMY_MAX_LEN} chars; got len={len(value)}")
    if not _TAXONOMY_PATTERN.match(value):
        raise ValueError(f"{field} must match {_TAXONOMY_PATTERN.pattern!r}; got {value!r}")


@dataclass(frozen=True)
class ActuationDirective:
    """Envelope que ata una decisión a un comando opcional al actuador.

    ``decision`` es la decisión productora — viaja inline para que el
    directive sea auto-contenido y auditable sin depender del canal
    ``/decisions``.

    ``actuator_command`` es el comando concreto producido por la
    policy. **``None`` es un caso legítimo y explícito**: la policy
    declara que para esta decisión no procede emitir ningún comando
    (ejemplo típico: ``PROCEED`` sin mission planner que defina
    trayectoria).

    ``directive_stamp_sim_ns`` debe matchear
    ``decision.decision_stamp_sim_ns`` (síncrono v1; mismo posture
    que ADR-0021).

    ``policy_id`` y ``reason`` son identificadores snake_case
    taxonomizados — formato cerrado, no catálogo cerrado. Permite
    extensibilidad sin re-versionar el ADR.
    """

    decision: Decision
    actuator_command: AttitudeCommand | DirectMotorCommand | None
    directive_stamp_sim_ns: int
    policy_id: str
    reason: str
    schema_version: int = ACTION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.decision, Decision):
            raise TypeError(f"decision must be Decision; got {type(self.decision).__name__}")
        if self.directive_stamp_sim_ns < 0:
            raise ValueError(
                f"directive_stamp_sim_ns must be >= 0; got {self.directive_stamp_sim_ns}"
            )
        if self.directive_stamp_sim_ns != self.decision.decision_stamp_sim_ns:
            raise ValueError(
                f"directive_stamp_sim_ns ({self.directive_stamp_sim_ns}) "
                f"must equal decision.decision_stamp_sim_ns "
                f"({self.decision.decision_stamp_sim_ns}) — v1 enforces "
                f"synchronous emission"
            )
        if self.actuator_command is not None and not isinstance(
            self.actuator_command, (AttitudeCommand, DirectMotorCommand)
        ):
            raise TypeError(
                "actuator_command must be AttitudeCommand, "
                "DirectMotorCommand, or None; got "
                f"{type(self.actuator_command).__name__}"
            )
        _validate_taxonomy(self.policy_id, field="policy_id")
        _validate_taxonomy(self.reason, field="reason")
        if self.schema_version != ACTION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {ACTION_PROTOCOL_VERSION}; got {self.schema_version}"
            )


__all__ = [
    "ACTION_PROTOCOL_VERSION",
    "ActuationDirective",
]
