"""Reference Policy: ``KillOnlyActuationPolicy`` (ADR-0023).

Policy mínima documentada que demuestra que el contrato
``ActuationPolicy`` es sound.

Mapping (frozen):

+------------------------------+--------------------------------------+---------------------------+
| ``decision.kind``            | ``actuator_command``                 | ``reason``                |
+==============================+======================================+===========================+
| ``ENGAGE_KILL``              | ``DirectMotorCommand([0,0,0,0])``    | ``kill_zero_throttle``    |
+------------------------------+--------------------------------------+---------------------------+
| cualquier otro               | ``None``                             | ``no_command_for_<kind>`` |
+------------------------------+--------------------------------------+---------------------------+

**No es recomendación de control.** Es la validación más simple
posible del shape de la capa de actuación. Hasta que exista un
controlador, sólo ``ENGAGE_KILL`` es traducible sin ambiguedad: zero
throttle es universalmente "stop". Cualquier otra traducción requiere
trayectorias, attitude targets, etc. — eso es controlador, fuera de
scope de ADR-0023.

Determinista, pure, stdlib + numpy (numpy ya transitivamente presente
vía HAL).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

import numpy as np

from project_ghost.core.decisions.types import DecisionKind
from project_ghost.hal.messages.actuators import DirectMotorCommand

from .types import ActuationDirective

if TYPE_CHECKING:
    from project_ghost.core.decisions.types import Decision


_REASON_KILL: Final[str] = "kill_zero_throttle"
_REASON_PREFIX_NO_COMMAND: Final[str] = "no_command_for_"


class KillOnlyActuationPolicy:
    """Policy mínima: ``ENGAGE_KILL`` → zero throttle; cualquier otra
    decisión → directive con ``actuator_command=None``.

    Existe para demostrar que el contrato ``ActuationPolicy`` es
    sound. Operadores reales usan policies operativos (controladores,
    safety supervisors) que se compongan sobre este contrato en ADRs
    futuras.
    """

    POLICY_ID: ClassVar[str] = "kill_only_v1"

    @property
    def policy_id(self) -> str:
        return self.POLICY_ID

    def actuate(self, decision: Decision) -> ActuationDirective:
        if decision.kind == DecisionKind.ENGAGE_KILL:
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
            directive_stamp_sim_ns=decision.decision_stamp_sim_ns,
            policy_id=self.POLICY_ID,
            reason=reason,
        )


__all__ = ["KillOnlyActuationPolicy"]
