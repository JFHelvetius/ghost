"""ADR-0045 -- Epistemic Safety Contract framework (paper §3).

The five (now seven) properties Project Ghost ships
-- BAUD-v1, ERUR-v1, ERUR-v2, MD-v1, RLB-v1, FPB-v1, FPB-v2 --
were each introduced by an ADR with the same structural recipe:
property version string, a precondition + postcondition pair, a
``ScopeStatement`` (what the property claims and what it does NOT
claim), a pure-function verifier that consumes an MCAP and emits
a typed report, and a Hypothesis property test pinning the
verifier's invariants.

Until v0.2.5 the recipe was implicit -- every new property
re-derived it from the previous ones. v0.2.5 formalises the
recipe as a Python ``Protocol`` and ships a registry of all
shipped contracts. The benefits are:

- **A third party adding the eighth property no longer
  re-derives the recipe.** They subclass / conform to
  :class:`EpistemicSafetyContract` and the framework guarantees
  their property surface is consistent with the existing six.
- **The paper §3 can cite a single class definition** instead of
  six ad-hoc surfaces with the same shape.
- **Tooling can enumerate the property set programmatically**
  (e.g. for CI matrix generation, for an audit dashboard, for
  the verifier-discovery CLI).

This module is pure protocol + registry. It does NOT replace the
individual verifier functions ``verify_baud``, ``verify_erur``,
``verify_md``, ``verify_rlb``, ``verify_fpb``, ``verify_fpb_v2``,
``verify_erur_v2`` -- those remain the user-facing surface and
the v0.2.5 round is backwards-compatible. The contract objects
are *additional* descriptors that document each property and let
the framework reason about them as a class.

ADR-0045 §"Scope" enumerates exactly what this framework claims
and does NOT claim. It does NOT replace per-property ADRs
(0031-0035, 0039, 0040); it sits on top of them and makes their
shared shape explicit and machine-checkable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Scope statement (the "What this property claims / does NOT claim" block).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeStatement:
    """The "Scope" section every ADR carries, lifted to data.

    Every shipped property has a non-trivial scope. The fields are
    the three blocks the ADRs use uniformly: what is claimed, what
    is explicitly *not* claimed (the honest caveats), and what
    other properties this one depends on (e.g. FPB-v1 depends on
    BAUD-v1's precondition).
    """

    claims: tuple[str, ...]
    """Free-form bullets describing what the property formally
    asserts. Each bullet should be a complete sentence; the
    framework does not parse them but Hypothesis tests assert
    the tuple is non-empty for any registered contract."""

    does_not_claim: tuple[str, ...]
    """Free-form bullets describing what the property explicitly
    does NOT claim. The "honest caveats" section of each ADR.
    Non-empty for any non-trivial property; the framework
    enforces this so a contributor cannot register a contract
    that pretends to be unboundedly strong."""

    dependencies: tuple[str, ...] = ()
    """Property version strings (e.g. "BAUD-v1") that this
    property's precondition refers to. Empty when the property
    is structurally standalone (e.g. MD-v1)."""

    def __post_init__(self) -> None:
        if not isinstance(self.claims, tuple):
            raise TypeError(f"claims must be tuple; got {type(self.claims).__name__}")
        if not isinstance(self.does_not_claim, tuple):
            raise TypeError(
                f"does_not_claim must be tuple; got {type(self.does_not_claim).__name__}"
            )
        if not isinstance(self.dependencies, tuple):
            raise TypeError(f"dependencies must be tuple; got {type(self.dependencies).__name__}")
        if not self.claims:
            raise ValueError("ScopeStatement.claims must be non-empty")
        if not self.does_not_claim:
            raise ValueError("ScopeStatement.does_not_claim must be non-empty")


# ---------------------------------------------------------------------------
# Verification report Protocol.
# ---------------------------------------------------------------------------


@runtime_checkable
class VerificationReport(Protocol):
    """Minimal interface every verifier report exposes.

    The seven existing reports all carry ``mcap_sha256``,
    ``property_version``, and a ``holds`` property. This Protocol
    captures that contract. Concrete reports add property-specific
    fields (e.g. ``cycles_total``, ``violations``,
    ``confidence_upper_bound``); those are not part of the
    framework-level surface.
    """

    mcap_sha256: str
    property_version: str

    @property
    def holds(self) -> bool: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Verifier callable shape.
# ---------------------------------------------------------------------------


if TYPE_CHECKING:
    Verifier = Callable[..., VerificationReport]
    """Type of the verifier callable.

    Concrete signatures vary: ``verify_md(mcap_path)`` has no
    keyword arguments; ``verify_baud(mcap_path, *, min_outcomes,
    downgrade_threshold)`` has two; ``verify_fpb_v2`` has five.
    The framework treats them uniformly as ``Callable[..., R]``
    where R conforms to VerificationReport."""


# ---------------------------------------------------------------------------
# Epistemic Safety Contract Protocol.
# ---------------------------------------------------------------------------


@runtime_checkable
class EpistemicSafetyContract(Protocol):
    """The formal class definition behind paper §3.

    A property is shipped by Project Ghost iff it conforms to this
    Protocol. Conformance is structural (Python's typing-runtime
    checks instance attributes); it does not require subclassing.

    Each contract carries:

    - ``property_version`` -- string identifier like ``"BAUD-v1"``.
      Round-trips with verifier reports'
      :class:`VerificationReport.property_version` field, so a
      verdict bundle can be matched back to the contract that
      issued it.
    - ``scope`` -- the :class:`ScopeStatement` lifted from the
      ADR. The framework asserts non-empty ``claims`` and
      ``does_not_claim`` on every registered contract.
    - ``verifier`` -- the pure-function verifier from the
      ``properties.<name>`` module. Same callable, different
      access path.

    The Protocol is the **framework-level** surface; concrete
    contracts (one per property) live in this module's
    ``BUILTIN_CONTRACTS`` tuple.
    """

    @property
    def property_version(self) -> str: ...  # pragma: no cover

    @property
    def scope(self) -> ScopeStatement: ...  # pragma: no cover

    @property
    def verifier(self) -> object: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Concrete contract record + registry.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractRecord:
    """One row of the contract registry.

    Conforms to :class:`EpistemicSafetyContract` structurally
    (the three named properties are dataclass fields). Frozen so
    the registry cannot be mutated post-creation.
    """

    property_version: str
    scope: ScopeStatement
    verifier: object  # actually a Callable; widened to satisfy Protocol

    def __post_init__(self) -> None:
        if not self.property_version or not isinstance(self.property_version, str):
            raise ValueError(
                f"property_version must be a non-empty string; got {self.property_version!r}"
            )
        if not isinstance(self.scope, ScopeStatement):
            raise TypeError(f"scope must be ScopeStatement; got {type(self.scope).__name__}")
        if not callable(self.verifier):
            raise TypeError(f"verifier must be callable; got {type(self.verifier).__name__}")


_REGISTRY: dict[str, ContractRecord] = {}


def register_contract(record: ContractRecord) -> ContractRecord:
    """Add a contract to the framework registry. Idempotent on
    identical re-registration; raises on conflicting redefinition.

    Returns the record so module-level code can write
    ``BAUD_V1 = register_contract(ContractRecord(...))``.
    """
    existing = _REGISTRY.get(record.property_version)
    if existing is None:
        _REGISTRY[record.property_version] = record
        return record
    if existing is record:
        return record
    if existing.scope == record.scope and existing.verifier is record.verifier:
        return existing
    raise ValueError(
        f"Conflicting registration for {record.property_version!r}: "
        f"an earlier registration referenced a different verifier or scope."
    )


def list_contracts() -> tuple[ContractRecord, ...]:
    """Return all registered contracts, sorted by property
    version for deterministic iteration."""
    return tuple(sorted(_REGISTRY.values(), key=lambda r: r.property_version))


def get_contract(property_version: str) -> ContractRecord:
    """Look up a contract by property version string. Raises
    ``KeyError`` with the list of known versions on miss."""
    try:
        return _REGISTRY[property_version]
    except KeyError as exc:
        raise KeyError(
            f"No contract registered for {property_version!r}. Known: {sorted(_REGISTRY)}"
        ) from exc


__all__ = [
    "ContractRecord",
    "EpistemicSafetyContract",
    "ScopeStatement",
    "VerificationReport",
    "get_contract",
    "list_contracts",
    "register_contract",
]
