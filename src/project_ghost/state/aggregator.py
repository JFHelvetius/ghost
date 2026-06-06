"""Agregación de `VehicleState` desde fuentes canónicas (T2.a.6).

**Alcance honesto.** Este módulo entrega una sola función:
`vehicle_state_from_ground_truth`. NO entrega un agregador de producción
basado en estimación; ese llegará cuando exista un estimador, y se
llamará `vehicle_state_from_navigation` para hacer explícito el contraste.

**Por qué existe el path GT.** `GroundTruth` solo existe porque los
simuladores poseen información no disponible para vehículos reales (regla
arquitectónica de Project Ghost). En Fase 1 con backends sim-only, esta
información se usa como sustituto de un estimador para construir un
`VehicleState`. El nombre `from_ground_truth` deja claro que esta vía es
**sim-only por construcción**; un Phase 9+ hardware con un estimador
publicará `VehicleState` por el path `from_navigation`.

**Truth y belief son conceptos distintos.** El `VehicleState` producido
por esta función lleva ``nav.covariance_15x15 = None`` deliberadamente.
GT no es una estimación con covarianza pequeña — es la verdad, y se
**rehúsa pretender** que sea una creencia con incertidumbre cuantificada.
Consumidores aguas abajo deben distinguir: si ven ``covariance_15x15
None``, saben que la pose viene del oráculo del simulador, no de un
estimador.

**Propagación de incertidumbre.** En este path no hay propagación: la
covarianza es None. Cuando el path `from_navigation` aterrice, recibirá
un `NavigationState` ya con su covarianza propagada por el estimador
(aguas arriba); el agregador solo lo empaqueta en `VehicleState`.

**Separación sim/runtime.** Función pura, sin reloj, sin random, sin I/O.
Lee de inputs explícitos y construye el resultado. El `stamp_wall_ns`
viene como parámetro — el agregador no lee `time.monotonic_ns()` (ADR-0002).

**Determinismo.** Misma input -> mismo output bit a bit. Las
transformaciones de frame usan `state.transforms` (cuyo determinismo está
testeado en T2.a.5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .messages import (
    IMUBiases,
    NavigationState,
    Pose,
    Twist,
    VehicleState,
)
from .transforms import R_body_to_world, R_world_to_body

if TYPE_CHECKING:
    from project_ghost.hal.messages import GroundTruth

    from .messages import FlightStatus, MissionStatus, SensorHealthMap


def vehicle_state_from_ground_truth(
    *,
    gt: GroundTruth,
    sensors_health: SensorHealthMap,
    flight: FlightStatus,
    mission: MissionStatus,
    stamp_wall_ns: int,
) -> VehicleState:
    """Construye un `VehicleState` desde `GroundTruth` + estado discreto.

    Vía sim-only. ``covariance_15x15`` queda en ``None`` y los biases del
    IMU quedan en cero por contrato: en simulación con GT no hay error
    estimado que reportar. Un consumidor que ve este `VehicleState` puede
    distinguirlo de uno producido por estimador real chequeando
    ``state.nav.covariance_15x15 is None``.

    ``stamp_sim_ns`` se toma de ``gt.stamp_sim_ns`` (acoplado a la fecha
    del oráculo). ``stamp_wall_ns`` se pasa como parámetro — el agregador
    no lee el reloj de pared para preservar determinismo y testabilidad.

    Frame conversions usadas:

    - ``twist_world.angular_rps`` = ``R_body_to_world(q) @ gt.angular_velocity_body_rps``.
    - ``twist_body.linear_mps`` = ``R_world_to_body(q) @ gt.linear_velocity_world_mps``.

    El resto de campos se copian directamente del GroundTruth.
    """
    # Matrices de rotación. Ambas devueltas selladas por `state.transforms`;
    # son lectura-only para las operaciones matriciales aguas abajo.
    r_body_to_world = R_body_to_world(gt.orientation_q)
    r_world_to_body = R_world_to_body(gt.orientation_q)

    # Velocidad angular en world (gt.angular_velocity_body_rps -> world).
    angular_velocity_world_rps = np.ascontiguousarray(
        r_body_to_world @ gt.angular_velocity_body_rps, dtype=np.float64
    )

    # Velocidad lineal en body (gt.linear_velocity_world_mps -> body).
    linear_velocity_body_mps = np.ascontiguousarray(
        r_world_to_body @ gt.linear_velocity_world_mps, dtype=np.float64
    )

    # Construir cada subestructura. Cada dataclass valida y sella su input,
    # así que pasar copias frescas evita compartir vistas selladas que
    # pertenecen al GroundTruth original.
    pose = Pose(
        position_enu_m=gt.position_enu_m.copy(),
        orientation_q=gt.orientation_q.copy(),
    )
    twist_world = Twist(
        linear_mps=gt.linear_velocity_world_mps.copy(),
        angular_rps=angular_velocity_world_rps,
        frame="world",
    )
    twist_body = Twist(
        linear_mps=linear_velocity_body_mps,
        angular_rps=gt.angular_velocity_body_rps.copy(),
        frame="body",
    )

    # IMU biases cero: en simulación con GT el sensor es perfecto.
    # Esto NO es una afirmación sobre los biases del sensor real; es la
    # admisión de que no hay biases que estimar cuando la pose viene del
    # oráculo.
    biases = IMUBiases(
        accel_bias_mps2=np.zeros(3, dtype=np.float64),
        gyro_bias_rps=np.zeros(3, dtype=np.float64),
    )

    # NavigationState con covariance_15x15=None: GT no es una creencia,
    # es la verdad. No se simula incertidumbre estimada.
    nav = NavigationState(
        pose=pose,
        twist_world=twist_world,
        twist_body=twist_body,
        accel_body_mps2=gt.accel_body_mps2.copy(),
        imu_biases=biases,
        covariance_15x15=None,
    )

    return VehicleState(
        stamp_sim_ns=gt.stamp_sim_ns,
        stamp_wall_ns=stamp_wall_ns,
        nav=nav,
        sensors=sensors_health,
        flight=flight,
        mission=mission,
    )


__all__ = ["vehicle_state_from_ground_truth"]
