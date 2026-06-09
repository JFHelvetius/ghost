"""Orquestación canónica de la capa de fusion (ADR-0028)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocols import FusionResultSink, SensorFusionPolicy
    from .types import FusionInput, FusionResult


def fuse_and_publish(
    policy: SensorFusionPolicy,
    fusion_input: FusionInput,
    sink: FusionResultSink,
) -> FusionResult:
    """Ejecuta ``policy.fuse(input)`` y publica al sink.

    Pure (asumiendo policy y sink puros). Devuelve el result — útil
    cuando el caller necesita el belief aguas abajo (e.g. para
    feedearlo a ``assess_belief`` además de persistirlo).
    """
    result = policy.fuse(fusion_input)
    sink.publish(result)
    return result


__all__ = ["fuse_and_publish"]
