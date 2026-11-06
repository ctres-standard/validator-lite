"""CTRES validator-lite.

Structural and Referential validation (§11) of packages in the Common Transaction Reporting and
Evidence Standard (CTRES) v1.1: the universal edition of v1.0 extended with the gaming revenue
statement (R13), the venue count (R14), the bet event (R15) and the streaming mode of §8.4, under
which the same records travel as a stream of events with a checkpoint per gaming day. The stream
checks (STM-01 to STM-07) and the reconciliation of a package with its stream (REC-01 to REC-04)
are part of this package. Packages produced under v1.0 remain valid. Profile conformance,
completeness and the reconciliation of statement totals with the records behind them are outside
this package; they belong to the CTRES conformance suite.
"""

__version__ = "1.1.1"

# Version of the ctres-standard/schema release vendored under schema/ (written by scripts/sync_schema.py).
SCHEMA_VERSION = "1.1.0"

# Version of the Standard this validator implements; manifest.json states it in standard_version.
STANDARD_VERSION = "1.1"

from .validator import LEVELS, RECONCILE_RULES, RULES, STREAM_RULES, SchemaError, validate, validate_stream  # noqa: E402

__all__ = ["LEVELS", "RECONCILE_RULES", "RULES", "SCHEMA_VERSION", "STANDARD_VERSION", "STREAM_RULES", "SchemaError",
           "__version__", "validate", "validate_stream"]
