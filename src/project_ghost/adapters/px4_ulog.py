"""PX4 ULog → Ghost pipeline adapter (paper §8.7, candidate ADR-0037).

Reads a PX4 ULog file via ``pyulog`` and emits a time-aligned stream
of pose samples in the format the Ghost pipeline consumes. The
parser does *not* yet run the full closed-loop pipeline against the
samples (that requires a ground-truth source whose policy is the
next ADR's scope), but it does close the gap between "no real-flight
integration" and "we know exactly which ULog topics map to which
Ghost messages, and we have unit tests proving the mapping is
correct".

What this module does:

- Parses a ULog file with ``pyulog.ULog``.
- Extracts ``vehicle_local_position`` (EKF2 position estimate with
  variance) and ``vehicle_attitude`` (quaternion).
- Time-aligns the two streams to ``vehicle_local_position``'s
  timestamps (the slower of the two in typical PX4 logs).
- Returns a list of typed ``ULogPoseSample`` records — one per
  ``vehicle_local_position`` event — that downstream code can
  fold into ``VehicleState`` records.

What this module does **not** do (out of scope for v0.2.x; see paper
§8.7 commitment):

- It does not subsample to the Ghost cycle rate. A downstream
  driver picks the cycles.
- It does not source ground truth. The candidate ADR-0037 will
  enumerate the ground-truth policies (motion capture, RTK GPS,
  vacuous EKF2 fallback) and pick one per dataset.
- It does not write a full Ghost MCAP. The end-to-end
  ``ulg → MCAP → verify`` is the v0.3.0 deliverable.

Dependency: ``pyulog`` is *not* a base dependency of
``project_ghost``. It is declared as an optional ``adapters`` extra
in ``pyproject.toml`` so installations that do not need real-flight
ingestion remain lean. ``from project_ghost.adapters.px4_ulog
import ...`` raises ``ImportError`` with an actionable message if
``pyulog`` is missing.

This module is pure and deterministic given its inputs.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

try:
    import pyulog

    _HAVE_PYULOG: bool = True
except ImportError:  # pragma: no cover
    _HAVE_PYULOG = False

if TYPE_CHECKING:
    from pathlib import Path


class ULogParseError(Exception):
    """Raised when a ULog file is missing the topics the adapter
    needs, or when the topics fail timestamp-alignment.

    Distinguished from ``OSError`` (file not found) and from
    ``ImportError`` (pyulog not installed) so callers can give
    actionable feedback.
    """


@dataclass(frozen=True)
class ULogTopicNames:
    """PX4 topic names this adapter reads. Defaults match upstream
    PX4 ≥ 1.13. Override per-version if the topic naming changes.
    """

    local_position: str = "vehicle_local_position"
    attitude: str = "vehicle_attitude"


@dataclass(frozen=True)
class ULogPoseSample:
    """One time-aligned pose sample extracted from a ULog.

    All units match the Ghost pipeline's conventions: position in
    metres (ENU on the local NED → ENU transform), orientation as a
    Hamilton-convention quaternion ``[w, x, y, z]`` with unit norm.

    ``stamp_us`` is the ULog event timestamp in microseconds
    (the resolution PX4 logs at). Converting to nanoseconds for the
    Ghost pipeline is left to the caller so this struct stays
    transport-agnostic.
    """

    stamp_us: int
    # Position estimate, metres. Indexed (x, y, z) in PX4's local NED
    # frame. Downstream callers may rotate to ENU.
    position_m: tuple[float, float, float]
    # Per-axis position standard deviation, metres.
    position_std_m: tuple[float, float, float]
    # Orientation quaternion, Hamilton w-first convention, unit norm.
    quaternion_wxyz: tuple[float, float, float, float]


def _require_pyulog() -> None:
    if not _HAVE_PYULOG:  # pragma: no cover
        raise ImportError(
            "pyulog is required for PX4 ULog ingestion but is not "
            "installed. Install with "
            "`pip install 'project-ghost[adapters]'`."
        )


def _topic_by_name(ulog_obj: object, name: str) -> object:
    """Return the ``Data`` object for ``name`` from a ``ULog``, or
    raise ``ULogParseError`` with the available topics for context.
    """
    matches = [d for d in ulog_obj.data_list if d.name == name]  # type: ignore[attr-defined]
    if not matches:
        available = sorted({d.name for d in ulog_obj.data_list})  # type: ignore[attr-defined]
        raise ULogParseError(f"ULog has no topic named {name!r}. Available topics: {available}")
    if len(matches) > 1:
        raise ULogParseError(
            f"ULog has {len(matches)} instances of topic {name!r}; "
            "the adapter does not yet pick between multi-instance "
            "topics. Pre-filter or supply a stricter ULogTopicNames."
        )
    return matches[0]


def _quaternion_at(att_data: object, idx: int) -> tuple[float, float, float, float]:
    """Read one row of ``vehicle_attitude.q`` as a unit quaternion in
    Hamilton w-first convention.

    PX4 stores ``q[0..3]`` directly w-first; we copy. If the row
    is non-finite or zero-norm, raise ``ULogParseError`` rather than
    emit a bogus pose.
    """
    data = att_data.data  # type: ignore[attr-defined]
    components = (
        float(data["q[0]"][idx]),
        float(data["q[1]"][idx]),
        float(data["q[2]"][idx]),
        float(data["q[3]"][idx]),
    )
    norm = math.sqrt(sum(c * c for c in components))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ULogParseError(
            f"vehicle_attitude row {idx} has non-finite or zero-norm "
            f"quaternion {components}; cannot map to Ghost pipeline."
        )
    return tuple(c / norm for c in components)  # type: ignore[return-value]


def parse_ulog_pose_samples(
    ulog_path: Path,
    *,
    topic_names: ULogTopicNames | None = None,
) -> list[ULogPoseSample]:
    """Parse a PX4 ULog file and return the time-aligned pose samples.

    Each returned ``ULogPoseSample`` corresponds to one
    ``vehicle_local_position`` event whose timestamp has a nearest
    ``vehicle_attitude`` sibling. The pairing uses the nearest
    timestamp (clamped to the closest ``vehicle_attitude`` index by
    binary search); this is the standard PX4 analysis approach and
    is good enough for the calibration-history accumulation Ghost
    cares about.

    Parameters
    ----------
    ulog_path : Path
        Path to the ``.ulg`` file. Must exist.
    topic_names : ULogTopicNames, optional
        Override the PX4 topic names if a non-standard build is in
        use. Defaults to upstream PX4 ≥ 1.13 names.

    Returns
    -------
    list[ULogPoseSample]
        Pose samples, chronological, deterministic.

    Raises
    ------
    ImportError
        If ``pyulog`` is not installed.
    FileNotFoundError
        If the ULog path does not exist.
    ULogParseError
        If the file is missing the required topics or the topics
        fail alignment.
    """
    _require_pyulog()
    if not ulog_path.exists():
        raise FileNotFoundError(f"ULog file not found: {ulog_path}")

    names = topic_names or ULogTopicNames()

    ulog_obj = pyulog.ULog(str(ulog_path))
    pos_data = _topic_by_name(ulog_obj, names.local_position)
    att_data = _topic_by_name(ulog_obj, names.attitude)

    pos_dict = pos_data.data  # type: ignore[attr-defined]
    att_dict = att_data.data  # type: ignore[attr-defined]

    required_pos_fields = ("timestamp", "x", "y", "z")
    required_pos_std_fields = ("eph", "epv")  # px horiz / vert std
    required_att_fields = ("timestamp", "q[0]", "q[1]", "q[2]", "q[3]")

    for f in required_pos_fields + required_pos_std_fields:
        if f not in pos_dict:
            raise ULogParseError(
                f"vehicle_local_position is missing required field "
                f"{f!r}. Got: {sorted(pos_dict.keys())[:10]}..."
            )
    for f in required_att_fields:
        if f not in att_dict:
            raise ULogParseError(
                f"vehicle_attitude is missing required field {f!r}. "
                f"Got: {sorted(att_dict.keys())[:10]}..."
            )

    att_times = att_dict["timestamp"]
    pos_times = pos_dict["timestamp"]

    samples: list[ULogPoseSample] = []
    for i, t_pos in enumerate(pos_times):
        idx_att = _nearest_index(att_times, int(t_pos))
        quat = _quaternion_at(att_data, idx_att)
        # PX4 reports horizontal std eph (combined x,y) and vertical
        # std epv (z). We use eph as both x and y std (PX4 convention)
        # to stay honest about the source.
        eph = float(pos_dict["eph"][i])
        epv = float(pos_dict["epv"][i])
        samples.append(
            ULogPoseSample(
                stamp_us=int(t_pos),
                position_m=(
                    float(pos_dict["x"][i]),
                    float(pos_dict["y"][i]),
                    float(pos_dict["z"][i]),
                ),
                position_std_m=(eph, eph, epv),
                quaternion_wxyz=quat,
            )
        )
    return samples


def _nearest_index(sorted_times: object, target: int) -> int:
    """Binary search for the nearest index in a sorted timestamp
    array. Used to pair a ``vehicle_local_position`` event with its
    contemporary ``vehicle_attitude`` event.
    """
    arr: list[int] = list(sorted_times)  # type: ignore[call-overload]
    if not arr:
        raise ULogParseError("attitude timestamp array is empty")
    # bisect_left returns insertion index; pick the closer of i and i-1.
    i = bisect.bisect_left(arr, target)
    if i == 0:
        return 0
    if i == len(arr):
        return len(arr) - 1
    before = arr[i - 1]
    after = arr[i]
    return i - 1 if (target - before) <= (after - target) else i
