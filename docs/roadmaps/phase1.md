# Roadmap — Fase 1

- **Objetivo:** primer sistema ejecutable de Project Ghost: HAL operativo + PyBullet backend + telemetría Rerun/MCAP + control manual + replay determinista.
- **Duración estimada:** 3–4 semanas a foco completo.
- **Precondición:** Fase 0 (cimientos) cerrada: arquitectura, ADRs y specs aprobados.

## Definición de Hecho global

Fase 1 termina cuando un nuevo desarrollador puede:

1. Clonar el repo y ejecutar `python -m project_ghost.run --config configs/phase1/manual_pybullet.yaml`.
2. Ver un quadrotor en PyBullet, volar con teclado o gamepad.
3. Observar estado y cámara en vivo en Rerun.
4. Encontrar el archivo `runs/<run_id>/log.mcap` + `manifest.yaml`.
5. Ejecutar `python -m project_ghost.replay runs/<run_id>` y obtener la misma visualización Rerun reproducida desde el log.
6. Para corridas con inputs sintéticos (script), verificar que dos ejecuciones con misma seed producen `/groundtruth/pose` con hash idéntico.

## Convenciones de las tareas

Cada tarea declara: **Objetivo**, **Dependencias**, **Riesgos**, **Criterios de aceptación**, **Definición de terminado**.

---

## T1 — Scaffold y CI

**Objetivo.** Repo configurado, herramientas listas, CI en verde con suite vacía.

**Dependencias.** Ninguna.

**Riesgos.**
- Diferencias en ruff/mypy entre Linux y Windows.
- pre-commit hooks que no corren en Windows por shebangs.

**Criterios de aceptación.**
- `pip install -e ".[dev,sim,telemetry]"` funciona en Linux y Windows.
- `ruff check`, `ruff format --check`, `mypy`, `deptry src` pasan.
- `pre-commit run --all-files` pasa.
- `pytest` corre (suite vacía) en verde en ambos OS desde CI.
- `python scripts/check_no_global_random.py` corre y reporta 0.

**Definición de terminado.** PR merged a `main`; CI badge en `README.md`; tag `fase1-T1` aplicado.

---

## T2 — Mensajes y schemas del HAL

**Objetivo.** Dataclasses frozen para todos los mensajes (`SensorSample`, payloads, `ActuatorCommand`, `CommandAck`, `VehicleState`, `Event`, `Capabilities`, `ScenarioSpec`). Schemas Protobuf equivalentes en `protos/` con generación automatizada.

**Dependencias.** T1.

**Riesgos.**
- Inconsistencia entre dataclass Python y `.proto` (drift silencioso).
- Convenciones documentadas en specs pero no enforced (orden de cuaternión, unidades).
- Lectores antiguos rotos al añadir campos.

**Criterios de aceptación.**
- Cada dataclass tiene su `.proto` correspondiente.
- Roundtrip Python → Protobuf → Python preserva igualdad.
- Tests de hypothesis para mensajes con arrays: serialización conserva valores y shapes.
- `schema_version` presente en todo mensaje top-level.
- Validación: no se acepta `np.ndarray` con dtype distinto del declarado en docstring.

**Definición de terminado.** Módulo `core.messages` (y `hal.messages`) cubierto por tests. PR merged.

---

## T3 — SimClock determinista y RandomSource

**Objetivo.** `SimClock` con `now_ns`, `step_ns`, `advance`, `schedule`, `schedule_periodic`, `random_source`. `RandomSource` jerárquico con `child(label)` determinista. Scheduler de min-heap. Linter de aleatoriedad afinado contra falsos positivos.

**Dependencias.** T1.

**Riesgos.**
- Falsos positivos del linter rompen contribuciones.
- Bugs sutiles en orden de empates de timestamps.
- Acumulación accidental en `float`.

**Criterios de aceptación.**
- Test `test_clock_monotonic`: tras 10⁶ pasos, monotónico estricto.
- Test `test_periodic_count_exact`: tres callbacks periódicos co-primos (7 ms, 13 ms, 17 ms) tras 10 s, cuentas exactas predecibles.
- Test `test_random_source_deterministic`: dos runs con misma seed y mismas etiquetas hijas producen secuencias idénticas.
- Test `test_no_float_in_arithmetic`: chequeo estático de tipado, no se acepta `float` en API de tiempo.
- Linter `check_no_global_random.py` con cobertura de docstring tests.

**Definición de terminado.** Módulo `core.clock` cubierto > 90%. PR merged.

---

## T4 — Telemetry skeleton (MCAP + Rerun + console)

**Objetivo.** `TelemetryBus` con cola y writer thread. `MCAPFileSink`, `RerunSink`, `ConsoleSink`. Manifest por run.

**Dependencias.** T2 (schemas), T3 (clock).

**Riesgos.**
- Bloqueo del hot loop por backpressure mal manejado.
- MCAP corrupto si el writer no cierra limpio.
- Rerun pesado en CI sin GPU.

**Criterios de aceptación.**
- Stress test: 100k mensajes en 5 canales, MCAP válido (parseable y con índice), conteo correcto.
- `bus.publish()` p99 < 1 ms en máquina de dev (medido).
- `MCAPFileSink.close()` produce índice válido aun bajo SIGINT.
- `RerunSink` configurable para no abrirse en CI (`headless=True`).
- `manifest.yaml` generado con seed, config hash, git sha, sim_time_range.

**Definición de terminado.** Módulo `telemetry` cubierto > 85%. Test de SIGINT pasa. PR merged.

---

## T5 — Event bus

**Objetivo.** `EventBus` con publish, subscribe por tipo, subscribe_all, severities, correlation_id. Integración con telemetry (canal `/events`). Entrega ordenada por `(stamp_sim_ns, sequence)`.

**Dependencias.** T3, T4.

**Riesgos.**
- Deadlocks si un suscriber publica desde dentro de su callback.
- Pérdida de eventos críticos por backpressure.

**Criterios de aceptación.**
- Test `test_total_order_3_producers_5_subscribers`: orden total reproducible.
- Test `test_critical_synchronous_delivery`: handler de safety recibe `KILL` antes del siguiente `step()`.
- Test `test_replay_events_preserves_order`: leer `/events` de MCAP y reinyectar produce la misma secuencia.
- Subscribers que tardan > 50 ms emiten `TELEMETRY_BACKPRESSURE`.

**Definición de terminado.** Módulo `events` cubierto > 85%. PR merged.

---

## T6 — PyBullet backend: física y reset determinista

**Objetivo.** `PyBulletBackend` implementa `SimulationBackend`. Carga URDF de quadrotor (X-frame, parámetros tipo X500/Iris). `reset(seed)` + `step(dt_ns)` deterministas.

**Dependencias.** T2, T3.

**Riesgos.**
- URDF mal modelado: inercias incorrectas, motores invertidos.
- Físicas inestables a paso 1 ms.
- PyBullet no determinista en versiones recientes (revisar `setPhysicsEngineParameter`).

**Criterios de aceptación.**
- Test de caída libre: con motores apagados, posición a t=1 s coincide con `0.5·g·t²` con error < 0.1%.
- Test de reset: dos secuencias `reset(42), step×10000` producen GT idéntico (hash igual).
- Test de monotonía: `clock.now_ns()` avanza exactamente con `step`.
- Backend declara `capabilities.deterministic=True, synchronous_step=True, has_ground_truth=True`.

**Definición de terminado.** `simulation.pybullet.PyBulletBackend` pasa tests físicos y conformance. PR merged.

---

## T7 — PyBullet backend: sensores

**Objetivo.** `IMUProvider`, `RGBCameraProvider`, `AltimeterProvider`, `GpsProvider` (deshabilitado por default por scenario). Cada provider con ruido y bias modelable desde `RandomSource`.

**Dependencias.** T6.

**Riesgos.**
- Render de cámara lento bloquea el step (PyBullet usa OpenGL síncrono).
- Convención de ejes de cámara confusa (OpenGL vs computer vision).
- Ruido implementado como `np.random` global (violación de ADR-0002).

**Criterios de aceptación.**
- IMU produce muestras a 200 Hz (exacto) con jitter cero en sim.
- Cámara RGB a 30 Hz, resolución por defecto 320×240, latencia documentada.
- Test de ruido determinista: con misma seed, traza de IMU es bit-idéntica.
- `GpsProvider` presente pero deshabilitado en scenario `empty_room` (verificado).

**Definición de terminado.** Providers pasan conformance + tests específicos. PR merged.

---

## T8 — PyBullet backend: actuadores

**Objetivo.** `ActuatorSink` nivel 0 (`DirectMotorCommand`) que escribe pares de motores a PyBullet. Mixer X documentado en `actuators.mixer`. SafetyEnvelope mínima (NaN, rangos).

**Dependencias.** T6.

**Riesgos.**
- Convención de signo de motores invertida (motor 0 vs motor 3).
- Coeficiente de thrust mal calibrado: dron no levanta o explota.
- SafetyEnvelope demasiado estricta hace inviable manual flying.

**Criterios de aceptación.**
- Con throttle uniforme calibrado, hover ±10 cm durante 5 s (sin controller, prueba aritmética).
- `send(NaN)` retorna `CommandAck(accepted=False, reason=INVALID_VALUE)`.
- `send` con stale `stamp_ns` (> `command_timeout_ns`) rechazado.
- Hover verificado en escenario `empty_room`.

**Definición de terminado.** Sink pasa conformance. PR merged.

---

## T9 — Agregador de VehicleState

**Objetivo.** Módulo que combina groundtruth + health de sensores + `FlightStatus` + `MissionStatus` y publica `VehicleState` a 50 Hz al bus + telemetría.

**Dependencias.** T2, T5, T7.

**Riesgos.**
- Tentación de meter lógica de estimación aquí. **Prohibido en Fase 1**: pose viene de GT.
- Coste de creación de `VehicleState` (dataclass + arrays) a 50 Hz.

**Criterios de aceptación.**
- `VehicleState` publicado en canal `/state/nav`, persistido en MCAP.
- `schema_version=1`.
- Test: con quadrotor estático, `pose.position_enu_m` corresponde al spawn point con tolerancia ≤ 1 mm.
- Latencia p99 del agregador < 200 µs.

**Definición de terminado.** Módulo `state.aggregator` con tests. PR merged.

---

## T10 — Input manual

**Objetivo.** Lector de teclado y gamepad → `DirectMotorCommand` o (preferentemente) `BodyRateCommand` con un mixer naïve. Soporte de inputs sintéticos para tests deterministas.

**Dependencias.** T8.

**Riesgos.**
- Latencia variable de input degrada determinismo (no es problema para play, sí para benchmark).
- Diferencias entre Linux/Windows en backend de gamepad.
- Threading de input mal coordinado con `SimClock`.

**Criterios de aceptación.**
- Gamepad funcional en Linux (Xbox-class) y Windows.
- Teclado WASD + flechas + space funcional como fallback.
- Modo `--script-input <file.json>` reproduce inputs deterministas.
- Tests con script inputs son bit-deterministas (verificado contra T6).

**Definición de terminado.** Módulo `input` con tests. PR merged. Documentación de bindings en `docs/usage/manual_control.md`.

---

## T11 — Harness de ejecución

**Objetivo.** `python -m project_ghost.run --config configs/phase1/manual_pybullet.yaml` arranca backend, telemetría, bus, input, control passthrough y corre hasta Ctrl-C limpio.

**Dependencias.** T1–T10.

**Riesgos.**
- Cierre sucio deja MCAP corrupto.
- Orden de inicialización frágil (telemetry antes que bus, etc.).
- Configuración YAML mal validada.

**Criterios de aceptación.**
- Run de 60 s produce MCAP válido + manifest completo.
- Ctrl-C dispara cierre limpio: flush, close, evento `MISSION_END` registrado.
- Configuración validada con esquema (pydantic o similar); errores claros si falta campo.
- Test `test_harness_60s_clean_exit`: integración.

**Definición de terminado.** `project_ghost.run` ejecutable. PR merged.

---

## T12 — Replay determinista

**Objetivo.** `python -m project_ghost.replay <run_dir>` lee MCAP, instancia `ReplayBackend` (implementa `SimulationBackend` leyendo log), alimenta bus + Rerun, reproduce visualización idéntica al run original.

**Dependencias.** T4, T5, T6.

**Riesgos.**
- Desincronización por schema mismatch entre versión de log y código actual.
- Replay no reproduce el orden total exacto si el bus tiene heurísticas.
- Imágenes JPEG re-decodificadas no son bit-idénticas (aceptable para visualización; documentar).

**Criterios de aceptación.**
- Replay de un run de 60 s produce los mismos plots en Rerun (verificación visual + hash de `/state/nav`).
- Replay falla con error claro si `schema_version` del MCAP es incompatible.
- Replay puede correr más rápido que tiempo real con flag `--speed 5x`.

**Definición de terminado.** `project_ghost.replay` ejecutable. PR merged.

---

## T13 — Escenario de aceptación

**Objetivo.** Definir `worlds/empty_room.yaml` y `configs/phase1/manual_pybullet.yaml`. Escenario tiene un room 10×10×3 m, quadrotor X500-like, IMU, cámara front, altímetro, GPS (disabled).

**Dependencias.** T11.

**Riesgos.**
- Parámetros de quadrotor irreales hacen ingobernable el dron.
- Escena demasiado simple esconde futuros bugs.

**Criterios de aceptación.**
- Dos runs con misma seed e inputs sintéticos (`script-input/figure_eight.json`) producen `log.mcap` con hash idéntico en `/groundtruth/pose`.
- Demo viable: arrancar, despegar, volar figura-8 ~30 s, aterrizar.
- Manifest declara `deterministic=true` para esta corrida.

**Definición de terminado.** Escenario + script + manifest verificados en CI. PR merged. Demo grabable.

---

## T14 — Conformance suite HAL (mínima)

**Objetivo.** `tests/hal_conformance/` con tests parametrizados por backend.

**Dependencias.** T6, T7, T8 (puede arrancar antes en paralelo definiendo tests, completarse al final).

**Riesgos.**
- Tests acoplados a PyBullet (asumen GT siempre disponible).
- Suite que crece sin paralelización en CI se vuelve lenta.

**Criterios de aceptación.**
- Tests obligatorios (todos los backends los deben pasar): `reset_is_deterministic`, `clock_is_monotonic`, `no_shared_mutation`, `actuator_rejects_nan`, `actuator_accepts_valid_command`, `shutdown_and_recreate`, `capabilities_match_observed`.
- Tests opcionales (controlados por capabilities): determinismo bit-exacto, GT disponible, replay.
- Mock backend falsificado que pasa la suite, usado en tests unitarios.

**Definición de terminado.** Suite ejecutable con `pytest -m conformance`. PR merged.

---

## Plan de ejecución (orden)

```
T1
└─ T2 ── T3
        ├─ T4 ── T5
        ├─ T6 ── T7 ── T8
        │             └─ T14 (arranca aquí en paralelo)
        └─ T9
T8 + T9 ── T10
T10 + T4 + T5 ── T11 ── T12 ── T13
```

Camino crítico: T1 → T2 → T3 → T6 → T7 → T8 → T9 → T10 → T11 → T13.

## Riesgos transversales y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Acoplamiento accidental sim → resto | `import-linter`/`deptry` en CI desde T1 |
| Drift entre dataclass y `.proto` | Tests de roundtrip en T2 |
| Coste de cámara render bloqueando step | Resolución 320×240 default; medir en T7 |
| Determinismo silenciosamente roto | Test de hash en T13, conformance en T14 |
| Backpressure de telemetría | Cola dimensionada en T4 con stress test |
| MCAP corrupto en cierre | Context manager + SIGINT test en T4 y T11 |

## Métricas de salida de Fase 1

Reportadas en `runs/<id>/metrics.json`:

- `harness_p99_loop_latency_us` (target < 1000 µs)
- `telemetry_publish_p99_us` (target < 1000 µs)
- `mcap_size_per_minute_mb` (target < 100 MB con cámara JPEG)
- `bit_exact_replay_passing` (boolean, target true)
- `manual_demo_duration_s` (target ≥ 30 s)

## Lo que **no** se hace en Fase 1

Explícito por contraste con la red team review:

- Sin estimación de estado (T9 usa GT).
- Sin control de actitud cerrado (passthrough manual con mixer naïve).
- Sin perception, sin VO, sin SLAM, sin planning.
- Sin Gazebo, sin PX4, sin MAVLink.
- Sin ROS, sin asyncio elaborado, sin web dashboards.
- Sin políticas de retención de runs (siguen acumulándose).

Cualquier desviación se discute con ADR antes de implementar.
