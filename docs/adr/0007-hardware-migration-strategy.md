# ADR-0007 — Hardware Migration Strategy

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

Los proyectos de robótica suelen morir en el "valle de la muerte sim-to-real": el código que vuela bien en simulación se rompe al tocar hardware por una combinación de problemas: latencias reales, ruido real, calibración mala, marco de tiempo distinto, timeouts de red, sensores que fallan, ausencia de groundtruth.

Project Ghost se compromete con hardware real como objetivo declarado. Sin una estrategia explícita de migración, los axiomas de simulación contaminarán decisiones que deberían pensarse pensando en HW desde el inicio.

## Decision

Se adopta una **migración por etapas** con tres saltos controlados, no un único salto sim → real.

### Etapas

| Etapa | Backend | Quién maneja la física | Quién maneja sensores | Quién maneja control |
|---|---|---|---|---|
| **Sim pura** (Fases 1–3) | `PyBulletBackend` | PyBullet | PyBullet sintéticos | Ghost (PIDs propios) |
| **SITL** (Fases 4–7) | `GazeboPx4Backend` | Gazebo Harmonic | Gazebo + plugins | PX4 SITL + Ghost (offboard) |
| **HITL** (Fase 8) | `Px4HitlBackend` | Gazebo | Gazebo, vía MAVLink a Pixhawk real | PX4 firmware en HW + Ghost (offboard) |
| **HW real** (Fase 9+) | `HardwareBackend` | Mundo | Cámara, IMU, etc. reales | PX4 en HW + Ghost en companion computer |

### Decisiones de diseño que la habilitan

1. **HAL congelado desde Fase 1** (ADR-0001).
2. **`RuntimeBackend` separado de `SimulationBackend`.** El primero modela "el mundo corre solo" (hardware y sim free-running), el segundo "yo controlo el tiempo" (sim sincrónica).
3. **Adaptador MAVLink desde Fase 4.** El `GazeboPx4Backend` ya consume comandos de Ghost vía MAVSDK offboard. Mismo path para HITL y HW real.
4. **Niveles de comando jerárquicos** (Direct → Rate → Attitude → Velocity → Position) que mapean 1:1 a PX4 offboard mode.
5. **Convención `SafetyEnvelope`** que se vuelve crítica en HW real (geofence, altura, kill switch).
6. **Manifest por corrida** que marca explícitamente si el run es determinista (sim) o no (HW), evitando comparaciones inválidas.
7. **Calibración como artefacto del repo**, no del backend. Las intrínsecas de cámara, el `T_imu_cam`, las masas y los thrust coefficients viven en `configs/vehicles/` y se cargan tanto en sim como en HW.

### Plataforma target inicial (Fase 9)

- Frame F450 o Holybro X500 v2 económico.
- Autopilot Pixhawk 6C Mini o equivalente.
- Companion computer Raspberry Pi 5 (8 GB) o Orange Pi 5.
- Cámara Raspberry Pi Camera Module 3 o Arducam Global Shutter.
- IMU adicional opcional para redundancia.
- Coste objetivo ≤ 250 USD.

### Salvaguardas obligatorias antes de cualquier vuelo libre

- Kill switch hardware (canal RC dedicado, no software).
- Geofence software activa en PX4 con margen sobre el espacio de prueba.
- RTL configurado.
- Vuelos iniciales indoor o en jaula.
- Telemetría siempre activa, almacenada y revisada antes del siguiente vuelo.

## Consequences

**Positivas:**

- El gap sim-to-real se distribuye en tres saltos pequeños en lugar de uno grande.
- SITL valida el firmware path completo antes de tocar HW.
- HITL valida la Pixhawk exacta antes del primer vuelo libre.
- Reutilización máxima: el ~95% del código de capas 1–7 es idéntico en sim y HW.

**Negativas:**

- Mantener PX4 SITL + HITL implica conocer PX4 a fondo (params, modos, MAVLink). Curva de aprendizaje.
- Convivir con dos paradigmas de tiempo (`SimClock` vs `SystemClock`) añade complejidad en los harnesses.
- Las decisiones tomadas pensando en MAVLink (jerarquía de comandos, ack model) son a veces subóptimas para sim pura.

## Alternatives considered

**A. Salto único sim → HW real saltándose SITL y HITL.** Rechazado: la experiencia industrial muestra que casi nunca funciona; los bugs aparecen en HW donde son caros y peligrosos de depurar.

**B. Construir un autopiloto propio.** Rechazado: scope desmesurado. PX4 y ArduPilot resuelven control rígido del cuadricóptero; Ghost vive **encima**.

**C. ArduPilot en lugar de PX4.** Válido. ArduPilot tiene mejor soporte para algunos sensores y modos. Se deja como segundo target opcional; el adaptador MAVLink sirve para ambos. La elección actual de PX4 se basa en mejor integración con Gazebo Harmonic y MAVSDK más maduro en Python.

**D. Ignorar HW real "hasta que llegue el momento".** Rechazado: las decisiones de Fase 1 (jerarquía de comandos, frames, calibración como artefacto) deben pensarse pensando en HW desde ya, o se pagan después.

**E. Pixhawk Cube Orange / autopilot premium.** Considerado para fiabilidad. Rechazado por coste (~250 USD solo el autopilot). Pixhawk 6C Mini cubre el caso de uso a una fracción.
