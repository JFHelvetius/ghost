"""Project Ghost — professional Streamlit dashboard with EN/ES i18n."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from project_ghost.core.actuation.types import ActuationDirective
from project_ghost.core.decisions.types import DecisionRationale
from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.fusion.types import FusionResult
from project_ghost.core.prediction.divergence import PredictionOutcome
from project_ghost.core.uncertainty.self_assessment import BeliefSelfAssessment
from project_ghost.examples.closed_loop_smoke import (
    SmokeSummary,
    run_closed_loop_smoke,
)
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CHANNEL_DECISIONS,
    CHANNEL_FUSION_RESULTS,
    CHANNEL_PREDICTION_OUTCOMES,
    CHANNEL_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

# ─────────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────────

_KIND_COLOR: dict[str, str] = {
    "proceed": "#0f766e",
    "hold": "#b45309",
    "engage_kill": "#b91c1c",
}
_LEVEL_COLOR: dict[str, str] = {
    "known": "#0f766e",
    "uncertain": "#b45309",
    "unknown": "#b91c1c",
}
_VERDICT_COLOR: dict[str, str] = {
    "within_1_std": "#0f766e",
    "beyond_1_std": "#b45309",
    "beyond_3_std": "#b91c1c",
    "beyond_5_std": "#6d28d9",
}
_LEVEL_NUM: dict[str, int] = {"known": 0, "uncertain": 1, "unknown": 2}

_INK = "#0f172a"
_INK_SOFT = "#475569"
_INK_MUTED = "#94a3b8"
_BORDER = "#e2e8f0"
_GRID = "#eef2f6"
_SURFACE = "#ffffff"
_BLUE = "#1d4ed8"

# ─────────────────────────────────────────────────────────────────────────────
# i18n
# ─────────────────────────────────────────────────────────────────────────────

_LANG: dict[str, dict[str, str]] = {
    "en": {
        # Language picker
        "lang_label": "Language",
        # Hero
        "hero_eyebrow": "Research platform · Autonomy under uncertainty",
        "hero_h1": "Project Ghost",
        "hero_tagline": (
            "Imagine a self-driving car whose internal map has drifted ten "
            "meters from reality. It still <em>thinks</em> it knows the road "
            "— and keeps going. Project Ghost is a reference platform for "
            "autonomous systems that <strong>notice when their own model "
            "has drifted</strong>, and stop before they cause harm."
        ),
        # Concept cards
        "c1_num": "01 · THE PROBLEM",
        "c1_title": "Robots fail in silence",
        "c1_body": (
            "An autonomous system carries an internal picture of where it "
            "is and what is happening. When that picture stops matching "
            "reality — a sensor degrades, a wind gust hits, the world "
            "simply changes — most systems <strong>keep acting as if "
            "nothing is wrong</strong>. There is no warning. There is no "
            "safe stop. The first sign of trouble is usually the crash "
            "itself."
        ),
        "c2_num": "02 · THE APPROACH",
        "c2_title": "The robot watches itself",
        "c2_body": (
            "After every move, Ghost asks one question: <em>was I right?"
            "</em> It compares what it expected against what actually "
            "happened. A bad guess once is noise. Several in a row is a "
            "signal — the model is drifting. Ghost lowers its own "
            "confidence from <strong>“I know”</strong> to "
            "<strong>“I'm not sure”</strong> automatically."
        ),
        "c3_num": "03 · THE OUTCOME",
        "c3_title": "An honest robot stops",
        "c3_body": (
            "When confidence drops, Ghost stops emitting "
            "<strong>proceed</strong> commands and starts emitting "
            "<strong>hold</strong>. The vehicle pauses instead of acting "
            "on a stale belief. It isn't perfect autonomy — it's safer "
            "autonomy. And every decision is replayable byte-for-byte "
            "from the cryptographic log, so investigators can rebuild "
            "what happened later."
        ),
        # About expander
        "about_label": "About this work — what is the contribution?",
        "about_body": """
Project Ghost makes **five concrete, citable contributions** on top of
the existing literature on uncertainty in robotics. The underlying
ingredients (Bayesian filters, calibration, FDI, runtime supervisors)
are well-established; the contributions are in how they are
**combined, formally stated, and mechanically verified**.

- **PV-1 — Reproducibility primitive.**
  `ghost verify-properties --mcap <log>` reduces "is this run safe?"
  to one shell command returning a byte-exact verdict with exit code
  `0` iff every property holds. Verifier is a pure function over
  content-addressed MCAP — no replay, no simulation, no trust in the
  producer.
- **PV-2 — Formal partition theorem.**
  BAUD-v1 + ERUR-v1 partition the space of per-cycle conditional
  behaviour. Stated in TLA+ as `INV_PARTITION`, **mechanically
  verified by TLC** over the full reachable state space of the
  abstract model (ADR-0036). Promoted from "observed on one trace"
  to "proved on the model".
- **PV-3 — Structural recovery latency bound.**
  `L ≤ peak + W − 1` for sliding-window calibration histories with
  `MahalanobisDowngradePolicy(M, K)`. Drift-then-recovery smoke
  fires at the bound exactly (38 = 7 + 32 − 1), proving the bound
  is tight (RLB-v1).
- **PV-4 — Safe-reason set encoding pattern.**
  `S_BAUD-v1 = {"attitude_hold_hold", "kill_zero_throttle"}` — a
  closed taxonomy of strings classifying which non-PROCEED actuator
  commands count as conservative, replacing fragile `command is None`
  checks with an extensible, externally-auditable allowlist (BAUD-v1).
- **PV-5 — End-to-end safety citation pattern.**
  Content-addressed MCAP + ADR + pure-function verifier + Hypothesis
  property test + CI gate + tagged release + OIDC-signed PyPI wheel
  — assembled as one coherent reproducibility unit. The headline
  claim is operationally re-runnable from `pip install project-ghost==0.2.0`.

For each, the binding ADR is the formal statement, the verifier is
the executable test, the inline witness in `SmokeSummary.*_report`
is the self-evidence, and CI is the continuous guarantee.

Theoretically novel? No — this is an engineering and citation
contribution, not a new theorem. **Operationally novel? Yes** —
this is the pattern getting actually built and shipped, in a form
that lets third parties verify their own runs against the captured
MCAP without trusting the producer.
""",
        # Pipeline
        "pipeline_eyebrow": "The 8-step closed loop",
        "phase_perception": "Perception",
        "phase_action": "Action",
        "phase_learning": "Learning",
        "step_fusion_name": "Fusion",
        "step_fusion_desc": "Sensors → belief",
        "step_assess_name": "Assessment",
        "step_assess_desc": "Confidence raw",
        "step_calib_name": "Calibration",
        "step_calib_desc": "Adjust for past errors",
        "step_dec_name": "Decision",
        "step_dec_desc": "Proceed · Hold · Abort",
        "step_act_name": "Actuation",
        "step_act_desc": "Command to vehicle",
        "step_pred_name": "Prediction",
        "step_pred_desc": "Expected next state",
        "step_out_name": "Outcome",
        "step_out_desc": "Mahalanobis verdict",
        "step_fb_name": "Feedback",
        "step_fb_desc": "Update confidence model",
        "pipeline_caption": (
            "The <strong>Feedback</strong> arrow (Outcome → Calibration) "
            "closes the loop. When predictions are consistently wrong the "
            "confidence level is automatically downgraded, blocking PROCEED "
            "decisions until the model recovers. Without it, the agent "
            "would silently act on a stale belief."
        ),
        # Tabs
        "tab_run": "Try the simulation",
        "tab_inspect": "Inspect a run",
        # Run tab
        "run_intro": (
            "Every click of <strong>Run</strong> executes the complete "
            "8-step pipeline in your browser: oracle fusion → "
            "self-assessment → calibration feedback → decision → "
            "actuation → forward prediction → divergence evaluation. "
            "Results are captured to a downloadable MCAP telemetry file "
            "you can inspect below."
        ),
        "configure_eyebrow": "Configure the run",
        "slider_label": "Number of cycles",
        "slider_help": (
            "One cycle = one full pass through all 8 steps. Fewer than 5 "
            "won't trigger the calibration downgrade — use 10 or more to "
            "see the feedback loop in action."
        ),
        "run_caption": (
            "The simulation uses a deliberate overconfidence trap: the "
            "oracle believes the vehicle is stationary while ground truth "
            "drifts at 5 m/s. The calibration feedback loop is the only "
            "mechanism that can catch it."
        ),
        "run_button": "Run simulation",
        "spinner_run": "Running {n}-cycle closed loop…",
        "results_eyebrow": "Results",
        # Stats
        "stat_cycles": "Cycles",
        "stat_decisions": "Decisions",
        "stat_outcomes": "Outcomes",
        "stat_quality": "Prediction quality",
        # Sections
        "sec_decisions": "Decisions",
        "sec_calibration": "Calibration over time",
        "sec_provenance": "Provenance",
        "sec_properties": "Safety properties (ADR-0031..0035)",
        "properties_caption": (
            "Five formal properties verified inline against the captured "
            "MCAP. Each veredicto is byte-exact reproducible; the same "
            "<code>ghost verify-properties --mcap &lt;path&gt;</code> "
            "command from the shell produces identical output."
        ),
        "verdict_holds": "HOLDS",
        "verdict_violated": "VIOLATED",
        # Banners
        "banner_downgrade": (
            "<strong>Confidence downgraded at cycle {n}</strong> — "
            "prediction errors exceeded threshold"
        ),
        "banner_held": ("<strong>Confidence held</strong> — model stayed accurate throughout"),
        "banner_held_known": ("<strong>Confidence stayed KNOWN</strong> throughout"),
        # Provenance
        "provenance_caption": (
            "SHA-256 content address of this MCAP. Same inputs produce "
            "the same hash. Use it to prove this exact run was not "
            "tampered with."
        ),
        "download_button": "Download MCAP",
        # Inspect tab
        "upload_title": "Upload an MCAP telemetry file",
        "upload_body": (
            "Run the simulation in the <strong>Try the simulation</strong> "
            "tab, download the MCAP, and load it here to explore every "
            "layer of the pipeline."
        ),
        "upload_label": "Choose MCAP file",
        "upload_help": ("Files produced by ghost-app, the ghost CLI, or run_closed_loop_smoke()."),
        "decoding_spinner": "Decoding MCAP…",
        "no_messages_error": ("No decodeable messages found. Is this a valid Project Ghost MCAP?"),
        "loaded_msg": (
            "Loaded <strong>{n_channels} channels</strong> · <strong>{n_msgs} messages</strong>"
        ),
        "channel_overview_label": "Channel overview",
        # Inspect sections
        "ins_dec_title": "Decisions",
        "ins_dec_desc": (
            "Each cycle the agent chose one action based on its calibrated "
            "confidence. PROCEED = confident enough to continue. HOLD = "
            "uncertainty detected, the agent stopped to reassess."
        ),
        "ins_cal_title": "Calibration",
        "ins_cal_desc": (
            "Raw confidence adjusted by the feedback loop. When past "
            "predictions are consistently wrong the level downgrades from "
            "KNOWN to UNCERTAIN, blocking further PROCEED decisions until "
            "the model recovers."
        ),
        "ins_div_title": "Divergence outcomes",
        "ins_div_desc": (
            "Each cycle's prediction compared to ground truth. Mahalanobis "
            "distance is how many standard surprises off the prediction "
            "was. Values above 5-sigma indicate a severely wrong model."
        ),
        "ins_act_title": "Actuations",
        "ins_act_desc": (
            "The physical command issued each cycle. AttitudeCommand holds "
            "attitude and thrust. DirectMotorCommand drives motors "
            "directly (emergency). None means the policy suppressed the "
            "command."
        ),
        "ins_self_title": "Raw self-assessment",
        "ins_self_desc": (
            "The unfiltered confidence estimate before the calibration "
            "feedback loop. Compare with the calibrated level to see what "
            "the loop changed."
        ),
        "ins_fus_title": "Fusion results",
        "ins_fus_desc": (
            "The agent's belief about its current state from the fusion "
            "layer. In this simulation the oracle always reports position "
            "≈ 0 m while ground truth drifts. That gap drives the "
            "divergence."
        ),
        "fus_belief_caption": (
            "Oracle always reports x ≈ 0 m — ground truth drifts at 5 m/s. "
            "That gap drives the Mahalanobis divergence."
        ),
        # Replay
        "replay_label": "Replay verification",
        "replay_intro": (
            "Re-runs the downstream pipeline from the stored "
            "<code>/fusion/results</code> channel and compares every "
            "output message byte-for-byte against the original. A match "
            "proves the pipeline has no hidden non-determinism."
        ),
        "replay_button": "Run byte-exact verification",
        "replay_spinner": "Replaying downstream pipeline…",
        "replay_ok": (
            "<strong>Byte-perfect replay</strong> — all 6 downstream "
            "channels are identical between original run and replay"
        ),
        "replay_warn": (
            "<strong>Mismatch detected</strong> — at least one channel "
            "differs, indicating possible non-determinism in the pipeline"
        ),
        "replay_col_channel": "Channel",
        "replay_col_orig": "Original msgs",
        "replay_col_rep": "Replay msgs",
        "replay_col_result": "Result",
        "replay_byte_equal": "byte-equal",
        "replay_differs": "differs",
        # Narrative
        "narr_cycles": "The agent ran <strong>{n} full cycles</strong>.",
        "narr_downgrade": (
            "Cycles 1–{prev}: fully confident (<em>known</em>), decision "
            "was <strong>PROCEED</strong> every time. At cycle "
            "<strong>{cyc}</strong> accumulated prediction errors "
            "exceeded the calibration threshold — confidence dropped to "
            "<em>uncertain</em>, switching all subsequent decisions to "
            "<strong>HOLD</strong>."
        ),
        "narr_uncertain_start": (
            "The agent was <em>uncertain</em> from cycle 1 and held "
            "throughout — the model was never reliable enough to act."
        ),
        "narr_held": (
            "Confidence stayed <em>known</em> for every cycle — the agent "
            "chose <strong>PROCEED</strong> throughout."
        ),
        "narr_outro": (
            "Prediction quality: {verdict_human}. The simulation "
            "deliberately traps overconfident agents: the oracle reports a "
            "stationary vehicle while ground truth drifts at 5 m/s. The "
            "calibration loop is the only mechanism that can catch this."
        ),
        # Verdicts
        "verdict_5": ("consistently <strong>way off</strong> (&gt;5-sigma) — severe model failure"),
        "verdict_3": "significantly off (&gt;3-sigma) — model unreliable",
        "verdict_1": "moderately off (&gt;1-sigma) — mild drift detected",
        "verdict_in": "accurate (within 1-sigma) — model held",
        # Chart titles & axes
        "chart_dec_dist": "Decision distribution",
        "chart_calib_title": "Confidence level over cycles",
        "chart_div_title": "Position Mahalanobis distance",
        "chart_fusion_title": "Belief x-position (oracle vs. drift reality)",
        "axis_cycle": "Cycle",
        "axis_outcome": "Outcome",
        "axis_stddevs": "std-devs",
        "label_downgrade_at": "downgrade @ {n}",
    },
    "es": {
        "lang_label": "Idioma",
        "hero_eyebrow": "Plataforma de investigación · Autonomía bajo incertidumbre",
        "hero_h1": "Project Ghost",
        "hero_tagline": (
            "Imagina un coche autónomo cuyo mapa interno se ha desplazado "
            "diez metros de la realidad. El coche sigue <em>creyendo</em> "
            "que conoce la carretera — y sigue avanzando. Project Ghost es "
            "una plataforma de referencia para sistemas autónomos que "
            "<strong>detectan cuándo su propio modelo se ha "
            "desincronizado</strong> y se detienen antes de causar daño."
        ),
        "c1_num": "01 · EL PROBLEMA",
        "c1_title": "Los robots fallan en silencio",
        "c1_body": (
            "Un sistema autónomo lleva una imagen interna de dónde está y "
            "qué está pasando. Cuando esa imagen deja de coincidir con la "
            "realidad — un sensor se degrada, llega un golpe de viento, el "
            "mundo simplemente cambia — la mayoría siguen actuando "
            "<strong>como si nada estuviera mal</strong>. No hay aviso. "
            "No hay parada segura. La primera señal del problema suele "
            "ser el accidente."
        ),
        "c2_num": "02 · EL ENFOQUE",
        "c2_title": "El robot se observa a sí mismo",
        "c2_body": (
            "Después de cada movimiento, Ghost se hace una pregunta: "
            "<em>¿acerté?</em> Compara lo que esperaba con lo que pasó "
            "realmente. Una equivocación es ruido. Varias seguidas son "
            "señal — el modelo está derivando. Ghost baja su propia "
            "confianza de <strong>“lo sé”</strong> a "
            "<strong>“no estoy seguro”</strong> automáticamente."
        ),
        "c3_num": "03 · EL RESULTADO",
        "c3_title": "Un robot honesto se detiene",
        "c3_body": (
            "Cuando la confianza baja, Ghost deja de emitir "
            "<strong>proceed</strong> y empieza a emitir "
            "<strong>hold</strong>. El vehículo pausa en lugar de actuar "
            "sobre una creencia obsoleta. No es autonomía perfecta — es "
            "autonomía más segura. Y cada decisión es replayable byte a "
            "byte desde el log criptográfico, así que se puede reconstruir "
            "qué pasó después."
        ),
        "about_label": "Sobre este trabajo — ¿cuál es la contribución?",
        "about_body": """
Project Ghost aporta **cinco contribuciones concretas y citables**
sobre la literatura existente de incertidumbre en robótica. Los
ingredientes de base (filtros bayesianos, calibración, FDI,
supervisores en tiempo de ejecución) están bien establecidos; las
contribuciones están en **cómo se combinan, se enuncian formalmente
y se verifican mecánicamente**.

- **PV-1 — Primitivo de reproducibilidad.**
  `ghost verify-properties --mcap <log>` reduce "¿es seguro este
  run?" a un único comando de shell que devuelve un veredicto
  byte-exacto con código de salida `0` si y solo si toda propiedad
  se cumple. El verificador es una función pura sobre MCAP
  content-addressed — sin replay, sin simulación, sin confiar en el
  productor.
- **PV-2 — Teorema de partición formal.**
  BAUD-v1 + ERUR-v1 particionan el espacio de comportamiento
  condicional por ciclo. Enunciado en TLA+ como `INV_PARTITION`,
  **verificado mecánicamente por TLC** sobre el espacio de estados
  alcanzable completo del modelo abstracto (ADR-0036). Promovido de
  "observado en una traza" a "demostrado sobre el modelo".
- **PV-3 — Cota estructural de latencia de recuperación.**
  `L ≤ peak + W − 1` para historiales de calibración con ventana
  deslizante usando `MahalanobisDowngradePolicy(M, K)`. El smoke
  drift-then-recovery dispara exactamente en la cota
  (38 = 7 + 32 − 1), demostrando que la cota es ajustada (RLB-v1).
- **PV-4 — Patrón de codificación por safe-reason set.**
  `S_BAUD-v1 = {"attitude_hold_hold", "kill_zero_throttle"}` — una
  taxonomía cerrada de strings que clasifica qué comandos de
  actuador no-PROCEED cuentan como conservadores, reemplazando
  chequeos frágiles tipo `command is None` por una allowlist
  extensible y auditable externamente (BAUD-v1).
- **PV-5 — Patrón de citación end-to-end para safety.**
  MCAP content-addressed + ADR + verificador función pura + test
  de propiedades Hypothesis + gate de CI + release etiquetado +
  wheel firmado por OIDC en PyPI — ensamblados como una sola
  unidad coherente de reproducibilidad. La afirmación principal es
  re-ejecutable operacionalmente desde
  `pip install project-ghost==0.2.0`.

Para cada una: el ADR vinculante es el enunciado formal, el
verificador es el test ejecutable, el testigo inline en
`SmokeSummary.*_report` es la auto-evidencia, y CI es la garantía
continua.

¿Novedad teórica? No — esto es una contribución de ingeniería y
de patrón de citación, no un teorema nuevo. **¿Novedad
operacional? Sí** — este es el patrón realmente construido y
publicado, en una forma que permite a terceros verificar sus
propios runs contra el MCAP capturado sin confiar en el productor.
""",
        "pipeline_eyebrow": "El ciclo cerrado de 8 pasos",
        "phase_perception": "Percepción",
        "phase_action": "Acción",
        "phase_learning": "Aprendizaje",
        "step_fusion_name": "Fusión",
        "step_fusion_desc": "Sensores → belief",
        "step_assess_name": "Autoevaluación",
        "step_assess_desc": "Confianza bruta",
        "step_calib_name": "Calibración",
        "step_calib_desc": "Ajuste por errores pasados",
        "step_dec_name": "Decisión",
        "step_dec_desc": "Proceed · Hold · Abort",
        "step_act_name": "Actuación",
        "step_act_desc": "Comando al vehículo",
        "step_pred_name": "Predicción",
        "step_pred_desc": "Estado esperado",
        "step_out_name": "Outcome",
        "step_out_desc": "Veredicto Mahalanobis",
        "step_fb_name": "Feedback",
        "step_fb_desc": "Actualizar modelo de confianza",
        "pipeline_caption": (
            "La flecha <strong>Feedback</strong> (Outcome → Calibración) "
            "cierra el ciclo. Cuando las predicciones son consistentemente "
            "erróneas, el nivel de confianza baja automáticamente, "
            "bloqueando decisiones PROCEED hasta que el modelo se recupera. "
            "Sin él, el agente actuaría en silencio sobre una creencia "
            "obsoleta."
        ),
        "tab_run": "Probar la simulación",
        "tab_inspect": "Inspeccionar una ejecución",
        "run_intro": (
            "Cada clic en <strong>Ejecutar</strong> corre el pipeline "
            "completo de 8 pasos en tu navegador: fusión del oráculo → "
            "autoevaluación → feedback de calibración → decisión → "
            "actuación → predicción → evaluación de divergencia. Los "
            "resultados se capturan en un fichero MCAP descargable que "
            "puedes inspeccionar abajo."
        ),
        "configure_eyebrow": "Configurar la ejecución",
        "slider_label": "Número de ciclos",
        "slider_help": (
            "Un ciclo = una pasada completa por los 8 pasos. Con menos "
            "de 5 no se dispara la bajada de calibración — usa 10 o más "
            "para ver el lazo de feedback en acción."
        ),
        "run_caption": (
            "La simulación usa una trampa de sobreconfianza deliberada: "
            "el oráculo cree que el vehículo está parado mientras la "
            "verdad de fondo deriva a 5 m/s. El lazo de feedback de "
            "calibración es el único mecanismo que puede detectarlo."
        ),
        "run_button": "Ejecutar simulación",
        "spinner_run": "Ejecutando ciclo cerrado de {n} ciclos…",
        "results_eyebrow": "Resultados",
        "stat_cycles": "Ciclos",
        "stat_decisions": "Decisiones",
        "stat_outcomes": "Outcomes",
        "stat_quality": "Calidad de predicción",
        "sec_decisions": "Decisiones",
        "sec_calibration": "Calibración en el tiempo",
        "sec_provenance": "Procedencia",
        "sec_properties": "Propiedades formales de safety (ADR-0031..0035)",
        "properties_caption": (
            "Cinco propiedades formales verificadas inline sobre el MCAP "
            "capturado. Cada veredicto es byte-exacto reproducible; el "
            "mismo <code>ghost verify-properties --mcap &lt;path&gt;</code> "
            "desde shell produce salida idéntica."
        ),
        "verdict_holds": "HOLDS",
        "verdict_violated": "VIOLATED",
        "banner_downgrade": (
            "<strong>Confianza degradada en el ciclo {n}</strong> — los "
            "errores de predicción superaron el umbral"
        ),
        "banner_held": (
            "<strong>Confianza mantenida</strong> — el modelo se mantuvo "
            "preciso durante toda la ejecución"
        ),
        "banner_held_known": (
            "<strong>La confianza se mantuvo KNOWN</strong> durante todo el recorrido"
        ),
        "provenance_caption": (
            "Dirección de contenido SHA-256 de este MCAP. Los mismos "
            "inputs producen el mismo hash. Úsalo para demostrar que esta "
            "ejecución exacta no fue manipulada."
        ),
        "download_button": "Descargar MCAP",
        "upload_title": "Sube un fichero de telemetría MCAP",
        "upload_body": (
            "Ejecuta la simulación en la pestaña <strong>Probar la "
            "simulación</strong>, descarga el MCAP, y cárgalo aquí para "
            "explorar cada capa del pipeline."
        ),
        "upload_label": "Elegir fichero MCAP",
        "upload_help": (
            "Ficheros producidos por ghost-app, el CLI ghost, o run_closed_loop_smoke()."
        ),
        "decoding_spinner": "Decodificando MCAP…",
        "no_messages_error": (
            "No se encontraron mensajes decodificables. ¿Es un MCAP válido de Project Ghost?"
        ),
        "loaded_msg": (
            "Cargados <strong>{n_channels} canales</strong> · <strong>{n_msgs} mensajes</strong>"
        ),
        "channel_overview_label": "Resumen de canales",
        "ins_dec_title": "Decisiones",
        "ins_dec_desc": (
            "En cada ciclo el agente eligió una acción según su confianza "
            "calibrada. PROCEED = confianza suficiente para continuar. "
            "HOLD = se detectó incertidumbre, el agente paró para "
            "reevaluar."
        ),
        "ins_cal_title": "Calibración",
        "ins_cal_desc": (
            "Confianza bruta ajustada por el lazo de feedback. Cuando las "
            "predicciones pasadas son consistentemente erróneas el nivel "
            "baja de KNOWN a UNCERTAIN, bloqueando más decisiones PROCEED "
            "hasta que el modelo se recupere."
        ),
        "ins_div_title": "Outcomes de divergencia",
        "ins_div_desc": (
            "La predicción de cada ciclo comparada con la verdad real. "
            "La distancia de Mahalanobis es cuántas sorpresas estándar "
            "alejada estuvo la predicción. Valores por encima de 5-sigma "
            "indican un modelo gravemente erróneo."
        ),
        "ins_act_title": "Actuaciones",
        "ins_act_desc": (
            "El comando físico emitido en cada ciclo. AttitudeCommand "
            "mantiene attitude y empuje. DirectMotorCommand pilota los "
            "motores directamente (emergencia). None significa que la "
            "política suprimió el comando."
        ),
        "ins_self_title": "Autoevaluación bruta",
        "ins_self_desc": (
            "La estimación de confianza sin filtrar antes del lazo de "
            "calibración. Compárala con el nivel calibrado para ver qué "
            "cambió el lazo."
        ),
        "ins_fus_title": "Resultados de fusión",
        "ins_fus_desc": (
            "La creencia del agente sobre su estado actual desde la capa "
            "de fusión. En esta simulación el oráculo siempre reporta "
            "posición ≈ 0 m mientras la verdad de fondo deriva. Ese gap "
            "es lo que provoca la divergencia."
        ),
        "fus_belief_caption": (
            "El oráculo siempre reporta x ≈ 0 m — la verdad de fondo "
            "deriva a 5 m/s. Ese gap provoca la divergencia de "
            "Mahalanobis."
        ),
        "replay_label": "Verificación de replay",
        "replay_intro": (
            "Re-ejecuta el pipeline downstream desde el canal almacenado "
            "<code>/fusion/results</code> y compara cada mensaje de "
            "salida byte a byte contra el original. Una coincidencia "
            "demuestra que el pipeline no tiene no-determinismo oculto."
        ),
        "replay_button": "Ejecutar verificación byte-exacta",
        "replay_spinner": "Re-ejecutando pipeline downstream…",
        "replay_ok": (
            "<strong>Replay byte-perfecto</strong> — los 6 canales "
            "downstream son idénticos entre la ejecución original y el "
            "replay"
        ),
        "replay_warn": (
            "<strong>Diferencia detectada</strong> — al menos un canal "
            "difiere, indicando posible no-determinismo en el pipeline"
        ),
        "replay_col_channel": "Canal",
        "replay_col_orig": "Msgs originales",
        "replay_col_rep": "Msgs replay",
        "replay_col_result": "Resultado",
        "replay_byte_equal": "byte-iguales",
        "replay_differs": "difieren",
        "narr_cycles": "El agente corrió <strong>{n} ciclos completos</strong>.",
        "narr_downgrade": (
            "Ciclos 1–{prev}: plena confianza (<em>known</em>), la "
            "decisión fue <strong>PROCEED</strong> cada vez. En el ciclo "
            "<strong>{cyc}</strong> los errores acumulados de predicción "
            "superaron el umbral de calibración — la confianza bajó a "
            "<em>uncertain</em>, cambiando todas las decisiones "
            "posteriores a <strong>HOLD</strong>."
        ),
        "narr_uncertain_start": (
            "El agente estaba <em>uncertain</em> desde el ciclo 1 y "
            "mantuvo HOLD todo el tiempo — el modelo nunca fue lo "
            "suficientemente fiable para actuar."
        ),
        "narr_held": (
            "La confianza se mantuvo <em>known</em> en cada ciclo — el "
            "agente eligió <strong>PROCEED</strong> durante toda la "
            "ejecución."
        ),
        "narr_outro": (
            "Calidad de la predicción: {verdict_human}. La simulación "
            "atrapa deliberadamente a agentes sobre-confiados: el oráculo "
            "reporta un vehículo estático mientras la verdad de fondo "
            "deriva a 5 m/s. El lazo de calibración es el único mecanismo "
            "que puede detectarlo."
        ),
        "verdict_5": (
            "consistentemente <strong>muy lejos</strong> (&gt;5-sigma) — fallo severo del modelo"
        ),
        "verdict_3": ("significativamente lejos (&gt;3-sigma) — modelo no fiable"),
        "verdict_1": ("moderadamente lejos (&gt;1-sigma) — deriva leve detectada"),
        "verdict_in": "precisa (dentro de 1-sigma) — el modelo se mantuvo",
        "chart_dec_dist": "Distribución de decisiones",
        "chart_calib_title": "Nivel de confianza por ciclo",
        "chart_div_title": "Distancia de Mahalanobis (posición)",
        "chart_fusion_title": "Belief en x (oráculo vs. deriva real)",
        "axis_cycle": "Ciclo",
        "axis_outcome": "Outcome",
        "axis_stddevs": "std-devs",
        "label_downgrade_at": "bajada en ciclo {n}",
    },
}


def _lang() -> str:
    return st.session_state.get("lang", "en")


def t(key: str, **fmt: Any) -> str:
    """Translate a key into the active language, with optional .format args."""
    s = _LANG.get(_lang(), _LANG["en"]).get(key) or _LANG["en"].get(key, key)
    return s.format(**fmt) if fmt else s


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
.stApp {
    background: #fafbfc !important;
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI",
                 Roboto, "Helvetica Neue", Arial, sans-serif;
}
.main .block-container { max-width: 1180px; padding-top: 1.2rem; }

h1, h2, h3, h4, h5 { color: #0f172a; letter-spacing: -0.01em; }
p, li, span, label { color: #334155; }
hr { border-color: #e2e8f0 !important; }

/* Language picker (top right) */
.lang-bar {
    display: flex; justify-content: flex-end; align-items: center;
    gap: 0.4rem; margin-bottom: -0.2rem;
}

/* Hero */
.ghost-hero {
    padding: 0.5rem 0 2rem;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 2rem;
}
.ghost-hero .eyebrow {
    font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.8px; color: #1d4ed8; margin-bottom: 0.7rem;
}
.ghost-hero h1 {
    font-size: 2.6rem; font-weight: 700; color: #0f172a;
    line-height: 1.12; letter-spacing: -0.025em; margin: 0 0 0.8rem;
}
.ghost-hero .tagline {
    font-size: 1.08rem; color: #475569; line-height: 1.55;
    max-width: 740px; margin: 0; font-weight: 400;
}

/* Concept grid */
.concept-grid {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 1rem; margin: 1.6rem 0 1rem;
}
.concept-card {
    background: #ffffff; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 1.4rem 1.3rem 1.2rem;
    transition: border 0.15s, box-shadow 0.15s;
}
.concept-card:hover {
    border-color: #cbd5e1;
    box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.concept-card .cc-num {
    font-size: 0.7rem; font-weight: 700; color: #1d4ed8;
    letter-spacing: 1.2px; margin-bottom: 0.55rem;
}
.concept-card .cc-title {
    font-size: 1rem; font-weight: 600; color: #0f172a;
    margin-bottom: 0.55rem; letter-spacing: -0.01em;
}
.concept-card .cc-body {
    font-size: 0.88rem; color: #475569; line-height: 1.62;
}

/* Section header */
.section-eyebrow {
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.5px; color: #64748b; margin: 1.6rem 0 0.5rem;
    padding-bottom: 0.4rem; border-bottom: 1px solid #e2e8f0;
}

/* Pipeline */
.pipe-phase {
    font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1.3px; text-align: center; margin-bottom: 0.45rem;
    height: 14px;
}
.pipe-step {
    display: flex; flex-direction: column; align-items: center;
    padding: 0.85rem 0.4rem; border-radius: 8px;
    background: #ffffff; border: 1px solid #e2e8f0;
    min-height: 96px; justify-content: flex-start;
    transition: border 0.15s;
}
.pipe-step:hover { border-color: #94a3b8; }
.pipe-step .ps-icon { font-size: 1.25rem; margin-bottom: 0.25rem; }
.pipe-step .ps-name {
    font-size: 0.78rem; font-weight: 600; color: #0f172a; text-align: center;
}
.pipe-step .ps-desc {
    font-size: 0.66rem; color: #64748b; text-align: center;
    margin-top: 0.2rem; line-height: 1.45;
}
.pipe-arrow {
    text-align: center; font-size: 1rem; color: #cbd5e1; padding-top: 38px;
}

/* Stats */
.stats-grid {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 0.7rem; margin: 1rem 0 1.4rem;
}
.stat-card {
    background: #ffffff; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 1.1rem 1rem;
}
.stat-card .sc-lab {
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; color: #64748b; margin-bottom: 0.45rem;
}
.stat-card .sc-val {
    font-size: 1.85rem; font-weight: 700; color: #0f172a;
    line-height: 1; letter-spacing: -0.02em;
}
.stat-card .sc-val.small {
    font-size: 1rem; font-weight: 600; padding-top: 0.5rem;
}

/* Narrative */
.narrative {
    background: #ffffff; border: 1px solid #e2e8f0;
    border-left: 3px solid #1d4ed8; border-radius: 0 8px 8px 0;
    padding: 1.2rem 1.4rem; margin: 1rem 0 1.4rem;
    font-size: 0.95rem; line-height: 1.7; color: #1e293b;
}
.narrative b, .narrative strong { color: #0f172a; font-weight: 600; }
.narrative em { color: #1d4ed8; font-style: normal; font-weight: 500; }

/* Banners */
.banner-ok {
    background: #f0fdfa; border: 1px solid #99f6e4;
    border-left: 3px solid #0f766e; border-radius: 0 8px 8px 0;
    padding: 0.75rem 1.1rem; color: #134e4a;
    font-weight: 500; font-size: 0.9rem; margin: 0.5rem 0;
}
.banner-warn {
    background: #fffbeb; border: 1px solid #fde68a;
    border-left: 3px solid #b45309; border-radius: 0 8px 8px 0;
    padding: 0.75rem 1.1rem; color: #78350f;
    font-weight: 500; font-size: 0.9rem; margin: 0.5rem 0;
}

/* Badges */
.pg-badge {
    display: inline-block; padding: 3px 10px; border-radius: 5px;
    font-weight: 600; font-size: 11.5px; white-space: nowrap;
    color: #ffffff; margin: 2px; letter-spacing: 0.3px;
}

/* Upload area */
.upload-hint {
    text-align: center; padding: 2.2rem 2rem;
    border: 1px dashed #cbd5e1; border-radius: 12px;
    background: #ffffff; margin: 1rem 0;
}
.upload-hint .uh-icon { font-size: 2.2rem; margin-bottom: 0.55rem; opacity: 0.7; }
.upload-hint .uh-title { font-size: 1rem; font-weight: 600; color: #0f172a; margin-bottom: 0.3rem; }
.upload-hint .uh-body { font-size: 0.85rem; color: #64748b; line-height: 1.55; }

/* Property panel (ADR-0031..0035) */
.property-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 0.55rem;
    margin: 0.6rem 0 1.4rem;
}
.property-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-left: 3px solid #94a3b8;
    border-radius: 8px;
    padding: 0.85rem 0.8rem;
    transition: border-color 0.15s;
}
.property-card.holds { border-left-color: #0f766e; }
.property-card.violated { border-left-color: #b91c1c; }
.property-card .pc-name {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-weight: 700; color: #0f172a; font-size: 0.78rem;
    letter-spacing: 0.2px;
}
.property-card .pc-verdict {
    font-weight: 700; font-size: 0.85rem; margin-top: 0.3rem;
    letter-spacing: 0.5px;
}
.property-card.holds .pc-verdict { color: #0f766e; }
.property-card.violated .pc-verdict { color: #b91c1c; }
.property-card .pc-stat {
    font-size: 0.7rem; color: #64748b; margin-top: 0.3rem;
    line-height: 1.4;
}

/* Hash block */
.hash-block {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 0.7rem 0.95rem; font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.78rem; color: #1d4ed8; word-break: break-all; margin: 0.4rem 0;
}

/* Expanders */
[data-testid="stExpander"] {
    border: 1px solid #e2e8f0; border-radius: 8px;
    background: #ffffff; margin: 0.5rem 0;
}
[data-testid="stExpander"] summary { color: #0f172a; font-weight: 600; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid #e2e8f0; }
.stTabs [data-baseweb="tab"] {
    color: #64748b; font-weight: 500; padding: 0.65rem 1.2rem;
}
.stTabs [aria-selected="true"] { color: #0f172a; font-weight: 600; }

/* Buttons */
.stButton button[kind="primary"] {
    background: #1d4ed8; color: #ffffff; border: 1px solid #1e40af;
    font-weight: 600; letter-spacing: 0.2px; border-radius: 7px;
    padding: 0.55rem 1.1rem; transition: background 0.15s, box-shadow 0.15s;
}
.stButton button[kind="primary"]:hover {
    background: #1e40af; box-shadow: 0 1px 3px rgba(29,78,216,0.25);
}

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# Plotly helpers
# ─────────────────────────────────────────────────────────────────────────────


def _base_layout(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "paper_bgcolor": _SURFACE,
        "plot_bgcolor": _SURFACE,
        "font": {"color": _INK, "family": "-apple-system, Inter, Segoe UI, sans-serif", "size": 12},
        "margin": {"l": 44, "r": 18, "t": 34, "b": 42},
        "showlegend": False,
    }
    base.update(kw)
    return base


def _axis_style(**kw: Any) -> dict[str, Any]:
    return dict(
        color=_INK_MUTED,
        gridcolor=_GRID,
        zerolinecolor=_BORDER,
        linecolor=_BORDER,
        tickfont={"size": 11, "color": _INK_MUTED},
        title_font={"size": 11, "color": _INK_SOFT},
        **kw,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MCAP decode cache
# ─────────────────────────────────────────────────────────────────────────────


@st.cache_data(show_spinner=False)  # type: ignore[untyped-decorator,unused-ignore]
def _decode_mcap(file_bytes: bytes) -> dict[str, list[tuple[int, Any]]]:
    with tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    result: dict[str, list[tuple[int, Any]]] = {}
    try:
        with MCAPReplayReader(tmp_path) as reader:
            for msg in reader.iter_messages():
                try:
                    obj = decode_message(msg)
                    result.setdefault(msg.channel, []).append((msg.log_time_sim_ns, obj))
                except (KeyError, ValueError):
                    pass
    finally:
        tmp_path.unlink(missing_ok=True)
    return result


def _ms(ns: int) -> float:
    return round(ns / 1_000_000, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Language picker
# ─────────────────────────────────────────────────────────────────────────────


def _language_picker() -> None:
    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"

    _, col = st.columns([10, 1])
    with col:
        current_idx = 0 if st.session_state["lang"] == "en" else 1
        choice = st.radio(
            t("lang_label"),
            ["EN", "ES"],
            horizontal=True,
            label_visibility="collapsed",
            index=current_idx,
            key="_lang_radio",
        )
        new_lang = "en" if choice == "EN" else "es"
        if new_lang != st.session_state["lang"]:
            st.session_state["lang"] = new_lang
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Hero & concept cards
# ─────────────────────────────────────────────────────────────────────────────


def _hero() -> None:
    st.markdown(
        f"""
<div class="ghost-hero">
  <div class="eyebrow">{t("hero_eyebrow")}</div>
  <h1>{t("hero_h1")}</h1>
  <p class="tagline">{t("hero_tagline")}</p>
</div>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div class="concept-grid">
  <div class="concept-card">
    <div class="cc-num">{t("c1_num")}</div>
    <div class="cc-title">{t("c1_title")}</div>
    <div class="cc-body">{t("c1_body")}</div>
  </div>
  <div class="concept-card">
    <div class="cc-num">{t("c2_num")}</div>
    <div class="cc-title">{t("c2_title")}</div>
    <div class="cc-body">{t("c2_body")}</div>
  </div>
  <div class="concept-card">
    <div class="cc-num">{t("c3_num")}</div>
    <div class="cc-title">{t("c3_title")}</div>
    <div class="cc-body">{t("c3_body")}</div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )

    with st.expander(t("about_label"), expanded=False):
        st.markdown(t("about_body"))


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline diagram (three phases)
# ─────────────────────────────────────────────────────────────────────────────

_PHASE_LAYOUT: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "phase_perception",
        "#1d4ed8",
        [
            ("🔭", "step_fusion_name", "step_fusion_desc"),
            ("🧠", "step_assess_name", "step_assess_desc"),
            ("⚖️", "step_calib_name", "step_calib_desc"),
        ],
    ),
    (
        "phase_action",
        "#b45309",
        [
            ("🎯", "step_dec_name", "step_dec_desc"),
            ("⚙️", "step_act_name", "step_act_desc"),
        ],
    ),
    (
        "phase_learning",
        "#0f766e",
        [
            ("🔮", "step_pred_name", "step_pred_desc"),
            ("📊", "step_out_name", "step_out_desc"),
            ("🔄", "step_fb_name", "step_fb_desc"),
        ],
    ),
]


def _pipeline_diagram() -> None:
    st.markdown(
        f'<div class="section-eyebrow">{t("pipeline_eyebrow")}</div>',
        unsafe_allow_html=True,
    )

    col_specs: list[int] = []
    for pi, (_, _, steps) in enumerate(_PHASE_LAYOUT):
        for si in range(len(steps)):
            col_specs.append(3)
            if si < len(steps) - 1:
                col_specs.append(1)
        if pi < len(_PHASE_LAYOUT) - 1:
            col_specs.append(1)

    cols = st.columns(col_specs)
    ci = 0

    for pi, (phase_key, phase_color, steps) in enumerate(_PHASE_LAYOUT):
        for si, (icon, name_key, desc_key) in enumerate(steps):
            with cols[ci]:
                phase_label = t(phase_key) if si == 0 else ""
                st.markdown(
                    f"""
<div class="pipe-phase" style="color:{phase_color}">{phase_label}</div>
<div class="pipe-step">
  <div class="ps-icon">{icon}</div>
  <div class="ps-name">{t(name_key)}</div>
  <div class="ps-desc">{t(desc_key)}</div>
</div>""",
                    unsafe_allow_html=True,
                )
            ci += 1
            if si < len(steps) - 1:
                with cols[ci]:
                    st.markdown('<div class="pipe-arrow">→</div>', unsafe_allow_html=True)
                ci += 1
        if pi < len(_PHASE_LAYOUT) - 1:
            with cols[ci]:
                st.markdown(
                    '<div class="pipe-arrow" style="font-size:1.2rem;color:#94a3b8">⇒</div>',
                    unsafe_allow_html=True,
                )
            ci += 1

    st.markdown(
        f'<p style="color:#64748b;font-size:0.85rem;line-height:1.6;margin-top:0.9rem">'
        f"{t('pipeline_caption')}</p>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Narrative
# ─────────────────────────────────────────────────────────────────────────────

_VERDICT_KEYS = {
    "beyond_5_std": "verdict_5",
    "beyond_3_std": "verdict_3",
    "beyond_1_std": "verdict_1",
    "within_1_std": "verdict_in",
}


def _run_narrative(summary: SmokeSummary) -> str:
    levels = summary.calibrated_levels_observed
    first_change = next((i + 1 for i, lv in enumerate(levels) if lv != "known"), None)
    verdict = summary.final_verdict or ""
    vkey = _VERDICT_KEYS.get(verdict)
    verdict_human = t(vkey) if vkey else verdict.replace("_", " ")

    parts = [t("narr_cycles", n=summary.n_cycles)]

    if first_change and first_change > 1:
        parts.append(t("narr_downgrade", prev=first_change - 1, cyc=first_change))
    elif first_change == 1:
        parts.append(t("narr_uncertain_start"))
    else:
        parts.append(t("narr_held"))

    parts.append(t("narr_outro", verdict_human=verdict_human))
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Plotly chart helpers
# ─────────────────────────────────────────────────────────────────────────────


def _chart_decision_dist(decisions_by_kind: dict[str, int]) -> go.Figure:
    kinds = list(decisions_by_kind.keys())
    counts = list(decisions_by_kind.values())
    colors = [_KIND_COLOR.get(k, "#64748b") for k in kinds]
    labels = [k.replace("_", " ").upper() for k in kinds]

    fig = go.Figure(
        go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            marker={"color": colors, "line": {"color": _BORDER, "width": 0.5}},
            text=counts,
            textposition="outside",
            textfont={"color": _INK, "size": 12},
            hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        **_base_layout(height=170, margin={"l": 12, "r": 40, "t": 30, "b": 30}),
        title={"text": t("chart_dec_dist"), "font": {"size": 11, "color": _INK_SOFT}, "x": 0},
        xaxis=_axis_style(title="", showgrid=True),
        yaxis=_axis_style(showgrid=False, tickfont={"size": 11, "color": _INK}),
    )
    return fig


def _chart_calibration(levels: list[str]) -> go.Figure:
    cycles = list(range(1, len(levels) + 1))
    nums = [_LEVEL_NUM.get(lv, -1) for lv in levels]

    fig = go.Figure()
    fig.add_hrect(y0=-0.3, y1=0.5, fillcolor="rgba(15,118,110,0.06)", line_width=0)
    fig.add_hrect(y0=0.5, y1=1.5, fillcolor="rgba(180,83,9,0.06)", line_width=0)
    fig.add_hrect(y0=1.5, y1=2.3, fillcolor="rgba(185,28,28,0.06)", line_width=0)

    fig.add_trace(
        go.Scatter(
            x=cycles,
            y=nums,
            mode="lines+markers",
            line={"color": _BLUE, "width": 2.2, "shape": "hv"},
            marker={
                "size": 7,
                "color": [_LEVEL_COLOR.get(lv, "#64748b") for lv in levels],
                "line": {"color": "#ffffff", "width": 1.3},
            },
            hovertemplate=f"{t('axis_cycle')} %{{x}}<br>Level: %{{y}}<extra></extra>",
        )
    )
    downgrade = next((c for c, n in zip(cycles, nums, strict=False) if n > 0), None)
    if downgrade:
        fig.add_vline(
            x=downgrade,
            line_dash="dash",
            line_color="#b45309",
            line_width=1.4,
            annotation_text=t("label_downgrade_at", n=downgrade),
            annotation_font_color="#b45309",
            annotation_font_size=10,
            annotation_position="top right",
        )
    fig.update_layout(
        **_base_layout(height=220, margin={"l": 86, "r": 20, "t": 32, "b": 42}),
        title={"text": t("chart_calib_title"), "font": {"size": 11, "color": _INK_SOFT}, "x": 0},
        xaxis=_axis_style(title=t("axis_cycle")),
        yaxis=_axis_style(
            title="",
            tickmode="array",
            tickvals=[0, 1, 2],
            ticktext=["KNOWN", "UNCERTAIN", "UNKNOWN"],
            range=[-0.3, 2.3],
            tickfont={"size": 10, "color": _INK_SOFT},
        ),
    )
    return fig


def _chart_divergence(rows: list[dict[str, Any]]) -> go.Figure:
    outcomes = [r["Outcome"] for r in rows]
    maha = [r["Pos Mahalanobis"] for r in rows]
    verdicts = [r["Verdict"] for r in rows]

    fig = go.Figure()
    for sigma, color in ((5, "#6d28d9"), (3, "#b91c1c"), (1, "#b45309")):
        fig.add_hline(
            y=sigma,
            line_dash="dot",
            line_color=color,
            opacity=0.4,
            annotation_text=f"{sigma}σ",
            annotation_font_size=10,
            annotation_font_color=color,
            annotation_position="right",
        )
    fig.add_trace(
        go.Scatter(
            x=outcomes,
            y=maha,
            mode="lines+markers",
            line={"color": _INK_SOFT, "width": 1.5},
            marker={
                "size": 8,
                "color": [_VERDICT_COLOR.get(v, "#64748b") for v in verdicts],
                "line": {"color": "#ffffff", "width": 1.2},
            },
            hovertemplate=f"{t('axis_outcome')} %{{x}}<br>Mahalanobis: %{{y:.2f}}<extra></extra>",
        )
    )
    fig.update_layout(
        **_base_layout(height=200, margin={"l": 42, "r": 60, "t": 30, "b": 42}),
        title={"text": t("chart_div_title"), "font": {"size": 11, "color": _INK_SOFT}, "x": 0},
        xaxis=_axis_style(title=t("axis_outcome")),
        yaxis=_axis_style(title=t("axis_stddevs")),
    )
    return fig


def _chart_fusion_x(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            x=df["Cycle"],
            y=df["x (m)"],
            mode="lines+markers",
            line={"color": _BLUE, "width": 2},
            marker={"size": 5, "color": _BLUE},
            fill="tozeroy",
            fillcolor="rgba(29,78,216,0.05)",
            hovertemplate=f"{t('axis_cycle')} %{{x}}<br>x = %{{y:.4f}} m<extra></extra>",
        )
    )
    fig.update_layout(
        **_base_layout(height=180, margin={"l": 44, "r": 18, "t": 30, "b": 42}),
        title={"text": t("chart_fusion_title"), "font": {"size": 11, "color": _INK_SOFT}, "x": 0},
        xaxis=_axis_style(title=t("axis_cycle")),
        yaxis=_axis_style(title="x (m)"),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Badges
# ─────────────────────────────────────────────────────────────────────────────


def _badge(label: str, color: str) -> str:
    return f'<span class="pg-badge" style="background:{color}">{label}</span>'


def _badges(mapping: dict[str, int], color_map: dict[str, str]) -> None:
    parts = [
        _badge(f"{k.replace('_', ' ').upper()}  ×{v}", color_map.get(k, "#64748b"))
        for k, v in sorted(mapping.items(), key=lambda x: -x[1])
    ]
    st.markdown(" &nbsp; ".join(parts), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Run tab
# ─────────────────────────────────────────────────────────────────────────────


def _property_panel(summary: SmokeSummary) -> str:
    """Render the 5-property panel as an HTML grid for ``_show_run_results``.

    Each card carries the property tag (BAUD-v1, ERUR-v1, ...), the
    HOLDS / VIOLATED veredicto with colour-coded border, and a compact
    per-property stat block. Same data the ``ghost verify-properties``
    CLI emits, but in dashboard shape.
    """
    cards: list[str] = []
    for tag, report, stat in (
        (
            "BAUD-v1",
            summary.baud_report,
            f"M={summary.baud_report.min_outcomes}, "
            f"K={summary.baud_report.downgrade_threshold} · "
            f"{summary.baud_report.cycles_precondition_held}/"
            f"{summary.baud_report.cycles_total} cycles",
        ),
        (
            "ERUR-v1",
            summary.erur_report,
            f"M={summary.erur_report.min_outcomes}, "
            f"K={summary.erur_report.downgrade_threshold} · "
            f"{summary.erur_report.cycles_precondition_held}/"
            f"{summary.erur_report.cycles_total} cycles",
        ),
        (
            "MD-v1",
            summary.md_report,
            f"{summary.md_report.cycles_precondition_held}/{summary.md_report.cycles_total} cycles",
        ),
        (
            "RLB-v1",
            summary.rlb_report,
            f"W={summary.rlb_report.max_history} · "
            f"{summary.rlb_report.cycles_precondition_held}/"
            f"{summary.rlb_report.cycles_total} recoveries",
        ),
        (
            "FPB-v1",
            summary.fpb_report,
            f"fire_fraction={summary.fpb_report.fire_fraction:.2f} · "
            f"bound={summary.fpb_report.max_fire_fraction:.2f}",
        ),
    ):
        klass = "holds" if report.holds else "violated"
        verdict = t("verdict_holds") if report.holds else t("verdict_violated")
        cards.append(
            f'<div class="property-card {klass}">'
            f'<div class="pc-name">{tag}</div>'
            f'<div class="pc-verdict">{verdict}</div>'
            f'<div class="pc-stat">{stat}</div>'
            f"</div>"
        )
    return f'<div class="property-grid">{"".join(cards)}</div>'


def _show_run_results(summary: SmokeSummary, mcap_bytes: bytes) -> None:
    st.markdown(
        f'<div class="narrative">{_run_narrative(summary)}</div>',
        unsafe_allow_html=True,
    )

    verdict_str = (summary.final_verdict or "—").replace("_", " ")
    verdict_color = _VERDICT_COLOR.get(summary.final_verdict or "", _INK)
    st.markdown(
        f"""
<div class="stats-grid">
  <div class="stat-card">
    <div class="sc-lab">{t("stat_cycles")}</div>
    <div class="sc-val">{summary.n_cycles}</div>
  </div>
  <div class="stat-card">
    <div class="sc-lab">{t("stat_decisions")}</div>
    <div class="sc-val">{summary.n_decisions}</div>
  </div>
  <div class="stat-card">
    <div class="sc-lab">{t("stat_outcomes")}</div>
    <div class="sc-val">{summary.n_outcomes}</div>
  </div>
  <div class="stat-card">
    <div class="sc-lab">{t("stat_quality")}</div>
    <div class="sc-val small" style="color:{verdict_color}">{verdict_str}</div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(
            f'<div class="section-eyebrow">{t("sec_decisions")}</div>',
            unsafe_allow_html=True,
        )
        _badges(summary.decisions_by_kind, _KIND_COLOR)
        st.plotly_chart(
            _chart_decision_dist(summary.decisions_by_kind),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_b:
        st.markdown(
            f'<div class="section-eyebrow">{t("sec_calibration")}</div>',
            unsafe_allow_html=True,
        )
        levels = summary.calibrated_levels_observed
        downgrade = next((i + 1 for i, lv in enumerate(levels) if lv != "known"), None)
        if downgrade:
            st.markdown(
                f'<div class="banner-warn">{t("banner_downgrade", n=downgrade)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="banner-ok">{t("banner_held")}</div>',
                unsafe_allow_html=True,
            )
        st.plotly_chart(
            _chart_calibration(levels),
            use_container_width=True,
            config={"displayModeBar": False},
        )

    st.markdown(
        f'<div class="section-eyebrow">{t("sec_properties")}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="color:#64748b;font-size:0.85rem;line-height:1.55;margin:0 0 0.6rem">'
        f"{t('properties_caption')}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(_property_panel(summary), unsafe_allow_html=True)

    st.markdown(
        f'<div class="section-eyebrow">{t("sec_provenance")}</div>',
        unsafe_allow_html=True,
    )
    c_hash, c_dl = st.columns([4, 1])
    with c_hash:
        st.markdown(
            f'<p style="color:#64748b;font-size:0.85rem;line-height:1.55;margin:0 0 0.4rem">'
            f"{t('provenance_caption')}</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="hash-block">{summary.mcap_sha256}</div>',
            unsafe_allow_html=True,
        )
    with c_dl:
        st.download_button(
            t("download_button"),
            data=mcap_bytes,
            file_name="project_ghost_smoke.mcap",
            mime="application/octet-stream",
            use_container_width=True,
        )


def _run_tab() -> None:
    st.markdown(
        f'<p style="color:#475569;font-size:0.95rem;line-height:1.6;margin-bottom:0.5rem">'
        f"{t('run_intro')}</p>",
        unsafe_allow_html=True,
    )

    _pipeline_diagram()

    if "run_result" not in st.session_state:
        st.session_state["run_result"] = None

    st.markdown(
        f'<div class="section-eyebrow">{t("configure_eyebrow")}</div>',
        unsafe_allow_html=True,
    )
    n_cycles = st.slider(
        t("slider_label"),
        min_value=2,
        max_value=50,
        value=10,
        help=t("slider_help"),
    )
    st.markdown(
        f'<p style="color:#64748b;font-size:0.83rem;line-height:1.55;margin:0.4rem 0 1rem">'
        f"{t('run_caption')}</p>",
        unsafe_allow_html=True,
    )

    if st.button(t("run_button"), type="primary", use_container_width=True):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mcap_path = Path(tmp_dir) / "smoke.mcap"
            with st.spinner(t("spinner_run", n=n_cycles)):
                summary = run_closed_loop_smoke(mcap_path, n_cycles=n_cycles)
            mcap_bytes = mcap_path.read_bytes()
        st.session_state["run_result"] = (summary, mcap_bytes)

    result = st.session_state.get("run_result")
    if result is not None:
        st.markdown(
            f'<div class="section-eyebrow">{t("results_eyebrow")}</div>',
            unsafe_allow_html=True,
        )
        _show_run_results(*result)


# ─────────────────────────────────────────────────────────────────────────────
# Inspect tab — section renderers
# ─────────────────────────────────────────────────────────────────────────────


def _show_overview(messages: dict[str, list[tuple[int, Any]]]) -> None:
    rows = [{"Channel": ch, "Messages": len(msgs)} for ch, msgs in sorted(messages.items())]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _show_decisions(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (tns, obj) in enumerate(entries):
        if isinstance(obj, DecisionRationale):
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(tns),
                    "Kind": obj.decision.kind.value,
                    "Policy": obj.policy_id,
                }
            )
    if not rows:
        st.info("No DecisionRationale records.")
        return
    df = pd.DataFrame(rows)
    counts = df["Kind"].value_counts().to_dict()
    _badges(counts, _KIND_COLOR)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.plotly_chart(
            _chart_decision_dist(counts), use_container_width=True, config={"displayModeBar": False}
        )
    with col_b:
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_calibration(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (tns, obj) in enumerate(entries):
        if isinstance(obj, CalibratedSelfAssessment):
            lvl = obj.adjusted_overall_level.value
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(tns),
                    "Adjusted level": lvl,
                    "_num": _LEVEL_NUM.get(lvl, -1),
                }
            )
    if not rows:
        st.info("No CalibratedSelfAssessment records.")
        return
    df = pd.DataFrame(rows)
    rows_typed: list[dict[str, Any]] = rows
    downgrade_cycle = next(
        (r["Cycle"] for r in rows_typed if r["_num"] > 0),
        None,
    )
    if downgrade_cycle:
        st.markdown(
            f'<div class="banner-warn">{t("banner_downgrade", n=downgrade_cycle)}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="banner-ok">{t("banner_held_known")}</div>',
            unsafe_allow_html=True,
        )
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.plotly_chart(
            _chart_calibration(list(df["Adjusted level"])),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_b:
        st.dataframe(df.drop(columns=["_num"]), hide_index=True, use_container_width=True)


def _show_divergence(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (tns, obj) in enumerate(entries):
        if isinstance(obj, PredictionOutcome):
            rows.append(
                {
                    "Outcome": i + 1,
                    "Stamp (ms)": _ms(tns),
                    "Verdict": obj.verdict.value,
                    "Pos Mahalanobis": round(obj.position_mahalanobis_max, 2),
                    "Ori Mahalanobis": round(obj.orientation_mahalanobis_max, 2),
                    "Pos error (m)": round(float(obj.position_error_norm_m), 3),
                }
            )
    if not rows:
        st.info("No PredictionOutcome records.")
        return
    df = pd.DataFrame(rows)
    _badges(df["Verdict"].value_counts().to_dict(), _VERDICT_COLOR)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.plotly_chart(
            _chart_divergence(rows), use_container_width=True, config={"displayModeBar": False}
        )
    with col_b:
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_actuations(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (tns, obj) in enumerate(entries):
        if isinstance(obj, ActuationDirective):
            cmd = obj.actuator_command
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(tns),
                    "Command type": type(cmd).__name__ if cmd is not None else "—",
                    "Reason": obj.reason,
                    "Policy": obj.policy_id,
                }
            )
    if not rows:
        st.info("No ActuationDirective records.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _show_self_assessment(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (tns, obj) in enumerate(entries):
        if isinstance(obj, BeliefSelfAssessment):
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(tns),
                    "Overall": obj.overall_level.value,
                    "Position": obj.position_overall_level.value,
                    "Velocity": obj.velocity_overall_level.value,
                    "Orientation": obj.orientation_overall_level.value,
                    "Cov present": obj.covariance_available,
                }
            )
    if not rows:
        st.info("No BeliefSelfAssessment records.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _show_fusion(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (tns, obj) in enumerate(entries):
        if isinstance(obj, FusionResult):
            pos = obj.belief.nav.pose.position_enu_m
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(tns),
                    "Policy": obj.fusion_policy_id,
                    "x (m)": round(float(pos[0]), 4),
                    "y (m)": round(float(pos[1]), 4),
                    "z (m)": round(float(pos[2]), 4),
                }
            )
    if not rows:
        st.info("No FusionResult records.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.markdown(
            f'<p style="color:#64748b;font-size:0.82rem;line-height:1.55;margin:0 0 0.3rem">'
            f"{t('fus_belief_caption')}</p>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _chart_fusion_x(df), use_container_width=True, config={"displayModeBar": False}
        )
    with col_b:
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_replay_verification(file_bytes: bytes) -> None:
    st.markdown(
        f'<p style="color:#475569;font-size:0.9rem;line-height:1.6;margin-bottom:0.6rem">'
        f"{t('replay_intro')}</p>",
        unsafe_allow_html=True,
    )
    if not st.button(t("replay_button"), key="replay_btn"):
        return

    from project_ghost.examples.replay_verification import replay_downstream_from_fusion

    with (
        tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as src_f,
        tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as rpl_f,
    ):
        src_f.write(file_bytes)
        src_path, rpl_path = Path(src_f.name), Path(rpl_f.name)

    try:
        with st.spinner(t("replay_spinner")):
            vsummary = replay_downstream_from_fusion(src_path, rpl_path)
    finally:
        src_path.unlink(missing_ok=True)
        rpl_path.unlink(missing_ok=True)

    if vsummary.all_channels_byte_equal:
        st.markdown(f'<div class="banner-ok">{t("replay_ok")}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="banner-warn">{t("replay_warn")}</div>', unsafe_allow_html=True)

    rows = [
        {
            t("replay_col_channel"): cv.channel,
            t("replay_col_orig"): cv.source_count,
            t("replay_col_rep"): cv.replay_count,
            t("replay_col_result"): (
                t("replay_byte_equal") if cv.byte_equal else t("replay_differs")
            ),
        }
        for cv in vsummary.channels
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Inspect tab
# ─────────────────────────────────────────────────────────────────────────────


def _inspect_sections() -> list[tuple[str, str, str, str]]:
    return [
        (CHANNEL_DECISIONS, "🎯", t("ins_dec_title"), t("ins_dec_desc")),
        (CHANNEL_CALIBRATED_SELF_ASSESSMENT, "⚖️", t("ins_cal_title"), t("ins_cal_desc")),
        (CHANNEL_PREDICTION_OUTCOMES, "📊", t("ins_div_title"), t("ins_div_desc")),
        (CHANNEL_ACTUATIONS, "⚙️", t("ins_act_title"), t("ins_act_desc")),
        (CHANNEL_SELF_ASSESSMENT, "🧠", t("ins_self_title"), t("ins_self_desc")),
        (CHANNEL_FUSION_RESULTS, "🔭", t("ins_fus_title"), t("ins_fus_desc")),
    ]


_SECTION_FN = {
    CHANNEL_DECISIONS: _show_decisions,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT: _show_calibration,
    CHANNEL_PREDICTION_OUTCOMES: _show_divergence,
    CHANNEL_ACTUATIONS: _show_actuations,
    CHANNEL_SELF_ASSESSMENT: _show_self_assessment,
    CHANNEL_FUSION_RESULTS: _show_fusion,
}


def _inspect_tab() -> None:
    st.markdown(
        f"""
<div class="upload-hint">
  <div class="uh-icon">📂</div>
  <div class="uh-title">{t("upload_title")}</div>
  <div class="uh-body">{t("upload_body")}</div>
</div>""",
        unsafe_allow_html=True,
    )

    uploaded = st.file_uploader(
        t("upload_label"),
        type=["mcap"],
        help=t("upload_help"),
        label_visibility="collapsed",
    )
    if uploaded is None:
        return

    file_bytes = uploaded.read()
    with st.spinner(t("decoding_spinner")):
        messages = _decode_mcap(file_bytes)

    if not messages:
        st.error(t("no_messages_error"))
        return

    total = sum(len(v) for v in messages.values())
    st.markdown(
        f'<p style="color:#475569;font-size:0.9rem;margin:0.8rem 0 0.4rem">'
        f"{t('loaded_msg', n_channels=len(messages), n_msgs=total)}</p>",
        unsafe_allow_html=True,
    )

    with st.expander(t("channel_overview_label"), expanded=False):
        _show_overview(messages)

    for channel, icon, title_, description in _inspect_sections():
        if channel not in messages:
            continue
        with st.expander(f"{icon}  {title_}", expanded=True):
            st.markdown(
                f'<p style="font-size:0.83rem;color:#64748b;margin:0 0 0.7rem;'
                f'line-height:1.55">{description}</p>',
                unsafe_allow_html=True,
            )
            _SECTION_FN[channel](messages[channel])

    if CHANNEL_FUSION_RESULTS in messages:
        with st.expander(t("replay_label"), expanded=False):
            _show_replay_verification(file_bytes)


# ─────────────────────────────────────────────────────────────────────────────
# Page layout
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Project Ghost",
    page_icon="◉",
    layout="wide",
    menu_items={"About": "Project Ghost — autonomy under uncertainty · Apache 2.0"},
)

st.markdown(_CSS, unsafe_allow_html=True)

_language_picker()

_hero()

_tab_run, _tab_inspect = st.tabs([t("tab_run"), t("tab_inspect")])

with _tab_run:
    _run_tab()

with _tab_inspect:
    _inspect_tab()
