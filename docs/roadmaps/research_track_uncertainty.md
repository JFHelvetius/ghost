# Roadmap — Research Track: Autonomía bajo incertidumbre (U1–U6)

- **Objetivo del track:** desarrollar, validar y endurecer la maquinaria de incertidumbre del sistema, en paralelo a las fases de implementación.
- **Cobertura ADRs:** ADR-0008 (mecanismo), ADR-0009 (política).
- **Specs vinculantes:** `docs/specs/uncertainty.md`, `docs/specs/perception.md`, `docs/specs/mission.md`.
- **Carácter:** investigación + ingeniería. Cada U produce código en `src/`, datasets reproducibles, pruebas adversariales y un informe corto.

## Relación con las fases del producto

El track de incertidumbre **no sustituye** las fases del producto (Fase 0–9). Corre en paralelo: cada `Ux` se acopla con una fase del producto que ya provee la base perceptual o de control necesaria.

```
Fases producto:  0 ── 1 ── 2 ── 3 ── 4 ── 5 ── 6 ── 7 ── 8 ── 9
Track U:                   U1 ── U2 ── U3 ── U4 ── U5 ── U6
                           │     │     │     │     │     │
                           │     │     │     │     │     └─ Hardware uncertainty
                           │     │     │     │     └─────── Adversarial + benchmarks
                           │     │     │     └───────────── Active perception loop
                           │     │     └─────────────────── Uncertainty-aware planning
                           │     └───────────────────────── Filter-level inflation
                           └─────────────────────────────── Mechanism in code
```

## Convenciones de cada U

Cada U declara: **Objetivo**, **Dependencias**, **Entregables**, **Criterios cuantitativos de aceptación**, **Definición de terminado**, **Riesgos abiertos**.

---

## U1 — Mechanism in code

**Objetivo.** Llevar a código el mecanismo de ADR-0008: tipos `Estimate[T]`, `Validity`, `EstimateSource`, `PerceptionMode`, helpers de `core.uncertainty` y telemetría de modo. Sin productores reales todavía; solo el esqueleto + tests de propiedad.

**Dependencias.** Fase 1 cerrada (HAL, clock, telemetry, events operativos). T1, T2, T3 del roadmap de producto.

**Entregables.**

- Módulo `core.uncertainty` con todos los tipos y helpers de `docs/specs/uncertainty.md` §2 y §8.
- Canal `/perception/mode` declarado en telemetry y `PerceptionModeDetector` con FSM (sin productores reales conectados, alimentado por mocks).
- Suite de tests de propiedad (`hypothesis`) sobre simetría, PSD, sealing, downgrade por edad, composición de validity.
- Notebook reproducible `notebooks/u1_uncertainty_envelope.ipynb` que ilustra el envelope con datos sintéticos.

**Criterios cuantitativos.**

- Cobertura de `core.uncertainty` > 90 %.
- 100 % de los tests obligatorios listados en `uncertainty.md` §11 pasan en CI Linux y Windows.
- Throughput de `make_estimate` ≥ 100 k/s en máquina dev (medido y reportado en `runs/u1/metrics.json`).
- FSM del detector no oscila bajo entrada sintética alternante con cadencia < `nominal_hold_ms / 2` (verificado en test).

**Definición de terminado.** PR merged a `main`; tag `u1`; informe corto `docs/research/u1_report.md` con resultados de los benchmarks.

**Riesgos abiertos.**

- Costo de simetrización y verificación PSD en hot path. Mitigación: helper con flag `skip_psd_check` para uso interno controlado.
- Telemetría de modo demasiado verbosa. Mitigación: histeresis ya impuesta por FSM + submuestreo.

---

## U2 — Filter-level inflation

**Objetivo.** Implementar los modelos de inflación de covarianza de `uncertainty.md` §5 dentro del primer estimador real (EKF de Fase 3). Demostrar que la covarianza inflada es **calibrada**: la sigma reportada no es ni optimista ni pesimista por más de un factor 2 sobre verdad de campo en PyBullet.

**Dependencias.** U1; Fase 3 producto (EKF + IMU preintegrado, primer VO). T6–T9 del roadmap.

**Entregables.**

- `core.uncertainty.inflate_*` integrado en EKF y en productores perceptuales.
- Dataset reproducible `datasets/u2_calibration/`: 30 trayectorias PyBullet con perturbaciones controladas (ruido IMU, drop frames, low texture sintético).
- Métrica de calibración: NEES (Normalized Estimation Error Squared) sobre las trayectorias.
- Informe `docs/research/u2_report.md` con curvas de calibración por modo.

**Criterios cuantitativos.**

- NEES medio dentro de `[0.5, 2.0]` sobre el dataset completo en modo `NOMINAL`.
- NEES medio dentro de `[0.3, 3.0]` en modos `LOW_TEXTURE` y `LOW_LIGHT` (más permisivo, refleja que la inflación debe ser conservadora).
- **Tail coverage:** fracción de muestras donde `|err_verdadero|` está dentro de `3σ` reportado ≥ 99 % en `NOMINAL`; ≥ 97 % en modos degradados. NEES por sí solo es una métrica de calibración estadística, no de seguridad; tail coverage captura específicamente la cola del error, que es la que en hardware termina causando incidentes (ver `uncertainty_red_team_review.md` §2.5).
- **Worst-case ratio:** máximo de `|err_verdadero| / σ_reportado` sobre todo el dataset ≤ 5.0. El umbral no es 3.0 porque queremos margen contra escenarios no observados durante U2.
- En modo `STALE`, la sigma reportada crece monotónicamente con la edad en al menos el 99 % de las muestras.
- No regresión: tests de Fase 1 siguen pasando.

**Definición de terminado.** PR merged; tag `u2`; dataset publicado dentro del repo o, si supera 100 MB, en release de GitHub.

**Riesgos abiertos.**

- Inflación calibrada en PyBullet puede ser miscalibrada en Gazebo o hardware. Mitigación documentada: revisitar `Q_dr` y `α` en U6.
- Modelo direccional (§5.2) asume rotación cámara-mundo precisa; con sigma alta de actitud puede ser inestable. Test específico.

---

## U3 — Uncertainty-aware planning

**Objetivo.** Implementar el planner descrito en `mission.md` §3–§5: presupuestos por goal, modelo forward, rechazo de planes que excedan presupuesto, inserción de sub-goals `ACTIVE_PERCEPTION`. Demostrar que el planner prefiere caminos menos inciertos cuando hay alternativas equivalentes en distancia.

**Dependencias.** U1, U2; Fase 5 producto (primer planner real, A* o RRT*). Spec `mission.md` congelado.

**Entregables.**

- Módulo `mission.planner` con scorer que combina costo de distancia y costo de incertidumbre forward.
- Suite de escenarios `tests/scenarios/u3/`: ambientes con áreas texturadas y áreas pobres; el planner debe elegir el camino texturado cuando la diferencia de longitud es ≤ 20 %.
- **Registro de perfiles de escena** (`registries/scene_profiles.yaml`): primera versión poblada con perfiles texturados y pobres usados en las escenas U3. Sin este registro, `mission.md §4.5` deja el `pessimism_factor` por default en 2.0 (escena no caracterizada). U3 baja explícitamente perfiles a 1.0 donde corresponda.
- Métricas: tasa de planes que cumplen el presupuesto declarado en ≥ 100 ejecuciones por escenario.
- Informe `docs/research/u3_report.md`.

**Criterios cuantitativos.**

- En escenarios con alternativa texturada disponible, el planner elige texturada en > 95 % de las corridas.
- 0 violaciones silenciosas de presupuesto (toda violación genera `MISSION_REPLAN` con `reason="budget_exceeded"`).
- Tiempo de planning p99 < 200 ms para escenarios de 50 m × 50 m.
- Replay determinista: misma seed + misma escena = mismo plan, hash idéntico de `MissionPlan.sequence`.

**Definición de terminado.** PR merged; tag `u3`; nuevas escenas añadidas al conformance.

**Riesgos abiertos.**

- Modelo forward de §4 puede subestimar crecimiento real bajo perturbación adversarial. Mitigación: U5 cubre adversarial.
- Sub-goals `ACTIVE_PERCEPTION` mal diseñados pueden generar bucles. Test específico de no-loop.

---

## U4 — Active perception loop

**Objetivo.** Convertir `ACTIVE_PERCEPTION` en una primitiva ejecutable: yaw scan, ascenso lento, revisita de landmark. Cada primitiva tiene política de éxito/fallo cuantitativa y debe **reducir** la sigma observada de manera medible en el dataset.

**Dependencias.** U3; Fase 5–6 producto (planner + behaviors); SLAM básico de Fase 4 (para revisita de landmark).

**Entregables.**

- Módulo `mission.behaviors.active_perception` con primitivas `YawScan`, `SlowAscend`, `RevisitLandmark`.
- Criterio de éxito por primitiva (reducción de sigma de posición ≥ X %).
- Dataset `datasets/u4_active/`: 50 ejecuciones por primitiva en escenarios pobres en features.
- Informe `docs/research/u4_report.md` con histogramas de reducción de sigma pre/post primitiva.

**Criterios cuantitativos.**

- `YawScan` reduce sigma horizontal en mediana ≥ 30 % cuando se ejecuta tras entrar a `LOW_TEXTURE`.
- `SlowAscend` reduce sigma vertical en mediana ≥ 40 % cuando se ejecuta tras `LOW_LIGHT`.
- `RevisitLandmark` reduce sigma horizontal en mediana ≥ 60 % cuando se ejecuta con landmark a ≤ 5 m.
- Tasa de éxito agregada de primitivas > 70 %; fallos producen evento `ACTIVE_PERCEPTION_FAILED` con causa.

**Definición de terminado.** PR merged; tag `u4`; primitivas integradas en planner via U3.

**Riesgos abiertos.**

- Las primitivas pueden interferir con safety invariants (`max_altitude_m`). Test obligatorio: T0 las recorta correctamente.
- Revisita de landmark exige memoria persistente entre runs si la sesión es larga; fuera de scope para U4 (sesión única).

---

## U5 — Adversarial campaign + benchmarks

**Objetivo.** Construir una campaña adversarial sistemática contra el sistema completo (perception + estimación + planning + behaviors): condiciones de luz extremas, pérdida temporal de cámara, drift inducido en IMU, ambientes repetitivos visuales. Establecer benchmarks comparables con literatura (EuRoC, TUM-VI) en lo aplicable.

**Dependencias.** U1–U4; Fase 6 producto (navegación autónoma). Disponibilidad de Gazebo+PX4 SITL si avanzó por ahí.

**Entregables.**

- Suite `tests/adversarial/u5/` con escenarios paramétricos: luz, ruido, oclusión, textura.
- Benchmark report contra mínimo dos secuencias de EuRoC adaptadas al pipeline (con adaptador de frames si se mantiene ENU/FLU).
- Métricas de degradación: tasa de `PERCEPTION_DEAD`, tiempo medio en `DEGRADED`, ATE (Absolute Trajectory Error) por escenario.
- Informe `docs/research/u5_report.md` con comparación contra al menos un baseline publicado.

**Criterios cuantitativos.**

- ATE p50 ≤ 0.15 m sobre 60 s de vuelo en escenarios `NOMINAL`.
- ATE p50 ≤ 0.5 m sobre 60 s en escenarios `LOW_TEXTURE` (con reducción de velocidad esperada).
- Tasa de `PERCEPTION_DEAD` < 1 % del tiempo de vuelo en escenarios adversariales no-extremos.
- Cero violaciones de safety invariants (T0) durante toda la campaña.

**Definición de terminado.** PR merged; tag `u5`; informe linkable desde README. Datasets publicados.

**Riesgos abiertos.**

- Adaptación de EuRoC a ENU/FLU puede ser costosa. Si no se completa, documentar como deuda técnica y diferir a U6.
- Benchmarks de literatura usan métricas ligeramente distintas; documentar las diferencias.

---

## U6 — Hardware uncertainty

**Objetivo.** Transferir los modelos de incertidumbre validados en simulación a hardware real (Fase 9). Recalibrar `Q_dr`, `α`, factores direccionales y thresholds del catálogo de modos sobre dataset capturado por la plataforma real. Demostrar que el sistema mantiene las garantías de honestidad sobre la incertidumbre fuera del simulador.

**Duración estimada.** 3–4 meses de trabajo dedicado, asumiendo hardware disponible al inicio. Desglose realista:

- 1 semana de calibración cámara–IMU (rehacerse cada vez que cambie el rig o entre sesiones largas).
- 1–2 semanas de bring-up de MoCap o RTK como groundtruth externo.
- 2–3 semanas de captura de dataset, incluyendo crashes, debug de ESCs, baterías muertas, GPS denegado en interior, fallos transitorios.
- 2 semanas de análisis y recalibración de parámetros.
- 1 semana de redacción del informe comparativo.
- **Total mínimo absoluto:** 7 semanas. **Realista con contratiempos hardware:** 12–16 semanas. Si los recursos no alcanzan, degradar U6 a "esquema parcial" con scope reducido documentado en `docs/research/u6_partial.md`, y abrir U7 para completar la recalibración faltante.

Esta calibración temporal cierra el riesgo identificado en `uncertainty_red_team_review.md` §2.8.

**Dependencias.** U1–U5; Fase 9 producto (hardware operativo); calibración cámara-IMU completa.

**Entregables.**

- Dataset `datasets/u6_hardware/`: ≥ 20 vuelos reales con groundtruth externo (MoCap o RTK, si disponible).
- Recalibración de todos los parámetros numéricos de `uncertainty.md` para hardware; publicada en `configs/hardware/uncertainty.yaml`.
- Informe comparativo `docs/research/u6_report.md`: sim vs hardware, qué se mantiene, qué cambia, qué no extrapola.
- Lista de bugs descubiertos contra ADR-0008 y ADR-0009; cada uno cerrado o documentado como deuda con ADR de seguimiento.

**Criterios cuantitativos.**

- NEES medio (sigma reportada vs verdad MoCap) dentro de [0.5, 3.0] sobre el dataset hardware completo.
- Misión autónoma "despegar → cruzar room → aterrizar" exitosa con métrica de éxito ≥ 90 % de los intentos.
- 0 incidentes de seguridad (definido como cualquier evento `SAFETY_VIOLATION` no anticipado).
- Tasa de `PERCEPTION_DEAD` por escenario hardware documentada y razonable (< 5 % esperado en interior bien iluminado).

**Definición de terminado.** PR merged; tag `u6`; documento `docs/research/u6_report.md` linkado en README como "estado de la maquinaria de incertidumbre en hardware". Cierre formal del track de investigación; cualquier extensión posterior abre un nuevo track.

**Riesgos abiertos.**

- Acceso a MoCap o RTK es caro/restringido; alternativa documentada (ArUco grid + cámara externa) tiene precisión limitada.
- Drift de calibración cámara-IMU entre sesiones puede confundir métricas; protocolo de re-calibración por sesión obligatorio.

---

## Plan de ejecución global del track

```
U1
└─ U2 ── U3 ── U4
              └─ U5
                  └─ U6
```

Camino crítico: U1 → U2 → U3 → U4 → U5 → U6. Cada U debe terminar (tag + informe) antes de iniciar la siguiente, con una excepción declarada: U5 puede arrancar en paralelo con la fase final de U4 si los recursos lo permiten.

## Riesgos transversales del track

| Riesgo | Mitigación |
|---|---|
| Parámetros calibrados en sim no transfieren a hardware | U6 explícitamente recalibra; sin asumir transferencia |
| Catálogo de modos resulta incompleto en hardware | ADR de superseder ADR-0008 con extensión; sin parches silenciosos |
| Inflación calibrada bloquea misiones que sí son seguras (over-conservative) | U2 establece banda calibrada [0.5, 2.0] NEES; rechazo de hyper-inflación |
| Active perception entra en bucles | Test de no-loop en U4; timeout duro por sub-goal |
| Benchmarks contra literatura no son comparables | Documentar adaptación; reportar métrica nativa además de la adaptada |

## Métricas de salida del track

Reportadas globalmente al cerrar U6 en `docs/research/uncertainty_track_summary.md`:

- NEES sim, NEES hardware.
- Tasa de éxito de active perception por primitiva.
- ATE en escenarios baseline (NOMINAL + LOW_TEXTURE + LOW_LIGHT).
- Tasa de violaciones de safety durante toda la campaña adversarial.
- Diferencial sim↔hardware de cada parámetro recalibrado (qué se desvía y cuánto).

## Lo que **no** está en el track

- Aprendizaje profundo como mecanismo primario de detección de fallo. Permitido como opt-in en U5/U6 dentro del envelope `Estimate[T]`, nunca reemplazando el catálogo.
- Multi-vehículo o coordinación.
- Misiones de exterior con perturbaciones meteorológicas extremas (rayos, lluvia fuerte). Fuera de scope.
- Sustitución del catálogo discreto por un controlador continuo. Si en U6 emerge evidencia clara de que el discreto es insuficiente, abrir ADR; no actuar dentro de este track.
