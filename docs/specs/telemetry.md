# SPEC — Telemetry System

- **Estado:** congelado en Fase 0
- **ADR principal:** ADR-0003; política de retención: ADR-0012

## 1. Responsabilidades

- Capturar todo mensaje publicado al bus.
- Distribuir a múltiples sinks con políticas de drop independientes.
- Garantizar que el hot loop no bloquea por I/O.
- Producir artefactos auditables por corrida.

**No es responsabilidad de la Telemetría:**

- Decidir qué se publica (eso lo decide cada productor).
- Visualizar (Rerun es un sink, no parte del core).
- Servir como mensajería entre módulos (eso es el event bus).

## 2. Componentes

```python
class TelemetrySink(Protocol):
    name: str
    def write(self, channel: str, msg: Any,
              stamp_sim_ns: int, stamp_wall_ns: int) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...

class TelemetryBus:
    def __init__(self, sinks: Sequence[TelemetrySink],
                 queue_capacity: int = 200_000,
                 drop_policy: DropPolicy = ...): ...
    def publish(self, channel: str, msg: Any,
                stamp_sim_ns: int, stamp_wall_ns: int) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

## 3. Formato primario: MCAP

- Una corrida = un archivo `runs/<run_id>/log.mcap`.
- Mensajes serializados con **Protobuf**. Schemas en `protos/`.
- Channels nombrados como rutas: `/sensors/imu0`, `/sensors/cam_front`, `/state/nav`, `/cmd/attitude`, `/events`, `/metrics/<name>`.
- Cada channel asocia un `schema_id` y `schema_version`. Cambiar `schema_version` no rompe lectores viejos si el cambio es aditivo.

## 4. Sinks estándar

| Sink | Función | Política de drop |
|---|---|---|
| `MCAPFileSink` | Verdad de fuente, archivo .mcap | Cola grande; drop → evento `TELEMETRY_BACKPRESSURE`. Sujeto a política de retención (§11). |
| `RerunSink` | Visualización en vivo | Drop-oldest con cuota por canal |
| `ConsoleSink` | Salida de eventos críticos | Solo severity ≥ WARN |
| `FoxgloveWSSink` *(Fase 4+)* | Streaming remoto | Drop-oldest |

Reglas:

- Los sinks corren en un thread background dedicado al `TelemetryBus`.
- `bus.publish()` es no bloqueante (encolar) salvo desbordamiento de cola, en cuyo caso aplica la política configurada.
- `bus.flush()` espera vaciado de cola, usado solo en cierre.

## 5. Imágenes

- Por defecto: JPEG calidad 85.
- Bajo flag `--lossless-images`: PNG.
- Para datasets de SLAM o eval, configuración explícita en el ScenarioSpec.
- Rate de cámara puede ser submuestrado para telemetría (p. ej. log 10 Hz aunque sensor publique 30 Hz). Configurable por canal.

## 6. Manifest por corrida

`runs/<run_id>/manifest.yaml`:

```yaml
run_id: 2026-06-03_142312_a4f1
created_utc: 2026-06-03T14:23:12Z
deterministic: true
seed: 42
scenario: worlds/empty_room.yaml
config_hash: sha256:...
config_snapshot: config_snapshot.yaml
git:
  sha: 7c1f...
  dirty: false
software:
  python: "3.12.3"
  ghost: "0.1.0"
  hal_protocol_version: 1
sim_time:
  start_ns: 0
  end_ns: 60_000_000_000
channels:
  - /sensors/imu0
  - /sensors/cam_front
  - /state/nav
  - /cmd/direct_motor
  - /events
  - /groundtruth/pose
schemas:
  /state/nav: nav_state.proto@1
  /events: event.proto@1
replay_command: "python -m ghost.replay runs/2026-06-03_142312_a4f1"
retention:
  tier: EPHEMERAL                  # EPHEMERAL | RESEARCH | RESULT (ADR-0012)
  coupling_check: pending          # set by U1 tooling at run creation
  expires_at_utc: 2026-06-10T14:23:12Z
```

Una corrida sin manifest no se considera artefacto válido. El manifest se preserva perpetuamente en todos los tiers (ADR-0012); el resto de los artefactos sigue la política del tier.

## 7. Integración Rerun

Convenciones:

| Canal del bus | Render Rerun |
|---|---|
| `/state/nav` (pose) | `rr.Transform3D` en `/vehicle` |
| `/sensors/cam_*` (RGB) | `rr.Image` en `/sensors/<id>/image` |
| `/sensors/cam_*` (depth) | `rr.DepthImage` |
| `/groundtruth/pose` | `rr.Transform3D` en `/groundtruth` |
| Trayectoria | `rr.LineStrips3D` acumulada |
| `/cmd/attitude` setpoint | `rr.Arrows3D` o `rr.Scalars` por componente |
| `/events` | `rr.TextLog` con `level` mapeado de severity |

Rerun se puede arrancar offline sobre el MCAP grabado vía conversor `python -m ghost.tools.mcap_to_rerun runs/<id>`.

## 8. Casos de uso

### 8.1 Inicialización

```python
sinks = [
    MCAPFileSink(path=f"runs/{run_id}/log.mcap"),
    RerunSink(application_id="project-ghost", recording_id=run_id),
    ConsoleSink(min_severity=Severity.WARN),
]
tel = TelemetryBus(sinks)
```

### 8.2 Publicación desde un productor

```python
tel.publish("/sensors/imu0", sample, sample.stamp_sim_ns, sample.stamp_wall_ns)
```

### 8.3 Cierre limpio

```python
with TelemetryBus(sinks) as tel:
    run_simulation(tel)
# __exit__ llama a flush() + close() en orden
```

## 9. Backpressure

Cuando la cola excede el `queue_capacity * threshold` (p. ej. 80%):

- Se emite `Event(TELEMETRY_BACKPRESSURE, severity=WARN)` con detalles (cola usada, sink culpable estimado).
- Sinks no críticos (Rerun) inician drop-oldest.
- Si la cola alcanza el 100%, MCAP sí dropea y emite evento de severity ERROR.

Política configurable en `core.config.telemetry`.

## 10. Errores comunes a evitar

- **Llamar a `flush()` desde el hot loop.** Bloquea hasta vaciar; solo al cerrar.
- **Pasar objetos mutables al sink.** El thread background los puede leer cuando el productor los ha modificado. Mensajes son frozen, pero arrays internos no; tratarlos como inmutables.
- **Crear `TelemetryBus` con `queue_capacity` minúscula.** Drop constante. Valores < 10_000 son sospechosos.
- **Olvidar `close()`.** El MCAP queda sin índice y truncado.
- **Loggear strings formateados pesados** cuando un mensaje estructurado es más ligero.

## 11. Retención y rotación (ADR-0012)

La política completa de retención vive en ADR-0012. Resumen operativo:

- **Tres tiers por corrida:** `EPHEMERAL` (7 días, default), `RESEARCH` (90 días + archivo perpetuo del manifest comprimido), `RESULT` (perpetuo en release asset). Tier se fija en `manifest.yaml` al crear la corrida; promoción siempre explícita por operador.
- **Tres clases de archivos por corrida:** manifest (perpetuo en todos los tiers), raw log (sujeto a tier), derivados (sujeto a tier, retención independiente del log si se solicita).
- **`runs/` ignorado por git** sin excepciones. `RESULT` se publica como release asset.
- **Presupuesto local:** default 50 GB, warn a 80 %, **rechazo de nuevas corridas** a 95 % hasta que operador limpie. No hay borrado silencioso.
- **Compresión zstd a día 7** para `RESEARCH` y `RESULT`. Sin reducción lossy de contenido.
- **Tooling:** `scripts/manage_runs.py` (a implementar en U1) ofrece `list`, `tag`, `clean`, `clean --dry-run`, `archive`, `verify`. Acciones interactivas emiten eventos `RETENTION_*` al bus.
- **Datasets** (U2/U5) se gobiernan por política análoga: ≤100 MB en repo, >100 MB en release assets, hashing por contenido.

Cualquier extensión (cloud backup, encriptación at rest, reducciones lossy) requiere ADR adicional.

## 12. Evolución futura

- Soporte de compresión zstd a nivel chunk MCAP en el writer (vs. compresión post-hoc a día 7 de ADR-0012; ambas son compatibles, ADR-0012 cubre la post-hoc obligatoria).
- Esquemas JSON Schema como alternativa para usuarios que no quieran Protobuf (ADR adicional).
- Web dashboard sobre Foxglove WebSocket.
