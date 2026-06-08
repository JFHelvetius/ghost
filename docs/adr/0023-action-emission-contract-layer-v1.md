# ADR-0023 — Action Emission Contract Layer v1

## Status
Accepted (2026-06-07).

## Context

ADR-0021 introdujo el contrato `belief → decision` y dejó
explícitamente fuera del scope la traducción `Decision →
ActuatorCommand`. Esa capa nunca llegó, y mientras no llegue:

- El catálogo `DecisionKind` (PROCEED, HOLD, ENGAGE_KILL, …) es
  semántica sin efecto. Un agente que decide `PROCEED` y un agente
  que decide `ENGAGE_KILL` emiten **exactamente el mismo conjunto
  vacío de comandos** al actuador: ninguno.
- La cláusula 3 de la misión ("consecuencias de la diferencia entre
  creer y saber") sigue siendo indemostrable. La introspección del
  agente — ADR-0020 — y la decisión que de ella se deriva — ADR-0021
  — tienen **cero consecuencia mecánica**.
- Cinco ADRs encadenados están bloqueados: tier T0 safety (ADR-0011),
  tiers T1/T2/T3 (ADR-0009 §1), pilot override (ADR-0011 §5),
  futuros controladores, futuros backends de simulación. Todas
  esperan el shape `Decision → ActuatorCommand`.
- Cuando llegue el sim backend, no tiene actuator stream que
  consumir; cuando llegue un controlador, no tiene shape al que
  conformarse.

ADR-0023 cierra este gap con **el contrato** — no con un controlador,
no con un mission planner, no con un translator inteligente. Sólo
shapes verificables: un envelope que ata cada `Decision` a un
`ActuatorCommand` opcional, los Protocols correspondientes, una
política de referencia mínima que demuestra que el contrato es sound,
y el wiring de telemetría para que cada directive sea capturable y
auditable.

## Decision

Añadir el paquete `project_ghost.core.actuation` con cinco contratos
puros + un wiring mínimo de telemetría. Patrón idéntico al de
ADR-0021. Stdlib only; cero nuevas dependencias.

### 1. `ActuationDirective` (frozen dataclass)

Envelope que ata la decisión al comando opcional:

```python
decision: Decision
actuator_command: AttitudeCommand | DirectMotorCommand | None
directive_stamp_sim_ns: int   # = decision.decision_stamp_sim_ns
policy_id: str                # snake_case identifier estable
reason: str                   # snake_case taxonomy
schema_version: int = 1
```

Invariantes (enforced por `__post_init__`):

- `directive_stamp_sim_ns == decision.decision_stamp_sim_ns`
  (síncrono v1; mismo posture que ADR-0021 con
  `belief_stamp == decision_stamp`).
- `policy_id` y `reason` matchan `^[a-z][a-z0-9_]*$`, longitud 1-64.
- `actuator_command` es uno de los tipos del catálogo `hal.messages.actuators`
  o `None`. `None` es **caso legítimo y explícito** — la policy
  declara que para esta decisión no procede emitir ningún comando.

### 2. `ActuationPolicy` (Protocol, runtime_checkable)

```python
@property
def policy_id(self) -> str: ...

def actuate(self, decision: Decision) -> ActuationDirective: ...
```

Pure function shape: mismo `decision` → mismo `directive`. Sin
reloj, sin random, sin estado mutable visible.

### 3. `ActuationSink` (Protocol, runtime_checkable)

```python
def publish(self, directive: ActuationDirective) -> None: ...
```

`NullActuationSink` (descarta) y `RecordingActuationSink` (guarda
in-memory para tests) como implementaciones de referencia.

### 4. `KillOnlyActuationPolicy` (reference)

La policy más simple que demuestra el contrato. Mapping frozen:

| `decision.kind` | `actuator_command`              | `reason`                           |
|---|---|---|
| `ENGAGE_KILL`   | `DirectMotorCommand([0,0,0,0])` | `kill_zero_throttle`               |
| cualquier otro  | `None`                          | `no_command_for_<kind>`            |

**Por qué tan mínima.** Hasta que exista un controlador, sólo
`ENGAGE_KILL` es traducible sin ambiguedad: zero throttle es
universalmente "stop". Cualquier otro kind requiere trayectorias,
attitude targets, etc., que son ya un controlador. La policy de
referencia demuestra que el contrato es sound; controladores reales
se añadirán como `ActuationPolicy` distintos en ADRs futuras.

### 5. Orquestación

```python
def actuate_and_publish(
    policy: ActuationPolicy,
    decision: Decision,
    sink: ActuationSink,
) -> ActuationDirective: ...
```

One-shot canónico: ejecuta la policy, publica el directive, devuelve
el directive (por si el caller lo necesita aguas abajo).

### 6. Telemetría

- `CHANNEL_ACTUATIONS = "/actuations"` en `telemetry.channels`.
- `ActuationToTelemetryAdapter` (mismo patrón que
  `DecisionToTelemetryAdapter` de ADR-0021).
  - Acepta `directive`, valida `isinstance(directive, ActuationDirective)`,
    publica al sink usando `directive_stamp_sim_ns` como `log_time`
    de MCAP (ADR-0002, sin reloj de pared).
  - Satisface estructuralmente `ActuationSink`.
- Decoder `_decode_actuation_directive` registrado en
  `telemetry.replay._build_decoder_table()` para el qualified name de
  `ActuationDirective`.

### Cadena de provenance extendida

Tras este ADR, la cadena auditable de runtime es:

```
VehicleState (belief)
  → assess_belief
  → BeliefSelfAssessment            [/self_assessment]
  → DecisionContext
  → Policy.decide
  → Decision
  → DecisionRationale               [/decisions]
  → ActuationPolicy.actuate
  → ActuationDirective              [/actuations]
```

Cinco canales auditables, todos byte-deterministas. La cadena belief
→ acción queda íntegra de extremo a extremo al nivel contractual.

## Inputs

- Un `Decision` (ADR-0021).
- Un `ActuationPolicy` (caller declara qué política usar).
- Opcionalmente un `ActuationSink` (para persistencia / replay).

## Outputs

- `ActuationDirective` (in-memory).
- Records `/actuations` (cuando un `ActuationToTelemetryAdapter` esté
  wireado a un MCAP sink).

## Limits

- **Una decisión por directive, síncrono.**
  `directive_stamp_sim_ns == decision.decision_stamp_sim_ns` enforced.
  Decisiones diferidas (decisión que cuaje en un comando emitido N ns
  después) están fuera de scope v1.
- **No controlador, no trayectoria, no attitude target.** La policy
  de referencia sólo mapea `KILL → zero throttle`. Cualquier otra
  política operativa (hover controller, RTL, land) es ADR distinta
  componiéndose sobre este contrato.
- **No translation contextual.** La policy recibe sólo `Decision`,
  no el `DecisionContext`. Futuras policies que necesiten state pueden
  ser construidas con referencias internas a un state provider, o un
  futuro ADR puede extender la firma. v1 mantiene mínima.
- **No vetos automáticos.** ADR-0011 define que un safety supervisor
  veta comandos; aquí no hay veto. Un futuro `VetoActuationPolicy`
  envoltorio se compondrá sobre este contrato.
- **No fan-out a múltiples sinks.** Un `actuate_and_publish` apunta a
  un sink. El caller puede componer múltiples sinks con un sink
  compuesto, pero esa composición no es parte de este ADR.
- **Solo dos tipos de `ActuatorCommand`**: `AttitudeCommand` y
  `DirectMotorCommand` (los actualmente definidos en
  `hal.messages.actuators`). Si HAL añade más tipos, este ADR los
  acomoda automáticamente (`Union[..., None]` se extiende).
- **No mission planning.** Un `PROCEED` no se traduce porque no hay
  goal. Cuando llegue mission planner, será una policy distinta.

## Determinism

- `KillOnlyActuationPolicy.actuate` es pure function: mismo
  `Decision` → mismo `ActuationDirective` byte-a-byte tras
  serialización.
- `ActuationToTelemetryAdapter.publish` no lee reloj de pared (usa
  `directive_stamp_sim_ns`).
- MCAP round-trip: write N directives → read → decoded == originals.
- SHA-256 del MCAP estable cross-process con mismos inputs.

El módulo:

- No lee reloj, no usa random.
- Stdlib only (`dataclasses`, `numpy` ya presente en HAL).
- No introduce dependencias nuevas.

## Exclusiones explícitas

- **No controlador.** PID, MPC, LQR, control adaptativo, todo fuera.
- **No mission planner.** Goals/waypoints fuera.
- **No safety supervisor concreto.** El veto operativo es ADR
  distinta.
- **No pilot override concreto.** El pass-through pilot es ADR
  distinta.
- **No analytical layer para `/actuations`.** ADR-0022 trazó decisions;
  el análogo para actuations vendría en una ADR futura (probablemente
  ADR-0024 con trace + verify chain decision→actuation).
- **No retro-feedback.** Las consecuencias de la actuación no
  modifican la creencia automáticamente. Eso requiere sim backend
  + sensor producers, ambos fuera.
- **No CLI subcommand en este ADR.** La capa analítica de
  `/actuations` (cuando llegue) traerá su CLI.
- **No re-clasificación de `DecisionKind`.** El catálogo cerrado se
  respeta tal cual; no se añade ni se quita un kind.

**Cláusula reforzada:**

> *Emitir es declarar. Un directive con `actuator_command=None` es la
> policy declarando "para esta decisión, no procede emitir ningún
> comando". Es estado legítimo, no error. El veto operativo, la
> trayectoria, la attitude target, todo eso es responsabilidad de
> policies aguas arriba que se compongan sobre este contrato.*

## Consequences

**Positivo.**

- Por primera vez **el agente puede producir un efecto observable
  distinguible al nivel de actuador**: `ENGAGE_KILL` emite zero
  throttle; cualquier otra decisión emite nada. La diferencia es
  real, capturable, auditable.
- Cinco ADRs encadenadas (T0 safety, T1 reflex, T2 reactive, T3
  deliberative, pilot override) **dejan de estar bloqueadas**. Cada
  una se modela como un `ActuationPolicy` independiente.
- Sim backend, cuando llegue, tiene un stream concreto
  (`/actuations`) decodificable a `ActuatorCommand` que consumir.
- La cadena `belief → action` queda íntegra de extremo a extremo
  al nivel contractual.
- Cero nuevas dependencias. Cero modificación de artefactos previos.

**Negativo.**

- La policy de referencia es **deliberadamente mínima** (sólo
  `KILL`). Operadores pueden esperar más; el ADR debe explicar
  consistentemente que cualquier mapeo más rico requiere un
  controlador, y construir un controlador no es scope de este ADR.
- Cinco de siete `DecisionKind` mapean siempre a `actuator_command=None`
  en v1. Los `/actuations` capturados en runs reales serán mayormente
  no-emisión hasta que policies operativas existan. Documentado.
- Coupling fijo a `AttitudeCommand` / `DirectMotorCommand`: si HAL
  añade un tercer tipo (e.g. `TrajectoryCommand`), la annotation se
  extiende y los tests se actualizan. Aceptable.

## Alternativas consideradas

1. **`ActuationPolicy.actuate(decision_context)`** (recibir context
   completo). Rechazado v1: el reference policy no lo necesita,
   y `Decision` ya contiene el stamp y kind, que es todo lo que
   requiere KILL. Una future ADR puede extender la firma si un
   controlador real lo necesita.
2. **Bundlar `Decision + Rationale` en el directive.** Rechazado:
   `DecisionRationale` ya viaja en `/decisions`. El directive sólo
   necesita la decision para que la cadena sea auditable; el rationale
   se mira en su propio canal vía ADR-0022.
3. **Catálogo cerrado `ActuationReason` (StrEnum).** Rechazado:
   sigue el patrón de `Decision.reason` (formato cerrado, no
   catálogo cerrado). Permite que futuros policies introduzcan
   reasons nuevos sin amendment del ADR.
4. **Permitir múltiples actuator commands por directive.** Rechazado:
   un actuador, una decisión, un comando. Composiciones más complejas
   son responsabilidad del caller.
5. **No incluir el `decision` en el `directive` (sólo el
   actuator_command).** Rechazado: rompe la cadena auditable. El
   directive debe poder citar su decisión productora.

## Backward compatibility

- ADR-0001..0022 sin tocar.
- Nuevo paquete `core.actuation`.
- Nuevo canal `/actuations` (canales previos intactos).
- Nuevo adapter (adapters previos intactos).
- Nuevo decoder en el catálogo cerrado (entradas previas intactas).
- Cero rotura.

## Invariantes verificables

| # | Invariante | Verificación |
|---|---|---|
| 1 | `ActuationDirective(directive_stamp != decision.decision_stamp)` raises ValueError | Test. |
| 2 | `ActuationDirective` con `actuator_command` que no es AttitudeCommand/DirectMotorCommand/None raises TypeError | Test. |
| 3 | `policy_id` / `reason` con formato inválido raises ValueError | Test. |
| 4 | `KillOnlyActuationPolicy.actuate(decision_with_kind=ENGAGE_KILL)` produce DirectMotorCommand con throttle todo cero | Test. |
| 5 | `KillOnlyActuationPolicy.actuate(any_other_kind)` produce directive con `actuator_command is None` | Test sobre los 6 kinds restantes. |
| 6 | `actuate_and_publish` invoca `policy.actuate` y luego `sink.publish` con el directive | Test con `RecordingActuationSink`. |
| 7 | `ActuationToTelemetryAdapter.publish` usa `directive_stamp_sim_ns` como log_time | Test con `InMemorySink`. |
| 8 | MCAP round-trip: write N directives → read → decoded == originals | Test con MCAPFileSink. |
| 9 | `KillOnlyActuationPolicy.policy_id == "kill_only_v1"` estable | Test. |
| 10 | Misma `(policy, decision)` → mismos bytes MCAP en N invocaciones | Test cross-process. |
| 11 | `NullActuationSink.publish` no eleva, no almacena | Test. |
| 12 | `RecordingActuationSink.records` preserva orden de publicación | Test. |
| 13 | `ActuationPolicy`, `ActuationSink` satisfechos por implementaciones (`isinstance`) | Test. |
| 14 | `ActuationDirective` frozen | Test. |
| 15 | Pipeline completo `belief → assess → decide → actuate → MCAP` produce directive auditable | Smoke test. |

## Mission posture

Es el primer ADR que da al agente la capacidad de **producir un
efecto observable distinguible cuando su creencia degrada**. Hasta
hoy el agente declaraba qué decidía (`ENGAGE_KILL` como label en
`/decisions`); desde hoy ese label produce un comando real al
actuador (zero throttle en `/actuations`).

La cláusula 3 de la misión ("consecuencias de la diferencia entre
creer y saber") pasa de **indemostrable** a **demostrable al nivel
KILL**. El agente ya **actúa diferente** cuando sabe que no sabe
suficiente para volar — al menos para el único caso donde la
traducción es inambigua.

Cuando lleguen las ADRs operativas (controlador, mission planner,
tiers), se componen trivialmente sobre este contrato. ADR-0023 es la
foundation sobre la que toda la mitad "act" del roadmap se construye.
