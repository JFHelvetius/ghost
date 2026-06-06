# Uncertainty Design Red Team Review — Fase 0

- **Status:** review hostil, cerrado tras pasada de resolución
- **Reviewer:** Principal Engineer adversarial
- **Date (original review):** 2026-06-04
- **Date (closure pass):** 2026-06-04 (mismo día; cero quemado entre review y cierre)
- **Target:** ADR-0008, ADR-0009, ADR-0010, ADR-0011, ADR-0012, `docs/specs/uncertainty.md`, `docs/specs/perception.md`, `docs/specs/mission.md`, `docs/specs/telemetry.md`, `docs/roadmaps/research_track_uncertainty.md`

> **Postura original:** este documento intentó romper el diseño de incertidumbre. No suavizó críticas. Los hallazgos vivían como obligaciones a cerrar antes de implementar U1.
>
> **Postura post-cierre:** las 12 acciones se procesaron. **10 quedan cerradas, 2 quedan mitigadas con riesgo residual documentado, 0 quedan abiertas.** Detalle por hallazgo abajo. El diseño está listo para U1 sobre una base estable.

---

## 0. Resumen de cierre

| Tipo | Conteo | Hallazgos |
|---|---|---|
| Closed | 10 | §2.1, §2.2, §2.3, §2.5, §2.6, §2.7, §2.8, §3.1, §3.2, §3.4 |
| Mitigated (with residual risk) | 2 | §2.4 (calibración del factor de pesimismo pendiente de U3), §3.3 (linter no cubre toda la superficie de no-determinismo algorítmico) |
| Accepted as risk (not addressed) | 0 | — |

Cambios estructurales producidos por este cierre:

- **3 ADRs nuevos:** ADR-0010 (catálogo revisado + acoplamiento), ADR-0011 (T0 veta piloto), ADR-0012 (retención de runs).
- **5 specs/roadmaps editados:** `uncertainty.md`, `perception.md`, `mission.md`, `telemetry.md`, `research_track_uncertainty.md`.
- **Catálogo de modos perceptuales:** 7 → 8 (`MOTION_AGGRESSIVE` añadido); apéndice de modos considerados-y-rechazados publicado en ADR-0010 §2.
- **FSM endurecida:** doble condición `window_ms + k_consecutive` con test obligatorio de no-oscilación contra señal alternante.
- **Disciplina de parámetros acoplados:** 8 pares mecanismo↔policy enumerados en ADR-0010 §3; PRs deben justificar el par.
- **Política de overrides del piloto:** lista cerrada de combinaciones `(intent × mode)` donde T0 veta (ADR-0011 §2).
- **Política de retención:** tres tiers con presupuesto local, refuse-not-delete, tooling planificado para U1 (ADR-0012).

---

## 1. Resumen ejecutivo (original)

El diseño de incertidumbre es **mejor que el promedio** de proyectos open-source de drones. Pero esa vara es baja. Examinado de cerca, tiene **ocho problemas serios** y **cuatro autoengaños sutiles**:

1. La calibración de la inflación de covarianza (§5 del spec) no tiene fuente: los números son adivinanzas vestidas de números.
2. El catálogo cerrado de modos perceptuales es defendible como ingeniería y peligroso como compromiso: ya falta al menos un modo común.
3. La FSM de transiciones entre modos (perception.md §4) tiene huecos y oscila bajo señal realista.
4. El presupuesto de incertidumbre por goal (mission.md) sobreestima lo bien que un planner puede predecir sigma forward.
5. El criterio NEES como métrica de aceptación de U2 confunde calibración con seguridad.
6. La separación "mechanism (ADR-0008) vs policy (ADR-0009)" se rompe en cuanto un parámetro del mechanism cambia.
7. El override del piloto es ingenuo sobre cómo los pilotos reales reaccionan bajo presión.
8. El research track no tiene presupuesto temporal realista para U6 (hardware).

Los autoengaños son las cosas que el diseño se dice a sí mismo y que no resistirían un test honesto.

---

## 2. Problemas serios

### 2.1 La inflación de covarianza está calibrada contra nada

`uncertainty.md` §5 fija valores numéricos para `α`, `Q_dr`, factores direccionales, etc. **Ninguno tiene fuente.** No hay paper citado, no hay dataset que los respalde, no hay análisis de sensibilidad. Son valores que suenan razonables a un ingeniero que conoce el orden de magnitud.

Esto sería aceptable si el documento lo dijera. **No lo dice.** Los presenta como defaults con autoridad, como si vinieran de una calibración previa. Cuando alguien (incluido tú dentro de seis meses) los ajuste para que la misión funcione, lo hará sin saber que el valor base era una conjetura.

**Recomendación dura:** en `uncertainty.md` §5 cada tabla de números debe abrir con una nota: *"Valores iniciales por ingeniería de orden de magnitud. Recalibrar en U2 contra dataset PyBullet y en U6 contra hardware. Hasta entonces, tratar como hipótesis."* Sin esta nota, el spec es deshonesto sobre su propia certeza.

**Status: Closed.** Disclaimer de "valores conjeturados, no calibrados" añadido al encabezado de `uncertainty.md` §5 y replicado en §7 (catálogo de thresholds) y `mission.md` §4 (modelo forward). El disclaimer enlaza explícitamente a U2/U6 como responsables de la recalibración. Cualquier ajuste de los números ahora se documenta como "ajuste de hipótesis", no como "corrección".

---

### 2.2 El catálogo cerrado de 7 modos ya tiene un agujero

ADR-0008 fija siete `PerceptionMode`. Falta al menos uno común en práctica:

- **`MOTION_AGGRESSIVE`**: vibración mecánica del cuadricóptero a alto throttle degrada IMU y cámara simultáneamente sin saturar. VO pierde tracking por motion blur antes de que `LOW_TEXTURE` o `IMU_SATURATION` se disparen.

También faltaría discutibles:

- **`DUST` / `WATER_DROP_ON_LENS`** (hardware): no es perception-dead pero tampoco low-light; es perception-occluded parcial.
- **`HORIZON_GLARE`**: AGC pelea con luz directa; ni `LOW_LIGHT` ni `NOMINAL`.

ADR-0008 dice que añadir un modo "requiere ADR que supersede ADR-0008". **Esto es fricción correctamente impuesta**, pero el diseño aún no ha hecho el ejercicio de listar los modos que la literatura conoce y justificar por qué quedan dentro o fuera del catálogo.

**Recomendación dura:** añadir un anexo a ADR-0008 (sin superseder, como nota de design) con una tabla de modos *considerados y rechazados* y la razón. Sin eso, el catálogo parece arbitrario y el primer modo encontrado en hardware forzará un ADR-0010 con menos contexto del que debería tener.

**Status: Closed.** Resuelto por ADR-0010:
- §1: `MOTION_AGGRESSIVE` añadido al catálogo (8º modo) con criterio cuantitativo de entrada/salida y mapeo de behavior a T2.
- §2: apéndice de modos considerados-y-rechazados: `DUST`, `WATER_DROP_ON_LENS`, `HORIZON_GLARE`, `THERMAL_SHIMMER`, `EM_INTERFERENCE`, `MULTIPATH_VIO`, cada uno con razón de rechazo y disposición futura.
- `HORIZON_GLARE` subsumido en un criterio revisado de `LOW_LIGHT` (AGC saturado a min de ganancia, además del max); reflejado en `uncertainty.md` §7.
- Spec `perception.md` actualizado con productor `motion.aggressive` y métricas asociadas.

---

### 2.3 La FSM oscila bajo señal realista

`perception.md` §4 declara que `nominal_hold_ms` (200 ms) sostiene `VALID` antes de salir de un modo degradado. Bajo señal real:

- `feature_count` oscila frame a frame entre 25 y 35 cerca del umbral 30.
- `mean_luminance` cambia cada tres frames cuando el dron rota hacia ventana.

200 ms a 30 Hz son 6 frames. Si la señal cruza el umbral cada 3 frames, **la FSM puede oscilar dentro del propio "hold"**. La histeresis (factor ×1.5 para salir) ayuda pero no es suficiente si el umbral está cerca del nivel observado.

**Recomendación dura:** sustituir `nominal_hold_ms` por una **doble condición**: hold temporal Y `K` muestras consecutivas dentro de envelope. Documentar `K` por canal en `uncertainty.md`. Test obligatorio adicional: "señal sintética alternante a 0.45 × `nominal_hold_ms` no produce más de N transiciones por minuto".

**Status: Closed.** Doble condición `(window_ms ∧ k_consecutive)` adoptada formalmente:
- `uncertainty.md` §7: cada modo del catálogo declara `_window_ms` y `_k_consecutive` con defaults por canal.
- `perception.md` §4.1: regla explícita "ambas condiciones operan en conjunción"; señal que cruza umbral cada N frames falla K antes que window.
- `perception.md` §4.3: test obligatorio `test_fsm_no_oscillation_under_alternating_signal` verifica que señal sintética alternante a `0.45 / window_ms` produce ≤ 2 transiciones por minuto.
- `uncertainty.md` §11: test añadido al inventario de pruebas obligatorias.

---

### 2.4 Presupuesto forward de incertidumbre asume que el planner puede predecir VO

`mission.md` §4.1 dice `σ_pos_end² = σ_pos_start² + (k_vio · L)²`. **Esto es VO ideal sobre área uniforme texturada.** En la realidad:

- La distribución de features depende de la escena, no de la longitud.
- El crecimiento de sigma es altamente no-lineal cerca de áreas pobres.
- Loop closure colapsa sigma de forma escalonada, no continua.

Un planner que cree este modelo va a producir presupuestos que parecen cumplidos en planning y se violan en ejecución sistemáticamente. La excusa "es un proxy" en §4 cierre del spec es honesta, pero el proxy es **estructuralmente sesgado** hacia el optimismo en escenas adversariales.

**Recomendación dura:** el proxy debe tener un **factor de pesimismo escenario-específico**. Para escenas no caracterizadas, `k_vio` se infla en ×2. El planner solo usa el `k_vio` nominal cuando la escena tiene un perfil de textura conocido (caracterizado en U3 o U5). Sin esta regla, el "uncertainty-aware planning" engaña a sí mismo.

**Status: Mitigated (calibración del factor pendiente de U3).** Regla añadida en `mission.md` §4.5:

- Tabla de `pessimism_factor` por estado de caracterización: 1.0 (caracterizada), 1.5 (parcial), **2.0 (default, no caracterizada)**, 3.0 (adversarial explícita).
- `k_vio_eff = k_vio_nominal · pessimism_factor` se aplica en §4.1.
- Default es escena no caracterizada (factor 2.0) hasta que U3 pueble `registries/scene_profiles.yaml`.
- El factor se reporta en `MissionStatus.budget_remaining` para que el operador sepa por qué un plan fue rechazado.
- Entregable explícito de U3: registro de perfiles de escena con perfiles caracterizados.

**Riesgo residual:** los valores del factor (1.5, 2.0, 3.0) son hipótesis iniciales sin calibración. U3 produce el primer dato real; hasta entonces, el planner es conservador-de-más en escenas que sí estarían bien caracterizadas. Esto es preferible al sesgo optimista original.

---

### 2.5 NEES como criterio de aceptación confunde calibración con seguridad

U2 acepta una banda NEES de `[0.5, 2.0]` en `NOMINAL`. **NEES es una métrica de calibración estadística**, no de seguridad. Un estimador puede tener NEES perfecto y aún así fallar en la cola: el 1 % de error mayor que 3σ puede ser el que estrelle el dron.

**Recomendación dura:** complementar NEES con dos métricas adicionales en U2:

- **Tail coverage**: fracción de muestras donde error verdadero está dentro de `3σ` reportado. Target ≥ 99 %.
- **Worst-case ratio**: peor `|err| / σ` sobre todo el dataset, target ≤ 5 (no 3, porque queremos margen).

Sin esto, U2 puede tachar la casilla y dejar pasar un estimador peligroso.

**Status: Closed.** Criterios de aceptación de U2 expandidos en `research_track_uncertainty.md`:
- Tail coverage ≥ 99 % en `NOMINAL`, ≥ 97 % en degradados.
- Worst-case ratio ≤ 5.0 sobre todo el dataset.
- Justificación explícita en U2 de por qué NEES por sí solo no basta.

---

### 2.6 La separación mechanism/policy es falsa cuando los parámetros cambian

ADR-0008 (mechanism) fija el catálogo de modos y los criterios de entrada (`min_features`, `min_luminance`, etc.). ADR-0009 (policy) decide qué hacer en cada modo. La separación suena limpia pero **se rompe el primer día que cambias un threshold**:

- Si bajas `min_features` de 30 a 20, el modo `LOW_TEXTURE` entra menos frecuentemente, y el behavior reactivo de ADR-0009 §2 efectivamente cambia de carácter.
- Un mismo `slow_ascend_mps` (ADR-0009 default 0.3) puede ser correcto cuando `LOW_LIGHT` entra al 5 % de luminancia y peligroso cuando entra al 15 %.

Cambiar mechanism toca policy aunque el código no cambie. La idea de "ADR-0008 es estable, ADR-0009 cambia" no se sostiene.

**Recomendación dura:** introducir explícitamente en ambos ADRs una sección "Parámetros acoplados" que liste qué números de cada ADR no son ajustables independientemente del otro. Para los acoplados, exigir revisión conjunta. Sin esto, el primer ajuste de threshold romperá la política sin que nadie lo note.

**Status: Closed.** Resuelto por ADR-0010 §3 — *Parameter Coupling Discipline*:
- Tabla de 8 pares acoplados mecanismo↔policy (low_texture, low_light, imu_saturation, vio_lost, map_ambiguous, perception_dead, motion_aggressive, nominal_hold base).
- Discipline: un PR que modifique un parámetro del par MUST actualizar o justificar explícitamente el otro lado en el mismo PR.
- `manifest.yaml` incorpora campo `retention.coupling_check` que tooling de U1 setea automáticamente.
- `uncertainty.md` §10: nueva restricción que prohíbe ajustar un parámetro acoplado sin tocar el otro.

---

### 2.7 Override del piloto modela al piloto que el diseñador quisiera

ADR-0009 §5 dice que el piloto es T2 por default y puede escalar a T0 con kill. **Esto es como debería funcionar; no es como funciona.** Pilotos reales bajo estrés:

- Sobre-corrigen yaw cuando ven que el dron deriva, generando saturación de IMU justo cuando la perception ya estaba degradada.
- Demandan "RTL ahora" cuando el RTL ciego no es seguro porque el camino al home está peor que quedarse hoverando.
- Ignoran avisos visuales si el dron parece estable.

El diseño actual registra `PILOT_OVERRIDE_DEGRADED` pero **no actúa sobre él**. El sistema permite que el piloto degrade activamente la seguridad mientras la maquinaria de incertidumbre observa pasivamente.

**Recomendación dura:** introducir un comportamiento `T0-vetoes-pilot` para una lista corta de combinaciones piloto+modo demostrablemente peligrosas (por ejemplo: piloto demandando RTL bajo `PERCEPTION_DEAD`). No es paternalismo; es seguridad funcional. Si esto es controversial, dejarlo como configuración y documentar el default.

**Status: Closed.** Resuelto por ADR-0011 — *T0 Safety Vetoes Over Pilot Input*:
- Vocabulario explícito de `PilotIntent`: MANUAL_FLIGHT, AGGRESSIVE_MANEUVER, REQUEST_RTL, REQUEST_LAND, REQUEST_KILL, RELEASE_TO_AUTO.
- Tabla cerrada de 7 combinaciones `(intent × mode)` donde T0 veta o suaviza al piloto, con acción concreta (cap, defer, reject, replace).
- `REQUEST_KILL` y `REQUEST_LAND` nunca vetados (preserva autoridad última del piloto).
- Veto **no deshabilitable en runtime**; sim y hardware comparten la tabla.
- Telemetría obligatoria `PILOT_VETOED` con snapshot de inputs.

---

### 2.8 El presupuesto temporal de U6 es ficción

U6 promete: ≥20 vuelos hardware con groundtruth, recalibración de todos los parámetros, informe comparativo, dataset publicado. Tiempo realista para una persona:

- 1 semana de calibración cámara-IMU (por sesión, y hay que rehacerla).
- 1 semana de bring-up del MoCap o RTK.
- 2 semanas de captura de dataset incluyendo crashes y debug.
- 2 semanas de análisis y recalibración.
- 1 semana de informe.

**7 semanas como mínimo absoluto, asumiendo cero contratiempos.** La realidad de hardware (baterías muertas, motor quemado, GPS denegado en interior, ESC mal calibrados) duplica eso fácilmente.

**Recomendación dura:** U6 debe declarar "duración estimada: 3–4 meses dedicados" en su sección de overview, o degradarse a "esquema parcial; recalibración completa puede no completarse en este ciclo". Sin esto, el track entero parece más cerrado de lo que está.

**Status: Closed.** Sección "Duración estimada" añadida a U6 en `research_track_uncertainty.md`:
- Desglose realista: 1 semana calibración + 1–2 bring-up MoCap + 2–3 captura + 2 análisis + 1 informe.
- Mínimo absoluto declarado: 7 semanas. Realista con contratiempos: 12–16 semanas.
- Fallback explícito: si recursos no alcanzan, degradar a "esquema parcial" en `docs/research/u6_partial.md` y abrir U7 para completar.

---

## 3. Autoengaños sutiles

### 3.1 "Incertidumbre como objeto de primera clase" implica que sabemos qué es

El proyecto repite que la incertidumbre es objeto de primera clase. **Pero el spec equivocadamente trata `validity` y `covariance` como dimensiones independientes.** No lo son. Una covarianza pequeña y un `validity=DEGRADED` es una contradicción que el spec permite. ¿Qué consume el downstream? El diseño no lo dice.

**Recomendación:** en `uncertainty.md` añadir invariante explícito: `validity` se deriva de un conjunto reglado de condiciones, y `covariance` debe ser consistente con ese `validity`. Si no es consistente, el constructor de `Estimate` lo detecta y rechaza.

**Status: Closed.** Invariante #10 añadido a `uncertainty.md` §3: *"Validity y covariance son consistentes, no independientes. El constructor verifica que la covarianza esté dentro del rango esperado para el `validity` declarado, dado el `nominal_covariance_envelope` del productor."* Test obligatorio `test_estimate_rejects_validity_covariance_inconsistency` añadido a §11.

---

### 3.2 "Sealing de arrays" no captura mutación profunda

`uncertainty.md` §3.2 sella `value` y `covariance` con `flags.writeable=False`. **Pero `value` puede ser una dataclass que contiene otros arrays.** El sealing no se propaga automáticamente. Un `Estimate[Pose]` con `Pose(position_enu_m, orientation_q)` solo sella si Pose ya lo hizo.

**Recomendación:** documentar que el constructor de `Estimate` aplica sealing recursivo sobre cualquier ndarray accesible por traversal de campos. O alternativamente, exigir que todo `T` parametrizable tenga su propio sealing en su constructor (consistente con ADR-0005).

**Status: Closed.** `uncertainty.md` §3.2 reescrito: *"Sealing recursivo de arrays. El constructor aplica `flags.writeable=False` a cualquier `np.ndarray` accesible por traversal de los campos de `value` cuando es dataclass. Verifica el sealing tras construcción y rechaza con `ValueError` si encuentra array escribible."* Test correspondiente `test_estimate_seals_arrays_recursively` añadido a §11.

---

### 3.3 "Determinismo bit-a-bit" en perception es aspiracional

`perception.md` §6.3 promete determinismo bit-a-bit. **VO real depende de RANSAC, que con misma seed produce misma salida solo si el orden de iteración sobre features es estable.** Diccionarios Python en CPython 3.11+ son ordenados por inserción; pero un cambio de versión, una refactorización que use `set`, o un `Counter` rompe el orden.

**Recomendación:** linter adicional `check_no_unstable_collections.py` que prohíba `set`, `dict.keys()` sin sort, `Counter` y similares en `perception/` y `state/`. O documentar el riesgo explícitamente.

**Status: Mitigated (linter no cubre toda la superficie).** Linter especificado en `uncertainty.md` §10: prohíbe `set`, `frozenset`, `dict.keys()` sin sort, `collections.Counter` en `perception/`, `state/`, `mission/`. Implementación deferida a U1 como `scripts/check_no_unstable_collections.py`. Excepciones permitidas con `# noqa: stable-collection` + razón.

**Riesgo residual:** el linter cierra la mayor parte de la superficie estructural pero no garantiza determinismo contra:
- RANSAC con seed pero orden de pares no estable internamente al algoritmo (decisión de librería).
- Operaciones de scipy/numpy con orden no determinista en BLAS multi-threaded.
- Drift de comportamiento entre versiones de CPython.

Estos casos se observan caso por caso en U2/U5 cuando se rompa la reproducibilidad bit-a-bit; mitigación se trata como deuda explícita, no como cobertura del linter.

---

### 3.4 "Sin política de retención de runs (acumulan)" es solo postergar el problema

`phase1.md` cierra con "Sin políticas de retención de runs (siguen acumulándose)". En el research track, U2 y U5 generan datasets grandes. **Para el final de U5 el repo o el disco del desarrollador colapsa.** No es Fase 1, es ahora.

**Recomendación:** decidir, antes de iniciar U2, una política mínima: `runs/` excluido de git por default; manifest persistido siempre; raw MCAP comprimido a partir de 7 días; rotación local con presupuesto declarado en GB.

**Status: Closed.** Resuelto por ADR-0012 — *Run Retention Policy*:
- Tres tiers (`EPHEMERAL` 7 días, `RESEARCH` 90 días + archivo perpetuo del manifest, `RESULT` perpetuo en release asset).
- `runs/` ignorado por git; release assets para `RESULT`.
- Presupuesto local 50 GB default, warn a 80 %, **refuse-not-delete** a 95 %.
- Compresión zstd lossless a día 7.
- Tooling `scripts/manage_runs.py` planificado para U1 con `list / tag / clean / clean --dry-run / archive / verify`.
- Datasets U2/U5 con política análoga: ≤100 MB en repo, >100 MB en release assets.

---

## 4. Lo que el diseño hace bien y debe protegerse

No todo es crítica. Algunos elementos son raros de ver tan bien planteados en proyectos abiertos y vale la pena no perderlos al iterar:

- **Validity como enum totalmente ordenado.** La regla "composición = min" es una de las mejores líneas de defensa contra silent upgrade. Mantenerla.
- **`covariance is None` solo para `kind=groundtruth`.** Asimetría que hace explícito que GT no existe en hardware. Esto es ingeniería honesta.
- **Tiered autonomy T0/T1/T2/T3 con T0 inviolable.** El veto del safety supervisor es el patrón que mejor sobrevive de la academia al campo. No diluir. (ADR-0011 lo extiende sin romperlo.)
- **Mode change como evento de bus persistido.** Hace cualquier incidente reproducible. Es barato de implementar y caro de añadir después. Bien.
- **Pilot override registrado aun cuando degrada.** Honesto sobre el factor humano. El veto de ADR-0011 cubre las combinaciones más peligrosas sin caer en paternalismo general.

---

## 5. Tabla de acciones (con status post-cierre)

| # | Acción | Dónde | Esfuerzo | Status | Resolución |
|---|---|---|---|---|---|
| 1 | Nota de "valores conjeturados" en `uncertainty.md` §5 | spec | 30 min | ✅ Closed | `uncertainty.md` §5 y §7 |
| 2 | Anexo de modos considerados-y-rechazados en ADR-0008 | ADR | 2 h | ✅ Closed | ADR-0010 §1 + §2 |
| 3 | Doble condición (hold + K muestras) en FSM | spec + test | 2 h | ✅ Closed | `uncertainty.md` §7 + `perception.md` §4.1–4.3 |
| 4 | Factor de pesimismo escenario-específico en forward planner | mission.md §4 | 1 h docs + en U3 | 🟡 Mitigated | `mission.md` §4.5 (regla en place; calibración deferida a U3) |
| 5 | Tail coverage + worst-case ratio en U2 | research track | 30 min docs | ✅ Closed | `research_track_uncertainty.md` U2 |
| 6 | Sección "Parámetros acoplados" en ADR-0008 y ADR-0009 | ADRs | 1 h | ✅ Closed | ADR-0010 §3 |
| 7 | Behavior `T0-vetoes-pilot` para combinaciones peligrosas | ADR-0009 §5 | 2 h decisión + ADR | ✅ Closed | ADR-0011 |
| 8 | Recalibrar tiempo declarado de U6 | research track | 15 min | ✅ Closed | `research_track_uncertainty.md` U6 (sección Duración estimada) |
| 9 | Invariante validity↔covariance consistente | uncertainty.md §3 | 1 h | ✅ Closed | `uncertainty.md` §3 (invariante #10) |
| 10 | Sealing recursivo documentado | uncertainty.md §3.2 | 30 min | ✅ Closed | `uncertainty.md` §3.2 reescrito |
| 11 | Linter de colecciones inestables | spec + script | 4 h | 🟡 Mitigated | `uncertainty.md` §10 (spec); implementación en U1; riesgo residual algoritmico documentado |
| 12 | Política de retención de runs antes de U2 | docs/specs/telemetry.md | 1 h | ✅ Closed | ADR-0012 + `telemetry.md` §11 |

---

## 6. Veredicto (original)

El diseño de incertidumbre **no está listo para implementación todavía**, pero está muy cerca. Los problemas de §2 son corregibles en docs antes de que U1 empiece; los autoengaños de §3 deben quedar al menos documentados como deuda conocida. Si los doce ítems de §5 se cierran o se aceptan explícitamente como deuda, el track puede arrancar con honestidad.

Sin embargo: **el éxito real del diseño no se mide en este review**. Se mide en U2 (¿NEES en banda?), U5 (¿ATE razonable bajo adversarial?), y U6 (¿el sistema deja de mentir sobre sí mismo en hardware?). Hasta entonces, todo lo de aquí es papel.

---

## 7. Veredicto post-cierre

El precondicionamiento documental está completo. Los 12 hallazgos están cerrados o mitigados con riesgo residual explícito; ninguno queda abierto sin disposición.

**El diseño está listo para U1.** En particular están en su lugar:

- Contratos de `Estimate[T]` con invariantes verificados por constructor (sealing recursivo, validity↔covariance consistente).
- Catálogo de 8 `PerceptionMode` con criterios cuantitativos y apéndice de rechazos documentados.
- FSM endurecida con doble condición y test de no-oscilación obligatorio.
- Modelo forward con factor de pesimismo y default conservador para escenas no caracterizadas.
- Métricas de U2 que cubren cola, no solo calibración media.
- Disciplina de acoplamiento mecanismo↔policy con 8 pares enumerados.
- Tabla de veto T0 sobre piloto con combinaciones nombradas y telemetría obligatoria.
- Política de retención con tiers, presupuesto y refuse-not-delete.
- Linter de colecciones inestables especificado (implementación parte de U1).
- Cronograma de U6 honesto (12–16 semanas realistas).

**Lo que sigue siendo papel y se medirá en ejecución:**
- La banda de calibración real de los parámetros conjeturados (validable en U2/U6).
- Que el factor de pesimismo 2.0 sea ni muy conservador ni muy optimista para escenas reales (validable en U3 con `scene_profiles.yaml`).
- Que el linter de colecciones inestables capture, en práctica, los casos que importan (validable en U1 al primer caso real).
- Que la tabla de veto T0 no rechace combinaciones legítimas que aún no anticipamos (validable en U5).

Estos cuatro son riesgos asumidos conscientemente para no diferir más U1. La iteración del review es un evento periódico, no un ritual previo a cada fase: la próxima pasada hostil se programa para el cierre de U2 con dataset real en mano.
