# ADR-0012 — Run Retention Policy

- **Status:** Accepted
- **Date:** 2026-06-04
- **Relationship to prior ADRs:** New decision. References ADR-0003 (telemetry everywhere) and the future research track artifacts in `docs/roadmaps/research_track_uncertainty.md`. Replaces the bullet "Política de retención y rotación" in `docs/specs/telemetry.md` §11 (Evolución futura).

## Context

ADR-0003 commits Project Ghost to obsessive telemetry: every bus message is persisted to MCAP, every run produces an indexed file plus a manifest. The cost of this commitment is **monotonic disk growth**, paid by the developer's local machine. `docs/roadmaps/phase1.md` closes with an explicit acknowledgement: "no run retention policies (they accumulate)".

The uncertainty red-team review (§3.4) flagged this as deferred-but-not-deferable: the research track's U2 and U5 produce **datasets** in addition to per-run logs. By the end of U5 the local disk and the repository will collapse if no policy exists. The right time to decide is **before U1 starts**, so U1 can implement the tooling alongside the rest of `core.uncertainty`.

Three constraints inform the policy:

1. **Reproducibility is non-negotiable.** A run that produced a published result must remain reproducible. The manifest, the config snapshot, and the input scripts are small and cheap to keep forever.
2. **Raw MCAP is expensive.** Camera-on runs produce ~50–100 MB per minute. Keeping every minute of every exploration run is not viable on a developer laptop.
3. **Compression buys time, not capacity.** Zstd typically halves MCAP size for camera-heavy logs but is still expensive over months.

The policy must be **explicit, automated where possible, and reviewable**. Implicit policies (developer remembers to clean up) fail; opaque policies (the tool deletes files silently) destroy trust.

## Decision

### 1. Tiered retention

Each run is classified into one of three retention tiers, with explicit lifetime and storage rules. The tier is set in the manifest at the time of run creation; tier upgrades are explicit operator decisions and emit a `RETENTION_TIER_CHANGED` event.

| Tier | Source of classification | Lifetime | Storage |
|---|---|---|---|
| `EPHEMERAL` | Default for all runs | 7 days from creation | Local disk only; never published |
| `RESEARCH` | Runs produced under a tagged research task (U1–U6) or explicitly tagged by operator | 90 days from creation, then archive of compressed manifest + downsampled telemetry forever | Local disk + release-asset archive at expiration |
| `RESULT` | Runs that backed a published result (informe, paper, demo) | Forever | Local disk + GitHub release asset; manifest + compressed log retained as artifact |

Defaults are conservative: ephemerality is the rule, durability is the exception. A run that turns out to matter is upgraded; a run that does not matter is forgotten.

### 2. Files within a run

A run directory `runs/<run_id>/` contains three classes of files. Retention applies per class.

| Class | Examples | Retention rule |
|---|---|---|
| **Manifest** | `manifest.yaml`, `config_snapshot.yaml`, `script_inputs.json` if present | Forever in all tiers. Always retained, regardless of MCAP fate. |
| **Raw log** | `log.mcap`, `images/` if separate, video exports | Per tier table in §1. `EPHEMERAL` deletes; `RESEARCH` compresses to zstd at day 7 and re-evaluates at day 90; `RESULT` compresses to zstd at day 7 and retains forever. |
| **Derived** | `metrics.json`, `plots/`, notebooks rendered | Per tier table; same as raw log but cheaper to keep. May be retained beyond raw log lifetime if explicitly requested by tooling. |

The manifest's permanence is the load-bearing property: any future need to "recover what was in this run" starts from the manifest. Losing the manifest equals losing the run as a citable artifact.

### 3. Git policy

`runs/` is **ignored by git** in its entirety. No exceptions. Manifests of `RESULT`-tier runs are referenced from `docs/research/*.md` by content hash and stored as GitHub release assets, never as repo blobs. This keeps the repo small, decouples result reproducibility from repo size, and avoids the pattern of "git LFS for telemetry" that has failed in similar projects.

### 4. Storage budget

Local disk has a declared budget, enforced by tooling:

```yaml
retention:
  local_disk_budget_gb: 50        # default; override per developer
  warn_threshold_pct: 80          # warn at 40 GB
  hard_threshold_pct: 95          # refuse new runs at 47.5 GB
```

When the budget approaches `warn_threshold_pct`, the next run creation emits a `RETENTION_BUDGET_WARN` event. When it reaches `hard_threshold_pct`, run creation **refuses** until the operator runs the cleanup tool. Tooling does not auto-delete `RESEARCH` or `RESULT` runs to make space; only `EPHEMERAL` runs are eligible for automatic cleanup, and only past their lifetime.

This refusal-not-deletion stance protects against the failure mode where a runaway script generates 200 ephemeral runs in an hour and the cleanup quietly destroys yesterday's calibration log.

### 5. Tooling contract

`scripts/manage_runs.py` (to be implemented in U1) provides:

- `list` — table of all runs with tier, age, size, status.
- `tag <run_id> --tier <TIER>` — upgrade tier (downgrade allowed only with `--force`).
- `clean --dry-run` — print what `clean` would delete.
- `clean` — delete `EPHEMERAL` runs past 7 days; compress `RESEARCH` runs past 7 days; never touches `RESULT`.
- `archive <run_id>` — produce a `runs/<run_id>.archive.tar.zst` ready for upload as a release asset.
- `verify <run_id>` — check manifest integrity and MCAP index, report status.

The tool operates only on `runs/` under the project root. It does not delete anything outside that directory. It emits `RETENTION_*` events to the bus when run interactively (so its actions appear in MCAP alongside the runs it touches).

### 6. Compression

- All `RESEARCH` and `RESULT` MCAPs are compressed to **zstd** at day 7 post-creation by the `clean` tooling.
- Compression is **lossless** for log content. No frame dropping, no resolution reduction.
- Compressed MCAPs retain their internal index; replay reads compressed files transparently via the MCAP library's zstd support.
- Compression target: ~50 % of original size for camera-heavy runs in tests so far. Actual ratio reported per run by `manage_runs.py verify`.

Lossy reductions (downsampling, video re-encoding) are explicitly **not part of this policy** and require a separate ADR if proposed in the future.

### 7. Datasets (U2/U5)

Datasets generated by the research track are governed separately from runs:

- Each U-task produces a `datasets/u<n>_<topic>/` directory.
- Datasets are versioned by content hash, never by mtime.
- Datasets up to 100 MB live in the git repo (with attention from `pre-commit`).
- Datasets >100 MB are published as release assets; the repo contains only the manifest pointing to them.
- Datasets used by a `RESULT`-tier run inherit the `RESULT` tier and forever-retention obligation.

This treatment is consistent with the run tiers: cheap-to-keep stays close, expensive-to-keep moves out.

### 8. Out of scope

- **Cloud-backed retention.** No commitment to S3, GCS, or any cloud archive. Operators may add cloud backup outside the scope of this ADR.
- **Encryption at rest.** Project Ghost runs do not contain sensitive data. Operators with regulatory needs add their own layer.
- **Cross-developer synchronization.** Each developer has their own local `runs/`. Collaboration is via release assets and dataset hashes, not via shared raw log stores.
- **Automatic tier promotion based on content.** A run does not auto-upgrade from `EPHEMERAL` to `RESEARCH` because it "looks important". Tier promotion is always an explicit operator action.

## Consequences

**Positive.**

- Disk growth is bounded. A developer working on Project Ghost for two years does not need 5 TB of local storage.
- The single most important artifact (the manifest) is kept forever in all tiers, preserving the citability and reproducibility intent of ADR-0003.
- Cleanup is automated but **refuses to be silent**: tooling reports, warns, and asks before destroying anything beyond `EPHEMERAL` runs past their lifetime.
- Datasets and runs share a single mental model: cheap stays, expensive moves out, results are forever.
- The git repository stays small and contributable.

**Negative.**

- An operator who forgets to tag a research run before it ages past 7 days loses the raw log. Mitigated by `clean --dry-run` and the WARN-before-HARD threshold ladder, but not eliminated.
- The `RESULT` tier's "forever" obligation creates a long tail of release assets to maintain on GitHub. Mitigated by hashing and content addressing; the obligation is per-release, not per-day.
- Per-developer local budgets mean that two developers may have different reproducibility states. Mitigated: `RESULT` runs are guaranteed reproducible across developers because they live in release assets; lower tiers do not need cross-developer reproducibility by definition.
- The cleanup tool is new code that must be reliable. Mitigated by `--dry-run`, explicit tier rules, and integration tests in U1.

## Alternatives considered

**A. Time-based deletion only, no tiers.** Delete everything older than N days. Rejected: research runs and result-backing runs cannot be on the same clock as one-off explorations.

**B. Size-based deletion (delete oldest until budget OK).** LRU on disk. Rejected: deletes the wrong things. A small old `RESULT` run gets evicted by a large young `EPHEMERAL` run. The tier system inverts this correctly.

**C. Keep everything; let the operator clean up manually.** Status quo. Rejected by the review and confirmed here: the operator does not in fact clean up, and disk fills.

**D. Cloud-first: stream all telemetry to S3, keep nothing locally.** Rejected: introduces dependency on external services, network costs for hardware deployments in field conditions, and an operational surface (credentials, quotas) the project does not want to own. May be a community extension; not a core commitment.

**E. Git LFS for run logs.** Rejected: LFS has a poor track record at the volumes Project Ghost will produce (tens of GB per week during U5), and the cost model is hostile for open-source projects.

**F. Auto-promote runs that produce certain metrics.** Rejected: tooling cannot reliably know when a run "matters". The operator's explicit tag is the source of truth.

**G. Lossy downsampling of old camera streams.** Rejected for this ADR — may revisit if zstd compression alone proves insufficient. Lossy reductions break replay determinism (ADR-0002 contract) and require their own ADR.
