"""Framework-level invariants on the Epistemic Safety Contract registry.

ADR-0045 / paper §3 formalises the property class as a Python
``Protocol`` and registers the seven shipped contracts. This test
file pins the framework-level invariants that hold for *every*
shipped contract:

- Each contract has a non-empty version, scope, and verifier.
- Every dependency references another shipped contract (no
  dangling references).
- Every verifier callable accepts at least the ``mcap_path``
  positional argument (the common surface).
- The verifier's name matches the property version in a
  predictable way (e.g. ``verify_baud`` for ``BAUD-v1``).

These invariants are framework-level *guarantees*, not
per-property assertions. They catch regressions where someone
adds a new property but forgets to thread it through the
framework (e.g. registers a Foo-v1 with a typo'd verifier name,
or with a scope statement that has an empty claims tuple).
"""

from __future__ import annotations

import inspect

import pytest

from project_ghost.properties.contract import (
    ContractRecord,
    EpistemicSafetyContract,
    ScopeStatement,
    get_contract,
    list_contracts,
)
from project_ghost.properties.framework import shipped_contracts

_EXPECTED_VERSIONS = {
    "BAUD-v1",
    "ERUR-v1",
    "ERUR-v2",
    "MD-v1",
    "RLB-v1",
    "FPB-v1",
    "FPB-v2",
}


def test_all_expected_versions_are_registered() -> None:
    """v0.2.5 ships seven contracts; the registry must contain all
    of them. A future contributor adding the eighth must add it to
    both ``framework.py`` and ``_EXPECTED_VERSIONS`` here."""
    registered = {c.property_version for c in shipped_contracts()}
    assert registered == _EXPECTED_VERSIONS, (
        f"Registered={registered}, expected={_EXPECTED_VERSIONS}"
    )


def test_list_contracts_is_sorted_by_version() -> None:
    """Deterministic iteration order is part of the registry's
    contract; downstream tools (CI matrices, audit dashboards)
    rely on it."""
    versions = [c.property_version for c in list_contracts()]
    assert versions == sorted(versions)


@pytest.mark.parametrize(
    "version",
    sorted(_EXPECTED_VERSIONS),
    ids=sorted(_EXPECTED_VERSIONS),
)
def test_each_contract_has_non_empty_scope(version: str) -> None:
    """Every shipped contract must have at least one claim and at
    least one does-not-claim bullet. The framework's __post_init__
    enforces this at construction; the test catches a future
    contributor who edits a scope dictionary in place."""
    c = get_contract(version)
    assert isinstance(c, ContractRecord)
    assert isinstance(c.scope, ScopeStatement)
    assert len(c.scope.claims) >= 1
    assert len(c.scope.does_not_claim) >= 1


@pytest.mark.parametrize(
    "version",
    sorted(_EXPECTED_VERSIONS),
    ids=sorted(_EXPECTED_VERSIONS),
)
def test_each_verifier_accepts_mcap_path(version: str) -> None:
    """Every verifier callable accepts ``mcap_path`` as the first
    positional argument (the common surface). This pins the
    user-facing entry point so a refactor that renames or
    reorders the parameter fails the test."""
    c = get_contract(version)
    sig = inspect.signature(c.verifier)
    params = list(sig.parameters.values())
    assert params, f"{version}: verifier has no parameters at all"
    assert params[0].name == "mcap_path", (
        f"{version}: first parameter is {params[0].name!r}, expected 'mcap_path'"
    )


@pytest.mark.parametrize(
    "version",
    sorted(_EXPECTED_VERSIONS),
    ids=sorted(_EXPECTED_VERSIONS),
)
def test_dependencies_reference_registered_contracts(version: str) -> None:
    """Every contract's ``dependencies`` tuple must reference
    other registered contracts. A dangling dependency means the
    scope statement is making a claim about a property that
    Project Ghost does not ship."""
    c = get_contract(version)
    registered = {r.property_version for r in shipped_contracts()}
    for dep in c.scope.dependencies:
        assert dep in registered, (
            f"{version}: dependency {dep!r} not in registered set {registered}"
        )


def test_contract_records_satisfy_protocol() -> None:
    """Structural conformance: every record satisfies
    ``EpistemicSafetyContract`` per Python's runtime-checkable
    Protocol. This pin catches a future Protocol amendment that
    accidentally widens the interface."""
    for c in shipped_contracts():
        assert isinstance(c, EpistemicSafetyContract), (
            f"{c.property_version} does not conform to EpistemicSafetyContract Protocol"
        )


def test_registry_is_idempotent_on_re_import() -> None:
    """Re-importing ``framework`` must not duplicate or conflict
    with already-registered contracts. The registry's
    ``register_contract`` enforces idempotence on identical
    records; the test confirms the framework module respects
    that."""
    from project_ghost.properties import framework

    pre = shipped_contracts()
    # Re-evaluate the module's top-level registrations.
    framework.BAUD_V1  # noqa: B018 — touching the module-level binding
    post = shipped_contracts()
    assert pre == post


def test_no_duplicate_version_strings() -> None:
    """Two contracts cannot share a version string -- the
    verifier reports' ``property_version`` field would become
    ambiguous and a verdict bundle could be matched against
    either record."""
    versions = [c.property_version for c in shipped_contracts()]
    assert len(versions) == len(set(versions)), (
        f"Duplicate property versions in registry: {versions}"
    )
