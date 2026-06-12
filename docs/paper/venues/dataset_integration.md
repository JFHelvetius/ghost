# Real-data integration roadmap

Roadmap for upgrading the verifier from shape-realistic synthetic
scenarios (paper §8.5) to real flight telemetry. Out of scope for
v0.2.x; candidate ADR-0037 once a HAL backend exists.

## Current state (v0.2.1)

The verifier reads MCAPs produced by the Ghost closed-loop pipeline.
Those MCAPs have a known schema:

- `/fusion/results` — `FusionResult` (belief)
- `/state/nav` — `VehicleState`
- `/self_assessment` + `/self_assessment/calibrated`
- `/decisions` + `/actuations`
- `/predictions/forward` + `/predictions/outcomes`

Any MCAP missing these channels cannot be verified directly. The
verifier is a function of the captured run, not of the underlying
hardware or simulator.

## Target candidates

Three open formats common in drone and autonomous-vehicle telemetry,
in increasing order of integration cost:

### 1. PX4 ULog (`.ulg`)

PX4's native log format. Contains:

- IMU samples (accelerometer, gyroscope) at 250–1000 Hz.
- Position estimates from EKF2 with covariance.
- Attitude estimates with covariance.
- GPS fix status (relevant for the GPS-denial scenario).
- Mission status.

**Library**: [`pyulog`](https://pypi.org/project/pyulog/), MIT-licensed.

**Integration sketch**:

1. Read the ULog with `pyulog.ULog`.
2. Subsample to Ghost's cycle rate (default 10 Hz).
3. Build a `VehicleState` per cycle from the EKF2 outputs +
   IMU samples.
4. Run the standard Ghost pipeline starting from those states.
5. Capture to MCAP and verify.

The ground-truth source is the question: PX4 ULogs typically do
not carry an independent ground truth. Two options:

- Use the *initial* EKF2 estimate as a proxy ground truth (assumes
  the early estimate is correct, fails late).
- For lab datasets, pair the ULog with motion-capture truth
  (VICON, OptiTrack); these are typically in separate ROSBags
  that must be time-aligned.

### 2. ROSBag (`.bag` / ROS 1) and `.mcap` (ROS 2 Foxglove)

Generic ROS recordings. Common in:

- KITTI Odometry (camera + LiDAR + IMU + GPS) — research benchmark.
- EuRoC MAV (stereo + IMU + VICON) — VIO benchmark.
- TUM VI datasets.

**Library**: [`rosbags`](https://gitlab.com/ternaris/rosbags) for ROS 1
.bag reading without ROS installed. Native MCAP reader for ROS 2.

**Integration sketch**:

1. Identify the topics carrying pose estimate, pose covariance,
   IMU, and (if present) ground truth.
2. Time-align estimate ↔ ground truth.
3. Subsample to Ghost cycle rate.
4. Build `VehicleState`/`Pose` pairs per cycle.
5. Run Ghost pipeline + verifier.

### 3. NUTH ROS 2 MCAP recordings

ROS 2 native MCAP recordings already use the MCAP container — the
schema mismatch is the only barrier. A `convert-ros2mcap-to-ghost`
script would map ROS 2 topic schemas to Ghost message types where
the semantics line up.

## What an integration ADR (ADR-0037 candidate) would specify

1. **Source format declaration**: which formats are first-class
   citizens of the conversion layer.
2. **Sampling discipline**: subsampling, interpolation, gap policy.
3. **Ground-truth source policy**: how the converter sources the
   "truth" pose that the divergence step compares against; honest
   documentation of when truth is the EKF2's own early estimate
   vs an independent source.
4. **Covariance handling**: how the converter passes per-axis
   covariance through to `BeliefSelfAssessment` (real EKFs have
   richer covariance than the simple `eye(15) * diag` assumption
   of the basic smoke).
5. **Calibration policy parameter discovery**: at production scale,
   `(M, K, W)` should be tuned per sensor noise model; an ADR
   would document the tuning procedure.

## Why v0.2.x explicitly excludes this

- **HAL backend not yet shipped.** The pipeline's input contract
  (`VehicleState` schema) anticipates a future HAL but is not yet
  bound to any production backend.
- **Calibration policy parameters are sim-tuned.** `(M=4, K=2,
  W=32)` works for the reference smoke's noise profile; real
  flight noise differs and the parameters would need re-tuning.
- **Comparison-against-real-truth is a separate research project.**
  Real-flight evaluation needs ground-truth methodology that is
  out of scope for a tools paper.

The paper §8.5 instead validates the verifier and property set on
shape-realistic synthetic profiles. Reviewers asking for real-flight
validation should be pointed at this document as the explicit
roadmap.

## Concrete next steps if someone wants to attempt real-data
integration

1. **Pick a single dataset family** (EuRoC MAV is the canonical
   choice — has IMU + stereo + VICON truth + open license).
2. **Write `src/project_ghost/io/euroc_adapter.py`** that maps
   EuRoC's `state_groundtruth_estimate0/data.csv` + IMU + camera
   outputs to a stream of `VehicleState` records.
3. **Add an integration test** that runs the adapter on one
   sequence from EuRoC, produces an MCAP, and verifies the
   property set.
4. **Document the policy parameter tuning** in a new ADR; do not
   assume the sim defaults transfer.
5. **Submit results as a follow-up paper** or as a tool-paper
   appendix rather than re-submitting the v0.2.x paper.
