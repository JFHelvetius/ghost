# ADR-0021 — Belief-to-Action Contract Layer v1

## Status
Accepted (2026-06-07).

## Context

Hasta ADR-0020 todo el sistema vive a un lado de la creencia. El agente
**produce** belief, lo **introspecta** y el operador lo **analiza** offline.
Nada cierra el ciclo: la creencia no se consume para producir
**consecuencias**.

La pregunta central de misión —*"¿qué consecuencias tiene la diferencia
entre lo que el agente cree saber y lo que sabe?"*— **es indemostrable**
porque el agente carece de un contrato runtime que conecte creencia +
introspección con acción.

Cinco gaps estructurales están bloqueados por la misma falta de
contrato:

1. **ADR-0009 (Autonomy Under Uncertainty)** define tiers T0/T1/T2/T3
   con autoridad sobre actuadores; ninguno es instanciable sin un tipo
   `Decision`. Cada futura implementación inventaría el suyo.
2. **ADR-0011 (T0 Safety Vetoes)** define vetos sobre comandos; no
   existe el "comando-de-intención" que vetar. Los `ActuatorCommand`
   son un nivel demasiado bajo.
3. **ADR-0020 (BeliefSelfAssessment)** publica una afirmación
   estructurada sobre lo que el agente cree saber. **Nadie la consume**.
   Sin un `Policy` que la lea, el canal `/self_assessment` es señal
   observacional sin efecto.
4. Cualquier estimador real futuro (Kalman, factor graph) duplicaría
   wiring belief → acción si el contrato no existe primero.
5. Cualquier backend de simulación concreto (PyBullet, Gazebo)
   acabaría wireando belief → policy → actuator ad-hoc.

ADR-0021 cierra este gap con **contratos**, no implementaciones. Define
los shapes mínimos auditables para que toda futura ADR de control /
safety / pilot override / mission planning / hardware migration se
componga sobre la misma capa, sin re-invención y sin acoplamiento
prematuro a una política específica.

Esta es la primera ADR que define el lado **decide / act** de la misión.

## Decision

Añadir el paquete `project_ghost.core.decisions` con cinco contratos
puros y un wiring mínimo de telemetría. No incluye controladores,
planners, vetos concretos ni translation a `ActuatorCommand`. Solo
shapes.

### 1. `DecisionKind` (StrEnum cerrada)

Catálogo de decisiones legales del agente. Modificar requiere ADR
explícito (misma disciplina que `PerceptionMode`, `Validity`,
`SelfAssessmentLevel`).

- `proceed` — "Continúo la misión con la creencia actual."
- `hold` — "Mantengo posición; mi creencia no es suficiente para
  navegar pero sí para sostenerme."
- `yield_to_pilot` — "Cedo autoridad al piloto humano."
- `engage_rtl` — "Inicio Return-To-Launch por degradación de creencia."
- `engage_land` — "Inicio aterrizaje controlado."
- `engage_kill` — "Corto thrust por imposibilidad de operar de forma
  segura."
- `abstain_uncertain` — "Me abstengo de tomar una decisión; mi creencia
  no soporta ninguna afirmación."

### 2. `DecisionContext` (frozen dataclass)

Lo que el `Policy` ve. Auto-contenido para que `decide` sea pure
function.

- `belief_stamp_sim_ns: int`
- `self_assessment: BeliefSelfAssessment | None` (None cuando no hay
  introspección disponible)
- `flight_status: FlightStatus`
- `mission_status: MissionStatus`
- `perception_mode: PerceptionMode | None` (opcional; presente cuando
  un `PerceptionModeDetector` esté wireado)

### 3. `Decision` (frozen dataclass)

La afirmación clasificatoria del agente sobre qué decide hacer.

- `kind: DecisionKind`
- `decision_stamp_sim_ns: int` (igual a `context.belief_stamp_sim_ns`
  típicamente; reactivo síncrono)
- `reason: str` — taxonomizado por formato (`^[a-z][a-z0-9_]*$`,
  longitud 1-64). No es free text; es un identificador estable que el
  caller usa consistentemente.

### 4. `DecisionRationale` (frozen dataclass)

Artefacto auditable que une la decisión con sus inputs. Content-addressed
vía SHA-256 del `BeliefSelfAssessment` input.

- `decision: Decision`
- `belief_stamp_sim_ns: int` (debe matchear `decision.decision_stamp_sim_ns`)
- `self_assessment_sha256: str | None` (64-char lowercase hex; None
  cuando no hubo self-assessment en el context)
- `policy_id: str` (identificador estable del policy productor)

Invariante: dado un `BeliefSelfAssessment` `S`, el `DecisionRationale`
que lo cite con `self_assessment_sha256 = sha256(canonical(S))` deja
trazable bit-a-bit qué assessment justificó la decisión.

### 5. Protocols

```python
@runtime_checkable
class Policy(Protocol):
    @property
    def policy_id(self) -> str: ...
    def decide(self, context: DecisionContext) -> Decision: ...

@runtime_checkable
class DecisionSink(Protocol):
    def publish(
        self,
        decision: Decision,
        rationale: DecisionRationale,
    ) -> None: ...
```

`DecisionSink.publish` toma **siempre los dos** — Decision Y Rationale.
Esta es la enforcement contractual de "ninguna decisión sin
justificación". No se puede publicar una decisión sola.

### 6. Implementaciones de referencia

- `NullDecisionSink` — descarta. Para tests y para usar
  `decide_and_publish` cuando no se quiere persistir.
- `RecordingDecisionSink` — guarda en memoria. Para tests y verificación.
- `UncertaintyAwareReferencePolicy` — policy mínima documentada que
  mapea `SelfAssessmentLevel.{KNOWN, UNCERTAIN, UNKNOWN}` →
  `DecisionKind.{proceed, hold, abstain_uncertain}`. No usa
  `yield_to_pilot`, `engage_rtl`, `engage_land`, `engage_kill` — esos
  del catálogo quedan disponibles para policies futuras (tier 0/1
  safety, pilot override). Es **observacional**: PROCEED dice
  "afirmo poder navegar", HOLD dice "afirmo que debo esperar",
  ABSTAIN dice "afirmo no poder decidir".

### 7. Orquestación

```python
def decide_with_rationale(
    policy: Policy, context: DecisionContext,
) -> tuple[Decision, DecisionRationale]: ...

def decide_and_publish(
    policy: Policy, context: DecisionContext, sink: DecisionSink,
) -> Decision: ...
```

`decide_with_rationale` ejecuta el policy y construye el `DecisionRationale`
calculando el SHA-256 canónico del self-assessment del context (stdlib
puro; sin dep de telemetry).

`decide_and_publish` es el one-shot canónico para la mayoría de
callers.

### 8. Telemetría

- `CHANNEL_DECISIONS = "/decisions"` en `telemetry.channels`.
- `DecisionToTelemetryAdapter` (mismo patrón que
  `SelfAssessmentToTelemetryAdapter`). Acepta `(decision, rationale)`,
  valida que `rationale.decision == decision`, publica el `rationale`
  como record (contiene el decision dentro) usando
  `decision.decision_stamp_sim_ns` como `log_time` (ADR-0002).
- Decoder registrado en `telemetry.replay._build_decoder_table()` para
  el qualified name de `DecisionRationale`.

## Inputs

- En runtime: un `Policy`, un `DecisionContext`, opcionalmente un
  `DecisionSink`.
- Para replay: un `.mcap` con records en `/decisions`.

## Outputs

- `Decision` + `DecisionRationale` por cada invocación de policy.
- Records `DecisionRationale` publicados en `/decisions` (cuando un
  sink esté wireado).

## Limits

- **No traduce `Decision` a `ActuatorCommand`.** Esa translation layer
  es una ADR distinta. Decision es la intención; ActuatorCommand es la
  ejecución; el mapeo entre ambas tiene grados de libertad (qué
  ActuatorLevel, qué trayectoria) que merecen su propio diseño.
- **No define cómo se construye un `DecisionContext`** desde el runtime.
  Caller responsibility. El context es input, no output, de esta capa.
- **No define cómo se compone una policy con otra.** La envoltura
  estilo `SafetyVetoPolicy(inner_policy)` es construcción del caller;
  el contrato `Policy` lo permite trivialmente porque es un Protocol.
- **No persiste el `BeliefSelfAssessment` referenciado por el rationale.**
  El operador debe garantizar que el assessment está accesible (típicamente
  en `/self_assessment` del mismo MCAP); el rationale sólo carga su
  hash.
- **El catálogo `DecisionKind` es cerrado para v1.** Añadir un kind
  requiere ADR amendment (mismo posture que `PerceptionMode`).
- **`reason` es taxonómico por formato, no por catálogo cerrado.**
  Cualquier policy puede usar nuevos reasons; el contrato sólo asegura
  formato estable. Permite extensibilidad sin re-versionar el ADR.
- **No reacciona a perception mode automáticamente.** El reference
  policy ignora `context.perception_mode`. Una future policy puede
  consumirlo; el contrato lo expone.
- **`decision_stamp_sim_ns == belief_stamp_sim_ns` enforced.** Decisión
  diferida (decisión que reaccione a un belief de hace N ns) queda
  fuera de scope; una ADR futura la habilitaría con un campo separado.

## Determinism

- Mismo `(policy, context)` → mismo `Decision` y mismo
  `DecisionRationale` byte-a-byte tras serialización canónica.
- `decide_with_rationale` es pure function (siempre que la policy lo
  sea).
- `UncertaintyAwareReferencePolicy.decide` es pure function.
- SHA-256 del self-assessment es estable cross-CPython porque se
  computa con `hashlib.sha256` + `json.dumps(sort_keys=True,
  ensure_ascii=False, separators=(",", ":"))` sobre `dataclasses.asdict`
  del assessment — mismo posture que `thresholds_sha256` (ADR-0020).
- Round-trip MCAP: `DecisionRationale` capturado → leído → decoded →
  igual al original.
- `DecisionToTelemetryAdapter` usa `decision.decision_stamp_sim_ns` como
  `log_time`. Sin reloj de pared (ADR-0002).

## Exclusiones explícitas

NO implementadas y NO extension points sancionados por esta ADR:

- **No controlador concreto.** Ningún PID, MPC, LQR.
- **No safety supervisor concreto.** ADR-0011 define qué debe hacer un
  T0; esta ADR provee `Policy`/`Decision` para que un T0 futuro se
  modele sin reinventar el tipo.
- **No mission planner concreto.** ADR-0009 §3 lo describe; esta ADR
  no lo implementa.
- **No pilot override concreto.** ADR-0011 §5; futuro ADR lo modela
  como un `Policy`.
- **No translation Decision → ActuatorCommand.** Capa distinta.
- **No backend de simulación.** PyBullet/Gazebo siguen fuera.
- **No real estimator.** Sigue toy (ADR-0015).
- **No "decision score" / "decision confidence".** Las decisiones son
  categóricas; no se le pone score a una decisión sin pasar por
  inferencia probabilística (rechazado de raíz).
- **No detección de "decisiones malas" post-hoc.** Cualquier análisis
  comparativo de decisiones es ADR distinta.
- **No corrección automática de decisiones.** Las decisiones son
  publicadas; consumidores aguas abajo deciden cómo reaccionar.

**Cláusula reforzada:**

> *Decidir es declarar. No es inferir, no es calcular, no es scoring.
> El sistema expone el shape del declaramiento; el operador escoge la
> policy.*

## Cadena de provenance completa

Tras este ADR, la cadena auditable de runtime es:

```
VehicleState (belief)
  → assess_belief()
  → BeliefSelfAssessment (sha = S)
  → DecisionContext (incluye assessment)
  → Policy.decide(context)
  → Decision
  → DecisionRationale (carga self_assessment_sha256 = S)
  → DecisionSink.publish(decision, rationale)
  → MCAP /decisions
```

Un auditor con el MCAP puede:

1. Leer `/decisions` → obtener `(decision, rationale)`.
2. Leer `rationale.self_assessment_sha256` y `rationale.policy_id`.
3. Leer `/self_assessment` y verificar que existe un assessment con el
   mismo SHA y `belief_stamp_sim_ns`.
4. Confirmar que el `decision_stamp_sim_ns` matchea.
5. Re-aplicar el policy (si es público) y verificar bit-a-bit que
   produce el mismo `Decision`.

Trazabilidad bit-a-bit del belief al acto.

## Consequences

**Positivo.**

- Cierre del ciclo creencia → introspección → **acción**. Por primera
  vez el agente puede *afirmar qué decide hacer*, no sólo qué cree.
- Cinco ADRs futuras (todos los tiers de ADR-0009, el safety de
  ADR-0011, futuro pilot override, futura mission planner) **se
  modelan trivialmente como `Policy` distintas** sobre el mismo
  contract.
- El self-assessment de ADR-0020 gana **un consumer natural**: deja de
  ser señal observacional sin efecto.
- El channel `/decisions` se suma a los canales auditables estándar.
- La cadena de provenance content-addressed vía SHA-256 cierra
  end-to-end: belief → assessment → rationale → decision.

**Negativo.**

- El operador ahora debe declarar una `Policy`. Es responsabilidad
  consciente; las consecuencias son trazables.
- El catálogo cerrado `DecisionKind` limita la expresividad — sólo
  siete kinds. Si la investigación requiere finer-grained, ADR
  amendment necesaria. Trade-off intencional: auditabilidad sobre
  flexibilidad.

## Alternativas consideradas

1. **Hacer `Decision` un `ActuatorCommand` directo.** Rechazado:
   acopla intención con ejecución. Imposibilita la composición de
   policies sobre la misma intención.
2. **No incluir `DecisionRationale`; sólo `Decision`.** Rechazado:
   perdería content-address al assessment. La cadena de provenance se
   rompería.
3. **`reason` como StrEnum cerrada.** Rechazado: cada policy nueva
   requeriría amendment. Trade-off: extensibilidad sin re-versionar.
4. **Incluir `PerceptionMode` como required, no optional.** Rechazado:
   forzaría el wiring del `PerceptionModeDetector` antes de que sea
   necesario. Optional permite construir DecisionContext sin él.
5. **Permitir `decision_stamp_sim_ns != belief_stamp_sim_ns`.** Rechazado
   en v1: introduciría ambigüedad sobre qué creencia justifica la
   decisión. Una future ADR puede liberar este enforcement.

## Backward compatibility

- ADR-0001..0020 sin tocar.
- Nuevo paquete `core.decisions`.
- Nuevo canal `/decisions` (canales previos intactos).
- Nuevo adapter (adapters previos intactos).
- Decoder añadido al catálogo cerrado (entradas previas intactas).
- Cero rotura.

## Mission posture

Es el primer ADR que da al agente el shape para **actuar**. Hasta hoy
el agente sólo afirmaba creer. Desde hoy puede afirmar **qué hacer**.

La misión del proyecto sigue siendo construir agentes que sepan cuándo
no saben y **actúen en consecuencia**. ADR-0020 implementó la primera
parte. ADR-0021 da el shape para la segunda, sin asumir ninguna
política específica de actuación.

Las consecuencias de creer mal — la tercera cláusula de la pregunta de
misión — son ahora **representables** y **auditables**. Una future ADR
les pondrá implementación; ésta les pone contrato.
