"""Protocol estructural de la capa de feedback (ADR-0026, ADR-0040).

Dos protocols:

- ``CalibrationAdjustmentPolicy`` (ADR-0026): pure function shape
  mapping ``(BeliefSelfAssessment, CalibrationHistory) →
  CalibratedSelfAssessment``.
- ``DriftPreconditionProvider`` (ADR-0040): pure function shape
  ``CalibrationHistory → bool`` exposing the policy's *own* judgement
  of whether the history contains evidence of drift. Used by ERUR-v2
  (``verify_erur_v2``) to lift the precondition off Mahalanobis-
  specific ``(M, K)`` parameters to the policy's own contract.

Both are ``@runtime_checkable`` para detección por ``isinstance``.
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


@runtime_checkable
class DriftPreconditionProvider(Protocol):
    """Pure function shape returning *the policy's own* judgement of
    whether the calibration history contains evidence of drift.

    Distinct from ``CalibrationAdjustmentPolicy.adjust``: this method
    answers only the question "would *I* (this policy) consider this
    history as drifted?" — without producing a calibrated assessment.
    A policy that downgrades on drift will return ``True`` exactly on
    histories where its ``adjust`` method downgrades.

    The Protocol is the verifier-side input that lets ERUR-v2 lift
    its precondition off the reference Mahalanobis ``(M, K)``
    parameters. Each calibrator exposes its own drift criterion, the
    verifier delegates, and ERUR-v2 holds iff *every* cycle whose
    policy's own drift criterion is absent (and whose raw belief is
    KNOWN) emits PROCEED. Paper §3.2 (long) and §4 (short) state the
    contract; ``project_ghost.properties.erur_v2.verify_erur_v2``
    implements it.

    Contracts:

    - ``policy_id`` matches the policy's
      ``CalibrationAdjustmentPolicy.policy_id`` (1:1 with the
      ``adjustment_policy_id`` field of the
      ``CalibratedSelfAssessment`` it produces). This is the join
      key used by the v2 verifier to dispatch from
      ``adjustment_policy_id`` (read from the MCAP) to this callable.
    - ``drift_precondition(history)`` is pure: same input → same
      output. No clock, no random, no mutable state.
    - For a policy that *also* implements
      ``CalibrationAdjustmentPolicy``, the contract is that
      ``drift_precondition(h) == True`` iff ``adjust(raw, h)`` would
      downgrade the calibrated level relative to ``raw.overall_level``
      (for any non-INVALID raw level). Enforced by property tests in
      ``tests/properties/test_erur_v2.py``.
    """

    @property
    def policy_id(self) -> str: ...

    def drift_precondition(self, history: CalibrationHistory) -> bool: ...


__all__ = ["CalibrationAdjustmentPolicy", "DriftPreconditionProvider"]
