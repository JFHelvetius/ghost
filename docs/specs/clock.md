# SPEC — Simulation / System Clock

- **Estado:** congelado en Fase 0
- **ADR principal:** ADR-0002

## 1. Responsabilidades

- Proveer una única fuente de tiempo dentro de la simulación.
- Permitir step síncrono determinista.
- Coordinar callbacks periódicos de múltiples consumidores (sensores, control, telemetría).
- Proveer aleatoriedad reproducible via `RandomSource`.

**No es responsabilidad del Clock:**

- Conocer el contenido de los mensajes.
- Persistir nada a disco.
- Coordinar entrega ordenada (eso lo hace el bus consumiendo timestamps del clock).

## 2. Interfaces

```python
class SimClock(Protocol):
    def now_ns(self) -> int: ...
    def step_ns(self) -> int: ...                # tamaño del paso del backend
    def advance(self, dt_ns: int) -> None: ...   # solo backend de sim
    def schedule(self, at_ns: int, cb: Callable[[], None]) -> Handle: ...
    def schedule_periodic(self, period_ns: int, cb: Callable[[], None],
                          phase_ns: int = 0) -> Handle: ...
    def random_source(self) -> RandomSource: ...

class SystemClock(Protocol):                     # hardware o sim free-running
    def now_ns(self) -> int: ...
    def random_source(self) -> RandomSource: ...

@dataclass(frozen=True)
class Handle:
    cancel: Callable[[], None]
```

## 3. Contratos vinculantes

1. **Unidad atómica entera en nanosegundos.** No se aceptan `float` para `now_ns()`, `advance()`, `at_ns`, `period_ns`. La conversión a segundos es solo para visualización.
2. **Monotonía.** `clock.now_ns()` nunca retrocede.
3. **`advance()` solo en `SimClock`.** En hardware el tiempo avanza solo.
4. **Determinismo.** En `SimClock`, dada la misma seed y el mismo conjunto de `schedule_periodic` con los mismos parámetros, el orden y los timestamps de los callbacks son idénticos.
5. **`schedule_periodic(period, cb, phase)`** dispara `cb` en `t = phase, phase+period, phase+2·period, ...` siempre que `t ≤ now_ns()`. La acumulación se hace en `int`, no en `float`.
6. **Cancelación segura.** `handle.cancel()` puede llamarse en cualquier momento sin lanzar; double-cancel es idempotente.

## 4. Aleatoriedad

```python
class RandomSource(Protocol):
    seed: int
    label: str                                   # ruta jerárquica, ej. "/imu_noise"
    def child(self, label: str) -> "RandomSource": ...
    def uniform(self, a: float, b: float) -> float: ...
    def normal(self, mu: float, sigma: float) -> float: ...
    def integers(self, low: int, high: int) -> int: ...
    def numpy_rng(self) -> np.random.Generator: ...
```

Reglas:

- **Única raíz.** El `ScenarioSpec.seed` es la única semilla declarada.
- **Subgeneradores deterministas.** `child("imu_noise")` deriva de la raíz vía hash determinista de la etiqueta. Mismo árbol de etiquetas + misma raíz = mismos números.
- **Prohibido `random.*` y `np.random.*` globales.** Linter custom (en `tools/lint_random.py`) detecta usos en el código del proyecto.
- **Etiquetas jerárquicas.** Convención: `/<modulo>/<sub>/<...>`. Ej: `/sensors/imu0/noise`, `/sensors/cam_front/dropout`.

## 5. Arquitectura del scheduler

Implementación recomendada: **time wheel** o **min-heap**. Para Fase 1 un min-heap es suficiente; al crecer la carga puede sustituirse sin cambiar la API.

Pseudo-flujo de `advance(dt_ns)`:

```
target = now + dt
while heap.peek().at_ns <= target:
    item = heap.pop()
    now = item.at_ns
    item.cb()
    if item.periodic:
        heap.push(at_ns=item.at_ns + item.period_ns, ...)
now = target
```

Reglas:

- Si un callback programa nuevos eventos cuyo `at_ns ≤ target`, se procesan dentro del mismo `advance()`.
- Si un callback lanza excepción, se captura, se publica `Event(SCHEDULER_CALLBACK_FAILED)` y el scheduler continúa.

## 6. Orden total

Cada llamada a `bus.publish()` adquiere un `sequence` global atómico. La tupla `(stamp_sim_ns, sequence)` es el orden total. Subscribers reciben en este orden, no en orden de inscripción.

Para callbacks del scheduler ejecutados con el mismo `at_ns`, el orden lo define el **orden de inserción en el heap** (FIFO para empates). Esto debe documentarse en la implementación y testearse.

## 7. Replay

`ReplayClock` implementa `SimClock` leyendo timestamps del MCAP:

- `advance(dt_ns)` reproduce todos los mensajes y eventos del MCAP cuyo stamp cae en `(now, now+dt]`, en el mismo orden total.
- Los callbacks de control no se ejecutan automáticamente en replay (se pueden activar opcionalmente).
- `RandomSource` en replay no produce números (no se necesita), o se reproduce del log si fue persistido.

## 8. Casos de uso

### 8.1 Loop principal de Fase 1

```python
clock = backend.clock                   # SimClock determinista
clock.schedule_periodic(5_000_000, controller.tick)     # 200 Hz
clock.schedule_periodic(20_000_000, telemetry.flush_tick) # 50 Hz
while clock.now_ns() < END_NS:
    backend.step(1_000_000)             # 1 ms
```

### 8.2 Aleatoriedad limpia

```python
rng = clock.random_source().child("/sensors/imu0/noise")
accel_noise = rng.normal(0.0, 0.05, size=3)
```

### 8.3 Hardware

```python
clock = backend.clock                   # SystemClock
def tick():
    process_sensors()
    publish_command()
schedule_periodic_thread(period_ns=10_000_000, cb=tick, clock=clock)
```

(En hardware el "schedule" es un thread loop con `time.sleep_ns()` calibrado, no el time-wheel determinista.)

## 9. Errores comunes a evitar

- **Usar `time.time()` o `time.monotonic()` dentro del backend de sim.** Violación de contrato.
- **Acumular `dt` en `float`.** Drift garantizado.
- **Pedir un `child` con etiqueta dinámica** (ej: `f"/run_{uuid}"`). Rompe determinismo.
- **Programar callbacks que lanzan sin manejar.** El scheduler los aísla pero el bug queda invisible.
- **Confiar en que dos `schedule_periodic` con mismo periodo y fase distinta no se intercalen "raramente".** El orden está fijado; testearlo.

## 10. Evolución futura

- En hardware real: `SystemClock` puede leer del reloj de PX4 vía MAVLink para alinear con el firmware.
- Soporte PTP / hardware timestamping en cámaras (Fase 9+).
- Modo "wall-clock-throttle" en sim para correr a velocidad real (no determinista, solo para demos).
