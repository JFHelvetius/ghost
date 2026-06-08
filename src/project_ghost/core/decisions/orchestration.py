"""Orquestación canónica de la capa decisión (ADR-0021).

``decide_with_rationale``: ejecuta el policy y construye el
``DecisionRationale`` calculando SHA-256 canónico del self-assessment
del context. Pure function (asumiendo policy pure).

``decide_and_publish``: one-shot canónico para callers runtime.

Stdlib only (``hashlib``, ``json``, ``dataclasses``). NO depende de
``telemetry`` — la dirección de dependencia es ``telemetry -> decisions``,
no al revés. La firma canónica se computa con el mismo posture que
``thresholds_sha256`` (ADR-0020): ``json.dumps(sort_keys=True,
ensure_ascii=False, separators=(",", ":"))`` sobre
``dataclasses.asdict``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import TYPE_CHECKING

from .types import DecisionRationale

if TYPE_CHECKING:
    from project_ghost.core.uncertainty.self_assessment import (
        BeliefSelfAssessment,
    )

    from .protocols import DecisionSink, Policy
    from .types import Decision, DecisionContext


def self_assessment_sha256(
    assessment: BeliefSelfAssessment,
) -> str:
    """SHA-256 hex digest del JSON canónico de ``assessment``.

    Canonical: ``sort_keys=True``, ``ensure_ascii=False``,
    ``separators=(",", ":")`` sobre ``dataclasses.asdict``. Estable
    cross-CPython.

    El hash es la identidad content-addressed del assessment: dos
    assessments con el mismo hash son bit-equal por construcción.
    """
    payload = dataclasses.asdict(assessment)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def decide_with_rationale(
    policy: Policy,
    context: DecisionContext,
) -> tuple[Decision, DecisionRationale]:
    """Ejecuta el policy y construye el rationale.

    Pure function (asumiendo policy pure). El rationale carga:

    - el ``decision`` retornado por el policy,
    - ``belief_stamp_sim_ns`` del context (que el ``DecisionRationale.__post_init__``
      enforza igual al ``decision.decision_stamp_sim_ns``),
    - ``self_assessment_sha256`` calculado del context.self_assessment
      (o ``None`` si no había assessment),
    - ``policy_id`` declarado por el policy.
    """
    decision = policy.decide(context)
    if context.self_assessment is None:
        sa_sha: str | None = None
    else:
        sa_sha = self_assessment_sha256(context.self_assessment)
    rationale = DecisionRationale(
        decision=decision,
        belief_stamp_sim_ns=context.belief_stamp_sim_ns,
        self_assessment_sha256=sa_sha,
        policy_id=policy.policy_id,
    )
    return decision, rationale


def decide_and_publish(
    policy: Policy,
    context: DecisionContext,
    sink: DecisionSink,
) -> Decision:
    """One-shot canónico: decide, construye rationale, publica.

    Retorna el ``Decision`` para que el caller pueda usarlo aguas
    abajo (e.g. emitirlo a un futuro controlador). El rationale se
    publica al sink junto con la decisión; ya no es accesible al
    caller (intencional: el rationale es para audit, no para
    feedback).
    """
    decision, rationale = decide_with_rationale(policy, context)
    sink.publish(decision, rationale)
    return decision


__all__ = [
    "decide_and_publish",
    "decide_with_rationale",
    "self_assessment_sha256",
]
