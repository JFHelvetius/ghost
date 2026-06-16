# Contratos epistémicos para sistemas autónomos: un patrón verificable de afirmaciones de seguridad bajo incertidumbre

**Autor:** Javier Menéndez Mateos (`jfhelvetius@gmail.com`)
**Afiliación:** Independiente
**Versión:** v0.2.3 (2026-06-12)
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

> *Un agente autónomo debería tener obligaciones verificables
> sobre cómo se relaciona con su propia incertidumbre.*
>
> *Una afirmación de seguridad debe emitirse junto con todo lo que
> un tercero necesita para rechazarla.*
>
> — Las dos frases que este paper existe para defender.

---

## Resumen

**Tesis: los agentes autónomos deberían tener contratos
verificables sobre su propia postura epistémica — cómo degradan
la confianza, se recuperan, permanecen acotados, y traducen
creencia en acción bajo incertidumbre.** La mayoría de los
verificadores runtime existentes preguntan predicados del mundo
(velocidad, distancia, temperatura); nosotros proponemos preguntar
predicados de la postura del agente hacia su propia
incertidumbre. Los llamamos **contratos epistémicos de
seguridad**. Describimos **Project Ghost**, una plataforma open
source que (i) define cinco contratos epistémicos para un
supervisor de autonomía de referencia (BAUD/ERUR/MD/RLB/FPB),
(ii) verifica cada uno vía función pura sobre un log MCAP
content-addressed, (iii) chequea mecánicamente los invariantes
subyacentes vía TLA+/TLC, y (iv) empaqueta cada contrato junto
con un run grabado y el verificador en una **cita de seguridad
ejecutable**: `pip install project-ghost==0.2.3` seguido de
`ghost verify-properties --mcap <log>` permite a un tercero
reproducir el veredicto — o contradecirlo.

Los contratos de referencia cubren una teoría mínima de
comportamiento bajo incertidumbre: si sospechas que estás
equivocado, actúa conservadoramente (BAUD); cuando la evidencia
se restablece, vuelve a actuar (ERUR); nunca afirmes saber más
de lo que la evidencia respalda (MD); la incertidumbre no puede
durar indefinidamente (RLB); la desconfianza debe ser medible y
auditable (FPB). Tres specs TLA+ chequean conjuntamente 11
invariantes en CI, incluyendo el teorema de partición
`BAUD ⊕ ERUR` y la cota de latencia de recuperación
`L ≤ peak + W − 1`.

La evaluación empírica sobre una violation matrix de seis
categorías de bugs inyectados, tres policies de calibración
estructuralmente distintas, tres perfiles de drift
shape-realistic, un benchmark head-to-head contra RTAMT, y un
experimento de discriminación sobre telemetría real de vuelo PX4
v1.10 — donde dos componentes buggy independientes, substituidos
en el mismo vuelo físico, flipean BAUD-v1 de HOLDS a VIOLATED
mientras las cuatro otras propiedades siguen HOLD — establece
que el verificador es policy-agnostic, determinístico across
runners Linux y Windows en CI, e informativo sobre telemetría
real. El artefacto completo es re-ejecutable desde
`pip install project-ghost==0.2.3`.

**Palabras clave:** contratos epistémicos de seguridad, runtime
verification, incertidumbre en autonomía, citas de seguridad
ejecutables, telemetría content-addressed, TLA+/TLC, MCAP.

---

## 1. Introducción

La mayoría de los verificadores runtime existentes preguntan
predicados del mundo: velocidad por debajo de una cota, distancia
por encima de un margen, temperatura dentro de un envelope.
Nosotros preguntamos predicados de la postura del agente hacia su
propia incertidumbre: contratos que el agente debe satisfacer
sobre *cómo* degrada la confianza, *cómo* se recupera, *cómo* su
incertidumbre permanece acotada, y *cómo* la creencia se traduce
en acción. Los llamamos **contratos epistémicos de seguridad**.

Los contratos epistémicos no son contratos sobre lo que el agente
cree; son contratos sobre lo que el agente debe hacer *dado* lo
que cree sobre sí mismo. "Si detectas que tu historia de
calibración contiene evidencia de drift, no puedes emitir una
acción no-conservadora" (BAUD) es una forma de propiedad distinta
a "la velocidad debe permanecer bajo 5 m/s" (un predicado STL
sobre una señal): la precondición se refiere al auto-assessment
del agente, no al mundo.

De ahí sigue una segunda brecha: incluso si la forma correcta de
propiedad existe, un tercero que quiere verificar una afirmación
de seguridad contra un run grabado típicamente no puede — no hay
comando de shell, ni log content-addressed, ni verificador
función-pura que pueda re-ejecutar en su propia máquina. Cerramos
ambas brechas en una sola plataforma. Project Ghost es sim-first,
escrito en Python, y se distribuye como paquete `pip`-instalable
con un subcomando CLI (`ghost verify-properties`) que toma un log
MCAP capturado y devuelve un veredicto byte-exact sobre cinco
contratos epistémicos para un supervisor de autonomía de
referencia. Cada contrato está enunciado en un ADR vinculante,
verificado por una función pura, ejercitado por property tests
Hypothesis, y self-enforced en cada push por CI. Dos contratos
(BAUD-v1 y ERUR-v1) están adicionalmente **verificados
mecánicamente** por TLA+/TLC.

El empaquetado de un contrato epistémico junto con su run grabado
y su verificador en una sola unidad citable y falsable por
terceros es lo que llamamos una **cita de seguridad ejecutable**.
El artefacto citado *es* el mecanismo de falsación.

### 1.1 Contribuciones

**Los contratos epistémicos de seguridad son obligaciones
verificables que un agente autónomo debe satisfacer sobre su
propia incertidumbre.** Un contrato es una tripla (precondición
sobre el estado epistémico del agente, postcondición sobre el
comportamiento del agente, verificador función-pura sobre un run
grabado) — una clase de propiedad distinta de los predicados
sobre el mundo que dominan runtime verification hoy. Empaquetamos
cada contrato junto con el run y el verificador en una **cita de
seguridad ejecutable**.

Hacemos **tres contribuciones**:

- **C1 — Contratos epistémicos de seguridad como objetivo de
  verificación (conceptual).** Una clase de propiedades de
  seguridad cuyas precondiciones se refieren a la creencia del
  agente sobre su propia incertidumbre (nivel de
  calibrated-self-assessment, detección de drift, medición de
  fire-rate) en lugar de a señales del mundo externo. Distinto
  de predicados STL sobre señales y de belief monitoring estilo
  POMDP; definición formal en §1.2.

- **C2 — Implementación de referencia: Ghost (artefacto).** Un
  supervisor de autonomía closed-loop que instancia cinco
  contratos epistémicos (BAUD-v1, ERUR-v1, MD-v1, RLB-v1, FPB-v1)
  empaquetados como citas de seguridad ejecutables — ADRs
  vinculantes, telemetría MCAP content-addressed,
  `ghost verify-properties --mcap`, wheels PyPI firmadas por
  OIDC, y verificador policy-agnostic across tres policies de
  calibración (§8.4).

- **C3 — Verificación mecánica + evaluación empírica
  (validación).** Tres specs TLA+ (11 invariantes en CI,
  incluyendo el teorema de partición `BAUD ⊕ ERUR`), una
  violation matrix de seis categorías (§8.2), perfiles de drift
  shape-realistic (§8.5), un benchmark de capacidades contra
  RTAMT (§8.6), y discriminación sobre telemetría real PX4: dos
  componentes buggy substituidos en el mismo vuelo físico flipean
  BAUD-v1 de HOLDS a VIOLATED (§8.8).

La cota de latencia de recuperación `L ≤ peak + W − 1` se
presenta como **resultado de apoyo**, no como contribución.

### 1.2 Contratos epistémicos de seguridad: definición formal

Un **contrato epistémico de seguridad** es una tripla `(P, Q, V)`
donde:

- `P` es un predicado sobre el **estado epistémico del agente en
  el ciclo `t`** — una función del registro de self-assessment,
  historia de calibración, y stream de outcomes disponible en
  `t`. `P` no se refiere directamente al mundo; se refiere a lo
  que el agente cree sobre su propia postura hacia el mundo.
- `Q` es un predicado sobre el **comportamiento del agente en el
  ciclo `t`** — una función del calibrated assessment, decisión,
  y comando de actuador emitido en `t`.
- `V` es un verificador función-pura tal que, dado un run grabado
  `r` (una secuencia content-addressed de records de telemetría
  per-ciclo), `V(r)` retorna HOLDS sii cada ciclo `t` de `r` que
  satisface `P_t` también satisface `Q_t`, y VIOLATED en caso
  contrario con un ciclo testigo.

Tres observaciones:

1. **Un contrato epistémico no es un predicado STL.** Los
   monitores STL evalúan predicados de la forma `señal <
   umbral` sobre señales temporales reales. Los predicados
   atómicos de un contrato epistémico son sobre el *registro
   interno* del agente, que es data estructurada, no una señal
   continua. Los operadores STL (always, eventually, until) se
   pueden elevar para actuar sobre el índice de ciclo de un
   contrato epistémico; así se expresa RLB-v1.

2. **Un contrato epistémico no es belief monitoring.** El belief
   monitoring rastrea lo que un agente cree sobre el estado
   oculto del mundo (e.g., updates de creencia POMDP). Un
   contrato epistémico verifica una obligación sobre la
   *relación del agente con* su propia creencia — que debe
   degradar la confianza en las condiciones correctas,
   recuperarse en latencia acotada, y nunca afirmar más
   confianza que la evidencia respalda. El contrato está un
   nivel por encima de la creencia: es una propiedad de la
   *política epistémica* del agente, no de sus creencias.

3. **Un contrato epistémico se vuelve una afirmación de
   seguridad falsable por terceros cuando se empaqueta junto a
   un run grabado content-addressed y un wheel verificador
   OIDC-firmado.** A este empaquetado lo llamamos **cita de
   seguridad ejecutable** (Figura 1).

Los cinco contratos que enviamos (§3) instancian esta definición
sobre un supervisor de autonomía representativo.

### 1.3 Qué es y qué no es este paper

Este es un paper de ingeniería e infraestructura que introduce
una clase de propiedad, no un paper de teoría que prueba una
lógica nueva. Los ingredientes de filtrado, calibración, y FDI
sobre los que Ghost descansa están bien establecidos (§2.1). La
cota de latencia de recuperación es un resultado auxiliar, no
una contribución. El teorema de partición de §5.3 es novedoso *en
la forma que lo mecanizamos* — un `INV_PARTITION` en TLA+ sobre
el ciclo cerrado de referencia. Las contribuciones que
defendemos son **el framing epistemic-contracts** (C1), **la
implementación de referencia** (C2), y **la validación** (C3).

#### Figura 1: El patrón de citación de seguridad

```mermaid
flowchart LR
    subgraph P["Productor (autor Ghost / operador)"]
        ADR["📜 ADR vinculante<br/>predicado de propiedad"]
        Code["🔧 Verificador función-pura<br/>+ pipeline closed-loop"]
        Spec["🧪 Property tests + TLA+<br/>(11 invariantes)"]
    end
    subgraph R["CI + release firmado"]
        CIv["⚙ ghost verify-properties<br/>+ TLC + cross-machine"]
        Tag["🏷 Release tagged v0.2.3<br/>wheel PyPI firmada OIDC"]
    end
    subgraph A["Artefacto citable"]
        MCAP["📦 Log MCAP<br/>SHA-256, byte-exact"]
        Cite["🔗 La citación<br/>pip install + SHA-256 + ADR ID"]
    end
    subgraph V["Tercero (cualquiera)"]
        Cmd["💻 ghost verify-properties<br/>--mcap log.mcap"]
        Out["📋 Exit 0/1 + JSON determinístico<br/>(veredicto por propiedad)"]
    end
    ADR --> Code
    Code --> Spec
    Spec --> CIv
    CIv --> Tag
    Code -. produce .-> MCAP
    Tag --> Cite
    MCAP --> Cite
    Cite ==> Cmd
    Cmd ==> Out
```

La figura se lee de izquierda a derecha como el pipeline operacional
de una afirmación de seguridad bajo el patrón. En el lado del
productor, un ADR vinculante enuncia el predicado de la propiedad,
un verificador función-pura implementa su semántica, y los property
tests Hypothesis + specs TLA+ ejercitan los invariantes. CI gate-ea
cada push y el tagging emite un release firmado por OIDC. El
artefacto citable carga dos mitades: el run (MCAP con SHA-256) y la
herramienta de verificación (wheel PyPI fijada por versión). Un
tercero las concatena con un comando de shell y obtiene un JSON
veredicto determinístico por propiedad. **La contribución del paper es el ensamblaje de las siete cajas en
una sola unidad shippable, de modo que — por primera vez, hasta
donde sabemos dentro de los venues revisados — una afirmación de
seguridad puede emitirse junto con todo lo que un tercero necesita
para rechazarla.** Todo lo demás (el conjunto de propiedades, la
cota cerrada, los specs TLA+) instancia el patrón sobre un
supervisor representativo.

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
  automata no dan esa cota cerrada.
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
| Demo de detección de bugs | **Sí (§8.2)** | N/A | N/A | N/A | N/A | N/A | N/A |

Hasta donde sabemos, **ningún tool previo distribuye un verificador
content-addressed, función-pura, de propiedades de seguridad vía
`pip install` + wheels OIDC-firmadas con invariantes subyacentes
mecánicamente verificados**. Tratamos eso como el claim operacional
principal de Ghost; la comparación de arriba es la evidencia.

El eje en el que Ghost es genuinamente distinto del tooling de
runtime verification de arriba es el *tipo* de predicado que
monitoriza. RTAMT, MoonLight, ROSMonitoring y shielding
monitorizan predicados sobre el mundo externo (cotas de velocidad,
umbrales de distancia, envolventes de señal). Las cinco
propiedades de Ghost (§3) son contratos sobre la **postura
epistémica** del agente — cómo su propia confianza puede
degradarse, recuperarse, acotarse y traducirse en acción bajo
incertidumbre. La mecánica se solapa (ambos replay-eamos
traces); la pregunta que se hace no es la misma.

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
  cotas cuantitativas concretas. La formalizamos como RLB-v1
  (§6.4) y demostramos que es ajustada por construcción.
- **El teorema de partición `BAUD ⊕ ERUR`** sobre el espacio de
  comportamiento condicional por-ciclo de un supervisor de autonomía
  closed-loop, probado por TLC sobre el modelo abstracto. No hemos
  localizado formalización previa de partición de comportamiento
  condicional para supervisores de seguridad de ventana deslizante
  específicamente.

### 2.5 Dónde se sitúa Ghost frente a la práctica industrial

El paisaje autonomía-seguridad está dominado por esfuerzos
industriales que operan a escalas que Ghost no alcanza: el safety
case framework de Waymo, la state machine `commander` de PX4, la
tradición NFM de NASA, la arquitectura de seguridad de Autoware, la
metodología de safety case de Cruise. Todos comparten una propiedad
organizacional que Ghost no tiene: **equipos de safety engineers y
acceso propietario a telemetría, infraestructura de testing y
reguladores**. Producen artefactos de assurance que justifican
deployment operacional.

Ghost hace un claim mucho más pequeño — *un tercero puede verificar
una propiedad enunciada contra un run capturado emitiendo un comando
de shell* — pero lo hace **operacionalmente**, no por apelación a
review interno. El nicho complementario que creemos llenar es el gap
entre *"este software es seguro"* (un claim cerrado firmado por una
organización) y *"aquí está el verificador y el log; chequéalo tú
mismo"* (un claim abierto citable por un tercero). El citation
pattern no es un substituto de safety cases industriales; es un
primitivo que esos cases podrían citar. No reclamamos equivalencia,
scope o madurez frente a los trabajos arriba.

---

## 3. El conjunto de propiedades

**A diferencia de la runtime verification tradicional, que
principalmente monitoriza predicados sobre el mundo externo
(velocidad, distancia, temperatura), Ghost verifica contratos
sobre la postura epistémica del agente: cómo la confianza puede
degradarse, recuperarse, acotarse y traducirse en acción bajo
incertidumbre.** Las cinco propiedades forman una teoría mínima
del comportamiento bajo incertidumbre para un agente autónomo:

| ID | Predicado formal | Lectura epistémica |
|---|---|---|
| **BAUD-v1** | Drift detectado → no PROCEED + acción conservadora | *Si sospechas que estás equivocado, actúa conservadoramente.* |
| **ERUR-v1** | Drift ausente ∧ belief KNOWN → PROCEED | *Cuando la evidencia se restablece, vuelve a actuar.* |
| **MD-v1** | `adjusted ≼ raw` (sin inflación) | *Nunca afirmes saber más de lo que la evidencia respalda.* |
| **RLB-v1** | `L ≤ peak + W − 1` (recuperación acotada) | *La incertidumbre no puede durar indefinidamente.* |
| **FPB-v1** | Tasa empírica expuesta y pineada | *La desconfianza debe ser medible y auditable.* |

Cada propiedad está enunciada en un ADR vinculante (inmutable
una vez aceptado) y verificada por una función pura en
`src/project_ghost/properties/`.

### 3.1 BAUD-v1 — Bounded Action Under Drift

> *Si el agente sospecha que su propia creencia es incorrecta,
> debe actuar conservadoramente.*

Cuando el drift se detecta (≥M outcomes en window con ≥K dirty), el
adjusted level baja en el lattice, la decisión no es PROCEED, y el
actuator command (si lo hay) pertenece al safe-reason set cerrado
`S_BAUD = {attitude_hold_hold, kill_zero_throttle}`. ADR-0031.

### 3.2 ERUR — Eventual Reactivation Under Recovery (ADR-0032)

> *Cuando la evidencia se restablece, el agente debe volver a
> actuar.*

El contrato se enuncia en dos capas: un predicado de referencia
concreto (v1) y un lifting policy-paramétrico (v2).

**ERUR-v1 (predicado de referencia).** Precondición: drift ausente
bajo la regla *de referencia* count-of-K-in-W (`outcomes < M` o
`dirty_count < K`, con `M=4, K=2`) y raw belief es KNOWN.
Postcondición: adjusted level es KNOWN y la decisión es PROCEED.
v1 fija los parámetros de la precondición al calibrador
Mahalanobis de referencia; esto es lo que el verificador v0.2.3
distribuye.

**ERUR-v2 (policy-paramétrico).** Sea `policy.drift_precondition`
un método del Protocol calibration-policy que retorna, para la
historia de calibración actual, el juicio *propio* del policy
sobre si hay drift (un Boolean por ciclo). La precondición de
ERUR-v2 es: `not policy.drift_precondition(history)` y raw belief
KNOWN. ERUR-v2 es lo que el claim **policy-agnostic** de §2.3
realmente sostiene: ERUR se satisface por cualquier policy cuyo
criterio propio de drift está ausente y cuya belief es KNOWN, no
solo por calibradores que comparten los `(M,K)` de Mahalanobis. El
verificador v2 delega la precondición a cada policy bajo test; el
verificador v1 es el verificador v2 instanciado con el predicado
del policy de referencia. §8.4 evalúa ambos y la discrepancia
entre veredictos v1 y v2 sobre calibradores alternativos es la
evidencia operacional de que el lifting es significativo.

Forma con BAUD el **teorema de partición**: cada ciclo donde raw
belief es KNOWN cumple o la precondición de BAUD o la de ERUR, y
las dos nunca se solapan. El spec TLA+ promueve esto a un
**teorema probado sobre el modelo abstracto** bajo v1 (Sección 5);
el argumento de partición se eleva a v2 por construcción ya que
v2 delega estrictamente la precondición al calibration policy.

### 3.3 MD-v1 — Monotonic Degradation

> *El agente nunca debe afirmar saber más de lo que la evidencia
> respalda.*

Para todo ciclo, `adjusted ≼ raw` en el confidence lattice. El
calibrador nunca *inventa* confianza. ADR-0033.

### 3.4 RLB-v1 — Recovery Latency Bound

> *La incertidumbre del agente no puede durar indefinidamente;
> la recuperación está acotada por la estructura de la ventana
> de calibración.*

`L ≤ peak + W − 1` para sliding-window count-of-K-in-W filters. Es
la cota de latencia de recuperación (§6.3). ADR-0034.

### 3.5 FPB — False Positive Bound observer (ADR-0035, ADR-0039)

> *La desconfianza del agente debe ser medible y auditable, no
> implícita.*

Dos contratos coexisten:

**FPB-v1 (ADR-0035, observacional).** Empirical BAUD fire rate
sobre el run, expuesto como métrica estructurada. Verdict:
`fire_fraction <= max_fire_fraction` — point estimate, regression
gate para CI. No hace claim sobre sample size ni sobre la firing
probability *subyacente*.

**FPB-v2 (ADR-0039, estadístico; ships en v0.2.5).** Cota
superior unilateral de confianza sobre la firing probability
verdadera ``p`` dado el sample observado
``(cycles_fires, cycles_total)`` a un ``confidence_level``
configurable (default 0.95). Verdict:
`confidence_upper_bound <= max_fire_probability`. Samples pequeños
correctamente fallan al certificar cotas apretadas (el CI es
ancho); samples grandes se ganan el derecho a regression gates
apretados (el CI es estrecho). Dos estimadores ship behind un
enum `ConfidenceMethod` cerrado:

- ``HOEFFDING`` (default, stdlib-only): closed-form
  distribution-free
  `ub = p_hat + sqrt(ln(1/(1-level)) / (2n))`.
- ``CLOPPER_PEARSON`` (opt-in, requiere SciPy): exact one-sided
  binomial via inverse Beta. Más apretado que Hoeffding cuando
  vale la asunción iid Bernoulli.

Seis invariantes Hypothesis pineadas en
`tests/properties/test_fpb_v2_property.py`: sound bound
(`p_hat ≤ ub ≤ 1`), Hoeffding domina Clopper-Pearson, monotonía
en `p_hat`, decrecimiento en `n` a `p_hat` fijo, gap a `p_hat` <
0.05 a `n = 10 000`, y zero-sample devuelve cota vacua `1.0`.

Los dos contratos contestan preguntas distintas y ambos ship.
v1 es CI smoke (§8.2 pinea el rate empírico del reference run);
v2 es el statistical safety case que cierra el caveat de §9
sobre "no statistical bound".

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
$ pip install project-ghost==0.2.3
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
  consecutivo de la cota de latencia de recuperación vía dos fases (`ACCUMULATING`,
  `RECOVERING`). Mirror-ea el algoritmo del verificador
  `properties/rlb.py`.
- **`Fpb.tla`** modela el counter automaton de FPB-v1 en aritmética
  entera. Verifica la well-formedness estructural del counter, no
  una cota probabilística sobre el fire rate (eso sería FPB-v2).

### 5.3 Invariantes verificados

Los tres specs juntos verifican 11 invariantes en CI continuo (5 en
BaudErur, 3 en Rlb, 3 en Fpb), cubriendo BAUD/ERUR/MD/RLB/FPB con al
menos un invariante estructural cada una. Esto eleva la cobertura
mecánica de 3/5 propiedades en v0.2.1 a **5/5 en v0.2.3**.

### 5.4 Bounds y qué prueban

Para tractabilidad, cada spec corre con constantes bounded pequeñas:

| Spec | Bounds | Por qué es suficiente |
|---|---|---|
| `BaudErur.tla` | `M=2, K=1, W=3` | Casos *frontera* de la precondición exhaustos en cualquier `M > 0`; `W ≥ M` ejercita la ventana deslizante. |
| `Rlb.tla` | `W=4, MAX_DRIFT=4` | Ejercita las cuatro fases de la prueba de la cota de latencia de recuperación (acumulación, saturación, flush, recovery). |
| `Fpb.tla` | `MAX_CYCLES=8` | Ocho ciclos enumeran el counter automaton through cada alternancia fire/non-fire. |

Comportamiento a constantes de escala de producción (`M=4, K=2,
W=32`) está cubierto por los property tests. TLA+ rellena el rincón
*pequeño pero exhaustivo*. Elevar la cota de latencia de recuperación a *cualquier W finito*
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

### 6.3 La cota de latencia de recuperación

**Cota de latencia de recuperación (RLB-v1, régimen transitorio).** *Sea
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
está ingeniado para exhibir la cota de latencia de recuperación en las constantes de producción
(`N = peak = 7`, `W = 32`):

```
L_observed = 38 = 7 + 32 − 1 = peak + W − 1.
```

El test de integración
`tests/integration/test_closed_loop_smoke_with_recovery.py`
asserta que la recovery transition fires exactamente en el ciclo 39
y en ningún otro lugar antes o después. El smoke por tanto es testigo
de que la cota es *alcanzable* — es decir, está ajustada en
el régimen transitorio.

### 6.5 Scope y limitaciones

La cota de latencia de recuperación aplica al calibrador de referencia
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

> Project Ghost v0.2.3 satisface BAUD-v1 sobre el MCAP del smoke de
> referencia incluido `SHA-256:<hash>`, verificado por
> `ghost verify-properties --mcap closed_loop_smoke.mcap` desde
> `pip install project-ghost==0.2.3`, y adicionalmente satisface
> `INV_BAUD`, `INV_ERUR`, `INV_PARTITION` sobre el modelo abstracto
> `BaudErur.tla` en bounds `M=2, K=1, W=3`, y `INV_RLB` (la cota de latencia de recuperación)
> sobre `Rlb.tla` en `W=4`.

Esa es la contribución C4 en acción.

---

## 8. Evaluación

Resumen interno. Para detalles cuantitativos completos (tablas,
JSONs reproducibles) consultar la versión inglesa.

### 8.1 Tests, CI y verificación mecánica

1687 tests passing, ruff + mypy strict + deptry clean, CI matrix de
4 combinaciones (ubuntu/windows × py 3.11/3.12), 3 specs TLA+ en
CI continuo.

### 8.2 Capacidad de detección de bugs (Violation Matrix)

6 categorías de bugs, todas detectadas por el verificador no
modificado: `calibrator_no_downgrade` → BAUD-v1;
`calibrator_invents_confidence` → MD-v1; `decision_proceeds_anyway`
→ BAUD-v1; `decision_never_proceeds` → ERUR-v1;
`actuation_non_safe_reason` → BAUD-v1; `fpb_threshold_exceeded` →
FPB-v1.

### 8.3 Evaluación paramétrica de policy

9 corridas (3 policies × 3 longitudes de trace), las 5 propiedades
HOLD en todas. Verificador lineal en longitud del trace: 21 ms para
n=10, 100 ms para n=50, 406 ms para n=200.

### 8.4 Verificador policy-agnostic, precondiciones policy-paramétricas

Corriendo el smoke bajo `MahalanobisDowngradePolicy`,
`EWMADowngradePolicy`, y `PerAxisHysteresisDowngradePolicy`, el
verificador procesa los tres MCAPs sin cambios — bajo **ambas**
ERUR-v1 (predicado de referencia, §3.2) y ERUR-v2
(policy-paramétrico, §3.2):

| Policy | BAUD | ERUR-v1 | ERUR-v2 | MD | RLB | FPB |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `Mahalanobis(M=4,K=2)` referencia | OK | OK | OK | OK | OK | OK |
| `EWMA(α=0.5,min=3,thr=0.3)` | OK | **VIOL** | **OK** | OK | OK | OK |
| `PerAxisHysteresis(up=3.0)` | OK | **VIOL** | **OK** | OK | OK | OK |

**Lectura de la matriz:** ERUR-v1 está fijada al predicado de
referencia y por tanto reporta VIOL en EWMA y PerAxis — pero esa
señal es "la policy alternativa no se comporta como la
referencia", no "la policy alternativa es insegura". Esta es
precisamente la discrepancia que motivó el lifting v2 de §3.2.
**ERUR-v2 sostiene sobre las tres policies**: cada alternativa
satisface su contrato propio: cuando su criterio *propio* de
drift está ausente y la belief es KNOWN, emite PROCEED. ERUR-v2
captura así la garantía policy-agnostic que la columna
"multi-property output" de §2.3 promete.

**Estado de implementación (v0.2.4).** Ambos verificadores se
distribuyen como funciones genéricas policy-agnostic.
`verify_erur` (v1) evalúa el predicado de referencia con
parámetros `(M, K)` provistos por el caller; nada cambió en
v0.2.4 — backwards-compat absoluta. `verify_erur_v2` (nuevo en
v0.2.4, ADR-0040 aceptado) acepta un
`Mapping[policy_id, Callable[[CalibrationHistory], bool]]` y
delega la precondición al método propio `drift_precondition` de
cada policy vía el Protocol `DriftPreconditionProvider`
implementado por los tres calibradores arriba. El verificador
sigue siendo función pura sobre el MCAP. **La matriz de arriba
es generada por el verificador en cada push de CI**, no manual;
`docs/paper/scripts/compare_policies.py` la produce junto con
`docs/paper/outputs/policy_comparison.json`.

### 8.5 Escenarios shape-realistic

3 perfiles inspirados en literatura VIO/SLAM (gps_denial,
slow_biased_drift, cascading_failure). Las 5 propiedades HOLD en
los 3. Honesto: shape-realistic, no data-real; integración con
datos reales de PX4/ROSBag es roadmap futuro.

### 8.6 Comparación contra RTAMT: matriz de capacidades, no carrera

Después de intentar un benchmark head-to-head (script preservado en
[`benchmark_vs_rtamt.py`](../scripts/benchmark_vs_rtamt.py)) decidimos
**no tratarlo como comparación competitiva**: Ghost y RTAMT
codifican propiedades distintas sobre el mismo trace, así que una
diferencia de veredicto no establece un defecto en ninguno de los
dos tools. En su lugar reportamos una matriz de **capacidades**
publicadas por ambos tools sobre el mismo MCAP (RTAMT 0.3.5; Ghost
v0.2.3):

| Capacidad | Ghost v0.2.3 | RTAMT 0.3.5 |
|---|:---:|:---:|
| Lenguaje nativo | Predicado Python sobre schema MCAP | STL |
| Lee MCAP directo | Sí | No (usuario extrae signals) |
| K-en-W como single formula | Sí (intrínseco) | No (contadores auxiliares) |
| Semántica robustness | No (solo veredicto) | Sí (real-valued) |
| STL arbitrario | Fuera de scope | Sí (propósito del tool) |
| Detección de bugs sobre pipeline Ghost | Sistemático (§8.2) | Requiere re-encoding por propiedad |
| Distribución | PyPI + wheel firmado OIDC | PyPI source |

Los tools son complementarios. **RTAMT es la elección correcta
cuando el usuario quiere STL declarativo sobre signals arbitrarios
con robustness cuantitativo**. **Ghost es la elección correcta
cuando el usuario quiere un verificador CLI content-addressed
schema-aware para un supervisor específico con predicados
hand-stated**. Medición de performance reportada solo como orden de
magnitud (Ghost ~23 ms, RTAMT ~0.15 ms + ~20 ms de signal
extraction); los números miden cosas distintas.

### 8.7 El verificador sobre telemetría de vuelo real

> **El verificador se ejecutó sin modificaciones sobre telemetría
> de vuelo real.**
>
> Esta es la única frase cuya ausencia las versiones previas del
> paper tenían que disculpar. v0.2.3 nos permite escribirla.

**Lo que esta sección entrega en v0.2.3:**

- Un ULog real de PX4, obtenido de los test fixtures de PX4/pyulog
  (`test/sample_log_small.ulg`, ~921 KB, vuelo SITL de la era PX4
  v1.10, BSD-3 vía PX4). Bundle en
  [`docs/paper/data/sample.ulg`](../data/sample.ulg), SHA-256
  `68d1020f...`.
- Un orchestrator end-to-end
  ([`project_ghost.adapters.real_ulog_smoke.run_real_ulog_smoke`](../../../src/project_ghost/adapters/real_ulog_smoke.py))
  que lee el ULog vía `parse_ulog_pose_samples`, subsamplea a 10 Hz,
  drive el pipeline closed-loop **sin modificar**, materializa el
  MCAP, y corre los 5 verificadores.
- Un CLI driver en
  [`docs/paper/scripts/verify_real_ulog.py`](../scripts/verify_real_ulog.py).
- 3 integration tests en
  [`tests/adapters/test_real_ulog_smoke.py`](../../../tests/adapters/test_real_ulog_smoke.py)
  pinning end-to-end: pipeline corre, MCAP byte-determinístico,
  veredictos exactos como tabla.

**Verdict bundle sobre el ULog real PX4 incluido:**

| Campo | Valor |
|---|---|
| Pose samples extraídos | 636 |
| Cycles Ghost ejecutados | 71 |
| MCAP SHA-256 | `49fd0a48...720a4591` |
| BAUD-v1 | HOLDS |
| ERUR-v1 | HOLDS |
| MD-v1 | HOLDS |
| RLB-v1 | HOLDS |
| FPB-v1 | HOLDS (fire_fraction = 0.9437) |

**Caveat sobre el veredicto.** El orchestrator usa el estimate
EKF2 propio del ULog como belief Y como ground truth oracle vacuo,
así que el all-HOLDS es vacuo como safety claim. Un ground truth
no vacuo (mocap, RTK GPS, post-flight optimised) es ADR-0037
candidato; la cláusula "Sim, no hardware" de §9 sigue intacta para
la lectura fuerte.

**Lo que esta sección establece**, con la advertencia anterior
explícita, es el hecho estructural que las versiones previas no
podían enunciar:

> **El verificador se ejecutó sin modificaciones sobre telemetría
> de vuelo PX4 v1.10 real, en CI, con salida MCAP determinística
> reproducible desde un único comando de shell.**

Esa es la frase load-bearing de §8.7 — no la fila del veredicto.

### 8.8 Discriminación sobre telemetría de vuelo real

§8.7 establece que el verificador *se ejecuta* sobre telemetría
real. No establece, por sí solo, que el verificador *detecte* algo
sobre telemetría real — el all-HOLDS lo produciría tanto un
verificador vacío como uno correcto. Esta subsección cierra ese
hueco.

**El experimento.** Sobre el **mismo ULog real** de §8.7,
re-corremos la pipeline closed-loop dos veces más, cada una
substituyendo **un solo** componente buggy importado verbatim de la
violation matrix §8.2. El oracle de fusión, el esquema MCAP, el
verificador y el ULog input se mantienen idénticos al nominal; solo
un componente nombrado difiere por caso buggy.

**Delta de veredictos sobre el ULog real bundleado.** v0.2.4
expande el experimento de dos categorías buggy a las seis
categorías de la violation matrix (§8.2). Cada fila substituye
exactamente un componente nombrado importado verbatim de la
matrix sintética; oracle de fusión, esquema MCAP, verificador y
ULog input se mantienen idénticos entre filas:

| Run | Violador esperado | BAUD | ERUR | MD | RLB | FPB |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| nominal (policies de referencia) | — | HOLDS | HOLDS | HOLDS | HOLDS | HOLDS |
| `calibrator_no_downgrade` | BAUD-v1 | **VIOLATED** | HOLDS | HOLDS | HOLDS | HOLDS |
| `calibrator_invents_confidence` | MD-v1 | **VIOLATED** | HOLDS | **VIOLATED** | HOLDS | HOLDS |
| `decision_proceeds_anyway` | BAUD-v1 | **VIOLATED** | HOLDS | HOLDS | HOLDS | HOLDS |
| `decision_never_proceeds` | ERUR-v1 | HOLDS | **VIOLATED** | HOLDS | HOLDS | HOLDS |
| `actuation_non_safe_reason` | BAUD-v1 | **VIOLATED** | HOLDS | HOLDS | HOLDS | HOLDS |
| `fpb_threshold_exceeded` | FPB-v1 | HOLDS | HOLDS | HOLDS | HOLDS | **VIOLATED** |

**6/6 categorías flipean su propiedad esperada; 5/6 quedan
aisladas.** La única fila no aislada es
`calibrator_invents_confidence`: el calibrador con confianza
inflada viola MD-v1 *y* BAUD-v1 a la vez, porque un calibrador
que miente sobre confianza simultáneamente rompe el contrato
de downgrade Mahalanobis (la propiedad que ataca más
directamente) y el contrato de abstain-under-drift (la creencia
estacionaria sigue drift-eando, pero el calibrador ya no lo
marca). Es una co-violación real, no un artefacto del
verificador: un calibrador puede corromper comportamiento
downstream a través de varios invariantes a la vez, y el
verificador reporta ambos.

**Reproducibilidad.** End-to-end runnable desde
`pip install 'project-ghost[adapters]==0.2.4'`:

```
python docs/paper/scripts/verify_real_ulog_discriminate.py \
    --ulog docs/paper/data/sample.ulg \
    --out-dir docs/paper/outputs/real_ulog_discrim
```

Exit code 0 sii toda categoría buggy flipea su propiedad esperada.
Seis tests de integración pinean el experimento en CI
(`tests/adapters/test_real_ulog_discrimination.py`).

**Por qué esto responde al crítico residual de §8.7.** El delta de
§8.8 muestra — sobre el mismo vuelo físico — que swappear cualquiera
de seis componentes nombrados por su versión buggy de una línea
flipea la propiedad esperada del veredicto. Las detecciones
sintéticas de la violation matrix §8.2 transfieren a telemetría
real sobre este ULog para las categorías cuya precondición el
patrón de drift real ejercita.

#### 8.8.1 Generalización a un corpus de 3 ULogs

§8.8 descansa sobre *un* ULog PX4 SITL. Ese es el ataque más
común que un reviewer hace contra este tipo de resultado, y en
v0.2.4 lo cerramos directamente expandiendo el experimento a un
**corpus de tres ULogs PX4 estructuralmente distintos**
tomados del set público de fixtures de PX4 (BSD-3, license-
clean, reproducción sin mediación nuestra):

| ULog | Pose samples | Duración | FPB `fire_fraction` |
|---|---:|---:|---:|
| `sample.ulg` (anchor §8.8) | 636 | 6.5 s | 0.9437 |
| `corpus/sample_appended.ulg` (multi-segmento) | 1110 | 112.6 s | 0.9800 |
| `corpus/sample_logging_tagged.ulg` (logging-tagged) | 1268 | 10.1 s | 0.0000 |

El corpus deliberadamente cubre rango de duración 16× e incluye
un log (`sample_logging_tagged.ulg`) cuyo segmento grabado es
**mayormente estacionario** — `fire_fraction = 0.00` significa
que la creencia estacionaria nunca observa drift contra GT
grabado. No filtramos ese log: el corpus es el set público de
PX4 as-shipped, y un paper que hand-pickea logs donde toda
propiedad dispara es cherry-picked por definición.

**La matriz de detección del corpus** se regenera por CI en cada
push y se emite como
[`docs/paper/outputs/multi_ulog_discrimination/matrix.json`](../outputs/multi_ulog_discrimination/matrix.json)
(self-describing — `schema_version`, diagnósticos per-ULog,
ambas matrices). YES = el verificador flipea la propiedad
esperada en ese ULog; NO = la propiedad mantiene HOLDS entre
nominal y buggy:

| Categoría de bug | `sample.ulg` | `sample_appended.ulg` | `sample_logging_tagged.ulg` |
|---|:---:|:---:|:---:|
| `calibrator_no_downgrade` | YES | YES | **NO** |
| `calibrator_invents_confidence` | YES | YES | YES |
| `decision_proceeds_anyway` | YES | YES | **NO** |
| `decision_never_proceeds` | YES | YES | YES |
| `actuation_non_safe_reason` | YES | YES | **NO** |
| `fpb_threshold_exceeded` | YES | YES | **NO** |

**Lectura honesta: 12 de 18 celdas discriminan.** En los dos
ULogs **activos** (`fire_fraction > 0.9`), la matriz está
totalmente verde — seis de seis categorías flipean la propiedad
esperada en cada uno, con la misma fila de co-violación que §8.8.
En el ULog **estacionario** (`fire_fraction = 0.00`), cuatro de
seis categorías reportan HOLDS entre nominal y buggy.

Esto es **no-discriminación informativa**, no un fallo del
verificador. Las cuatro categorías HOLDS-everywhere
(`calibrator_no_downgrade`, `decision_proceeds_anyway`,
`actuation_non_safe_reason`, `fpb_threshold_exceeded`) comparten
una precondición: la señal de drift BAUD-v1 debe dispararse al
menos una vez. En un log donde el agente está mayormente
estacionario y la creencia estacionaria nunca diverge de GT,
esa precondición se cumple vacuamente para nominal y buggy, y
la propiedad reporta correctamente HOLDS para ambos. Las dos
restantes (`calibrator_invents_confidence`,
`decision_never_proceeds`) no requieren que la señal de drift
dispare — el calibrador infla confianza haya drift observado o
no, y la policy never-PROCEED viola el brazo "release después
de K ciclos stale" de ERUR-v1 independientemente del drift.
Estas flipean correctamente en los tres ULogs.

El verificador hace **lo que dice hacer**: flagea exactamente
los bugs del producer cuya precondición el ULog realmente
ejercita. Un resultado más pulido filtraría el corpus o
sourcearía drift desde una referencia independiente; reportamos
la matriz honesta aquí y deferimos la mitigación "fuente de GT
independiente" a ADR-0037 (que v0.2.4 cubre parcialmente con
el corpus SITL, cierre completo en v0.2.5).

**Reproducibilidad.** Ejecutar
`python docs/paper/scripts/run_multi_ulog_corpus.py` — emite
`docs/paper/outputs/multi_ulog_discrimination/matrix.json` y
sale con código no-cero si el invariante de ULogs activos
regresa. Seis tests de integración en
`tests/adapters/test_real_ulog_corpus.py` pinean la forma de la
matriz, el invariante de ULogs activos, el invariante
"auto-detect SITL GT" del ULog estacionario (§8.8.2) y el schema
del artefacto JSON.

La sustitución buggy es en la capa de policy; ningún run buggy
voló nada. Generalizar a stacks **no-PX4** (ROSBag,
ArduPilot, EuRoC) sigue siendo scope del roadmap ADR-0037.

#### 8.8.2 GT independiente cierra el gap del ULog estacionario

§8.8.1 reportó que en `sample_logging_tagged.ulg` el verificador
devolvía HOLDS para 4/6 categorías buggy — no-discriminación
informativa, porque la precondición de drift de BAUD-v1 nunca
se ejercitaba en ese ULog. Esa fila es el gap residual que §8.8.2
cierra en v0.2.5.

**Por qué §8.8.1 era vacuo en ese ULog.** La pipeline closed-loop
computaba `divergence = predict(belief) − ground_truth`, y el
stream de GT se reconstruía del *mismo* topic
`vehicle_local_position` del ULog — es decir, el propio estimado
EKF2 del agente. En un segmento estacionario el estimado EKF2
apenas se mueve (x-range reportado ≈ 2 mm) y la creencia
estacionaria apenas diverge. El verificador reportaba HOLDS
correctamente para cualquier propiedad cuya precondición
requería drift observado, pero la señal GT era
**auto-consistente con la fusión del agente por construcción** —
el experimento no podía falsificar al agente.

**Qué cambia §8.8.2.** `sample_logging_tagged.ulg` lleva
`vehicle_local_position_groundtruth` + `vehicle_attitude_groundtruth`,
emitidos directamente por el simulador SITL de PX4 e
**independientes de EKF2**. La pose GT en ese ULog tiene
x-range ≈ 33 mm — oscilación sub-cm alrededor del setpoint de
hover que EKF2 ocultaba. v0.2.5 añade
`project_ghost.adapters.px4_ulog.GroundTruthSource` y un
auto-detector que cambia un ULog de `EKF2_FALLBACK` a
`SITL_SIMULATOR` cuando los topics GT están presentes. El
adapter de pose, el verificador y el esquema MCAP están
inalterados; solo la fuente de GT flipea.

**A/B en el mismo ULog estacionario, mismos componentes buggy,
mismo verificador:**

| Métrica | `EKF2_FALLBACK` (v0.2.4) | `SITL_SIMULATOR` (v0.2.5) |
|---|---:|---:|
| FPB `fire_fraction` | 0.0000 | 0.8585 |
| Categorías que discriminan | 2 / 6 | **6 / 6** |
| `all_discriminate` | False | **True** |

Las 4 categorías que eran vacuamente HOLDS en §8.8.1
(`calibrator_no_downgrade`, `decision_proceeds_anyway`,
`actuation_non_safe_reason`, `fpb_threshold_exceeded`) flipean
correctamente bajo el GT independiente. Las dos que ya
funcionaban (`calibrator_invents_confidence`,
`decision_never_proceeds`) siguen funcionando.

**Matriz de corpus refrescada.** Con auto-detect habilitado:

| Categoría de bug | `sample.ulg` | `sample_appended.ulg` | `sample_logging_tagged.ulg` |
|---|:---:|:---:|:---:|
| `calibrator_no_downgrade` | YES | YES | YES |
| `calibrator_invents_confidence` | YES | YES | YES |
| `decision_proceeds_anyway` | YES | YES | YES |
| `decision_never_proceeds` | YES | YES | YES |
| `actuation_non_safe_reason` | YES | YES | YES |
| `fpb_threshold_exceeded` | YES | YES | YES |

**18/18 celdas discriminan** (`all_discriminate=True`). 15/18
están aisladas; las 3 no aisladas son todas
`calibrator_invents_confidence`, la misma fila co-violación
BAUD-v1 ∧ MD-v1 documentada en §8.8. Dos de los tres ULogs
siguen con `EKF2_FALLBACK` (`sample.ulg`, `sample_appended.ulg`
sin topics SITL GT); la matriz está verde en esos ULogs porque
sus vuelos *no* son estacionarios (`fire_fraction` ≈ 0.94 /
0.98), así que la precondición dispara incluso bajo GT
circular.

**Trazabilidad.** El artefacto `matrix.json` lleva un campo
per-ULog `groundtruth_source` (`"sitl_simulator"` o
`"ekf2_fallback"`); el `RealULogSmokeSummary` lo lleva en cada
verdict bundle. Un reviewer puede `grep`-ear el JSON para
verificar qué celdas usaron GT independiente y cuáles cayeron
en el fallback EKF2. Tratar una fila `ekf2_fallback` como
"verificada" es la única forma de malinterpretar §8.8.2; el
campo explícito hace ese malentendido imposible de hacer
silenciosamente.

**Qué no cierra §8.8.2 todavía.** Dos limitaciones honestas:

- `sample.ulg` y `sample_appended.ulg` no llevan topics SITL GT.
  Sus columnas totalmente verdes dependen del vuelo mismo
  ejercitando la precondición bajo fallback EKF2; si un futuro
  mantenedor re-corre §8.8.2 sobre una variante estacionaria de
  `sample.ulg`, esas columnas volverían a HOLDS vacuos.
- SITL GT es independiente de EKF2 pero no de la física del
  simulador. Un futuro contribuidor de ADR-0037 cerrando vuelos
  de hardware real sourceará GT desde motion capture o RTK GPS;
  el enum ya enumera esos slots aunque solo `SITL_SIMULATOR`
  está implementado.

**Reproducibilidad.** Re-correr
`python docs/paper/scripts/run_multi_ulog_corpus.py` — auto-
detect es el default. Seis tests smoke-A/B en
`tests/adapters/test_real_ulog_smoke_gt_source.py` pinean el
lift cuantitativo de `fire_fraction`, los resultados del
auto-detect y el caso de error SITL-sobre-real-only-log. Seis
tests de adapter en `tests/adapters/test_px4_ulog_groundtruth.py`
pinean `detect_groundtruth_source`, el invariante orden-
cronológico de las muestras GT parseadas, el invariante de
norma-unidad de quaterniones y la fixture de disponibilidad GT
en el corpus bundleado.

### 8.9 Determinismo cross-replicates y cross-machine

Enforced por CI con matrix ubuntu+windows que diff-ea SHA-256 del
MCAP y del JSON canonicalizado.

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
- **TLC bounded, cobertura unbounded parcial.** TLC es exhaustiva
  sobre el espacio de estados finito en cada `W` configurada.
  v0.2.5 entrega un sweep paramétrico sobre `W ∈ {4, 8, 16}` (§6.3,
  ADR-0038) y una prueba manual rigurosa del teorema unbounded;
  la prueba TLAPS-mecánica completa de la afirmación unbounded
  queda abierta. El outline TLAPS en `Rlb_unbounded.tla` contiene
  la estructura de lemmas + discharge guidance por step para un
  futuro contributor con TLAPS instalado (Linux/macOS; Windows
  nativo no soportado).
- **Bridge Python↔TLA+ por inspección.** Una divergencia futura
  entre el código Python y la definición TLA+ podría silenciosamente
  debilitar el claim. Mitigación: revisar y re-correr TLC en cada
  cambio al calibrador de referencia o policy de decisión.
- **FPB estadístico ya entregado, scope acotado.** FPB-v2
  (ADR-0039, v0.2.5) cierra la cota estadística previamente
  diferida con estimadores closed-form Hoeffding y Clopper-
  Pearson (§3.5). Lo que queda abierto: FPB-v2 no valida la
  asunción iid Bernoulli que Clopper-Pearson invoca (el verifier
  confía en la elección de modelo del caller), no ajusta por
  multiple-testing sobre sweeps de parámetros, y solo reporta
  cota unilateral superior. Variantes Wilson-score y
  bidireccionales quedan diferidas.
- **HOLDS vacuos en ULogs estacionarios (cerrado en v0.2.5 para
  SITL, abierto para hardware).** §8.8.1 reportaba que en el
  ULog estacionario del corpus el GT-circular EKF2 producía
  HOLDS vacuos para 4/6 categorías. §8.8.2 cierra ese gap para
  cualquier ULog que lleve topics `vehicle_*_groundtruth`
  auto-detectando el track SITL GT independiente — la matriz
  refrescada del corpus es 18/18 verde. El gap honesto que
  queda: para ULogs de hardware real sin topics SITL GT (sin
  `_groundtruth` ni referencia externa), la pipeline sigue
  cayendo en fallback EKF2 con el mismo riesgo de HOLDS vacuos.
  El campo `groundtruth_source` de `RealULogSmokeSummary`
  expone el fallback para que un reviewer no lo confunda con
  verificación; las fuentes GT motion-capture / RTK GPS quedan
  enumeradas en el enum pero sin implementar.

---

## 10. Future work

- **ADR-0037 (más abordado, v0.2.5)**: integración con datos de
  flight reales. v0.2.4 entregó el adapter PX4 ULog y el corpus
  SITL de 3 ULogs (§8.8.1). v0.2.5 (§8.8.2) entrega el enum
  `GroundTruthSource` + auto-detector, cerrando el gap de HOLDS
  vacuos del ULog estacionario para cualquier ULog que lleve
  topics SITL GT — la matriz del corpus es ahora 18/18 verde.
  Abierto: motion-capture y RTK-GPS están enumerados pero sin
  implementar; adapters ROSBag / EuRoC MAV y un stack no-PX4
  siguen abiertos.
- **ADR-0038 (aceptado con discharge parcial, v0.2.5)**: evidencia
  unbounded para RLB-v1. Entrega tres artefactos: (1) sweep
  paramétrico TLC en `W ∈ {4, 8, 16}` (mecánico, enumeración
  completa de estados por escala), (2) prueba manual rigurosa del
  teorema unbounded sin dependencia de `W` en los argumentos
  (auditable, no SMT-checked), y (3) outline TLAPS refinado con
  discharge guidance per lemma. Una prueba TLAPS-mecánica completa
  queda abierta como follow-up ADR-0042 candidate. La prueba TLAPS
  unbounded del partition theorem es independiente y queda como
  future work.
- **ADR-0039 (accepted, v0.2.5)**: FPB-v2 estadístico. Ships
  Hoeffding closed-form (default, stdlib-only) y Clopper-Pearson
  exact (opt-in, SciPy) cotas superiores unilaterales sobre la
  firing probability verdadera. Cierra el gap "statistical bound"
  previamente diferido (§3.5, §9). Seis tests Hypothesis pinean
  la shape cualitativa que cualquier futuro estimador (e.g.
  Wilson) debe satisfacer. Surface:
  `project_ghost.properties.verify_fpb_v2`.
- **ADR-0040 (aceptado, v0.2.4)**: ERUR-v2 enunciado
  abstractamente sobre `policy.drift_precondition(history)`,
  generalizando la parametrización. Distribuido en v0.2.4 como
  `project_ghost.properties.erur_v2.verify_erur_v2` junto con el
  Protocol `DriftPreconditionProvider`; las tres policies
  (Mahalanobis, EWMA, PerAxisHysteresis) lo implementan.
  Testeado por `tests/properties/test_erur_v2_property.py`.
- **HAL backend campaign**: backend hardware (Pixhawk + companion).
- **Conformance suite** poblando el marker `conformance` de pytest
  con el contrato HAL.

---

## 11. Conclusión

**Los agentes autónomos deberían tener contratos verificables
sobre su propia postura epistémica, y esos contratos deberían
distribuirse como citas ejecutables que un tercero pueda
falsar.** Esa es la proposición load-bearing que este paper
existe para defender.

Los contratos epistémicos de seguridad son una clase de propiedad
adyacente pero distinta a los predicados STL sobre señales y al
belief monitoring estilo POMDP (§1.2): verifican obligaciones que
el agente debe satisfacer sobre cómo se relaciona con su propia
incertidumbre — degradar, recuperar, acotar, y actuar. Project
Ghost distribuye cinco de estos contratos para un supervisor de
autonomía de referencia (BAUD, ERUR, MD, RLB, FPB), empaqueta
cada uno junto con un run content-addressed y un verificador
función-pura como cita de seguridad ejecutable, y demuestra que
el verificador discrimina telemetría real PX4 contra regresiones
nombradas (§8.8).

Lo que *no* afirmamos: que los contratos epistémicos subsumen STL
o shielding (responden una pregunta distinta); que este es el
conjunto maximal de contratos (FPB-v1 puede ajustarse, faltan
contratos sobre procedencia de sensor-fusion o presupuestos de
actuación); que tenemos un claim de licencia exclusivo sobre el
término (se solapa con cómo las comunidades de epistemic logic,
doxastic logic y self-assessment han usado vocabulario
adyacente).

Lo que *sí* afirmamos: que el framing es operacionalmente
defendible — el artefacto es re-ejecutable desde
`pip install project-ghost==0.2.3`; el veredicto sobre telemetría
real de vuelo PX4 es reproducible desde un único comando de
shell; el artefacto citado *es* el mecanismo de falsación.

---

## Referencias

Mismo conjunto de 18 referencias que la versión inglesa. Para evitar
duplicación y deriva, consultar
[`docs/paper/project_ghost_v0_2.md` § References](../project_ghost_v0_2.md#references).

## Índice de artefactos

Mismo conjunto de artefactos (ADRs, specs TLA+, verificadores,
scripts de reproducibilidad, tests, CI workflows, citation file)
que la versión inglesa. Ver
[`docs/paper/project_ghost_v0_2.md` § Artifact index](../project_ghost_v0_2.md#artifact-index)
para la lista canónica.
