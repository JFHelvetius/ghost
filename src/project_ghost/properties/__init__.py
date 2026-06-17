"""Formal properties of the Project Ghost closed loop.

Each property is a precisely-stated, falsifiable claim about the behaviour
of the system under a specified policy pair. Properties are introduced via
ADR (see ``docs/adr/0031-*`` for the framework) and verified end-to-end
against captured MCAPs.

Public surface:

- :class:`BAUDVerificationReport` and :func:`verify_baud` — verify ADR-0031
  (Bounded Action Under Drift) against any MCAP. ``report.holds`` is the
  citable veredicto.
"""

from __future__ import annotations

from .baud import (
    BAUD_PROPERTY_VERSION,
    BAUDVerificationReport,
    BAUDViolation,
    BAUDViolationKind,
    verify_baud,
)
from .contract import (
    ContractRecord,
    EpistemicSafetyContract,
    ScopeStatement,
    VerificationReport,
    get_contract,
    list_contracts,
    register_contract,
)
from .erur import (
    ERUR_PROPERTY_VERSION,
    ERURVerificationReport,
    ERURViolation,
    ERURViolationKind,
    verify_erur,
)
from .erur_v2 import (
    ERUR_V2_PROPERTY_VERSION,
    ERURv2VerificationReport,
    UnknownPolicyError,
    verify_erur_v2,
)
from .fpb import (
    FPB_PROPERTY_VERSION,
    FPBVerificationReport,
    FPBViolation,
    FPBViolationKind,
    verify_fpb,
)
from .fpb_v2 import (
    FPB_V2_PROPERTY_VERSION,
    ConfidenceMethod,
    FPBv2VerificationReport,
    FPBv2Violation,
    FPBv2ViolationKind,
    verify_fpb_v2,
)
from .framework import shipped_contracts
from .md import (
    MD_PROPERTY_VERSION,
    MDVerificationReport,
    MDViolation,
    MDViolationKind,
    verify_md,
)
from .rlb import (
    RLB_PROPERTY_VERSION,
    RLBVerificationReport,
    RLBViolation,
    RLBViolationKind,
    verify_rlb,
)

__all__ = [
    "BAUD_PROPERTY_VERSION",
    "ERUR_PROPERTY_VERSION",
    "ERUR_V2_PROPERTY_VERSION",
    "FPB_PROPERTY_VERSION",
    "FPB_V2_PROPERTY_VERSION",
    "MD_PROPERTY_VERSION",
    "RLB_PROPERTY_VERSION",
    "BAUDVerificationReport",
    "BAUDViolation",
    "BAUDViolationKind",
    "ConfidenceMethod",
    "ContractRecord",
    "ERURVerificationReport",
    "ERURViolation",
    "ERURViolationKind",
    "ERURv2VerificationReport",
    "EpistemicSafetyContract",
    "FPBVerificationReport",
    "FPBViolation",
    "FPBViolationKind",
    "FPBv2VerificationReport",
    "FPBv2Violation",
    "FPBv2ViolationKind",
    "MDVerificationReport",
    "MDViolation",
    "MDViolationKind",
    "RLBVerificationReport",
    "RLBViolation",
    "RLBViolationKind",
    "ScopeStatement",
    "UnknownPolicyError",
    "VerificationReport",
    "get_contract",
    "list_contracts",
    "register_contract",
    "shipped_contracts",
    "verify_baud",
    "verify_erur",
    "verify_erur_v2",
    "verify_fpb",
    "verify_fpb_v2",
    "verify_md",
    "verify_rlb",
]
