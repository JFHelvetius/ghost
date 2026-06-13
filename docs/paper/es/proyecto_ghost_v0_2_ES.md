# Project Ghost: una superficie de propiedades de seguridad verificable para autonomía bajo incertidumbre

**Autor:** Javier Menéndez Mateos (`jfhelvetius@gmail.com`)
**Afiliación:** Independiente
**Versión:** v0.2.2 (2026-06-12)
**Repositorio:** <https://github.com/JFHelvetius/ghost>
**PyPI:** <https://pypi.org/project/project-ghost/>
**Documentación:** <https://JFHelvetius.github.io/ghost/>
**Licencia:** Apache-2.0

> **Nota interna:** Esta es una traducción al español del paper técnico
> [`project_ghost_v0_2.md`](../project_ghost_v0_2.md) para uso del
> autor y de colaboradores hispanohablantes. La versión canónica
> para arXiv y FMAS 2026 es la inglesa; cualquier divergencia entre
> las dos debe resolverse a favor de la inglesa. Se mantienen en
> inglés los nombres técnicos (BAUD-v1, ERUR-v1, etc.), las
> referencias a archivos del repositorio, las tablas, los snippets
> de código y los nombres de las propiedades formales.

---

## Resumen

Describimos **Project Ghost**, una implementación de referencia open
source de cinco propiedades formales de seguridad para autonomía
bajo incertidumbre, verificables byte-exact desde cualquier run
capturado mediante un único comando de shell:
`ghost verify-properties --mcap <log>`. El conjunto de propiedades
(BAUD-v1, ERUR-v1, MD-v1, RLB-v1, FPB-v1) cubre cuatro naturalezas
distintas de afirmación de seguridad — comportamiento condicional en
ambas direcciones del drift, una propiedad estructural incondicional
del calibrador, una cota cuantitativa de latencia de recuperación, y
un observador empírico para gating de regresión — cada una enunciada
en un Architectural Decision Record (ADR) vinculante, verificada por
una función pura sobre telemetría MCAP content-addressed, ejercitada
por ~50 property tests dentro de una suite de 1687 tests,
testimoniada inline en cada smoke de referencia, y self-enforced en
cada push por CI.

La partición BAUD/ERUR y la propiedad de degradación monótona están
adicionalmente **verificadas mecánicamente** por TLA+/TLC sobre el
espacio de estados abstracto del par de policies de referencia.
Hacemos cuatro contribuciones claimable: **(1)** una cota
estructural cerrada y ajustada de latencia de recuperación
`L ≤ peak + W − 1` para filtros de ventana deslizante de
count-of-K-in-W (Theorem 1, §6.4); **(2)** un teorema de partición
formal `BAUD ⊕ ERUR` sobre el espacio de comportamiento condicional
del ciclo cerrado, verificado mecánicamente por TLC; **(3)** un
primitivo de reproducibilidad — un verificador content-addressed
alcanzable desde `pip install project-ghost==0.2.2` que detecta bugs
inyectados (§7.2) y produce JSON output determinístico across
machines; y **(4)** un patrón end-to-end de citación de seguridad —
MCAP + ADR + verificador + Hypothesis test + CI gate + tagged
release + wheel OIDC-firmada como una unidad coherente.

La evaluación empírica sobre 9 combinaciones (policy, cycle-count)
muestra que el verificador completa en 21 ms para runs de 10 ciclos
y 406 ms para runs de 200 ciclos (lineal en la longitud del trace),
y que el conjunto de propiedades se mantiene en las tres
parametrizaciones de policy de referencia.

**Palabras clave:** autonomía verificable, propiedades formales de
seguridad, runtime verification, confianza calibrada, verificación
de replay byte-exact, TLA+, MCAP, monitores de ventana deslizante.

---

## 1. Introducción

Las afirmaciones de seguridad en robótica se sostienen rutinariamente
mediante prosa escrita a mano en documentos de diseño y videos de
simulación que el lector no puede re-ejecutar. La literatura sobre
incertidumbre en autonomía es rica — filtros bayesianos, calibración
de predicciones probabilísticas, incertidumbre epistémica vs
aleatoria, detección y aislamiento de fallos (FDI), supervisores de
seguridad en tiempo de ejecución — pero la brecha entre *la teoría
existe* y *este run específico, sobre este código específico,
satisface la propiedad* rara vez se cierra operacionalmente. Un
tercero que quiere verificar una afirmación de seguridad contra un
run grabado típicamente no puede: no hay comando de shell, ni log
content-addressed, ni verificador función-pura que pueda re-ejecutar
en su propia máquina.

Describimos Project Ghost, una plataforma de referencia opinionada
construida precisamente alrededor de esa brecha. Ghost es sim-first,
escrito en Python, y se distribuye como un paquete `pip`-instalable
con un subcomando CLI (`ghost verify-properties`) que toma un log
MCAP capturado y devuelve un veredicto byte-exact sobre cinco
propiedades formales de seguridad. Cada propiedad está enunciada en
un ADR vinculante; verificada por una función pura sobre el log;
ejercitada por property tests basados en Hypothesis; testimoniada
inline en cada smoke de referencia closed-loop; y self-enforced en
cada push por CI. Dos de las propiedades (BAUD-v1 y ERUR-v1) están
adicionalmente **verificadas mecánicamente** por TLA+/TLC sobre el
espacio de estados abstracto del par de policies de referencia,
junto con el teorema de partición que ambas propiedades juntas
cubren el espacio de comportamiento condicional completo. La cota
ajustada de latencia de recuperación RLB-v1 está verificada
mecánicamente por un spec TLA+ separado que mirror-ea el algoritmo
del verificador.

### 1.1 Contribuciones

Hacemos **cuatro contribuciones claimable**, dos formales y dos
operacionales:

- **C1 — Theorem 1 (cota ajustada de latencia de recuperación).**
  Una cota cerrada superior `L ≤ peak + W − 1` sobre la latencia
  de recuperación de cualquier supervisor de autonomía closed-loop
  que use una ventana deslizante de tamaño `W` y un threshold
  count-of-K-in-W sobre outcomes mínimos `M`, formalizada en §6.4 y
  mostrada ajustada mediante un trace testigo donde la igualdad se
  alcanza (`L = 38 = 7 + 32 − 1`).
- **C2 — Teorema de partición verificado mecánicamente.** El
  comportamiento condicional del ciclo cerrado de referencia se
  particiona en `BAUD ⊕ ERUR`. Enunciado en TLA+ como
  `INV_PARTITION` y verificado por TLC sobre el espacio de estados
  alcanzable completo del modelo abstracto (constantes bounded
  `M=2, K=1, W=3`), es la primera formalización que conocemos para
  supervisores de seguridad de ventana deslizante.
- **C3 — Primitivo de reproducibilidad con capacidad de detección
  demostrada.** Un verificador CLI de una línea
  `ghost verify-properties` sobre logs MCAP content-addressed,
  distribuido vía PyPI con OIDC trusted publishing. Capacidad de
  detección de bugs demostrada en §8.2: un smoke con un calibrador
  buggy inyectado produce `BAUD-v1: VIOLATED`, exit code 1,
  `violation_count: 12` en el verificador no modificado.
- **C4 — Patrón end-to-end de citación de seguridad.** MCAP
  content-addressed + ADR + verificador función-pura + Hypothesis
  property test + CI gate + tagged release + wheel PyPI firmada por
  OIDC, ensamblados como una sola unidad de reproducibilidad para
  que un tercero pueda verificar cualquier afirmación de seguridad
  citada contra el run capturado sin confiar en el productor.

C1 y C2 son contribuciones formales, novedosas hasta donde sabemos
después de una revisión deliberada de prior art (§2.3). C3 y C4 son
contribuciones operacionales y de patrón; su novedad descansa en la
matriz de comparación de §2.3.

### 1.2 Qué es y qué no es este paper

Este paper no introduce nueva teoría de estimación; los ingredientes
de filtrado, calibración, y FDI sobre los que Ghost descansa están
bien establecidos (§2.1). La matemática de C1 es elemental en
retrospectiva pero no, hasta donde sabemos, previamente enunciada
como una cota cerrada en la literatura peer-reviewed de runtime
verification. La novedad de C2 está en mecanizar la partición para
supervisores de autonomía de ventana deslizante específicamente;
patrones TLA+ análogos existen para algoritmos distribuidos pero no
para este dominio.

---

## 2. Background y trabajo relacionado

### 2.1 Ingredientes subyacentes

Project Ghost se construye sobre ingredientes que son parte de la
práctica estándar de robótica y control: filtrado bayesiano y de
partículas; calibración de predicciones probabilísticas; incertidumbre
epistémica vs aleatoria; FDI; runtime verification; TLA+ y TLC para
explicit-state model checking; MCAP para serialización portable de
telemetría de robótica.

### 2.2 Trabajo previo más cercano

- **RTAMT** [Niković et al., ATVA 2020]: monitores STL sobre logs
  CPS con algoritmos online/offline y API Python. Lenguaje de
  propiedades es STL, no predicados hand-crafted; no hay capa de
  prueba mecánicamente verificada ni cadena de reproducibilidad
  content-addressed.
- **MoonLight** [Bartocci et al., RV 2020]: monitor STREL en Java
  con CLI, usado para benchmarks automotivos. Foco espacial; sin
  verificación formal del monitor.
- **ROSMonitoring** [Ferrando et al., 2020] y **ROSRV** [Huang et
  al., RV 2014]: monitores live del middleware ROS. Ambos online;
  ninguno hace verificación post-hoc con CLI de una línea.
- **Safe RL via shielding** [Jansen et al., CONCUR 2020]:
  enforcement runtime de seguridad vía filtros de acción. Online,
  action-blocking; Ghost es offline, log-verifying.
- **Control Barrier Functions** [MIT Lincoln Lab CBF Toolbox]:
  síntesis de controladores para restricciones continuas de
  seguridad. Complementario, no compitiendo.
- **Conformal prediction para robot safety** [Chakraborty et al.,
  TAC 2024]: cotas forward-looking sin distribución para gating de
  acciones. Predictivo; Ghost es retrospectivo.
- **Supervisory control of timed automata** [Flordal et al., 2022]:
  sintetiza supervisores timed. Construye nuevos supervisores;
  Ghost verifica traces existentes. Trabajos previos de timed
  automata no dan la cota cerrada de Theorem 1.
- **Surveys de formal verification para autonomía** [Rizaldi et al.,
  ACM CSUR 2020]: catalogan trabajo Coq/Lean/Isabelle/Alloy. Notan
  la ausencia de specs TLA+ mecánicamente verificados para
  supervisores de autonomía específicamente.

### 2.3 Matriz de comparación

| Dimensión | **Ghost** | RTAMT | MoonLight | Shielding | CBF | Conformal | Timed Aut. SC |
|---|---|---|---|---|---|---|---|
| Modo de verificación | Post-hoc log | On/offline | On/offline | Online enforce | Online control | Online gating | Offline synth. |
| Distribución | PyPI + OIDC | Source | Source | Framework | Toolbox | Code + paper | Synth. tool |
| Input content-addressed | **Sí** (SHA-256) | No | No | N/A | N/A | N/A | No |
| Verificador CLI de una línea | **Sí** | No | No | No | No | No | No |
| Naturaleza de propiedad | Comportamiento + latencia | STL | STREL | Invariantes | CBF | Predictiva | Discreta/timed |
| Prueba mecánica | **TLA+/TLC** | Ninguna | Ninguna | Informal | Informal | Ninguna | Timed-aut. |
| Output multi-propiedad | **5 reports/run** | 1/spec | 1/spec | Modular | 1/CBF | 1/model | 1/synth. |
| Teorema de partición | **BAUD ⊕ ERUR** | N/A | N/A | N/A | N/A | N/A | N/A |
| Cota cerrada de recovery | **L ≤ peak + W − 1** | N/A | N/A | N/A | N/A | Indirecta | Ninguna |
| Demo de detección de bugs | **Sí (§7.2)** | N/A | N/A | N/A | N/A | N/A | N/A |

Hasta donde sabemos, **ningún tool previo distribuye un verificador
content-addressed, función-pura, de propiedades de seguridad vía
`pip install` + wheels OIDC-firmadas con invariantes subyacentes
mecánicamente verificados**. Tratamos eso como el claim operacional
principal de Ghost; la comparación de arriba es la evidencia.

### 2.4 Qué es novedoso aquí

Dos contribuciones son claims operacionales de patrón (el primitivo
de reproducibilidad y el patrón end-to-end de citación). Dos son
claims formales que, hasta donde sabemos después de una revisión
deliberada de prior art across CAV, RV, FMAS, TACAS, ICRA, IROS,
CoRL 2018–2026 y los surveys citados arriba, no aparecen en la
literatura peer-reviewed en la forma que enunciamos:

- **La cota cerrada de latencia de recuperación `L ≤ peak + W − 1`**
  para monitores de ventana deslizante count-of-K-in-W. Los
  sequential probability ratio tests dan cotas óptimas de sample
  size para hypothesis testing, pero no esta forma cerrada exacta
  para recovery de ventana deslizante, y el trabajo de timed
  automata prefiere garantías cualitativas de non-blocking sobre
  cotas cuantitativas concretas. La formalizamos como Theorem 1
  (§6.4) y demostramos que es ajustada por construcción.
- **El teorema de partición `BAUD ⊕ ERUR`** sobre el espacio de
  comportamiento condicional por-ciclo de un supervisor de autonomía
  closed-loop, probado por TLC sobre el modelo abstracto. No hemos
  localizado formalización previa de partición de comportamiento
  condicional para supervisores de seguridad de ventana deslizante
  específicamente.

---

## 3. El conjunto de propiedades

Las cinco propiedades están enunciadas en ADRs vinculantes
(inmutables una vez aceptados) y verificadas por funciones puras en
`src/project_ghost/properties/`. Cada verificador retorna un report
typed con `holds: bool`, metadata estructurada por-ciclo, y el
SHA-256 del MCAP.

| ID | Propiedad | Naturaleza | Multi-ciclo? |
|---|---|---|---|
| **BAUD-v1** | Bounded Action Under Drift | Condicional sobre drift | No, per-ciclo |
| **ERUR-v1** | Eventual Reactivation Under Recovery | Condicional sobre drift ausente + KNOWN | No, per-ciclo |
| **MD-v1** | Monotonic Degradation | Estructural incondicional | No, per-ciclo |
| **RLB-v1** | Recovery Latency Bound | Temporal cuantitativa | Sí |
| **FPB-v1** | False Positive Bound observer | Observacional cuantitativa | No, per-ciclo |

Las cinco son self-contained: cada una está enunciada formalmente en
un ADR, verificada por una función Python en `properties/`, y
testimoniada inline en cada smoke. Las descripciones detalladas y
sus pre/postcondiciones formales viven en los ADRs respectivos
0031–0035.

---

## 4. Arquitectura del verificador

### 4.1 MCAP content-addressed

Cada run capturado se materializa como un MCAP con un schema de
mensaje conocido por canal. Canales de interés incluyen
`/fusion/results`, `/uncertainty/*`, `/decisions/decision`,
`/actuation/command`, `/prediction/*`. Cada mensaje es determinista
dado los inputs upstream (replay verification, ADR-0030, lo asegura
byte-exact). El SHA-256 del MCAP es la dirección de contenido y se
registra dentro del report de cada verificador.

### 4.2 Verificadores función-pura

Cada propiedad tiene un verificador en
`src/project_ghost/properties/verify_<id>.py`. El verificador (a)
abre el MCAP read-only, (b) recorre los canales en orden por ciclo,
(c) computa la precondición y la postcondición por ciclo a partir
únicamente de los mensajes almacenados (sin replay, sin simulación),
y (d) retorna un report typed.

### 4.3 Superficie CLI

```bash
$ pip install project-ghost==0.2.2
$ python -m project_ghost.examples.closed_loop_smoke
$ ghost verify-properties --mcap closed_loop_smoke.mcap
BAUD-v1: HOLDS  (M=4, K=2, 6/10 cycles evaluated)
ERUR-v1: HOLDS  (M=4, K=2, 4/10 cycles evaluated)
MD-v1:   HOLDS  (10/10 cycles evaluated)
RLB-v1:  HOLDS  (W=32, 0/10 cycles evaluated)
FPB-v1:  HOLDS  (fire_fraction=0.60, 6/10 cycles evaluated)
$ echo $?
0
```

Convenciones de exit code: `0` iff todas las propiedades holden,
`1` si alguna viola o el verificador crashea, `2` para errores de
argumentos. `--json` emite un objeto JSON determinístico apto para
consumo de CI.

### 4.4 Self-evidence inline + CI como garantía continua

`run_closed_loop_smoke()` retorna un `SmokeSummary` que carga los
cinco property reports computados contra el MCAP recién escrito.
`ci.yml` corre el smoke + verificador en cada push, ejecuta TLC
sobre las tres specs TLA+, y verifica byte-equality cross-machine
del MCAP entre runners Linux y Windows. Cualquier violación bloquea
el build.

---

## 5. Verificación mecánica

### 5.1 Por qué TLA+

Property-based testing con Hypothesis (200+ ejemplos por propiedad)
provee evidencia fuerte a escala de producción, pero prueba que la
propiedad se mantiene *sobre los inputs que el generator sampleó*, no
sobre todos los inputs. El siguiente escalón de evidencia es
**verificación mecánica sobre un modelo abstracto finito**.
Escogemos TLA+ con TLC sobre theorem proving (Lean, Coq) por un
argumento de costo/beneficio: TLC es exhaustivo sobre el espacio de
estados bounded en segundos, donde una prueba en Lean serían
semanas.

### 5.2 Las tres especificaciones

Tres specs TLA+ cubren conjuntamente las cinco propiedades; cada una
mirror-ea el código Python línea por línea para los policies en
scope.

- **`BaudErur.tla`** modela el closed-loop como una state machine con
  una transición por ciclo. Verifica BAUD-v1, ERUR-v1, partition y
  MD-v1.
- **`Rlb.tla`** restringe el modelo a la hipótesis de drift
  consecutivo del Theorem 1 vía dos fases (`ACCUMULATING`,
  `RECOVERING`). Mirror-ea el algoritmo del verificador
  `properties/rlb.py`.
- **`Fpb.tla`** modela el counter automaton de FPB-v1 en aritmética
  entera. Verifica la well-formedness estructural del counter, no
  una cota probabilística sobre el fire rate (eso sería FPB-v2).

### 5.3 Invariantes verificados

Los tres specs juntos verifican 11 invariantes en CI continuo (5 en
BaudErur, 3 en Rlb, 3 en Fpb), cubriendo BAUD/ERUR/MD/RLB/FPB con al
menos un invariante estructural cada una. Esto eleva la cobertura
mecánica de 3/5 propiedades en v0.2.1 a **5/5 en v0.2.2**.

### 5.4 Bounds y qué prueban

Para tractabilidad, cada spec corre con constantes bounded pequeñas:

| Spec | Bounds | Por qué es suficiente |
|---|---|---|
| `BaudErur.tla` | `M=2, K=1, W=3` | Casos *frontera* de la precondición exhaustos en cualquier `M > 0`; `W ≥ M` ejercita la ventana deslizante. |
| `Rlb.tla` | `W=4, MAX_DRIFT=4` | Ejercita las cuatro fases de la prueba del Theorem 1 (acumulación, saturación, flush, recovery). |
| `Fpb.tla` | `MAX_CYCLES=8` | Ocho ciclos enumeran el counter automaton through cada alternancia fire/non-fire. |

Comportamiento a constantes de escala de producción (`M=4, K=2,
W=32`) está cubierto por los property tests. TLA+ rellena el rincón
*pequeño pero exhaustivo*. Elevar Theorem 1 a *cualquier W finito*
(prueba unbounded) es el candidato ADR-0038 documentado en
[`docs/proofs/TLAPS_roadmap.md`](../../proofs/TLAPS_roadmap.md).

### 5.5 Qué afirma y qué NO afirma

**Sí afirma:** que los enunciados de las propiedades en ADRs
0031–0033 son lógicamente consistentes con la semántica del policy
de referencia; que la partición BAUD + ERUR es estructuralmente
completa en el modelo abstracto; que ninguna combinación
(history, raw_level) en el espacio de estados bounded viola los
invariantes.

**No afirma:** que la implementación Python espeja fielmente al
modelo TLA+ (el bridge es por inspección humana; automatizarlo es
future work); que las constantes bounded prueban el caso unbounded;
que policies no-referencia satisfacen los invariantes (cada uno
necesitaría su propio spec).

---

## 6. Una cota cerrada de latencia de recuperación

### 6.1 Setting

Sea `(o_t)_{t ≥ 1}` el stream de outcomes de predicción por ciclo,
clasificados en una partición binaria `dirty ∈ {0, 1}` donde
`dirty = 1` cuando el verdict Mahalanobis está en o sobre el
threshold considerado por la precondición de BAUD. Sea `H_t` la
ventana deslizante de los últimos `W` outcomes disponibles en el
ciclo `t`:

```
H_t = (o_{max(1, t − W + 1)}, ..., o_t),    |H_t| ≤ W.
```

El calibrador de referencia (`MahalanobisDowngradePolicy(M, K)`)
hace downgrade del nivel de self-assessment ajustado en un rango en
el lattice de confianza en cualquier ciclo donde

```
|H_t| ≥ M    y    Σ_{o ∈ H_t} dirty(o) ≥ K.    (1)
```

### 6.2 Definiciones

- **peak** = máximo conteo de dirty observado en la ventana durante
  el dirty run.
- **drift interval** = sub-trace maximal terminando en el último
  ciclo donde (1) se mantiene.
- **L** = la latencia de recuperación: número de ciclos consecutivos
  donde la ventana contiene al menos un outcome dirty.

### 6.3 Theorem 1 (Cota ajustada de latencia de recuperación)

**Theorem 1 (RLB-v1, régimen transitorio).** *Sea
`(o_t)_{t ≥ 1}` un stream que contiene un drift interval transitorio
de `N ≤ W` outcomes dirty consecutivos seguidos por outcomes clean,
con ventana `W`. Defina:*

- *`peak = min(N, W) = N`, el máximo dirty count observado en la
  ventana durante el dirty run;*
- *`L`, la dirty-run length: el número de ciclos consecutivos donde
  la ventana contiene al menos un outcome dirty.*

*Entonces `L = peak + W − 1`. Equivalentemente, la cota
`L ≤ peak + W − 1` se alcanza con igualdad. La cota es por tanto
ajustada.*

**Prueba.** Trazar el estado de la ventana ciclo por ciclo, notando
el invariante de la ventana deslizante: en el ciclo `t`, la ventana
contiene los últimos `min(t, W)` outcomes.

- **Fase de acumulación** (ciclos 1..N). Cada ciclo agrega un
  outcome dirty; la ventana aún no está llena (porque `N ≤ W`), así
  que no hay expulsión. El dirty count sube de 1 a `N = peak`. Los
  `N` ciclos tienen count `≥ 1`, por tanto son dirty.
- **Fase de saturación** (ciclos N+1..W). Cada ciclo agrega un
  outcome clean; la ventana aún no está llena, sin expulsión. El
  dirty count se queda en `peak`. Los `W − N` ciclos son dirty.
- **Fase de flush** (ciclos W+1..W+peak−1). La ventana ahora está
  llena; cada nuevo outcome clean expulsa el más viejo. Por
  construcción, los más viejos son los outcomes dirty que llegaron
  primero. El dirty count baja en 1 por ciclo, de `peak` a `1`. Los
  `peak − 1` ciclos son dirty (count `≥ 1`).
- **Recovery** (ciclo W+peak). El último outcome dirty es expulsado.
  Dirty count baja a `0`. Este ciclo es clean.

Sumando los ciclos dirty: `N + (W − N) + (peak − 1) = W + peak − 1`.
Como `peak = N` en el régimen transitorio, `L = peak + W − 1`. ∎

**Corolario 1 (Régimen operacional).** Cuando `N > W`, el drift
sobrevive a la ventana; `peak = W` y `L = N + W − 1`. La cota
`peak + W − 1 = 2W − 1` se excede cuando `N > W`. La cota
`L ≤ peak + W − 1` caracteriza operacionalmente el régimen
*transitorio*; en el régimen de drift sostenido, no ocurre recovery
transition *durante el drift* y el verificador registra la propiedad
vacuamente en el trace capturado.

**Corolario 2 (Sanity estructural).** Un trace donde
`L > peak + W − 1` en una recovery transition es imposible bajo una
ventana deslizante de tamaño `W` correctamente implementada. El
`RLBViolation` del verificador por tanto también sirve como check de
integridad estructural sobre la implementación de la ventana.

### 6.4 Check operacional de ajustabilidad

El smoke drift-then-recovery (`closed_loop_smoke_with_recovery.py`)
está ingeniado para exhibir Theorem 1 en las constantes de producción
(`N = peak = 7`, `W = 32`):

```
L_observed = 38 = 7 + 32 − 1 = peak + W − 1.
```

El test de integración
`tests/integration/test_closed_loop_smoke_with_recovery.py`
asserta que la recovery transition fires exactamente en el ciclo 39
y en ningún otro lugar antes o después. El smoke por tanto es testigo
de que la cota es *alcanzable* — es decir, Theorem 1 es ajustado en
el régimen transitorio.

### 6.5 Scope y limitaciones

Theorem 1 aplica al calibrador de referencia
`MahalanobisDowngradePolicy(M, K)` y su mecanismo de ventana
deslizante con partición binaria dirty/clean de outcomes.
Calibradores con hysteresis, history recency-weighted, o partición
multi-banda están fuera de scope; sus cotas de recovery requerirían
sus propias derivaciones. La cota `peak + W − 1` es significativa
solo en el régimen transitorio (`N ≤ W`); en el régimen sostenido no
ocurre recovery transition durante el drift, y la propiedad se
mantiene vacuamente en el trace capturado hasta que el drift
termine.

`Rlb.tla` prueba el theorem por TLC sobre un modelo abstracto
bounded (`W=4`); un proof outline TLAPS para el caso unbounded vive
en [`docs/proofs/Rlb_unbounded.tla`](../../proofs/Rlb_unbounded.tla)
con el plan de discharge documentado en
[`docs/proofs/TLAPS_roadmap.md`](../../proofs/TLAPS_roadmap.md).
Elevar ese outline a prueba verificada es candidato ADR-0038.

---

## 7. Superficie de reproducibilidad

El claim de cabecera es que un tercero puede verificar el conjunto
de propiedades contra un run capturado **sin confiar en el
productor**. La superficie de reproducibilidad tiene cinco capas:

1. **MCAP content-addressed.** El SHA-256 se computa una vez y se
   carga dentro de cada property report.
2. **Pipeline determinístico.** ADR-0030 (Replay Verification v1)
   asserta que los canales downstream son reproducibles byte-exact.
3. **Verificador función-pura.** Sin I/O más allá de leer el MCAP;
   sin estado global; sin sources de random.
4. **Hypothesis property tests.** ~50 tests con 200+ ejemplos
   generados por propiedad.
5. **Self-check TLA+ continuo.** TLC corre en cada push y bloquea
   el build en cualquier violación de invariante.

Un lector que quiera citar un claim de seguridad de Project Ghost
puede entonces escribir:

> Project Ghost v0.2.2 satisface BAUD-v1 sobre el MCAP del smoke de
> referencia incluido `SHA-256:<hash>`, verificado por
> `ghost verify-properties --mcap closed_loop_smoke.mcap` desde
> `pip install project-ghost==0.2.2`, y adicionalmente satisface
> `INV_BAUD`, `INV_ERUR`, `INV_PARTITION` sobre el modelo abstracto
> `BaudErur.tla` en bounds `M=2, K=1, W=3`, y `INV_RLB` (Theorem 1)
> sobre `Rlb.tla` en `W=4`.

Esa es la contribución C4 en acción.

---

## 8. Evaluación

(Resumen interno. Para detalles cuantitativos consultar la versión
inglesa, secciones §8.1 a §8.7.)

- **§8.1** Tests + CI + verificación mecánica: 1687 tests passing,
  ruff + mypy strict + deptry clean, CI matrix 4 combinaciones, 3
  specs TLA+ en CI continuo.
- **§8.2** Violation matrix: 6 categorías de bugs, todas detectadas
  por el verificador no modificado. BAUD-v1 dispara en
  calibrator_no_downgrade, decision_proceeds_anyway,
  actuation_non_safe_reason; MD-v1 en calibrator_invents_confidence;
  ERUR-v1 en decision_never_proceeds; FPB-v1 en
  fpb_threshold_exceeded.
- **§8.3** Evaluación paramétrica: 9 corridas (3 policies × 3
  longitudes de trace), las 5 propiedades HOLD en todas. Verificador
  lineal en longitud del trace: 21 ms para n=10, 100 ms para n=50,
  406 ms para n=200.
- **§8.4** Verificador policy-agnostic, precondiciones
  policy-specific: corriendo el smoke bajo
  `MahalanobisDowngradePolicy`, `EWMADowngradePolicy`, y
  `PerAxisHysteresisDowngradePolicy`, el verificador procesa los
  tres MCAPs sin cambios. ERUR-v1 viola en EWMA y PerAxis porque se
  evalúa con los parámetros del reference, no de la policy. Insight
  importante: la propiedad es policy-agnostic en código pero
  policy-specific en su parametrización.
- **§8.5** Escenarios shape-realistic: 3 perfiles inspirados en
  literatura VIO/SLAM (gps_denial, slow_biased_drift,
  cascading_failure). Las 5 propiedades HOLD en los 3. Honesto:
  shape-realistic, no data-real; integración con datos reales de
  PX4/ROSBag es roadmap futuro.
- **§8.6** Benchmark cuantitativo vs RTAMT: Ghost (BAUD-v1 exacto)
  HOLDS en 23 ms; RTAMT (STL aproximación) VIOLATED en 0.15 ms.
  Diferencia de veredictos refleja gap de expresividad: STL no
  puede expresar K-of-M-in-W como single formula. Los tools son
  complementarios.
- **§8.7** Determinismo cross-machine: enforced por CI con matrix
  ubuntu+windows que diff-ea SHA-256 del MCAP y del JSON
  canonicalizado.

---

## 9. Limitaciones y threats to validity

Cataloguamos las limitaciones explícitamente, en el mismo espíritu
que las secciones §Scope per-propiedad de los ADRs.

- **Sim, no hardware.** Los MCAPs verificados aquí vienen de una
  trampa de overconfidence simulada, no de logs de flight reales.
  El conjunto de propiedades está bien definido sobre cualquier
  MCAP que respete el schema, pero el claim *del mundo real* (el
  agente parará bajo failure no modelado en un drone real) requiere
  un backend HAL y una campaña de hardware, ambas diferidas a fase
  posterior.
- **Solo policies de referencia.** La prueba TLA+ y la semántica de
  las propiedades targetan los policies específicos de referencia.
  Cada policy no-referencia necesitaría su propio ADR, su propia
  especialización del verificador, y su propio spec TLA+.
- **TLC bounded.** La prueba TLA+ es exhaustiva sobre un espacio de
  estados finito en constantes pequeñas; comportamiento en
  constantes de escala de producción descansa en los property
  tests, no en la prueba TLA+.
- **Bridge Python↔TLA+ por inspección.** Una divergencia futura
  entre el código Python y la definición TLA+ podría silenciosamente
  debilitar el claim. Mitigación: revisar y re-correr TLC en cada
  cambio al calibrador de referencia o policy de decisión.
- **FPB estadístico fuera de scope.** FPB-v1 es observacional; un
  FPB-v2 estadístico con cotas Monte Carlo es candidato ADR
  futuro.

---

## 10. Future work

- **ADR-0037 (candidate)**: integración con datos de flight reales
  vía adapter PX4 ULog / ROSBag / EuRoC MAV.
- **ADR-0038 (candidate)**: prueba TLAPS de la versión unbounded de
  Theorem 1 y del teorema de partición.
- **ADR-0039 (candidate)**: FPB-v2 estadístico con cota Monte Carlo
  sobre el fire rate empírico.
- **ADR-0040 (candidate)**: ERUR-v2 enunciado abstractamente sobre
  `policy.precondition(history)`, generalizando la
  parametrización.
- **HAL backend campaign**: backend hardware (Pixhawk + companion).
- **Conformance suite** poblando el marker `conformance` de pytest
  con el contrato HAL.

---

## 11. Conclusión

Project Ghost no es una nueva teoría de autonomía bajo incertidumbre.
Es una *referencia del patrón de citación* que la teoría existente
merece: un log content-addressed, un verificador función-pura sobre
CLI, statements de propiedades formales en ADRs vinculantes,
Hypothesis property tests, un CI gate, **tres specs TLA+
mecánicamente verificados por TLC**, un tagged release, y un wheel
firmado por OIDC — todo en un solo artefacto, todo en un comando de
shell. La contribución está en el ensamblaje; la evidencia es
re-ejecutable desde `pip install project-ghost==0.2.2`.

---

## Referencias

Mismo conjunto de 18 referencias que la versión inglesa. Para evitar
duplicación y deriva, consultar
[`docs/paper/project_ghost_v0_2.md` § References](../project_ghost_v0_2.md#references).
