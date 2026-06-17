"""Project Ghost — professional Streamlit dashboard with EN/ES i18n."""

from __future__ import annotations

import hashlib
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
Project Ghost makes **seven concrete, citable contributions** on top of
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
  abstract model (ADR-0036) and **fully discharged in Lean 4 with
  no `sorry`** (ADR-0042).
- **PV-3 — Structural recovery latency bound.**
  `L ≤ peak + W − 1` for sliding-window calibration histories with
  `MahalanobisDowngradePolicy(M, K)`. Drift-then-recovery smoke
  fires at the bound exactly (38 = 7 + 32 − 1), proving the bound
  is tight (RLB-v1, ADR-0034). v0.2.5 mechanises it via a
  parametric TLC sweep at `W ∈ {4, 8, 16}` and a Lean 4 proof of
  9 lemmas + Theorem 1 statement (only 1 `sorry` left,
  ADR-0038/ADR-0042).
- **PV-4 — The EpistemicSafetyContract framework.**
  The property class is formalised in v0.2.5 as a Python `Protocol`
  plus a registry of the seven shipped contracts (BAUD-v1, ERUR-v1/v2,
  MD-v1, RLB-v1, FPB-v1/v2). Adding the eighth contract is one
  `register_contract(...)` call away; eight framework-level
  invariants are pinned in tests (ADR-0045).
- **PV-5 — End-to-end safety citation pattern.**
  Content-addressed MCAP + ADR + pure-function verifier + Hypothesis
  property test + CI gate + tagged release + OIDC-signed PyPI wheel
  — assembled as one coherent reproducibility unit. The headline
  claim is operationally re-runnable from `pip install project-ghost==0.2.5`.
- **PV-6 — Real-telemetry discrimination experiment.**
  The 3-ULog × 6-category matrix on PX4 SITL flight logs yields
  **18/18 detection** with independent SITL GT auto-detection
  (ADR-0037); 15/18 cells isolate the violation to the expected
  property (§8.8.2).
- **PV-7 — Mechanically-checked Python ↔ TLA+ bridge (ADR-0043).**
  The previous "by inspection" caveat is closed in v0.2.5 by a
  Hypothesis-checked conformance test asserting the verifier core
  and the TLA+ state machine agree on `INV_RLB` for every
  Hypothesis-synthesised trace.

For each, the binding ADR is the formal statement, the verifier is
the executable test, the inline witness in `SmokeSummary.*_report`
and `matrix.json` is the self-evidence, and CI is the continuous
guarantee.

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
        "tab_paper": "Read the paper",
        # Paper tab
        "paper_eyebrow": "Technical paper",
        "paper_h1": (
            "Epistemic Safety Contracts as a Property Class for "
            "Autonomous Agents: A Formalised Framework with Mechanical "
            "Proofs and a Real-Telemetry Discrimination Experiment"
        ),
        "paper_lang_label": "Paper language",
        "paper_intro": (
            "The full technical paper — abstract, contributions, proof of "
            "the recovery latency bound, evaluation, and references — available in three "
            "languages. The English version is canonical for arXiv and "
            "TOSEM submission; the Spanish and Chinese versions are "
            "internal translations for collaborators."
        ),
        "paper_view_github": "View on GitHub",
        "paper_download_md": "Download Markdown",
        "paper_loading_error": "Could not load the paper file. The paper is also available at: ",
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
        "sec_properties": "Safety properties (v0.2.5: 7 shipped contracts)",
        "properties_caption": (
            "Seven formal properties verified inline against the captured "
            "MCAP, registered in the EpistemicSafetyContract framework "
            "(ADR-0045). Each verdict is byte-exact reproducible; the same "
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
Project Ghost aporta **siete contribuciones concretas y citables**
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
  alcanzable completo del modelo abstracto (ADR-0036) y
  **totalmente discharged en Lean 4 sin `sorry`** (ADR-0042).
- **PV-3 — Cota estructural de latencia de recuperación.**
  `L ≤ peak + W − 1` para historiales de calibración con ventana
  deslizante usando `MahalanobisDowngradePolicy(M, K)`. El smoke
  drift-then-recovery dispara exactamente en la cota
  (38 = 7 + 32 − 1), demostrando que la cota es ajustada (RLB-v1,
  ADR-0034). v0.2.5 lo mecaniza vía un TLC sweep paramétrico a
  `W ∈ {4, 8, 16}` y una prueba Lean 4 de 9 lemmas + Theorem 1
  statement (solo queda 1 `sorry`, ADR-0038/ADR-0042).
- **PV-4 — El framework EpistemicSafetyContract.**
  La clase de propiedades formalizada en v0.2.5 como Python
  `Protocol` más un registry de los siete contratos shipped
  (BAUD-v1, ERUR-v1/v2, MD-v1, RLB-v1, FPB-v1/v2). Añadir el
  octavo contrato es un solo `register_contract(...)`;
  8 invariantes framework-level pineadas en tests (ADR-0045).
- **PV-5 — Patrón de citación end-to-end para safety.**
  MCAP content-addressed + ADR + verificador función pura + test
  de propiedades Hypothesis + gate de CI + release etiquetado +
  wheel firmado por OIDC en PyPI — ensamblados como una sola
  unidad coherente de reproducibilidad. La afirmación principal es
  re-ejecutable operacionalmente desde
  `pip install project-ghost==0.2.5`.
- **PV-6 — Experimento de discriminación sobre telemetría real.**
  La matriz 3-ULog × 6 categorías sobre flight logs PX4 SITL da
  **18/18 detección** con auto-detección de SITL GT independiente
  (ADR-0037); 15/18 celdas aíslan la violación a la propiedad
  esperada (§8.8.2).
- **PV-7 — Bridge mecánico Python ↔ TLA+ (ADR-0043).**
  El caveat anterior "por inspección" queda cerrado en v0.2.5
  mediante un conformance test Hypothesis-checked que asserta
  que el verifier core y la TLA+ state machine coinciden en
  `INV_RLB` para cada trace sintetizado.

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
        "tab_paper": "Leer el paper",
        # Paper tab
        "paper_eyebrow": "Paper técnico",
        "paper_h1": (
            "Epistemic Safety Contracts como clase de propiedades para "
            "agentes autónomos: marco formalizado con pruebas mecánicas "
            "y experimento de discriminación sobre telemetría real"
        ),
        "paper_lang_label": "Idioma del paper",
        "paper_intro": (
            "El paper técnico completo — abstract, contribuciones, prueba "
            "de la cota de latencia de recuperación, evaluación y referencias — disponible en tres "
            "idiomas. La versión inglesa es la canónica para arXiv y para "
            "la submission a TOSEM; las versiones española y china son "
            "traducciones internas para colaboradores."
        ),
        "paper_view_github": "Ver en GitHub",
        "paper_download_md": "Descargar Markdown",
        "paper_loading_error": (
            "No se pudo cargar el archivo del paper. El paper también está disponible en: "
        ),
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
        "sec_properties": "Propiedades formales de safety (v0.2.5: 7 contratos shipped)",
        "properties_caption": (
            "Siete propiedades formales verificadas inline sobre el MCAP "
            "capturado, registradas en el framework EpistemicSafetyContract "
            "(ADR-0045). Cada veredicto es byte-exacto reproducible; el "
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
    "zh": {
        "lang_label": "语言",
        "hero_eyebrow": "研究平台 · 不确定性下的自主性",
        "hero_h1": "Project Ghost",
        "hero_tagline": (
            "想象一辆自动驾驶汽车，其内部地图已经偏离现实十米。它仍然<em>"
            "认为</em>自己认识这条路 —— 并继续前进。Project Ghost 是一个"
            "供自主系统使用的参考平台，<strong>能在自己的模型已经漂移时"
            "察觉</strong>，并在造成伤害之前停下来。"
        ),
        "c1_num": "01 · 问题",
        "c1_title": "机器人在沉默中失败",
        "c1_body": (
            "自主系统携带着对其位置和正在发生的事情的内部图景。当那幅"
            "图景与现实不再一致时 —— 传感器退化、突然的阵风袭来、世界"
            "本身在变化 —— 大多数系统<strong>仍然像没事一样行动</strong>。"
            "没有警告。没有安全停车。麻烦的第一个迹象通常就是事故本身。"
        ),
        "c2_num": "02 · 方法",
        "c2_title": "机器人观察自己",
        "c2_body": (
            "在每一次行动之后，Ghost 问一个问题：<em>我对了吗？</em>它"
            "比较预期与实际发生的情况。一次猜错是噪声。连续几次就是信号 —— "
            "模型正在漂移。Ghost 自动地把自己的信心从 <strong>"
            "“我知道”</strong> 降到 <strong>“我不确定”</strong>。"
        ),
        "c3_num": "03 · 结果",
        "c3_title": "诚实的机器人会停下来",
        "c3_body": (
            "当信心下降时，Ghost 停止发出 <strong>proceed</strong>，"
            "开始发出 <strong>hold</strong>。车辆暂停而不是在过时的信念"
            "上行动。这不是完美的自主性 —— 这是更安全的自主性。每个决定"
            "都可以从加密日志中按字节重放，因此可以重建之后发生了什么。"
        ),
        "about_label": "关于这项工作 —— 贡献是什么？",
        "about_body": """
Project Ghost 在不确定性下的机器人自主性的现有文献上贡献了
**七项具体且可引用的成果**。基础组件（贝叶斯滤波、校准、FDI、
运行时监督器）已经很成熟；贡献在于**如何把它们组合、形式化陈述
并机械化验证**。

- **PV-1 —— 可重现性原语。**
  `ghost verify-properties --mcap <log>` 把"这次运行安全吗？"
  简化为一条 shell 命令，返回字节精确的判定，退出码 `0` 当且仅当
  所有契约都满足。验证器是基于内容寻址 MCAP 的纯函数 —— 没有重放，
  没有模拟，不依赖于生产者。
- **PV-2 —— 形式化分区定理。**
  BAUD-v1 + ERUR-v1 按周期划分行为空间。在 TLA+ 中表述为
  `INV_PARTITION`，**通过 TLC 机械验证**于抽象模型的完整可达
  状态空间（ADR-0036），并在 **Lean 4 中完全证明，无 `sorry`**
  （ADR-0042）。
- **PV-3 —— 结构化恢复延迟界限。**
  对于使用 `MahalanobisDowngradePolicy(M, K)` 的滑动窗口校准
  历史：`L ≤ peak + W − 1`。drift-then-recovery 烟雾测试精确
  触发界限（38 = 7 + 32 − 1），证明界限紧致（RLB-v1，ADR-0034）。
  v0.2.5 通过 TLC 参数化扫描在 `W ∈ {4, 8, 16}` 验证机械化，
  并在 Lean 4 中证明（9 个引理 + Theorem 1 statement；
  仅剩 1 个 `sorry`，ADR-0038/ADR-0042）。
- **PV-4 —— EpistemicSafetyContract 框架。**
  v0.2.5 中将属性类形式化为 Python `Protocol`，加上 7 个 shipped
  契约的 registry（BAUD-v1、ERUR-v1/v2、MD-v1、RLB-v1、FPB-v1/v2）。
  添加第 8 个契约只需要一次 `register_contract(...)`；测试中固定
  了 8 个 framework 级别的不变量（ADR-0045）。
- **PV-5 —— 端到端 safety 引用模式。**
  内容寻址 MCAP + ADR + 纯函数验证器 + Hypothesis 属性测试 +
  CI gate + 带标签的 release + 在 PyPI 上 OIDC 签名的 wheel ——
  作为单一连贯的可重现性单元组装。主要主张可从
  `pip install project-ghost==0.2.5` 操作性地重新执行。
- **PV-6 —— 真实遥测的区分实验。**
  在 PX4 SITL 飞行日志的 3-ULog × 6 类别矩阵上，启用自动检测的
  独立 SITL GT（ADR-0037），生成 18/18 检测；15/18 隔离违规
  到预期属性（§8.8.2）。
- **PV-7 —— 机械化 Python ↔ TLA+ 桥（ADR-0043）。**
  之前的"by inspection"caveat 在 v0.2.5 由 Hypothesis-checked
  合规测试关闭，对每个生成的 trace assert verifier core 和 TLA+
  state machine 一致。

每一项：约束 ADR 是形式陈述，verifier 是可执行测试，`SmokeSummary`
和 `matrix.json` 中的内联见证是自我证据，CI 是持续保证。

理论新颖性？没有 —— 这是工程和引用模式贡献，不是新定理。
**操作新颖性？有** —— 这是实际构建和发布的模式，使第三方能够
验证他们自己对捕获的 MCAP 的运行，而无需信任生产者。
""",
        "pipeline_eyebrow": "8 步闭环",
        "phase_perception": "感知",
        "phase_action": "行动",
        "phase_learning": "学习",
        "step_fusion_name": "融合",
        "step_fusion_desc": "传感器 → belief",
        "step_assess_name": "自评估",
        "step_assess_desc": "原始信心",
        "step_calib_name": "校准",
        "step_calib_desc": "按过去错误调整",
        "step_dec_name": "决策",
        "step_dec_desc": "Proceed · Hold · Abort",
        "step_act_name": "执行",
        "step_act_desc": "向车辆发出命令",
        "step_pred_name": "预测",
        "step_pred_desc": "预期状态",
        "step_out_name": "Outcome",
        "step_out_desc": "Mahalanobis 判定",
        "step_fb_name": "反馈",
        "step_fb_desc": "更新信心模型",
        "pipeline_caption": (
            "<strong>反馈</strong>箭头（Outcome → 校准）闭合循环。"
            "当预测持续错误时，信心等级自动下降，阻止 PROCEED 决策直到"
            "模型恢复。没有它，代理会在过时的信念上沉默地行动。"
        ),
        "tab_run": "尝试模拟",
        "tab_inspect": "检查运行",
        "tab_paper": "阅读论文",
        "paper_eyebrow": "技术论文",
        "paper_h1": (
            "自主代理的 Epistemic Safety Contracts 作为属性类："
            "带有机械证明和真实遥测区分实验的形式化框架"
        ),
        "paper_lang_label": "论文语言",
        "paper_intro": (
            "完整的技术论文 —— 摘要、贡献、恢复延迟界限的证明、评估和"
            "参考文献 —— 有三种语言版本。英文版是 arXiv 的规范版本，"
            "也是 TOSEM 提交的版本；西班牙文和中文版本是供合作者使用的"
            "内部翻译。"
        ),
        "paper_view_github": "在 GitHub 上查看",
        "paper_download_md": "下载 Markdown",
        "paper_loading_error": (
            "无法加载论文文件。论文也可在以下位置获取： "
        ),
        "run_intro": (
            "每次点击<strong>运行</strong>都会在浏览器中执行完整的 8 步"
            "管道：融合预言机 → 自评估 → 校准反馈 → 决策 → 执行 → 预测 → "
            "差异评估。结果捕获在可下载的 MCAP 文件中，你可以在下面检查。"
        ),
        "configure_eyebrow": "配置运行",
        "slider_label": "周期数",
        "slider_help": (
            "一个周期 = 8 个步骤的一次完整传递。少于 5 个不会触发校准"
            "下调 —— 使用 10 个或更多来观察反馈循环的实际运行。"
        ),
        "run_caption": (
            "模拟使用故意的过度自信陷阱：预言机认为车辆静止不动，而背景"
            "真实情况以 5 m/s 漂移。校准反馈循环是唯一能检测它的机制。"
        ),
        "run_button": "运行模拟",
        "spinner_run": "运行 {n} 个周期的闭环……",
        "results_eyebrow": "结果",
        "stat_cycles": "周期",
        "stat_decisions": "决策",
        "stat_outcomes": "Outcomes",
        "stat_quality": "预测质量",
        "sec_decisions": "决策",
        "sec_calibration": "随时间变化的校准",
        "sec_provenance": "出处",
        "sec_properties": "形式化 safety 属性（v0.2.5 的 7 个契约）",
        "properties_caption": (
            "在捕获的 MCAP 上内联验证了七个形式化属性。每个判定都是字节"
            "精确可重现的；从 shell 运行相同的 "
            "<code>ghost verify-properties --mcap &lt;path&gt;</code> "
            "产生相同的输出。"
        ),
        "verdict_holds": "HOLDS",
        "verdict_violated": "VIOLATED",
        "banner_downgrade": (
            "<strong>在周期 {n} 信心被降级</strong> —— 预测错误超过了阈值"
        ),
        "banner_held": (
            "<strong>信心保持</strong> —— 模型在整个运行中保持准确"
        ),
        "banner_held_known": (
            "<strong>信心整个过程中保持 KNOWN</strong>"
        ),
        "provenance_caption": (
            "此 MCAP 的 SHA-256 内容地址。相同的输入产生相同的哈希。"
            "用它来证明这次确切的运行未被篡改。"
        ),
        "download_button": "下载 MCAP",
        "upload_title": "上传 MCAP 遥测文件",
        "upload_body": (
            "在<strong>尝试模拟</strong>标签中运行模拟，下载 MCAP，然后"
            "在此处加载它以探索管道的每一层。"
        ),
        "upload_label": "选择 MCAP 文件",
        "upload_help": (
            "由 ghost-app、ghost CLI 或 run_closed_loop_smoke() 生成的文件。"
        ),
        "decoding_spinner": "解码 MCAP……",
        "no_messages_error": (
            "未找到可解码消息。这是有效的 Project Ghost MCAP 吗？"
        ),
        "loaded_msg": (
            "已加载 <strong>{n_channels} 个通道</strong> · <strong>{n_msgs} 条消息</strong>"
        ),
        "channel_overview_label": "通道概览",
        "ins_dec_title": "决策",
        "ins_dec_desc": (
            "每个周期，代理根据其校准信心选择一个动作。PROCEED = 足够"
            "信心继续。HOLD = 检测到不确定性，代理停下来重新评估。"
        ),
        "ins_cal_title": "校准",
        "ins_cal_desc": (
            "由反馈循环调整的原始信心。当过去的预测持续错误时，等级"
            "从 KNOWN 降到 UNCERTAIN，阻止更多 PROCEED 决策直到模型恢复。"
        ),
        "ins_div_title": "差异 outcomes",
        "ins_div_desc": (
            "每个周期的预测与真实情况比较。Mahalanobis 距离是预测离"
            "实际有多少个标准惊讶。高于 5-sigma 的值表示严重错误的模型。"
        ),
        "ins_act_title": "执行",
        "ins_act_desc": (
            "每个周期发出的物理命令。AttitudeCommand 保持姿态和推力。"
            "DirectMotorCommand 直接控制电机（紧急情况）。None 表示"
            "策略抑制了命令。"
        ),
        "ins_self_title": "原始自评估",
        "ins_self_desc": (
            "在校准循环之前未过滤的信心估计。将其与校准等级比较以查看"
            "循环改变了什么。"
        ),
        "ins_fus_title": "融合结果",
        "ins_fus_desc": (
            "来自融合层的代理对其当前状态的信念。在此模拟中，预言机"
            "总是报告位置 ≈ 0 m，而背景真相在漂移。那个间隙就是触发"
            "差异的原因。"
        ),
        "fus_belief_caption": (
            "预言机总是报告 x ≈ 0 m —— 背景真相以 5 m/s 漂移。那个"
            "间隙触发 Mahalanobis 差异。"
        ),
        "replay_label": "重放验证",
        "replay_intro": (
            "从存储的 <code>/fusion/results</code> 通道重新执行下游管道，"
            "并将每个输出消息按字节与原始消息比较。匹配证明管道没有"
            "隐藏的非确定性。"
        ),
        "replay_button": "运行字节精确验证",
        "replay_spinner": "重新执行下游管道……",
        "replay_ok": (
            "<strong>字节完美重放</strong> —— 原始运行与重放之间 6 个"
            "下游通道相同"
        ),
        "replay_warn": (
            "<strong>检测到差异</strong> —— 至少一个通道不同，表明"
            "管道中可能有非确定性"
        ),
        "replay_col_channel": "通道",
        "replay_col_orig": "原始消息",
        "replay_col_rep": "重放消息",
        "replay_col_result": "结果",
        "replay_byte_equal": "字节相等",
        "replay_differs": "不同",
        "narr_cycles": "代理运行了 <strong>{n} 个完整周期</strong>。",
        "narr_downgrade": (
            "周期 1–{prev}：完全信心（<em>known</em>），决策每次都是 "
            "<strong>PROCEED</strong>。在周期 <strong>{cyc}</strong>，"
            "累积的预测错误超过校准阈值 —— 信心降到 <em>uncertain</em>，"
            "将所有后续决策切换为 <strong>HOLD</strong>。"
        ),
        "narr_uncertain_start": (
            "代理从周期 1 开始就<em>uncertain</em>并始终保持 HOLD —— "
            "模型从未足够可靠到可以行动。"
        ),
        "narr_held": (
            "信心在每个周期都保持<em>known</em> —— 代理在整个运行中都"
            "选择了 <strong>PROCEED</strong>。"
        ),
        "narr_outro": (
            "预测质量：{verdict_human}。模拟故意陷入过度自信的代理："
            "预言机报告车辆静止，而背景真相以 5 m/s 漂移。校准循环是"
            "唯一能检测它的机制。"
        ),
        "verdict_5": (
            "持续<strong>非常远</strong>（&gt;5-sigma）—— 模型严重失败"
        ),
        "verdict_3": "显著远（&gt;3-sigma）—— 模型不可靠",
        "verdict_1": "适度远（&gt;1-sigma）—— 检测到轻微漂移",
        "verdict_in": "精确（1-sigma 内）—— 模型保持住了",
        "chart_dec_dist": "决策分布",
        "chart_calib_title": "每周期信心等级",
        "chart_div_title": "Mahalanobis 距离（位置）",
        "chart_fusion_title": "x 上的信念（预言机 vs. 真实漂移）",
        "axis_cycle": "周期",
        "axis_outcome": "Outcome",
        "axis_stddevs": "标准差",
        "label_downgrade_at": "在周期 {n} 降级",
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
.property-card.neutral { border-left-color: #94a3b8; }
.property-card.neutral .pc-verdict { color: #94a3b8; }
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


def _sha256_prefix(data: bytes, n: int = 12) -> str:
    """Short hex prefix of the SHA-256 of ``data`` (default 12 chars).

    Used by the inspect tab's stat block to surface the uploaded
    MCAP's content-address without printing the full 64-char hash."""
    return hashlib.sha256(data).hexdigest()[:n]


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
    # NOTE: use dict-literal `{...}` (not `dict(**kw)`) so callers can
    # override the defaults (tickfont, title_font, etc.). With `dict()`,
    # passing tickfont in **kw raises TypeError: multiple values for
    # keyword argument 'tickfont'.
    return {
        "color": _INK_MUTED,
        "gridcolor": _GRID,
        "zerolinecolor": _BORDER,
        "linecolor": _BORDER,
        "tickfont": {"size": 11, "color": _INK_MUTED},
        "title_font": {"size": 11, "color": _INK_SOFT},
        **kw,
    }


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


_LANG_CHOICES: tuple[str, ...] = ("EN", "ES", "中文")
_LANG_CODE_OF: dict[str, str] = {"EN": "en", "ES": "es", "中文": "zh"}
_LANG_LABEL_OF: dict[str, str] = {"en": "EN", "es": "ES", "zh": "中文"}


def _language_picker() -> None:
    if "lang" not in st.session_state:
        st.session_state["lang"] = "en"

    _, col = st.columns([8, 2])
    with col:
        current = _LANG_LABEL_OF.get(st.session_state["lang"], "EN")
        current_idx = _LANG_CHOICES.index(current)
        choice = st.radio(
            t("lang_label"),
            list(_LANG_CHOICES),
            horizontal=True,
            label_visibility="collapsed",
            index=current_idx,
            key="_lang_radio",
        )
        new_lang = _LANG_CODE_OF[choice]
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


_GH_BASE = "https://github.com/JFHelvetius/ghost/blob/main/"
# Per-property "binding artefact" URL: the ADR if there is one,
# else the source module that documents the property inline. Every
# entry below is verified to resolve at the v0.2.5 tag; if a future
# round adds a missing ADR the URL flips painlessly.
_PROPERTY_DOCS: dict[str, str] = {
    "BAUD-v1": _GH_BASE + "docs/adr/0031-bounded-action-under-drift-property-v1.md",
    "ERUR-v1": _GH_BASE + "docs/adr/0032-eventual-reactivation-under-recovery-property-v1.md",
    # ERUR-v2 has no dedicated ADR file (it was accepted via the v0.2.4
    # paper §10 entry and lives inline in the source). Link to the
    # module that defines and documents it.
    "ERUR-v2": _GH_BASE + "src/project_ghost/properties/erur_v2.py",
    "MD-v1": _GH_BASE + "docs/adr/0033-monotonic-degradation-property-v1.md",
    "RLB-v1": _GH_BASE + "docs/adr/0034-recovery-latency-bound-property-v1.md",
    "FPB-v1": _GH_BASE + "docs/adr/0035-false-positive-bound-property-v1.md",
    "FPB-v2": _GH_BASE + "docs/adr/0039-false-positive-bound-property-v2.md",
}


def _verify_v2_extensions(
    mcap_bytes: bytes,
) -> tuple[Any | None, Any | None]:
    """Compute ERUR-v2 and FPB-v2 verdicts on the same MCAP the v1
    verifiers ran against. Returns (erur_v2_report, fpb_v2_report);
    either may be None if its verifier raises.

    Both verifiers are tolerant of the smoke MCAP: ERUR-v2 needs a
    ``drift_predicates`` mapping (we register the reference Mahalanobis
    policy under the smoke's policy_id), FPB-v2 ships closed-form
    Hoeffding by default and needs no extra params.

    Any exception from the v2 verifiers is swallowed and rendered as
    a `--` card downstream so a transient v2 issue cannot break the
    main 5-card v1 panel.
    """
    from project_ghost.core.feedback import MahalanobisDowngradePolicy
    from project_ghost.properties.erur_v2 import verify_erur_v2
    from project_ghost.properties.fpb_v2 import (
        ConfidenceMethod,
        verify_fpb_v2,
    )

    with tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as tmp:
        tmp.write(mcap_bytes)
        tmp_path = Path(tmp.name)

    ref_policy = MahalanobisDowngradePolicy(
        min_outcomes=4, downgrade_threshold=2,
    )
    # The smoke writes its actual policy_id into the MCAP; we register
    # the predicate under the real id (not a hardcoded guess). If the
    # smoke ever uses different M/K parameters, this still works
    # because policy_id encodes them.
    drift_predicates = {
        ref_policy.policy_id: ref_policy.drift_precondition,
    }

    erur_v2 = None
    fpb_v2 = None
    try:
        erur_v2 = verify_erur_v2(tmp_path, drift_predicates=drift_predicates)
    except Exception:
        erur_v2 = None
    try:
        fpb_v2 = verify_fpb_v2(
            tmp_path,
            max_fire_probability=1.0,
            confidence_level=0.95,
            method=ConfidenceMethod.HOEFFDING,
        )
    except Exception:
        fpb_v2 = None
    return erur_v2, fpb_v2


def _property_panel(summary: SmokeSummary, mcap_bytes: bytes | None = None) -> str:
    """Render the 7-property panel as an HTML grid for ``_show_run_results``.

    Each card carries the property tag (BAUD-v1, ERUR-v1, ...), the
    HOLDS / VIOLATED veredicto with colour-coded border, a compact
    per-property stat block, and a link to the binding ADR on GitHub.

    The 5 v1 contracts (BAUD/ERUR/MD/RLB/FPB) ship inline in the
    ``SmokeSummary``. The 2 v2 extensions (ERUR-v2, FPB-v2) are
    computed in-line from ``mcap_bytes`` (see ``_verify_v2_extensions``).
    If ``mcap_bytes`` is None or the v2 verifiers raise, the v2
    cards render as `--` so the panel keeps the 7-contract shape
    promised by paper §3.
    """
    # Compute v2 extensions on the same MCAP, defensive against any
    # verifier raising.
    erur_v2_report = None
    fpb_v2_report = None
    if mcap_bytes is not None:
        erur_v2_report, fpb_v2_report = _verify_v2_extensions(mcap_bytes)

    erur_v2_stat = (
        f"{erur_v2_report.cycles_precondition_held}/"
        f"{erur_v2_report.cycles_total} cycles · drift=mahalanobis"
        if erur_v2_report is not None
        else "policy-parametric · see ADR-0040"
    )
    fpb_v2_stat = (
        f"p_hat={fpb_v2_report.fire_fraction:.2f} · "
        f"ub={fpb_v2_report.confidence_upper_bound:.2f} · "
        f"95% Hoeffding"
        if fpb_v2_report is not None
        else "statistical · see ADR-0039"
    )

    rows: list[tuple[str, Any, str]] = [
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
        ("ERUR-v2", erur_v2_report, erur_v2_stat),
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
        ("FPB-v2", fpb_v2_report, fpb_v2_stat),
    ]

    cards: list[str] = []
    for tag, report, stat in rows:
        if report is None:
            # v2 verifier raised or no MCAP available: render neutral card.
            klass = "neutral"
            verdict = "—"
        else:
            klass = "holds" if report.holds else "violated"
            verdict = t("verdict_holds") if report.holds else t("verdict_violated")
        doc_url = _PROPERTY_DOCS.get(tag)
        name_html = (
            f'<a href="{doc_url}" target="_blank" rel="noopener" '
            f'style="text-decoration:none;color:inherit" '
            f'title="View binding artefact on GitHub">{tag} ↗</a>'
            if doc_url
            else tag
        )
        cards.append(
            f'<div class="property-card {klass}">'
            f'<div class="pc-name">{name_html}</div>'
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
    st.markdown(_property_panel(summary, mcap_bytes), unsafe_allow_html=True)

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

    # IMPORTANT: the file_uploader uses a STABLE label that does not change
    # with the UI language. In some Streamlit versions, changing a widget's
    # label between reruns invalidates the widget's internal state and the
    # uploaded file is silently lost. We dodge that by hardcoding a neutral
    # ASCII label and hiding it via label_visibility="collapsed"; the human
    # text comes from the `upload-hint` block above (which DOES translate).
    uploaded = st.file_uploader(
        "MCAP file",
        type=["mcap"],
        help=t("upload_help"),
        label_visibility="collapsed",
        key="inspect_uploader",
    )

    # Cache the upload contents in session_state so that a re-render
    # triggered by the language picker (or any st.rerun) does not lose
    # the loaded MCAP. Snapshot bytes once per file_id; subsequent reruns
    # re-use the cached payload.
    if uploaded is not None:
        cached_id = st.session_state.get("inspect_mcap_id")
        if cached_id != uploaded.file_id:
            # Use getvalue() rather than read(): it returns the bytes
            # without consuming the buffer, so subsequent reruns can
            # still query .name / .size on the same UploadedFile.
            try:
                data = uploaded.getvalue()
            except AttributeError:
                # Fallback for very old Streamlit versions (< 1.10).
                data = uploaded.read()
            st.session_state["inspect_mcap_id"] = uploaded.file_id
            st.session_state["inspect_mcap_name"] = uploaded.name
            st.session_state["inspect_mcap_bytes"] = data

    file_bytes = st.session_state.get("inspect_mcap_bytes")
    if file_bytes is None or len(file_bytes) == 0:
        return

    # Re-affirm to the user which file is loaded after a rerun. This is
    # informational only -- helps the user notice that a language switch
    # has preserved their loaded MCAP rather than silently swallowed it.
    cached_name = st.session_state.get("inspect_mcap_name", "<unnamed>")
    st.markdown(
        f'<p style="color:#94a3b8;font-size:0.78rem;margin:0.5rem 0 0;'
        f'font-family:ui-monospace,Consolas,monospace">'
        f'📎 {cached_name} · {len(file_bytes) / 1024:.1f} KB</p>',
        unsafe_allow_html=True,
    )

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

    # Stat block: surface the per-channel cycle counts of the uploaded
    # MCAP so the user can see "how many cycles does this file have?"
    # without having to expand each channel section.
    n_fusion = len(messages.get(CHANNEL_FUSION_RESULTS, []))
    n_decisions = len(messages.get(CHANNEL_DECISIONS, []))
    n_outcomes = len(messages.get(CHANNEL_PREDICTION_OUTCOMES, []))
    mcap_sha_prefix = _sha256_prefix(file_bytes)
    st.markdown(
        f"""
<div class="stats-grid">
  <div class="stat-card">
    <div class="sc-lab">{t("stat_cycles")}</div>
    <div class="sc-val">{n_fusion}</div>
  </div>
  <div class="stat-card">
    <div class="sc-lab">{t("stat_decisions")}</div>
    <div class="sc-val">{n_decisions}</div>
  </div>
  <div class="stat-card">
    <div class="sc-lab">{t("stat_outcomes")}</div>
    <div class="sc-val">{n_outcomes}</div>
  </div>
  <div class="stat-card">
    <div class="sc-lab">SHA-256</div>
    <div class="sc-val small" style="font-family:ui-monospace,Consolas,monospace;font-size:0.85rem">
      {mcap_sha_prefix}…
    </div>
  </div>
</div>""",
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
# Paper tab — typography-first markdown render in three languages
# ─────────────────────────────────────────────────────────────────────────────


_PAPER_FILES: dict[str, tuple[str, str]] = {
    # (display label, repo-relative path)
    "EN": ("English (canonical)", "docs/paper/project_ghost_v0_2.md"),
    "ES": ("Español (interno)", "docs/paper/es/proyecto_ghost_v0_2_ES.md"),
    "ZH": ("中文 (内部)", "docs/paper/zh/project_ghost_v0_2_ZH.md"),
}

_PAPER_GITHUB_BASE = "https://github.com/JFHelvetius/ghost/blob/main/"

# Typography CSS tuned for long-form reading (max-width, generous line-height,
# zebra-striped tables, monospace code with subtle background). Scoped under
# `.paper-prose` so the rest of the app keeps its own styling.
_PAPER_CSS = """
<style>
.paper-prose {
    max-width: 760px;
    margin: 0 auto;
    font-size: 1.02rem;
    line-height: 1.72;
    color: #1a1d23;
}
.paper-prose h1 {
    font-size: 1.95rem;
    line-height: 1.2;
    margin-top: 2.4rem;
    margin-bottom: 1.0rem;
    color: #0c1014;
    letter-spacing: -0.01em;
}
.paper-prose h2 {
    font-size: 1.55rem;
    line-height: 1.25;
    margin-top: 2.5rem;
    margin-bottom: 0.8rem;
    color: #0c1014;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 0.35rem;
}
.paper-prose h3 {
    font-size: 1.22rem;
    line-height: 1.3;
    margin-top: 2.0rem;
    margin-bottom: 0.6rem;
    color: #1a1d23;
}
.paper-prose h4 {
    font-size: 1.05rem;
    margin-top: 1.6rem;
    margin-bottom: 0.4rem;
    color: #1a1d23;
}
.paper-prose p {
    margin: 0.7rem 0;
}
.paper-prose blockquote {
    border-left: 3px solid #94a3b8;
    padding: 0.3rem 1.0rem;
    margin: 1.2rem 0;
    color: #475569;
    background: #f8fafc;
    border-radius: 0 4px 4px 0;
}
.paper-prose code {
    background: #f1f5f9;
    color: #1e293b;
    padding: 0.12rem 0.35rem;
    border-radius: 3px;
    font-size: 0.92em;
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
}
.paper-prose pre {
    background: #0f172a;
    color: #e2e8f0;
    padding: 0.9rem 1.1rem;
    border-radius: 6px;
    overflow-x: auto;
    line-height: 1.55;
    margin: 1.0rem 0;
}
.paper-prose pre code {
    background: transparent;
    color: inherit;
    padding: 0;
    font-size: 0.88rem;
}
.paper-prose ul, .paper-prose ol {
    margin: 0.6rem 0 0.9rem 1.3rem;
}
.paper-prose li {
    margin: 0.25rem 0;
}
.paper-prose table {
    border-collapse: collapse;
    width: 100%;
    margin: 1.1rem 0;
    font-size: 0.94rem;
}
.paper-prose th, .paper-prose td {
    border: 1px solid #e5e7eb;
    padding: 0.5rem 0.7rem;
    text-align: left;
    vertical-align: top;
}
.paper-prose th {
    background: #f1f5f9;
    font-weight: 600;
    color: #0c1014;
}
.paper-prose tbody tr:nth-child(even) {
    background: #fafafa;
}
.paper-prose a {
    color: #0c4a6e;
    text-decoration: underline;
    text-underline-offset: 2px;
}
.paper-prose a:hover {
    color: #0369a1;
}
.paper-prose hr {
    border: 0;
    border-top: 1px solid #e5e7eb;
    margin: 2.0rem 0;
}
.paper-prose strong {
    color: #0c1014;
    font-weight: 600;
}
.paper-prose em {
    color: #1a1d23;
}
.paper-meta-bar {
    max-width: 760px;
    margin: 0 auto 1.5rem auto;
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
}
</style>
"""


def _find_repo_root() -> Path | None:
    """Locate the repo root from the running module's path.

    Used by ``_paper_tab`` to read the markdown source from the same
    repository the app is shipped from. Returns ``None`` when the app
    is installed as a wheel without source — in that case the paper
    is fetched from the GitHub raw URL instead.
    """
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "docs" / "paper").is_dir():
            return parent
    return None


def _load_paper_markdown(rel_path: str) -> tuple[str, bool]:
    """Return (text, ok) for the paper at ``rel_path``.

    First tries the local repo; falls back to the GitHub raw URL when
    the app is running from an installed wheel without source.
    """
    root = _find_repo_root()
    if root is not None:
        candidate = root / rel_path
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8"), True
            except OSError:
                pass
    # Fall back to fetching from GitHub raw (best effort).
    raw_url = "https://raw.githubusercontent.com/JFHelvetius/ghost/main/" + rel_path
    try:
        import urllib.request

        with urllib.request.urlopen(raw_url, timeout=10) as resp:
            return resp.read().decode("utf-8"), True
    except Exception:
        return "", False


def _paper_tab() -> None:
    st.markdown(_PAPER_CSS, unsafe_allow_html=True)

    # Eyebrow + title + intro.
    st.markdown(
        f'<p class="section-eyebrow" style="text-align:center;'
        f'margin-top:2.5rem">{t("paper_eyebrow")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<h1 style="text-align:center;font-size:1.8rem;line-height:1.25;'
        f'max-width:760px;margin:0.4rem auto 1.0rem auto">{t("paper_h1")}</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="text-align:center;max-width:680px;margin:0 auto 2.0rem auto;'
        f'color:#475569;line-height:1.6">{t("paper_intro")}</p>',
        unsafe_allow_html=True,
    )

    # Language picker (independent of the global UI language).
    if "paper_lang" not in st.session_state:
        st.session_state["paper_lang"] = "EN"

    _centre_l, centre_c, _centre_r = st.columns([1, 2, 1])
    with centre_c:
        choice = st.radio(
            t("paper_lang_label"),
            list(_PAPER_FILES.keys()),
            horizontal=True,
            format_func=lambda k: _PAPER_FILES[k][0],
            index=list(_PAPER_FILES.keys()).index(st.session_state["paper_lang"]),
            key="_paper_lang_radio",
        )
        if choice != st.session_state["paper_lang"]:
            st.session_state["paper_lang"] = choice
            st.rerun()

    lang_key = st.session_state["paper_lang"]
    _, rel_path = _PAPER_FILES[lang_key]

    text, ok = _load_paper_markdown(rel_path)

    # Action bar: GitHub link + download.
    github_url = _PAPER_GITHUB_BASE + rel_path
    raw_url = "https://raw.githubusercontent.com/JFHelvetius/ghost/main/" + rel_path

    _bar_l, bar_c, _bar_r = st.columns([1, 2, 1])
    with bar_c:
        st.markdown(
            f'<div class="paper-meta-bar">'
            f'<a href="{github_url}" target="_blank" rel="noopener" '
            f'style="text-decoration:none;color:#0c4a6e;font-size:0.92rem">'
            f"↗ {t('paper_view_github')}</a>"
            f'<span style="color:#94a3b8;font-size:0.92rem">·</span>'
            f'<a href="{raw_url}" target="_blank" rel="noopener" '
            f'style="text-decoration:none;color:#0c4a6e;font-size:0.92rem">'
            f"⤓ {t('paper_download_md')}</a>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if not ok:
        st.warning(t("paper_loading_error") + f"[{github_url}]({github_url})")
        return

    # Render the markdown inside a typography-tuned container.
    st.markdown('<div class="paper-prose">', unsafe_allow_html=True)
    st.markdown(text, unsafe_allow_html=False)
    st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Page layout
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Project Ghost",
    page_icon="◉",
    layout="wide",
    menu_items={
        "About": (
            "Project Ghost v0.2.5 — Epistemic Safety Contracts for "
            "autonomous agents · 7 verified contracts · Apache-2.0 · "
            "https://github.com/JFHelvetius/ghost"
        ),
    },
)

st.markdown(_CSS, unsafe_allow_html=True)

_language_picker()

_hero()

_tab_run, _tab_inspect, _tab_paper = st.tabs([t("tab_run"), t("tab_inspect"), t("tab_paper")])

with _tab_run:
    _run_tab()

with _tab_inspect:
    _inspect_tab()

with _tab_paper:
    _paper_tab()
