"""Reference Trajectory Controller: ``AttitudeHoldReferencePolicy``
(ADR-0029).

Extends ``KillOnlyActuationPolicy`` (ADR-0023) by mapping ``PROCEED``
and ``HOLD`` decisions to ``AttitudeCommand`` instances rather than
``None``.

Mapping (frozen):

- ``PROCEED``     → ``AttitudeCommand(identity, proceed_thrust)``  /
  reason ``attitude_hold_proceed``
- ``HOLD``        → ``AttitudeCommand(identity, hold_thrust)``     /
  reason ``attitude_hold_hold``
- ``ENGAGE_KILL`` → ``DirectMotorCommand([0,0,0,0])``              /
  reason ``kill_zero_throttle``
- any other       → ``None``                                       /
  reason ``no_command_for_<kind>``

Orientation target is always the identity quaternion ``[1, 0, 0, 0]``
(no rotation from body frame). Thrust defaults to 0.5 for both
``proceed_thrust`` and ``hold_thrust``.

No trajectory planning, no belief dependency, no PD/PID gains. This is
the minimal reference that demonstrates ``AttitudeCommand`` round-trips
through the actuation pipeline. Real attitude controllers implement
``ActuationPolicy`` with the same shape and compose over this contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

import numpy as np

from project_ghost.core.decisions.types import DecisionKind
from project_ghost.hal.messages.actuators import (
    AttitudeCommand,
    DirectMotorCommand,
)

from .types import ActuationDirective

if TYPE_CHECKING:
    from project_ghost.core.decisions.types import Decision


_Q_IDENTITY: Final[np.ndarray] = np.array(
    [1.0, 0.0, 0.0, 0.0], dtype=np.float64
)

_REASON_PROCEED: Final[str] = "attitude_hold_proceed"
_REASON_HOLD: Final[str] = "attitude_hold_hold"
_REASON_KILL: Final[str] = "kill_zero_throttle"
_REASON_PREFIX_NO_COMMAND: Final[str] = "no_command_for_"

_THRUST_MIN: Final[float] = 0.0
_THRUST_MAX: Final[float] = 1.0


class AttitudeHoldReferencePolicy:
    """Reference actuation policy: identity attitude + configurable
    thrust for PROCEED and HOLD (ADR-0029).

    Parameters:

    - ``proceed_thrust``: thrust_normalized for PROCEED decisions.
      Default 0.5. Must be in [0.0, 1.0].
    - ``hold_thrust``: thrust_normalized for HOLD decisions.
      Default 0.5. Must be in [0.0, 1.0].

    This policy ensures that ``PROCEED`` and ``HOLD`` decisions produce
    ``AttitudeCommand`` instances (proving the type round-trips), while
    ``ENGAGE_KILL`` still produces zero-throttle ``DirectMotorCommand``.
    All other decision kinds yield ``None``.
    """

    POLICY_ID_BASE: ClassVar[str] = "attitude_hold_v1"

    def __init__(
        self,
        *,
        proceed_thrust: float = 0.5,
        hold_thrust: float = 0.5,
    ) -> None:
        if not (
            np.isfinite(proceed_thrust)
            and _THRUST_MIN <= proceed_thrust <= _THRUST_MAX
        ):
            raise ValueError(
                f"proceed_thrust must be in [{_THRUST_MIN}, {_THRUST_MAX}]; "
                f"got {proceed_thrust}"
            )
        if not (
            np.isfinite(hold_thrust)
            and _THRUST_MIN <= hold_thrust <= _THRUST_MAX
        ):
            raise ValueError(
                f"hold_thrust must be in [{_THRUST_MIN}, {_THRUST_MAX}]; "
                f"got {hold_thrust}"
            )
        self._proceed_thrust: float = float(proceed_thrust)
        self._hold_thrust: float = float(hold_thrust)
        self._policy_id: str = self.POLICY_ID_BASE

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def proceed_thrust(self) -> float:
        return self._proceed_thrust

    @property
    def hold_thrust(self) -> float:
        return self._hold_thrust

    def actuate(self, decision: Decision) -> ActuationDirective:
        stamp = decision.decision_stamp_sim_ns
        if decision.kind == DecisionKind.PROCEED:
            command: AttitudeCommand | DirectMotorCommand | None = (
                AttitudeCommand(
                    q_target=_Q_IDENTITY.copy(),
                    thrust_normalized=self._proceed_thrust,
                    stamp_ns=stamp,
                )
            )
            reason = _REASON_PROCEED
        elif decision.kind == DecisionKind.HOLD:
            command = AttitudeCommand(
                q_target=_Q_IDENTITY.copy(),
                thrust_normalized=self._hold_thrust,
                stamp_ns=stamp,
            )
            reason = _REASON_HOLD
        elif decision.kind == DecisionKind.ENGAGE_KILL:
            command = DirectMotorCommand(
                throttle=np.zeros(4, dtype=np.float64),
            )
            reason = _REASON_KILL
        else:
            command = None
            reason = _REASON_PREFIX_NO_COMMAND + decision.kind.value
        return ActuationDirective(
            decision=decision,
            actuator_command=command,
            directive_stamp_sim_ns=stamp,
            policy_id=self._policy_id,
            reason=reason,
        )


__all__ = ["AttitudeHoldReferencePolicy"]
