# Architecture Red Team Review — Fase 0

- **Status:** review hostil, no aceptación
- **Reviewer:** Principal Engineer adversarial
- **Date:** 2026-06-03
- **Target:** `docs/architecture.md`, ADR-0000…ADR-0007, specs en `docs/specs/`

> **Postura:** este documento intenta romper el diseño. No suaviza críticas. Lo que pase aquí se debe corregir en la documentación, en ADRs adicionales o aceptar conscientemente como deuda.

---

## 1. Resumen ejecutivo

El diseño es razonable y por encima del promedio para un proyecto open-source-personal. Pero tiene **siete riesgos serios** y **cinco mentiras cómodas** que no se han confrontado:

1. La promesa "5 backends intercambiables" es física y económicamente falsa para uno solo.
2. La conformance suite no captura las cosas que realmente difieren entre backends.
3. El bus pub/sub determinista en proceso es más difícil de implementar de lo que parece, y más caro de mantener que ROS 2 a 3 años vista.
4. Protobuf en Python a las tasas declaradas es un cuello de botella, no una decisión gratis.
5. PyBullet no es una buena maqueta de Gazebo, y validar contra él da falsa seguridad.
6. El "vision-only sin GPS" se sostiene en simulación trivial y colapsa en escenarios realistas.
7. El plan de hardware está infrafinanciado en tiempo de ingeniero, no en dólares.

A estos siete se suman acoplamientos ocultos, decisiones difíciles de revertir y un grupo de errores conceptuales menores.

---

## 2. Riesgos técnicos serios

### 2.1 "Cinco backends" es una ficción de marketing

El documento promete PyBullet, Gazebo+PX4 SITL, AirSim, Isaac Sim y hardware. **Un equipo de una persona no mantendrá cinco backends.** Históricamente:

- **AirSim** está deprecado por Microsoft desde 2022. Reemplazo Project Chrono / Cosys-AirSim. Apostar por AirSim hoy es deuda inmediata.
- **Isaac Sim** requiere GPU NVIDIA decente y licencias Omniverse en algunos casos. "Coste cero" se cae.
- **Gazebo+PX4** en Windows es hostil. WSL2 funciona pero añade fricción.

**Recomendación dura:** declarar explícitamente que el soporte real será **PyBullet + Gazebo+PX4 SITL + Hardware**. Quitar AirSim e Isaac del documento, o degradarlos a "backends comunitarios bienvenidos, no soportados oficialmente". La promesa exagerada va a costar credibilidad cuando alguien intente Isaac y descubra que no existe.

### 2.2 La conformance suite no captura lo que importa

Los tests propuestos (`test_reset_is_deterministic`, `test_no_shared_mutation`, etc.) son cosas mecánicas. **Los bugs reales entre backends no son esos.** Son:

- Convenciones de motor opuestas (PyBullet PX4-X vs PX4-+ vs ArduPilot).
- Modelos de cámara con orígenes distintos (OpenGL vs computer vision).
- Latencia de IMU modelada distinto.
- Gravedad signo opuesto en algún simulador.
- Saturación de actuadores aplicada en sitios distintos del pipeline.

**Recomendación dura:** añadir a la conformance suite **tests físicos**: caída libre, hover bajo throttle calibrado, rotación pura bajo par puro. Si dos backends fallan estos tests con tolerancias razonables, no son intercambiables aunque pasen los tests mecánicos.

### 2.3 Bus pub/sub determinista en Python: más caro que ROS 2 a 3 años

ADR-0006 desestima ROS 2 por instalación pesada y replay. **Eso es cierto hoy y mentira a 3 años.**

- Implementar un bus pub/sub con orden total determinista, dispatcher multi-thread, backpressure, subscribers con tipos y schemas evolucionables es **un proyecto en sí mismo**. Llevará al menos 2–3 semanas hacerlo bien y bugs recurrentes por meses.
- ROS 2 Humble en Linux funciona en 30 minutos. En Windows tiene fricción real, pero ROS 2 Iron+ tiene soporte oficial.
- El argumento "rompe replay" se cae con MCAP + sim time + uso disciplinado de DDS QoS.

**Recomendación dura:** considerar **dos caminos honestos**:

- (a) Mantener el bus interno y aceptar el coste. Pero entonces se documenta que mantener el bus es trabajo de plataforma, no de feature.
- (b) Usar ROS 2 desde Fase 1 con `rclpy`, comprometerse con Linux/WSL como dev environment, y acelerar las fases posteriores (RViz2, rqt, paquetes ROS de SLAM ya hechos).

La decisión actual es defendible pero hay que ser honesto sobre el coste real.

### 2.4 Protobuf + Python a 1 kHz es un cuello de botella

La spec de telemetría declara MCAP+Protobuf como formato primario y promete que todo lo del bus se persiste. **Protobuf Python en CPython a 1000 Hz para 5+ canales serializando arrays numpy genera GC pressure no trivial y latencia variable.** Medirlo es trivial; ignorarlo no.

Imágenes RGB 640x480 a 30 Hz comprimidas como JPEG son ~30 KB/frame × 30 = ~1 MB/s, pasable. Pero IMU 200 Hz × 5 sensores futuros + state 50 Hz + comandos 100 Hz + groundtruth puede acumular 50k mensajes/s en runs intensos.

**Recomendación dura:**

- Considerar **Cap'n Proto** o **MessagePack** como alternativa a Protobuf. Más rápidos en Python, schemas extensibles.
- O usar Protobuf solo para los schemas y serialización **batch** (acumular y serializar cada 100 ms), no por mensaje.
- En todo caso, medir antes de declarar la decisión correcta. ADR-0003 no menciona benchmark.

### 2.5 PyBullet no es una buena maqueta de Gazebo

PyBullet es excelente como sandbox de física, **pésimo como ensayo de Gazebo**. Diferencias relevantes:

- PyBullet renderiza con OpenGL básico; Gazebo usa Ogre con shaders más realistas.
- PyBullet no modela ruido óptico de cámara, vignette, motion blur, rolling shutter.
- PyBullet ignora aerodinámica más allá del integrador de cuerpo rígido. Gazebo tiene plugins de viento, drag, ground effect.
- PyBullet no tiene plugins de PX4. Para el SITL hay que reescribir el ActuatorSink completo.

Trabajar tres fases en PyBullet construye intuición que **se desmonta** al pasar a Gazebo. El sistema corre pero los hiperparámetros (PID gains, varianzas del filtro, tamaños de feature window) son distintos.

**Recomendación dura:** acortar la estancia en PyBullet. Cambiar a Gazebo+PX4 SITL **antes** de la Fase 4. Mejor aún: hacer un spike de 2–3 días en Fase 1 para validar que Gazebo+PX4 SITL es viable en la máquina del desarrollador. Si no lo es, ajustar planificación honestamente.

### 2.6 GPS-denied vision-only en escenarios reales es duro

ADR-0000 prohíbe consumir GPS y promete navegación sin él. **Esto suena heroico hasta que la cámara mira al techo blanco o el suelo de tierra o la pared de cemento.**

- Sin features, VO falla.
- Sin loop closure decente, drift se acumula.
- En oscuridad, sin IR ni LiDAR, no hay percepción.
- En entornos con repetición visual (corredor de almacén), el SLAM mete loop closures erróneos.

El diseño actual no plantea **degradación elegante** ante fallo de percepción. ¿Qué hace el dron si VIO pierde tracking? El documento dice "recovery behaviors" en Fase 6, pero no especifica.

**Recomendación dura:** crear un ADR adicional `ADR-0008 — Perception Failure Modes` donde se documente:

- Catálogo de modos de fallo de percepción.
- Política de degradación: hover en sitio, ascender lentamente, RTL ciego con dead reckoning, kill.
- Criterios cuantitativos para entrar en cada modo.

Sin esto, la promesa de vision-only es marketing.

### 2.7 Plan de hardware infrafinanciado en horas de ingeniero

ADR-0007 lista plataforma target con buen detalle. Lo que **falta**:

- Tiempo estimado de bring-up (no de hardware, de software): 4–8 semanas adicionales a las fases declaradas, mínimo.
- Tiempo de calibración (cámara, IMU, T_imu_cam): 1 semana cada vez que cambie el rig.
- Tiempo de identificación de parámetros del dron (masa, momentos de inercia, thrust coefficients): 1 semana.
- Soporte regulatorio mexicano (AFAC) para vuelos: trámites no instantáneos.

Las Fases 8–9 están descritas en una frase. **Eso es subestimación clara.**

**Recomendación dura:** Fase 8 (HIL) y Fase 9 (HW real) deben tener **roadmaps propios** comparables al `phase1.md`, no una mención casual.

---

## 3. Decisiones difíciles de revertir

### 3.1 Marco ENU/FLU + cuaternión Hamilton w-first

Bien fundamentada en ADR-0005, pero hay deuda silenciosa:

- Toda integración futura con PX4/MAVLink requiere conversión. Eso ya está reconocido.
- Toda integración con datasets públicos de SLAM (EuRoC, TUM-VI) requiere conversión. **No mencionado**.
- Todo paper de aerospace usa NED. Reproducir baselines requiere conversión. **No mencionado**.

**Coste de revertir:** ~2 semanas de refactor. **Coste de no revertir:** conversiones esparcidas + bugs ocasionales por años.

**Veredicto:** la decisión es defendible. Pero el adaptador debe ser **una capa formal** (`ghost.adapters.frame_conventions/`) auditada por tests, no funciones helper sueltas.

### 3.2 `VehicleState` como `dataclass(frozen=True)` con `np.ndarray` dentro

Frozen dataclass **no** impide mutar el `np.ndarray` interno. La disciplina de "tratar como inmutable" es voluntaria. **Esto se romperá.**

**Recomendación dura:** hacer arrays `read_only` con `flags.writeable=False` en el constructor. Esto produce excepciones al primer intento de mutar. Si el coste de validar no es aceptable, mover a `numpy.typing.NDArray` con copy-on-construction.

### 3.3 `schema_version` por dataclass, sin migración formal

El diseño dice "incrementar al añadir campos, prohibido remover". **Falta**:

- Cómo se leen MCAPs viejos con `schema_version` antigua.
- Quién valida que un nuevo campo es realmente aditivo y no rompe lectores.
- Política para campos cuyo significado cambia (mismo nombre, semántica distinta) — un anti-patrón típico.

**Recomendación dura:** ADR-0009 sobre evolución de schemas, o sección explícita en `docs/specs/state.md` con flujo de versiones y herramienta de migración.

---

## 4. Acoplamientos ocultos

### 4.1 Telemetría depende de Protobuf, Protobuf de schemas, schemas del estado

Si mañana cambia el `VehicleState`, hay que regenerar `.proto`, recompilar bindings, actualizar MCAPs viejos (o no), actualizar tests. **No hay tooling propuesto** para automatizar esto. La fricción se descubrirá en el primer cambio real.

### 4.2 RandomSource depende de etiquetas estables

Si alguien refactoriza `imu_noise` a `imu_noise_v2`, **todos los runs con seed antigua dejan de reproducirse exactamente**. No hay test que detecte esto, ni convención de que las etiquetas son inmutables. Está en la spec de Clock, pero no es accionable.

### 4.3 Conformance suite vs backends opcionales

Si un backend declara que **no** soporta `synchronous_step`, ¿se le aplica el test de determinismo? El documento dice "se documenta como no determinista". **Pero entonces la conformance suite tiene tests opcionales y la noción de "backend válido" se diluye**.

**Recomendación:** dividir conformance en obligatoria y opcional, explícito.

### 4.4 Hot path → bus → telemetría → MCAP writer

La cadena en el hot path es no trivial:

1. Productor crea dataclass frozen.
2. Bus copia referencia, adquiere sequence.
3. Telemetry recibe en cola.
4. Writer thread serializa con Protobuf.
5. Sink escribe a disco.

Cada eslabón puede bloquear. Ya hay un análisis básico, pero **falta presupuesto de latencia formal**: cuánto tiempo cada eslabón puede tomar a p99 sin degradar el sistema. Sin presupuesto, optimizar es a ciegas.

---

## 5. Cuellos de botella futuros

### 5.1 Logging de imágenes

JPEG 85 a 30 Hz desde una cámara 640×480 es ~30 KB/frame, ~1 MB/s, manejable. Pero:

- Si en Fase 3+ pasamos a stereo 720p (común en VIO), son ~150 KB/frame × 30 × 2 = 9 MB/s.
- Múltiples cámaras (Fase 5+) multiplican.
- Lossless en Fase 4 para datasets SLAM: 10× explosión.

**Recomendación:** política de "no todo lo de cámara va al MCAP por defecto" desde Fase 3. Submuestreo agresivo configurable por canal. Documentarlo desde Fase 0.

### 5.2 Conformance suite ejecutada por backend

Si crece a 100 tests × 4 backends, y cada test inicializa un backend pesado (Gazebo ~10s, Isaac ~30s), CI nightly puede tomar horas. **Sin paralelización** declarada, sin fixtures compartidas declaradas, sin GPU disponible en CI, el plan se rompe.

### 5.3 Scheduler de SimClock como min-heap

Min-heap es O(log n) por evento. Está bien para Fase 1–3. En Fase 5+ con muchos eventos en vuelo (sensores asíncronos, watchdogs, replanificación), puede ser sustituible. **Reemplazo no es trivial**: cambiar la implementación requiere preservar bit-exactitud de determinismo. Está en "evolución futura" pero el coste real no se mide.

### 5.4 Importadores y deptry vs rendimiento de start-up

`import-linter` o `deptry` en CI es barato. Pero **prohibir** imports de `cv2` en `hal/` no impide que un backend importe `cv2` y el HAL lo reciba indirectamente vía un payload con array OpenCV-like. **El cumplimiento del contrato es más que el grafo de imports.**

---

## 6. Mantenibilidad

### 6.1 Documentación masiva sin ownership

11 documentos largos en Fase 0. **¿Quién los actualiza cuando algo cambie?** El proyecto es de una persona. Sin política explícita, la documentación se desincroniza del código en 3–6 meses.

**Recomendación:** convención de pre-commit que **falla** si se modifica `src/project_ghost/hal/interfaces.py` sin tocar `docs/specs/hal.md` (heurística simple, falsos positivos aceptables). O al menos, checklist en PR template.

### 6.2 Lenguaje del repo: español vs inglés

La documentación es en español. Razonable hoy. **Cualquier contribuyente externo no hispano-hablante se queda fuera.** Open source con docs en español tiene una fracción del alcance.

**Recomendación honesta:** decidir explícitamente con ADR. Tres opciones:

- (a) Quedarse en español, aceptando comunidad reducida.
- (b) Migrar a inglés ahora (esfuerzo bajo, son 11 documentos).
- (c) Bilingüe en piezas clave (architecture.md y ADRs en inglés, specs en español).

Mi opinión: **(b)** es la decisión correcta para el objetivo declarado de proyecto open source. Pero es decisión del owner.

### 6.3 Linter custom para `random`

Se promete linter custom que detecta `np.random` y `random` globales. **Mantener un linter custom es trabajo recurrente**: cada release de Python o numpy puede romperlo, falsos positivos en strings, etc.

**Alternativa:** usar `ruff` rules custom o `flake8-print`-style plugin. O simplemente test que importa todo el código y verifica que `np.random.get_state()` es idéntico antes/después.

---

## 7. Rendimiento

### 7.1 Sin presupuesto de latencia por capa

El documento es elocuente sobre arquitectura pero **silencioso sobre números**:

- ¿Cuánto puede tomar `bus.publish()` a p99 sin degradar el hot loop?
- ¿Cuánto puede tomar `provider.poll()`?
- ¿Cuál es el dt máximo aceptable entre `step()` y publicación de IMU?

Sin estos números, optimizar es subjetivo. Recomendación: ADR-0010 sobre presupuestos de latencia y test que los falla.

### 7.2 `numpy` pequeño en hot loop

Crear `np.array([..., ...])` de 3 elementos en hot loop es ~µs por allocation. A 1 kHz × 5 sensores × varios arrays por mensaje = ~50k allocs/s en sub-arrays. **GC pressure no trivial**, especialmente en debug builds.

**Recomendación:** considerar `__slots__` en dataclasses y reusar buffers cuando el contrato lo permita (ojo con frozen).

---

## 8. Errores conceptuales

### 8.1 "Frozen dataclass" ≠ inmutable

Ya señalado en §3.2. El nombre `frozen=True` da falsa sensación de seguridad. Cualquier `ndarray` dentro es mutable.

### 8.2 `stamp_sim_ns` y `stamp_wall_ns` en hardware real

ADR-0007 dice que en HW el `RuntimeBackend` usa `SystemClock` monotónico. ¿Cuál es entonces `stamp_sim_ns` en HW? **¿Se rellena con `0`, con `stamp_wall_ns`, con `NaN`?** Si los consumidores miran `stamp_sim_ns`, cambian de comportamiento al pasar a HW. No documentado.

### 8.3 `SafetyEnvelope` en sim vs HW

En sim, violación de envelope produce un evento y un comando rechazado. **En HW real, eso es tarde.** El kill switch debe ser hardware. La spec mezcla los dos casos sin distinguir, lo cual es peligroso.

### 8.4 Capabilities como API extensible vs contrato firme

`capabilities.extensions: Mapping[str, Any]` es un escape hatch sin tipado. **Es el típico campo que crece sin control y se vuelve la API real**. Sin política explícita, el `extensions` será una API paralela no documentada en 6 meses.

### 8.5 `EventBus` thread propio vs `TelemetryBus` thread propio

Ambos sistemas declaran threads dedicados. ¿Cómo coordinan? ¿Comparten? ¿Cuál procesa primero un mensaje que es a la vez evento y telemetría? No documentado.

### 8.6 "Pub/sub agnóstico de asyncio"

Decirse a sí mismo "agnóstico de asyncio" mientras tienes threads dedicados y posiblemente callbacks que querrán hacer I/O es ingenuo. En el momento que un subscriber quiera, p. ej., escribir a una API HTTP en Fase 7+, **vas a tener un problema**. Mejor decidir hoy: o asyncio o threads, no ambos.

---

## 9. Lo que está bien (para no parecer un cínico unidimensional)

- **ADR-0001 (HAL First)** es la decisión correcta y suficientemente protegida.
- **Tiempo en int ns** es la decisión correcta. Comparable a PX4.
- **RandomSource jerárquico** es elegante, raro de ver en proyectos personales.
- **MCAP** es la elección correcta de formato, incluso si Protobuf como serializador es debatible.
- **Frozen `VehicleState`** es la dirección correcta aunque la implementación necesite endurecerse.
- **Specs separadas de ADRs** es buena práctica y se mantiene.
- **Capability discovery** es maduro; bien hecho cubre el 80% del problema de evolución.

---

## 10. Cosas que romperán en hardware real

Predicciones específicas:

1. La conversión ENU↔NED + FLU↔FRD en el adaptador MAVLink tendrá bugs de signo. Garantizado.
2. La calibración de cámara hecha en sim no se transfiere; hay que recalibrar con tablero.
3. Los timestamps de IMU del autopilot llegan con jitter incluido vía MAVLink. El estimador se va a sorprender.
4. El thrust coefficient real diferirá del de sim en 10–30%. Hover sintonizado en sim queda fuera de tune.
5. Vibración a 50–100 Hz del frame contaminará IMU. Sin filtrado notch, el estimador da bandazos.
6. La cámara real tendrá rolling shutter; los frames durante maniobras estarán deformados. VO sufre.
7. MAVSDK Python tiene timeouts y desconexiones esporádicas. El sistema debe manejarlos elegantemente; el diseño actual no lo menciona.
8. El kill switch no software del documento no existe en muchos receptores RC consumer; requerirá hardware extra.

Ninguno es bloqueante. Pero ninguno está reconocido en el diseño actual.

---

## 11. Acciones recomendadas (resumen)

Por orden de prioridad:

**Antes de Fase 1:**

1. Decidir explícitamente lenguaje de docs (ADR adicional).
2. Endurecer `VehicleState` (arrays read-only o equivalente).
3. Definir presupuestos de latencia (ADR-0010).
4. Definir `ADR-0008 — Perception Failure Modes`.
5. Reducir alcance declarado a 3 backends, no 5.

**Durante Fase 1:**

6. Añadir tests físicos a la conformance suite, no solo mecánicos.
7. Decidir Protobuf vs alternativa con benchmark real.
8. Spike de Gazebo+PX4 SITL para confirmar viabilidad antes de Fase 4.
9. Hacer el linter de aleatoriedad mediante ruff o test pinned, no script custom.

**Antes de Fase 4:**

10. Roadmaps formales para Fases 8 y 9.
11. ADR de evolución de schemas (`ADR-0009`).
12. Política de submuestreo de canales pesados (imágenes).

---

## 12. Conclusión

El diseño es honesto, técnicamente correcto en lo grueso y mejor que la mayoría de proyectos de su tamaño. Sus problemas no son fatales pero son reales y van a salir a flote.

**Lo más peligroso no son los errores técnicos.** Es el optimismo sobre el alcance: 5 backends, una persona, 5 años, hardware al final, sin GPS, todo open source. Cada uno de esos compromisos es defendible solo. Juntos son **una probabilidad significativa de no terminar**.

**Recomendación final del red team:** declarar Fase 1 con scope mínimo viable y aceptar que la arquitectura es buena solo si sirve para terminar Fase 1 y aprender. Cualquier refactor post-Fase-1 informado por datos será mejor que cualquier ADR escrito hoy sin datos.

No suavizar este documento. Convertir las críticas en backlog accionable.
