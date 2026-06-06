"""Tipos base, clock, RandomSource, configuracion.

Subpaquetes:

- `core.uncertainty` (U1.a + U1.b, implementado): tipos, helpers e
  invariantes del modelo de incertidumbre; FSM de modo perceptual. Ver
  ``docs/specs/uncertainty.md``.
- `core.clock` (T3, implementado): SimClock, RandomSource, scheduler
  determinista. Ver ``docs/specs/clock.md``.

Reservados, implementacion en Fase 1 (T2 del roadmap):

- `core.messages`: dataclasses de mensajes del HAL.
- `core.config`: validacion de configuracion.
"""
