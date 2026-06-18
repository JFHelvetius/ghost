# ADR-0037: Real-flight ULog ground-truth and the SITL_SIMULATOR source

- **Status**: Accepted (2026-06-12)
- **Driver**: paper §8.8 (real-telemetry discrimination experiment),
  §8.8.3 (independent ground-truth A/B)
- **Module**: `src/project_ghost/adapters/px4_ulog.py`,
  `src/project_ghost/adapters/real_ulog_smoke.py`,
  `src/project_ghost/adapters/real_ulog_discrimination.py`,
  `src/project_ghost/adapters/multi_ulog_discrimination.py`
- **Tests**: `tests/adapters/test_px4_ulog_groundtruth.py`,
  `tests/adapters/test_real_ulog_smoke.py`,
  `tests/adapters/test_real_ulog_smoke_gt_source.py`,
  `tests/adapters/test_real_ulog_discrimination.py`
- **Supersedes / depends on**: ADR-0036 (TLA+/TLC), property ADRs 0031–0035
- **Related**: paper §1.2 (C3), §8.7 (single-ULog real-telemetry smoke)

## Context

§8.7 of the paper runs the verifier against a single PX4 ULog
(`docs/paper/data/sample.ulg`) using the ULog's own EKF2 estimate as
both the agent's belief and the (vacuous) "ground truth" oracle.
The all-HOLDS verdict that follows is honest about its scope: it
demonstrates that the verifier runs end-to-end on real telemetry,
not that the contracts hold over an independent ground truth.

A reviewer's first observation on §8.7 is the circular-ness of the
ground-truth source: a violation that the EKF2 itself produces is
invisible to the verifier because both belief and oracle come from
the same numbers. The honest scope-limit is documented in §8.7's
"Read this before the verdict table" callout.

The §8.8 multi-ULog discrimination experiment cannot rely on EKF2
fallback alone: stationary flight segments produce all-HOLDS by
construction (the precondition for BAUD-v1 / FPB-v1 never fires
because the belief never disagrees with itself). §8.8.3 reports the
A/B between EKF2-fallback ground truth and a SITL-simulator ground
truth on `sample_logging_tagged.ulg`: the SITL GT lifts the FPB
fire fraction from 0.00 to 0.86 and closes 4 of the 6
vacuously-HOLDS rows.

## Decision

The orchestrator auto-detects an independent ground-truth source
when one is available in the ULog and falls back to EKF2 otherwise.

The data model is a small enum:

```python
class GroundTruthSource(StrEnum):
    EKF2_FALLBACK = "ekf2_fallback"      # current default for §8.7
    SITL_SIMULATOR = "sitl_simulator"    # PX4 SITL with vehicle_*_groundtruth
    MOTION_CAPTURE = "motion_capture"    # roadmap, not implemented
    RTK_GPS = "rtk_gps"                  # roadmap, not implemented
```

Auto-detection rule: if the ULog contains messages on either
`vehicle_local_position_groundtruth` or
`vehicle_global_position_groundtruth`, the orchestrator promotes the
source to `SITL_SIMULATOR` and uses those topics for the oracle while
keeping EKF2 for the agent's belief. Otherwise the source stays at
`EKF2_FALLBACK`.

The chosen source is recorded in the experiment artefact
(`multi_ulog_discrimination/matrix.json` per-ULog) so a reviewer can
audit which rows of §8.8 used independent ground truth and which
fell back to the circular EKF2 oracle.

## Scope

- Applies to the PX4 ULog adapter family in `src/project_ghost/adapters/`.
- Does NOT cover ROSBag, EuRoC, or non-PX4 stacks — those remain open.
- Does NOT claim motion-capture or RTK-GPS implementations; those are
  named in the enum for forward compatibility but are unimplemented in
  v0.2.5.
- Does NOT validate that the SITL ground truth itself is accurate;
  the verifier accepts it as given.

## Honest caveats

- The §8.8 discrimination matrix is 18/18 green; 15/18 cells isolate
  the violation to the expected property. The 3 non-isolated cells
  are the `calibrator_invents_confidence` row across all three
  ULogs, which is a real BAUD-v1 ∧ MD-v1 co-violation, not a
  spurious correlation.
- Two of the three ULogs (`sample.ulg`, `sample_appended.ulg`) still
  fall back to `EKF2_FALLBACK` in §8.8 because they predate the
  SITL-GT logging fixture; the discrimination still works because
  those flights are not stationary (FPB fire fractions 0.94 and 0.98
  respectively) and the precondition fires under circular GT anyway.
- The enum entries `MOTION_CAPTURE` and `RTK_GPS` are documented
  forward declarations; attempting to use them raises
  `NotImplementedError`. The roadmap is to ship a ROSBag adapter
  first (covered by a separate ADR) and the motion-capture path
  alongside it.

## Status of evidence

- 13 integration tests in `tests/adapters/` exercise the adapter
  family (single-ULog smoke, GT-source auto-detection, multi-ULog
  discrimination, byte-determinism).
- CI matrix `Tests (ubuntu-latest, py3.12)` and the other three legs
  run the full adapter suite on every push.
