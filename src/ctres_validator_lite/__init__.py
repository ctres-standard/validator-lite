"""CTRES validator-lite.

Structural and Referential validation (§11) of packages in the Common Transaction Reporting and
Evidence Standard (CTRES) v1.1: the universal edition of v1.0 extended with the gaming revenue
statement (R13) and the venue count (R14). Packages produced under v1.0 remain valid. Profile
conformance, completeness and reconciliation are outside this package; they belong to the CTRES
conformance suite.
"""

__version__ = "1.1.0"

# Version of the ctres-standard/schema release vendored under schema/ (written by scripts/sync_schema.py).
SCHEMA_VERSION = "1.1.0"

# Version of the Standard this validator implements; manifest.json states it in standard_version.
STANDARD_VERSION = "1.1"

from .validator import LEVELS, RULES, SchemaError, validate  # noqa: E402

__all__ = ["LEVELS", "RULES", "SCHEMA_VERSION", "STANDARD_VERSION", "SchemaError", "__version__", "validate"]
