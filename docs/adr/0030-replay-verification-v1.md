# ADR-0030 — Replay Verification v1

## Status

Accepted

## Context

ADR-0028 introduced `FusionResult` as the product of the sensor-to-belief
fusion layer. The closed-loop smoke stores `FusionResult` records in the
`/fusion/results` MCAP channel.

This raises a verifiability question: if the fusion layer is the only
source of ground-truth beliefs, can the entire downstream pipeline
(self-assessment → calibration → decision → actuation → prediction →
divergence) be reconstructed from those stored records with byte-identical
fidelity?

If the answer is yes, then:

1. Every run is auditable from its stored intermediate state, not only
   from its raw inputs.
2. The downstream pipeline has no hidden non-determinism (clock, random,
   mutable global state).
3. Any future tool that re-analyses a run can be tested against the
   replay guarantee.

## Decision

Introduce `replay_downstream_from_fusion` in
`project_ghost.examples.replay_verification`. The function:

1. Reads all `FusionResult` records from `/fusion/results` in a source
   MCAP (produced by `run_closed_loop_smoke`).
2. Re-executes the downstream pipeline with identical parameters:
   - `AssessmentThresholds` (same as smoke)
   - `MahalanobisDowngradePolicy(min_outcomes=4, downgrade_threshold=2)`
   - `UncertaintyAwareReferencePolicy`
   - `AttitudeHoldReferencePolicy`
   - `ConstantVelocityForwardPredictor`
   - Ground-truth function `(t_ns: int) -> Pose` (default: 5 m/s x-drift
     from t=1 s, matching the smoke scenario)
3. Writes the replay to a new MCAP containing only the six downstream
   channels.
4. Decodes and re-encodes each downstream message from both MCAPs, then
   compares byte-for-byte per channel.
5. Returns `ReplayVerificationSummary` with per-channel
   `ChannelVerification` records and `all_channels_byte_equal`.

Channels verified (compared byte-for-byte):

| Channel | Messages (N=10) |
|---|---|
| `/self_assessment` | 10 |
| `/self_assessment/calibrated` | 10 |
| `/decisions` | 10 |
| `/actuations` | 10 |
| `/predictions/forward` | 10 |
| `/predictions/outcomes` | 9 |

Channels NOT replayed (source only):

- `/fusion/results` — the replay source; not re-generated.
- `/state/nav` — `VehicleState` is `FusionResult.belief`; redundant.

The `ground_truth_fn` parameter is optional (default covers the smoke
scenario). Callers with a custom scenario pass their own function, and
the test suite verifies that a wrong ground-truth function breaks
byte-equality — confirming the function is actually used.

## Consequences

- The downstream pipeline is proven to have no hidden non-determinism.
  Any change that introduces clock reads, random, or mutable globals
  will break `test_replay_is_byte_deterministic_3x`.
- Analytical tools that re-process a run from stored `/fusion/results`
  can rely on byte-identical reconstruction of all downstream records.
- The `ground_truth_fn` parameter makes the function composable with
  scenarios beyond the default smoke.
- The replay MCAP omits `/fusion/results` and `/state/nav`; its SHA-256
  will always differ from the source SHA-256. This is expected and
  tested explicitly.

## Alternatives considered

- **Compare raw MCAP bytes (source == replay)** — rejected. Source and
  replay contain different channel sets; byte-identical MCAP files are
  impossible. Per-channel payload comparison is the correct granularity.
- **Use stored `PredictionOutcome` records for calibration** — rejected.
  Reading stored outcomes would bypass re-execution of `compute_divergence`
  and would not prove pipeline determinism. The replay must re-compute
  outcomes from the ground-truth function.
- **Parameterize all scenario constants** — deferred. The v1 function
  hardcodes `_DT_NS`, `_T0_NS`, and the feedback policy parameters to
  match the smoke. Future ADRs may add a `ScenarioConfig` dataclass if
  multiple scenarios need to be verified from the same function.
- **Put replay_verification in `core.*`** — rejected. This is an
  orchestration of multiple contracts, not a contract itself. It belongs
  in `examples/` alongside the smoke it verifies.
