"""Protocols de la capa de sensor-to-belief fusion (ADR-0028)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .types import FusionInput, FusionResult


@runtime_checkable
class SensorFusionPolicy(Protocol):
    """Pure function shape para producir el belief desde inputs de
    sensores.

    Contratos:

    - ``fusion_policy_id`` es estable durante la vida del objeto.
      Queda en ``FusionResult.fusion_policy_id``.
    - ``fuse(input)`` es pure: mismo input → mismo result. Sin reloj,
      sin random, sin estado mutable visible.
    - El result retornado debe satisfacer
      ``result.belief.stamp_sim_ns == input.target_stamp_sim_ns``
      (enforced documentalmente — la policy es responsable).
    - ``result.fusion_input_sha256`` debe matchear
      ``compute_fusion_input_sha256(input)`` (también responsabilidad
      del policy; tests lo verifican para la reference).
    """

    @property
    def fusion_policy_id(self) -> str: ...

    def fuse(self, fusion_input: FusionInput) -> FusionResult: ...


@runtime_checkable
class FusionResultSink(Protocol):
    """Consumer shape para ``FusionResult``."""

    def publish(self, result: FusionResult) -> None: ...


__all__ = [
    "FusionResultSink",
    "SensorFusionPolicy",
]
