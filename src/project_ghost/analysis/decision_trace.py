"""Decision trace and chain verification (ADR-0022).

Pure, deterministic, observational. Lee un MCAP capturado que contiene
``/self_assessment`` (ADR-0020) y ``/decisions`` (ADR-0021), empareja
cada ``DecisionRationale`` con el ``BeliefSelfAssessment`` que lo
justificó por ``belief_stamp_sim_ns``, re-computa el SHA-256 canónico
del assessment y verifica que matchea el ``self_assessment_sha256``
declarado en el rationale.

Emite un ``DecisionTraceReport`` content-addressed al MCAP fuente. La
primitiva ``verify_decision_chain`` devuelve ``(ok, messages)`` para
auditoría rápida.

**No clasifica** decisiones como buenas o malas. **No infiere
causalidad**. Reporta integridad de cadena content-addressed; el
operador interpreta.

Encoding posture (frozen): ``sort_keys=True``, ``indent=2``,
``ensure_ascii=False``, trailing newline, UTF-8.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from project_ghost.core.decisions.orchestration import (
    self_assessment_sha256,
)
from project_ghost.core.decisions.types import (
    DecisionKind,
    DecisionRationale,
)
from project_ghost.core.uncertainty.self_assessment import (
    BeliefSelfAssessment,
)
from project_ghost.telemetry import (
    CHANNEL_DECISIONS,
    CHANNEL_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

DECISION_TRACE_ANALYSIS_VERSION: Final[int] = 1
DECISION_TRACE_REPORT_SCHEMA_VERSION: Final[str] = "1"

_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")
_HASH_CHUNK_BYTES: Final[int] = 1 << 20  # 1 MiB


# ---------------------------------------------------------------------------
# ChainStatus
# ---------------------------------------------------------------------------


class ChainStatus(StrEnum):
    """Estado de la cadena belief → assessment → decision por record.

    Catálogo cerrado. Modificar requiere ADR amendment.

    - ``VERIFIED``: rationale carga SHA y matchea el assessment
      encontrado.
    - ``BROKEN``: rationale carga SHA, se encontró un assessment con
      el mismo stamp, pero su SHA NO matchea (manipulación o bug).
    - ``ASSESSMENT_MISSING``: rationale carga SHA pero no hay
      assessment con ese stamp en el MCAP.
    - ``NO_ASSESSMENT_CLAIMED``: rationale tiene
      ``self_assessment_sha256 is None``. La decisión se tomó sin
      introspección (caso legítimo).
    """

    VERIFIED = "verified"
    BROKEN = "broken"
    ASSESSMENT_MISSING = "assessment_missing"
    NO_ASSESSMENT_CLAIMED = "no_assessment_claimed"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _validate_sha256(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be str; got {type(value).__name__}"
        )
    if len(value) != _SHA256_HEX_LEN:
        raise ValueError(
            f"{field} must be {_SHA256_HEX_LEN} hex chars; got "
            f"len={len(value)}"
        )
    for c in value:
        if c not in _HEX_CHARS:
            raise ValueError(
                f"{field} must be lowercase hex; got {value!r}"
            )


def _validate_optional_sha256(value: str | None, *, field: str) -> None:
    if value is None:
        return
    _validate_sha256(value, field=field)


def _hash_mcap_file(path: Path) -> str:
    """SHA-256 hex digest del archivo MCAP completo."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


def _validate_envelope(
    data: object,
    *,
    schema_version: str,
    inner_key: str,
) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(
            f"expected JSON mapping; got {type(data).__name__}"
        )
    if "schema_version" not in data:
        raise ValueError("missing 'schema_version' in JSON envelope")
    if data["schema_version"] != schema_version:
        raise ValueError(
            f"incompatible schema_version {data['schema_version']!r}; "
            f"expected {schema_version!r}"
        )
    if inner_key not in data:
        raise ValueError(f"missing {inner_key!r} in JSON envelope")
    inner = data[inner_key]
    if not isinstance(inner, Mapping):
        raise TypeError(
            f"{inner_key!r} must be a mapping; got {type(inner).__name__}"
        )
    return inner


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionTraceRecord:
    """Un record per ``DecisionRationale`` en ``/decisions``.

    ``timestamp_ns`` matchea ``rationale.belief_stamp_sim_ns`` (que a
    su vez matchea ``decision.decision_stamp_sim_ns`` por invariante
    de ADR-0021).

    ``claimed_assessment_sha256`` es lo que el rationale afirmó;
    ``recomputed_assessment_sha256`` es lo que sale al re-hashear el
    assessment encontrado en el mismo MCAP. ``None`` cuando no se
    encontró o cuando el rationale no reclamó nada.

    ``chain_status`` resume el resultado de la verificación.
    """

    timestamp_ns: int
    decision_kind: DecisionKind
    decision_reason: str
    policy_id: str
    claimed_assessment_sha256: str | None
    recomputed_assessment_sha256: str | None
    chain_status: ChainStatus
    analysis_version: int = DECISION_TRACE_ANALYSIS_VERSION

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError(
                f"timestamp_ns must be >= 0; got {self.timestamp_ns}"
            )
        if not isinstance(self.decision_kind, DecisionKind):
            raise TypeError(
                f"decision_kind must be DecisionKind; got "
                f"{type(self.decision_kind).__name__}"
            )
        if not isinstance(self.chain_status, ChainStatus):
            raise TypeError(
                f"chain_status must be ChainStatus; got "
                f"{type(self.chain_status).__name__}"
            )
        _validate_optional_sha256(
            self.claimed_assessment_sha256,
            field="claimed_assessment_sha256",
        )
        _validate_optional_sha256(
            self.recomputed_assessment_sha256,
            field="recomputed_assessment_sha256",
        )


@dataclass(frozen=True)
class DecisionTraceReport:
    """Run-level trace report content-addressed al MCAP fuente.

    Invariante: ``verified_count + broken_count + assessment_missing_count
    + no_assessment_claimed_count == total_decisions``.

    ``per_decision_kind_counts`` y ``per_policy_id_counts`` son
    agregados descriptivos con claves ordenadas alfabéticamente.
    """

    source_mcap_sha256: str
    total_decisions: int
    verified_count: int
    broken_count: int
    assessment_missing_count: int
    no_assessment_claimed_count: int
    per_decision_kind_counts: Mapping[str, int]
    per_policy_id_counts: Mapping[str, int]
    timestamp_first_ns: int | None
    timestamp_last_ns: int | None
    timestamp_span_ns: int | None
    records: tuple[DecisionTraceRecord, ...]
    analysis_version: int = DECISION_TRACE_ANALYSIS_VERSION

    def __post_init__(self) -> None:
        _validate_sha256(
            self.source_mcap_sha256, field="source_mcap_sha256"
        )
        if not isinstance(self.records, tuple):
            raise TypeError(
                f"records must be a tuple; got {type(self.records).__name__}"
            )
        if self.total_decisions != len(self.records):
            raise ValueError(
                f"total_decisions {self.total_decisions} != len(records) "
                f"{len(self.records)}"
            )
        counts_sum = (
            self.verified_count
            + self.broken_count
            + self.assessment_missing_count
            + self.no_assessment_claimed_count
        )
        if counts_sum != self.total_decisions:
            raise ValueError(
                f"counts sum ({counts_sum}) must equal total_decisions "
                f"({self.total_decisions})"
            )
        for name, m in (
            ("per_decision_kind_counts", self.per_decision_kind_counts),
            ("per_policy_id_counts", self.per_policy_id_counts),
        ):
            if not isinstance(m, Mapping):
                raise TypeError(
                    f"{name} must be a Mapping; got {type(m).__name__}"
                )
        object.__setattr__(
            self,
            "per_decision_kind_counts",
            dict(self.per_decision_kind_counts),
        )
        object.__setattr__(
            self,
            "per_policy_id_counts",
            dict(self.per_policy_id_counts),
        )


# ---------------------------------------------------------------------------
# build_decision_trace_report
# ---------------------------------------------------------------------------


def build_decision_trace_report(  # noqa: PLR0912, PLR0915
    mcap_path: Path,
) -> DecisionTraceReport:
    """Lee el MCAP, empareja decisiones con assessments y produce el
    trace report.

    Single pass: indexa assessments por ``belief_stamp_sim_ns`` y
    recorre rationales en orden de stream. Si dos assessments comparten
    stamp, el último gana (documentado en el ADR).

    Pure function: cero clock, cero random; sólo I/O sobre el archivo
    MCAP (lectura) y ``hashlib`` para el SHA del MCAP fuente.

    PLR0912/PLR0915 silenciados: la función ejecuta secuencialmente
    cuatro fases distintas (read MCAP, classify rationales, compute
    counters, assemble report). Cada branch corresponde a un
    ``ChainStatus`` distinto y la legibilidad sufre si se parten.
    """
    source_sha = _hash_mcap_file(mcap_path)

    assessments_by_stamp: dict[int, BeliefSelfAssessment] = {}
    rationales: list[DecisionRationale] = []

    with MCAPReplayReader(mcap_path) as reader:
        for msg in reader.iter_messages():
            if msg.channel == CHANNEL_SELF_ASSESSMENT:
                decoded_sa = decode_message(msg)
                if isinstance(decoded_sa, BeliefSelfAssessment):
                    assessments_by_stamp[decoded_sa.belief_stamp_sim_ns] = (
                        decoded_sa
                    )
            elif msg.channel == CHANNEL_DECISIONS:
                decoded_d = decode_message(msg)
                if isinstance(decoded_d, DecisionRationale):
                    rationales.append(decoded_d)

    records: list[DecisionTraceRecord] = []
    verified = 0
    broken = 0
    missing = 0
    no_claim = 0
    per_kind: dict[str, int] = {}
    per_policy: dict[str, int] = {}
    timestamps: list[int] = []

    for r in rationales:
        stamp = r.belief_stamp_sim_ns
        claimed_sha = r.self_assessment_sha256
        recomputed_sha: str | None = None
        status: ChainStatus

        if claimed_sha is None:
            status = ChainStatus.NO_ASSESSMENT_CLAIMED
            no_claim += 1
        else:
            assessment = assessments_by_stamp.get(stamp)
            if assessment is None:
                status = ChainStatus.ASSESSMENT_MISSING
                missing += 1
            else:
                recomputed_sha = self_assessment_sha256(assessment)
                if recomputed_sha == claimed_sha:
                    status = ChainStatus.VERIFIED
                    verified += 1
                else:
                    status = ChainStatus.BROKEN
                    broken += 1

        records.append(
            DecisionTraceRecord(
                timestamp_ns=stamp,
                decision_kind=r.decision.kind,
                decision_reason=r.decision.reason,
                policy_id=r.policy_id,
                claimed_assessment_sha256=claimed_sha,
                recomputed_assessment_sha256=recomputed_sha,
                chain_status=status,
            )
        )

        kind_key = r.decision.kind.value
        per_kind[kind_key] = per_kind.get(kind_key, 0) + 1
        per_policy[r.policy_id] = per_policy.get(r.policy_id, 0) + 1
        timestamps.append(stamp)

    if timestamps:
        ts_first: int | None = min(timestamps)
        ts_last: int | None = max(timestamps)
        # Type narrowing for mypy after min/max on non-empty list.
        assert ts_first is not None
        assert ts_last is not None
        ts_span: int | None = ts_last - ts_first
    else:
        ts_first = None
        ts_last = None
        ts_span = None

    return DecisionTraceReport(
        source_mcap_sha256=source_sha,
        total_decisions=len(records),
        verified_count=verified,
        broken_count=broken,
        assessment_missing_count=missing,
        no_assessment_claimed_count=no_claim,
        per_decision_kind_counts=dict(sorted(per_kind.items())),
        per_policy_id_counts=dict(sorted(per_policy.items())),
        timestamp_first_ns=ts_first,
        timestamp_last_ns=ts_last,
        timestamp_span_ns=ts_span,
        records=tuple(records),
    )


# ---------------------------------------------------------------------------
# verify_decision_chain
# ---------------------------------------------------------------------------


def verify_decision_chain(
    mcap_path: Path,
) -> tuple[bool, tuple[str, ...]]:
    """Verifica la integridad de la cadena content-addressed del MCAP.

    Devuelve ``(True, ())`` sii ``broken_count == 0`` y
    ``assessment_missing_count == 0``. En caso de fallo, mensajes
    humanos por cada inconsistencia.

    Posture análogo a ``verify_run_manifest`` de ADR-0018: lectura
    pura del filesystem, salida deterministe ``(bool, tuple[str, ...])``,
    sin modificación.

    Note: ``no_assessment_claimed`` NO es un problema — es un caso
    legítimo donde el rationale explícitamente declaró que no se usó
    introspección.
    """
    report = build_decision_trace_report(mcap_path)
    messages: list[str] = []
    ok = True
    for r in report.records:
        if r.chain_status == ChainStatus.BROKEN:
            messages.append(
                f"sha256 mismatch at stamp {r.timestamp_ns}: "
                f"claimed={r.claimed_assessment_sha256} "
                f"recomputed={r.recomputed_assessment_sha256}"
            )
            ok = False
        elif r.chain_status == ChainStatus.ASSESSMENT_MISSING:
            messages.append(
                f"assessment missing at stamp {r.timestamp_ns}: "
                f"rationale claimed sha={r.claimed_assessment_sha256} "
                f"but no /self_assessment record at that stamp"
            )
            ok = False
    return (ok, tuple(messages))


# ---------------------------------------------------------------------------
# Encoder + decoder + writer
# ---------------------------------------------------------------------------


def encode_decision_trace_report_to_bytes(
    report: DecisionTraceReport,
) -> bytes:
    """Encode canonical JSON. ``sort_keys=True``, ``indent=2``,
    ``ensure_ascii=False``, trailing newline, UTF-8."""
    document = {
        "schema_version": DECISION_TRACE_REPORT_SCHEMA_VERSION,
        "trace": dataclasses.asdict(report),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def generate_decision_trace_report(
    report: DecisionTraceReport, output_path: Path
) -> None:
    """Write canonical JSON to ``output_path``."""
    output_path.write_bytes(encode_decision_trace_report_to_bytes(report))


def _decode_record(raw: Mapping[str, Any]) -> DecisionTraceRecord:
    return DecisionTraceRecord(
        timestamp_ns=raw["timestamp_ns"],
        decision_kind=DecisionKind(raw["decision_kind"]),
        decision_reason=raw["decision_reason"],
        policy_id=raw["policy_id"],
        claimed_assessment_sha256=raw["claimed_assessment_sha256"],
        recomputed_assessment_sha256=raw["recomputed_assessment_sha256"],
        chain_status=ChainStatus(raw["chain_status"]),
        analysis_version=raw.get(
            "analysis_version", DECISION_TRACE_ANALYSIS_VERSION
        ),
    )


def decode_decision_trace_report_from_json(
    data: Mapping[str, Any],
) -> DecisionTraceReport:
    """Reconstruct un ``DecisionTraceReport`` desde canonical JSON.

    Valida schema_version y analysis_version contra los literals.
    """
    inner = _validate_envelope(
        data,
        schema_version=DECISION_TRACE_REPORT_SCHEMA_VERSION,
        inner_key="trace",
    )
    analysis_version = inner.get(
        "analysis_version", DECISION_TRACE_ANALYSIS_VERSION
    )
    if analysis_version != DECISION_TRACE_ANALYSIS_VERSION:
        raise ValueError(
            f"incompatible analysis_version {analysis_version!r}; "
            f"expected {DECISION_TRACE_ANALYSIS_VERSION!r}"
        )
    return DecisionTraceReport(
        source_mcap_sha256=inner["source_mcap_sha256"],
        total_decisions=inner["total_decisions"],
        verified_count=inner["verified_count"],
        broken_count=inner["broken_count"],
        assessment_missing_count=inner["assessment_missing_count"],
        no_assessment_claimed_count=inner["no_assessment_claimed_count"],
        per_decision_kind_counts=dict(inner["per_decision_kind_counts"]),
        per_policy_id_counts=dict(inner["per_policy_id_counts"]),
        timestamp_first_ns=inner["timestamp_first_ns"],
        timestamp_last_ns=inner["timestamp_last_ns"],
        timestamp_span_ns=inner["timestamp_span_ns"],
        records=tuple(_decode_record(r) for r in inner["records"]),
        analysis_version=analysis_version,
    )


__all__ = [
    "DECISION_TRACE_ANALYSIS_VERSION",
    "DECISION_TRACE_REPORT_SCHEMA_VERSION",
    "ChainStatus",
    "DecisionTraceRecord",
    "DecisionTraceReport",
    "build_decision_trace_report",
    "decode_decision_trace_report_from_json",
    "encode_decision_trace_report_to_bytes",
    "generate_decision_trace_report",
    "verify_decision_chain",
]
