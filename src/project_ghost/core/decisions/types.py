"""Decision types — el shape de "lo que el agente decide hacer".

ADR-0021. Contratos puros: catálogo cerrado de `DecisionKind`,
contexto de entrada al policy, decisión emitida, rationale auditable
con content-address al `BeliefSelfAssessment` input.

Stdlib only. Cero IO, cero clock, cero random.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )
    from project_ghost.core.uncertainty.types import PerceptionMode
    from project_ghost.state.messages import FlightStatus, MissionStatus


DECISION_PROTOCOL_VERSION: Final[int] = 1

# Closed format for Decision.reason: snake_case, starts with letter,
# length 1-64. Stable identifier for auditing; not free text.
_REASON_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_REASON_MAX_LEN: Final[int] = 64
_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


class DecisionKind(StrEnum):
    """Catálogo cerrado de decisiones legales del agente.

    Modificar (añadir / renombrar / borrar) requiere ADR amendment
    explícito — mismo posture que ``PerceptionMode``, ``Validity``,
    ``SelfAssessmentLevel``.

    Semántica de cada kind (vinculante):

    - ``PROCEED``: el agente afirma poder continuar la misión con la
      creencia actual.
    - ``HOLD``: el agente afirma que debe sostenerse en posición; su
      creencia no es suficiente para navegar pero sí para no degradarse.
    - ``YIELD_TO_PILOT``: el agente cede autoridad al piloto humano.
    - ``ENGAGE_RTL``: el agente inicia Return-To-Launch por degradación
      de creencia.
    - ``ENGAGE_LAND``: el agente inicia aterrizaje controlado.
    - ``ENGAGE_KILL``: el agente corta thrust por imposibilidad de
      operación segura.
    - ``ABSTAIN_UNCERTAIN``: el agente se abstiene; su creencia no
      soporta ninguna afirmación de acción.
    """

    PROCEED = "proceed"
    HOLD = "hold"
    YIELD_TO_PILOT = "yield_to_pilot"
    ENGAGE_RTL = "engage_rtl"
    ENGAGE_LAND = "engage_land"
    ENGAGE_KILL = "engage_kill"
    ABSTAIN_UNCERTAIN = "abstain_uncertain"


def _validate_reason(reason: str, *, field: str = "reason") -> None:
    if not isinstance(reason, str):
        raise TypeError(
            f"{field} must be str; got {type(reason).__name__}"
        )
    if not reason:
        raise ValueError(f"{field} cannot be empty")
    if len(reason) > _REASON_MAX_LEN:
        raise ValueError(
            f"{field} must be <= {_REASON_MAX_LEN} chars; got "
            f"len={len(reason)}"
        )
    if not _REASON_PATTERN.match(reason):
        raise ValueError(
            f"{field} must match {_REASON_PATTERN.pattern!r}; got "
            f"{reason!r}"
        )


def _validate_sha256(value: str | None, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be str or None; got {type(value).__name__}"
        )
    if len(value) != _SHA256_HEX_LEN:
        raise ValueError(
            f"{field} must be {_SHA256_HEX_LEN} hex chars; got "
            f"len={len(value)}"
        )
    for c in value:
        if c not in _HEX_CHARS:
            raise ValueError(
                f"{field} must be lowercase hex; got {value!r}"
            )


@dataclass(frozen=True)
class DecisionContext:
    """Lo que el ``Policy`` ve en entrada para producir una decisión.

    Auto-contenido (no holds references a estado mutable) para que
    ``Policy.decide`` sea pure function: mismo context → misma decisión.

    ``self_assessment`` es ``None`` cuando no hay introspección
    disponible (e.g. el caller no wireó ``assess_belief``). Una policy
    bien comportada en ese caso debería emitir ``ABSTAIN_UNCERTAIN``
    con reason ``no_assessment`` — el agente reconoce que no puede ni
    siquiera afirmar qué cree saber.

    ``perception_mode`` es opcional; presente cuando un
    ``PerceptionModeDetector`` esté wireado.
    """

    belief_stamp_sim_ns: int
    self_assessment: BeliefSelfAssessment | None
    flight_status: FlightStatus
    mission_status: MissionStatus
    perception_mode: PerceptionMode | None
    schema_version: int = DECISION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.belief_stamp_sim_ns < 0:
            raise ValueError(
                f"belief_stamp_sim_ns must be >= 0; got "
                f"{self.belief_stamp_sim_ns}"
            )
        if self.schema_version != DECISION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {DECISION_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


@dataclass(frozen=True)
class Decision:
    """La afirmación clasificatoria del agente sobre qué decide hacer.

    ``kind`` viene del catálogo cerrado ``DecisionKind``.
    ``decision_stamp_sim_ns`` debe matchear el ``belief_stamp_sim_ns``
    del context que la produjo — la decisión es reactiva síncrona en
    v1 (sin desfase temporal).

    ``reason`` es un identificador estable taxonomizado por formato:
    snake_case (``^[a-z][a-z0-9_]*$``, longitud 1-64). No es free text;
    es la identidad clasificatoria de por qué se tomó esta decisión.
    """

    kind: DecisionKind
    decision_stamp_sim_ns: int
    reason: str
    schema_version: int = DECISION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DecisionKind):
            raise TypeError(
                f"kind must be DecisionKind; got {type(self.kind).__name__}"
            )
        if self.decision_stamp_sim_ns < 0:
            raise ValueError(
                f"decision_stamp_sim_ns must be >= 0; got "
                f"{self.decision_stamp_sim_ns}"
            )
        _validate_reason(self.reason)
        if self.schema_version != DECISION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {DECISION_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


@dataclass(frozen=True)
class DecisionRationale:
    """Artefacto auditable que ata una decisión a sus inputs.

    Content-addressed vía SHA-256 canónico del ``BeliefSelfAssessment``
    que produjo el context. Permite verificación bit-a-bit de la
    cadena belief → assessment → rationale → decision.

    ``decision`` y ``belief_stamp_sim_ns`` deben ser consistentes:
    ``decision.decision_stamp_sim_ns == belief_stamp_sim_ns`` (v1
    reactivo síncrono).

    ``self_assessment_sha256`` es ``None`` sólo cuando el context tenía
    ``self_assessment is None`` — el rationale acepta abiertamente que
    la decisión se tomó sin introspección.

    ``policy_id`` es el identificador estable del policy productor.
    """

    decision: Decision
    belief_stamp_sim_ns: int
    self_assessment_sha256: str | None
    policy_id: str
    schema_version: int = DECISION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.decision, Decision):
            raise TypeError(
                f"decision must be Decision; got "
                f"{type(self.decision).__name__}"
            )
        if self.belief_stamp_sim_ns < 0:
            raise ValueError(
                f"belief_stamp_sim_ns must be >= 0; got "
                f"{self.belief_stamp_sim_ns}"
            )
        if self.belief_stamp_sim_ns != self.decision.decision_stamp_sim_ns:
            raise ValueError(
                f"belief_stamp_sim_ns ({self.belief_stamp_sim_ns}) must "
                f"equal decision.decision_stamp_sim_ns "
                f"({self.decision.decision_stamp_sim_ns}) — v1 enforces "
                f"reactive synchronous decisions"
            )
        _validate_sha256(
            self.self_assessment_sha256, field="self_assessment_sha256"
        )
        _validate_reason(self.policy_id, field="policy_id")
        if self.schema_version != DECISION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {DECISION_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


__all__ = [
    "DECISION_PROTOCOL_VERSION",
    "Decision",
    "DecisionContext",
    "DecisionKind",
    "DecisionRationale",
]
