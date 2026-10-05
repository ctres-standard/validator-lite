"""CTRES validator-lite.

Structural and Referential validation (§11) of packages in the Common Transaction Reporting and
Evidence Standard (CTRES) v1.0, universal edition. Profile conformance, completeness and
reconciliation are outside this package; they belong to the CTRES conformance suite.
"""

__version__ = "1.0.0"

# Version of the ctres-standard/schema release vendored under schema/ (written by scripts/sync_schema.py).
SCHEMA_VERSION = "1.0.0"

# Version of the Standard this validator implements; manifest.json states it in standard_version.
STANDARD_VERSION = "1.0"

from .validator import RULES, SchemaError, validate  # noqa: E402

__all__ = ["RULES", "SCHEMA_VERSION", "STANDARD_VERSION", "SchemaError", "__version__", "validate"]
