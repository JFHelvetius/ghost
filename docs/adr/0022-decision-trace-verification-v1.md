# ADR-0022 — Decision Trace and Chain Verification v1

## Status
Accepted (2026-06-07).

## Context

ADR-0021 introdujo el contrato runtime `belief → assessment → decision`
con cadena content-addressed por SHA-256 del assessment, prometiendo
auditabilidad bit-a-bit del rationale. **La promesa es hoy teórica:**

- No existe ninguna pieza que re-compute el SHA-256 de un assessment
  capturado y lo verifique contra el `self_assessment_sha256` que el
  `DecisionRationale` afirmó.
- No existe ningún artefacto que empareje cada decisión con el
  assessment que la justificó en el mismo MCAP.
- No existen agregados sobre las decisiones de un run (cuántas
  PROCEED vs HOLD vs ABSTAIN, bajo qué policy_id, en qué ventana
  temporal).

Cualquier operador que capture un MCAP con `/decisions` y
`/self_assessment` tiene que escribir la lectura, decodificación,
emparejamiento y verificación a mano. **Esto rompe la promesa de
research platform reproducible**: el operador no puede estudiar las
decisiones del agente sin re-inventar la consumer-side de ADR-0021.

El gap es **simétrico** al que existía antes de ADR-0016: belief se
publicaba en `/state/nav` pero no había trace-report. Lo cerramos del
mismo modo.

## Decision

Añadir `project_ghost.analysis.decision_trace` con un único artefacto
analítico:

### 1. `ChainStatus` (StrEnum cerrada)

Estado de la cadena `decision → assessment` por record:

- `verified` — rationale carga SHA y matchea el assessment encontrado.
- `broken` — rationale carga SHA, se encontró un assessment con el
  mismo `belief_stamp_sim_ns`, pero su SHA NO matchea (manipulación o
  bug).
- `assessment_missing` — rationale carga SHA pero no hay assessment
  con ese stamp en el MCAP (capture incompleto o stream incoherente).
- `no_assessment_claimed` — rationale tiene
  `self_assessment_sha256 is None`. La decisión se tomó sin
  introspección (caso legítimo y explícito por ADR-0021).

Catálogo cerrado. Modificar requiere ADR amendment.

### 2. `DecisionTraceRecord` (frozen dataclass)

Un record por cada `DecisionRationale` en `/decisions`:

```python
timestamp_ns: int                          # = rationale.belief_stamp_sim_ns
decision_kind: DecisionKind
decision_reason: str
policy_id: str
claimed_assessment_sha256: str | None      # lo que el rationale afirmó
recomputed_assessment_sha256: str | None   # lo que re-hash del assessment encontrado, o None si no se encontró / no se reclamó
chain_status: ChainStatus
analysis_version: int
```

### 3. `DecisionTraceReport` (frozen dataclass)

Run-level. Content-addressed al MCAP fuente:

```python
source_mcap_sha256: str                    # SHA-256 hex del archivo MCAP
total_decisions: int
verified_count: int
broken_count: int
assessment_missing_count: int
no_assessment_claimed_count: int
per_decision_kind_counts: Mapping[str, int]    # {"proceed": 12, "hold": 3, ...}
per_policy_id_counts: Mapping[str, int]
timestamp_first_ns: int | None
timestamp_last_ns: int | None
timestamp_span_ns: int | None
records: tuple[DecisionTraceRecord, ...]
analysis_version: int
```

Invariante: `verified + broken + assessment_missing + no_assessment_claimed == total_decisions`. Validado en `__post_init__`.

### 4. Pure functions

```python
def build_decision_trace_report(mcap_path: Path) -> DecisionTraceReport: ...

def verify_decision_chain(
    mcap_path: Path,
) -> tuple[bool, tuple[str, ...]]: ...
```

`verify_decision_chain` devuelve `(True, ())` sii la cadena está
íntegra: `broken_count == 0 and assessment_missing_count == 0`. En
caso de fallo, mensajes humanos por cada inconsistencia (mismo posture
que `verify_run_manifest` de ADR-0018).

### 5. Canonical JSON

`encode_decision_trace_report_to_bytes`, `decode_decision_trace_report_from_json`,
`generate_decision_trace_report` — mismo posture que ADR-0013/16/17/18/19/20:
`sort_keys=True`, `indent=2`, `ensure_ascii=False`, trailing newline,
UTF-8.

### 6. CLI

```
ghost trace-decisions --mcap PATH [--output PATH]
```

Lee el MCAP, construye el reporte, emite JSON canónico a `--output` o
stdout. Returns:

- `0` éxito,
- `1` archivo no existe / no es MCAP,
- `2` argparse (args faltantes).

### Algoritmo (frozen)

Single pass del MCAP:

1. Acumular todos los `BeliefSelfAssessment` en `assessments_by_stamp: dict[int, BeliefSelfAssessment]` indexado por `belief_stamp_sim_ns`. Si dos records comparten stamp, el último publicado gana (documentado).
2. Acumular todos los `DecisionRationale` en una lista en orden de stream.
3. Para cada rationale:
   - Si `rationale.self_assessment_sha256 is None`: status =
     `no_assessment_claimed`, `recomputed_sha = None`.
   - Si el assessment con stamp `rationale.belief_stamp_sim_ns` NO
     existe: status = `assessment_missing`, `recomputed_sha = None`.
   - Si existe: re-hash con `self_assessment_sha256(assessment)` (de
     ADR-0021); si matchea → `verified`; si no → `broken`.
4. Emitir record + actualizar contadores.

### Cadena de provenance extendida

Con ADR-0022, la cadena de provenance es verificable end-to-end sin
escribir código:

```
VehicleState (belief)
  → assess_belief
  → BeliefSelfAssessment (sha = S)              [publicado en /self_assessment]
  → DecisionContext
  → Policy.decide(context)
  → Decision
  → DecisionRationale (self_assessment_sha256 = S)   [publicado en /decisions]
  → MCAP

  → ghost trace-decisions --mcap ...
  → DecisionTraceReport (each record carries chain_status)
  → verify_decision_chain → (True, ()) si íntegra
```

Un auditor sin conocimiento del código fuente puede:

1. `sha256sum run.mcap` y verificarlo contra
   `DecisionTraceReport.source_mcap_sha256`.
2. Para cada record `verified`, confiar bit-a-bit en la cadena belief
   → decision.
3. Cualquier `broken` o `assessment_missing` aparece en el output
   verificable con mensaje exacto.

## Inputs

- Un MCAP capturado con records en `/self_assessment` y `/decisions`.
- En el contexto de v1, el MCAP debe ser el output de un wiring que
  combine `SelfAssessmentToTelemetryAdapter` (ADR-0020) y
  `DecisionToTelemetryAdapter` (ADR-0021) sobre el mismo sink.

## Outputs

- `DecisionTraceReport` (in-memory).
- JSON canónico (in-process bytes o archivo).

## Limits

- **No infiere causalidad.** El reporte no afirma que un assessment
  causó una decisión; sólo registra que el rationale lo declaró así.
- **No verifica que el policy de ADR-0021 se haya aplicado
  correctamente.** Verifica que la cadena content-addressed es íntegra.
  Auditar coherencia policy ↔ decisión es objeto de un ADR distinto
  (futuro analog de ADR-0019 para policies).
- **No detecta decisiones "incorrectas".** Las decisiones no son
  correctas/incorrectas; son lo que el policy escogido emitió.
- **No empareja decisiones con sus consecuencias en el mundo.** No hay
  loop runtime ni sim backend; las consecuencias siguen fuera de
  scope.
- **No clasifica policies.** El `per_policy_id_counts` es agregado
  descriptivo, no calidad.
- **Duplicados de assessment al mismo stamp.** Si dos
  `BeliefSelfAssessment` comparten `belief_stamp_sim_ns`, el último en
  el stream gana. En la práctica esto no ocurre con
  `SelfAssessmentToTelemetryAdapter`, pero se documenta como
  convención del builder.
- **Sólo MCAPs locales.** No URLs, no streams remotos.
- **No interpreta `no_assessment_claimed` como problema.** Es un
  estado legítimo y explícito.

## Determinism

Para el mismo MCAP de entrada dentro de `(CPython, mcap library)` fijo:

- `build_decision_trace_report` produce un `DecisionTraceReport`
  field-by-field igual.
- `verify_decision_chain` produce el mismo `(bool, tuple[str, ...])`.
- El JSON encoded es byte-idéntico.
- SHA-256 del JSON encoded estable cross-process.

El módulo:

- No lee reloj, no usa random, no usa threading/asyncio.
- Es stdlib only (`hashlib`, `json`, `dataclasses`) + las dependencias
  ya transitivamente presentes (telemetry reader, decisions types).
- No introduce dependencias runtime nuevas.

## Exclusiones explícitas

NO implementadas y NO extension points de esta ADR:

- **No nuevo veredicto sobre el run.** El reporte no califica
  "successful" / "failed". Cuenta records y reporta integridad de
  cadena.
- **No comparación de decisiones cross-run.** Eso es un ADR futuro
  (analog de ADR-0018 para decisiones), construido sobre esta
  primitiva.
- **No calibración de policy** (¿el policy mapea coherentemente?). ADR
  futuro construido sobre los records de este trace.
- **No emparejamiento decisión ↔ ActuatorCommand.** No hay actuator
  commands publicados todavía.
- **No reactividad / streaming live.** Sólo lectura batch de MCAP
  capturado.
- **No HTML / charts / dashboards / ML / clustering.**
- **No corrección automática de cadenas rotas.** El reporte expone el
  problema; el operador investiga.

**Cláusula reforzada:**

> *El reporte no clasifica decisiones como buenas o malas. Reporta la
> integridad de la cadena content-addressed entre creencia,
> introspección y decisión. La interpretación es del operador.*

## Consecuencias

**Positivo.**

- La promesa de auditabilidad de ADR-0021 deja de ser teórica.
  Cualquier operador puede verificar bit-a-bit la cadena con un único
  comando.
- Las dos analíticas de runtime —belief introspection (ADR-0020) y
  decision making (ADR-0021)— quedan **simétricamente analizables**.
  Antes: belief tenía ADR-0016/17/18/19; decision tenía cero.
- Toda ADR futura de **comparación de decisions** o **calibración de
  policy** se compone sobre `DecisionTraceReport` sin re-inventar el
  reader.
- Cero dependencias nuevas. Cero modificación de ADRs previos.

**Negativo.**

- El operador ahora tiene una capa más que ejecutar para auditar. La
  reusabilidad de `build_decision_trace_report` lo mitiga.
- Si dos assessments comparten stamp, el último gana. Trade-off
  aceptable; el caso no ocurre con la pipeline canónica.

## Alternativas consideradas

1. **No incluir `source_mcap_sha256`.** Rechazado: rompe la cadena de
   provenance que ADR-0018 (manifests) y ADR-0019 (calibration)
   establecieron como posture. La consistencia importa.
2. **Hacer `verify_decision_chain` un método de
   `DecisionTraceReport`.** Rechazado: la primitiva debe poder
   ejecutarse SIN encoder JSON; ahorra una capa.
3. **Incluir `BeliefSelfAssessment` completo en cada record.**
   Rechazado: bloat. El SHA es suficiente para verificación; el
   assessment original está en el MCAP.
4. **Empaquetar `verify` y `build` en un único entrypoint.** Rechazado:
   `verify` puede ejecutarse sin construir el reporte completo si en
   el futuro hace falta optimizar. Mantener separados preserva
   composabilidad.
5. **Soportar múltiples MCAPs en una invocación.** Rechazado:
   comparison es ADR futura. Esta es la primitiva por-run.

## Backward compatibility

- ADR-0001..0021 sin tocar.
- Nuevo módulo `analysis.decision_trace`.
- Nuevo subcomando `ghost trace-decisions`.
- Cero rotura.

## Mission posture

Esta ADR cierra la promesa pendiente de ADR-0021. Convierte el contrato
auditable de la capa de decisión en **auditable en la práctica**, sin
que el operador escriba código. La research platform queda
estructuralmente simétrica respecto al estudio de creencias y al
estudio de decisiones.

Cualquier ADR futura sobre evaluación de policies, comparación de
runs decisionales, o calibración de coherencia se compone sobre esta
primitiva. ADR-0022 elimina trabajo futuro al centralizar el reader
del MCAP de decisiones.
