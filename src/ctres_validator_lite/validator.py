"""
CTRES validator-lite: the Structural and Referential classes of validation (CTRES v1.1, §11), the checks
of a stream (§8.4) and the reconciliation of a package with the stream that carried its records.

A package is a directory holding manifest.json and one JSON Lines file per record type (§8.2). A stream is an
NDJSON file of events, each an envelope around one record (§8.4). Each check has an identifier, a class
(structural, referential, stream, reconciliation), a severity and the section of the Standard it rests on, so
that any finding can be traced and argued. Profile conformance, completeness and the agreement of
statement totals with the records behind them (including the money bridge of §4.13) are not checked
here: they depend on profile parameters, tolerances and materiality, and belong to the CTRES
conformance suite. Where the manifest declares a conformance level (§10), the record types the level requires
must be present (STR-09), and a reference to a record type the level does not require and the package does not
carry is reported as advisory rather than resolved. Packages produced under CTRES v1.0 are validated unchanged.

Import:  from ctres_validator_lite import validate, validate_stream  ->  result dict (see README, "JSON output")
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re
from calendar import isleap
from collections import namedtuple
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from . import SCHEMA_VERSION, STANDARD_VERSION, __version__

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"   # vendored copy of ctres-standard/schema
CONFORMANCE_SUITE = "https://ctres.org/validator"

# id, class, severity, basis in CTRES v1.1, what the check requires, what a failure means.
RULES = [
    ("STR-01", "structural", "blocking", "§8.2",
     "Every file named in the manifest is present in the package",
     "A file named in the manifest is missing"),
    ("STR-02", "structural", "blocking", "§8.2; §3 Deterministic and verifiable",
     "The SHA-256 of each file matches the hash recorded in the manifest",
     "A file differs from the file the manifest was sealed with"),
    ("STR-03", "structural", "blocking", "§8.2",
     "Each file holds the number of records the manifest declares",
     "A file holds a different number of records than the manifest declares"),
    ("STR-04", "structural", "blocking", "§4; Annex A",
     "Each record is a JSON object that validates against the schema of its record type: mandatory fields "
     "present, conditional fields present where the record shows the condition, no undefined fields",
     "Records are malformed, lack mandatory or conditional fields, or carry fields the schema does not define"),
    ("STR-05", "structural", "blocking", "§4; Annex A",
     "Enumerated fields carry values from the permitted list",
     "Fields carry values outside the permitted list"),
    ("STR-06", "structural", "blocking", "§8.2; §3 Currency-aware",
     "Amounts are decimal strings; timestamps are ISO 8601 with an explicit offset; dates are calendar dates",
     "Amounts are not decimal strings, or timestamps or dates are malformed"),
    ("STR-07", "structural", "blocking", "§4",
     "Record identifiers are unique within each record type, across every file that holds it",
     "A record identifier appears more than once in a record type"),
    ("STR-08", "structural", "blocking", "§8.2",
     "manifest.json is present and validates against the manifest schema",
     "The manifest is missing, malformed or incomplete"),
    ("STR-09", "structural", "blocking", "§10; Annex D",
     "Every record type the declared conformance level requires is listed in the manifest and present; at "
     "level_2 and above, R14 where any R13 line has channel venue",
     "Record types the declared conformance level requires are missing from the package"),

    ("REF-01", "referential", "blocking", "§4.1; §4.6; §4.7; §4.11",
     "Every funds location referenced by R3, R4, R7 or R11 is in R1; each side of an R6 movement is a "
     "location in R1 or a provider in R10",
     "Records refer to funds locations or movement counterparties that are in neither R1 nor R10"),
    ("REF-02", "referential", "blocking", "§4.3; §4.5",
     "Every check_ids entry on R3 and R4, and every R5 supersedes reference, resolves to an R5 check "
     "decision; supersedes chains do not loop",
     "Records refer to check decisions that do not exist"),
    ("REF-03", "referential", "blocking", "§4.2; §4.3; §4.4",
     "Every instrument_id on R3 and R4, and every source_instrument_ids entry, is an instrument in R2",
     "Payments refer to instruments that are not in the R2 register"),
    ("REF-04", "referential", "blocking", "§4.3; §11 Referential",
     "Each rail reference, taken with its rail_reference_type and provider_id, is booked once across R3 and R4",
     "The same rail payment is booked more than once"),
    ("REF-05", "referential", "blocking", "§4.10; §4.1; §4.3; §4.11; §6",
     "Every provider_id on R1, R3, R4 and R11, and every provider named in an R2 instrument_detail, is in R10",
     "Records refer to providers that are not in the R10 register"),
    ("REF-06", "referential", "blocking", "§4.7; §4.8; §4.9; §4.12",
     "R7 exception_ids resolve to R8; R8 source_statement_id resolves to R7; related_record_ids on R8, R9 "
     "and R12 resolve to a record or a rail reference in the package",
     "Statements, exceptions, incidents or report references point at records that do not exist"),
    ("REF-07", "referential", "advisory", "§8.2; §8.1",
     "R3 and R4 transactions are dated inside the period stated in the manifest",
     "Transactions are dated outside the reporting period"),
    ("REF-08", "referential", "blocking", "§4.7; §4.11",
     "Every attestation_ref on R3 and R4 resolves to an R11 attestation that covers the transaction's "
     "funds location",
     "Pooled-custody transactions point at no valid provider attestation"),
    ("REF-09", "referential", "blocking", "§4.13; §4.14; §8.2",
     "Every R13 statement period, and every R14 gaming day or period, lies within the period stated in the "
     "manifest",
     "Revenue statements or venue counts fall outside the reporting period"),
    ("REF-10", "referential", "blocking", "§4.13",
     "Every R13 correction's corrects_statement_id names the statement it replaces: another R13 statement of "
     "the same licence, product line, channel and currency, where the package carries it",
     "Corrections name themselves, each other, or a statement of another line as the statement they replace"),
    ("REF-11", "referential", "blocking", "§4.14; §4.1; §4.6",
     "Every R14 venue_id is carried by an R1 location, and every R14 drop_deposit_ref is an R6 movement or "
     "an R1 location",
     "Venue counts cite a venue no R1 location carries, or a drop banking that is in neither R6 nor R1"),
    ("REF-12", "referential", "blocking", "§4.13; §4.12",
     "Every authority_figure_ref on an R13 statement cites a report reference in R12",
     "Statements cite an authority figure whose report reference does not exist"),
    ("REF-13", "referential", "advisory", "§4.13",
     "ggr_declared on each R13 statement equals the formula the statement names, all_in or cash_only, applied "
     "to the statement's own stakes and winnings, exactly",
     "Statements declare a gross gaming revenue that does not follow their own formula"),
    ("REF-14", "referential", "blocking", "§4.15; §4.1",
     "Every R15 venue_id is carried by an R1 location",
     "Bet events cite a venue no R1 location carries"),
]

# The checks of a stream (§8.4), run by validate_stream and, with --reconcile, alongside the package checks.
STREAM_RULES = [
    ("STM-01", "stream", "blocking", "§8.4",
     "Every line is a JSON object that validates against the stream event envelope: stream_id, sequence, "
     "emitted_at, licence_number, standard_version, record_type, op and record present and well formed, no "
     "undefined fields; a checkpoint event carries op create",
     "Lines are not valid event envelopes"),
    ("STM-02", "stream", "blocking", "§8.4",
     "Within each stream, sequence numbers are strictly increasing from line to line, without gaps",
     "Sequence numbers go backwards or leave gaps"),
    ("STM-03", "stream", "blocking", "§8.4",
     "No (stream_id, sequence) pair repeats; a repeat with identical bytes is a redelivery, ignored and reported "
     "as advisory, a repeat with different bytes a conflict",
     "A sequence number repeats within a stream"),
    ("STM-04", "stream", "blocking", "§8.4",
     "The record of each event validates against the schema of its record_type, or against the checkpoint schema "
     "for record_type checkpoint; with op void the record carries at least the record's identifier",
     "Records do not validate against the schema of their record type, or a void carries no identifier"),
    ("STM-05", "stream", "blocking", "§8.4",
     "Each checkpoint's first_sequence, last_sequence and event_count match the events of its stream, and its "
     "chain_hash is the SHA-256 of those event lines as transmitted; a gaming day with events but no checkpoint "
     "is advisory",
     "Checkpoints do not match the events they cover, or a day with events has no checkpoint"),
    ("STM-06", "stream", "advisory", "§8.4",
     "An event with op update or void names a record identifier an earlier event of the stream created; advisory, "
     "since the create may predate the file",
     "Updates or voids name records no earlier event of the file created"),
    ("STM-07", "stream", "blocking", "§8.4",
     "Where a maximum latency is given, each event is emitted no later than that duration after its record's "
     "anchor timestamp: R3 credited_at; R4 paid_at, else requested_at; R5 performed_at; R6 executed_at; R8 "
     "raised_at; R9 detected_at; R15 settled_at where the event reports it, else placed_at; R7, R13 and R14 "
     "period_end",
     "Events are emitted later than the maximum latency allows"),
]

# The reconciliation of a package with the stream that carried its records (§8.4; §11).
RECONCILE_RULES = [
    ("REC-01", "reconciliation", "blocking", "§8.4; §11",
     "Every record whose final streamed state is live, its last event an op create or update, is in the package",
     "Streamed records are absent from the package"),
    ("REC-02", "reconciliation", "blocking", "§8.4; §11",
     "Every package record of a record type the stream carries was streamed",
     "Package records of a streamed type were never streamed"),
    ("REC-03", "reconciliation", "blocking", "§8.4; §11",
     "Each package record equals the final streamed state of the record, field by field; a record the stream "
     "withdrew with op void is not in the package",
     "Package records differ from their final streamed state"),
    ("REC-04", "reconciliation", "blocking", "§8.4; §11",
     "The manifest's stream_checkpoints are the checkpoints the stream carries, one for one and field by field",
     "The manifest's stream checkpoints differ from the stream's"),
]

# Record type -> (schema file under schema/, identifier field).
RECORDS = {
    "R1": ("records/r01_funds_location.schema.json", "location_id"),
    "R2": ("records/r02_payment_instrument_link.schema.json", "instrument_id"),
    "R3": ("records/r03_deposit.schema.json", "tx_id"),
    "R4": ("records/r04_withdrawal.schema.json", "tx_id"),
    "R5": ("records/r05_check_decision.schema.json", "check_id"),
    "R6": ("records/r06_internal_movement.schema.json", "movement_id"),
    "R7": ("records/r07_reconciliation_statement.schema.json", "statement_id"),
    "R8": ("records/r08_exception.schema.json", "exception_id"),
    "R9": ("records/r09_incident.schema.json", "incident_id"),
    "R10": ("records/r10_provider_register.schema.json", "provider_id"),
    "R11": ("records/r11_provider_attestation.schema.json", "attestation_id"),
    "R12": ("records/r12_report_reference.schema.json", "report_reference_id"),
    "R13": ("records/r13_gaming_revenue_statement.schema.json", "statement_id"),
    "R14": ("records/r14_venue_count.schema.json", "count_id"),
    "R15": ("records/r15_bet_event.schema.json", "bet_id"),
}

SEVERITY = {r[0]: r[2] for r in RULES + STREAM_RULES + RECONCILE_RULES}

# The anchor timestamp of each record type for the latency of its events (STM-07; §8.4; §5 Submission latency):
# the first field present with a timestamp. R15 is settled_at where the event reports it, else placed_at. R1, R2,
# R10, R11 and R12 are streamed on creation and change and have no anchor; nor has a checkpoint event.
ANCHORS = {"R3": ("credited_at", "settled_at", "initiated_at"), "R4": ("paid_at", "requested_at"),
           "R5": ("performed_at",), "R6": ("executed_at",), "R7": ("period_end",), "R8": ("raised_at",),
           "R9": ("detected_at",), "R13": ("period_end",), "R14": ("period_end",), "R15": ("settled_at", "placed_at")}

# An ISO 8601 duration in weeks, days, hours, minutes and seconds (years and months have no fixed length).
DURATION = re.compile(r"P(?=\d|T\d)(?:(\d+)W)?(?:(\d+)D)?(?:T(?=\d)(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?")

# Conformance levels of §10, defined by scope: the name of each level and the record types it requires at
# minimum. The core is the manifest with R3, R4, R7 and R13; the Custody module (R1, R2, R6, R10, R11) joins at
# level_3 and the Supervision module (R5, R8, R9, R12) at level_4. Any record type may be included at any level.
# R14, the Venue module, is required at level_2 and above where an R13 line has channel venue. The levels are
# those of v1.1: in a package that declares standard_version 1.0, conformance_level_declared keeps its v1.0
# meaning (a delivery level), so STR-09 is not run and references are resolved as for a package without a level.
CORE = ("R3", "R4", "R7", "R13")
LEVELS = {
    "level_1": ("Return", ("R13",)),
    "level_2": ("Evidence", CORE),
    "level_3": ("Custody", CORE + ("R1", "R2", "R6", "R10", "R11")),
    "level_4": ("Supervision", CORE + ("R1", "R2", "R6", "R10", "R11", "R5", "R8", "R9", "R12")),
}

# A plain file name, as manifest.schema.json requires. Other names are never opened.
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(jsonl|csv)$")

# related_record_ids may name records of these types; they are resolved only when the package
# carries all of them, so that a partial or sampled package (§8.1) is not reported for records
# it was never meant to hold.
RELATED_TYPES = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R10")

# R8 categories that by definition concern something absent from the records (§4.8): a bank line
# with no ledger entry, a provider credit not booked, a location outside the inventory. Their
# related_record_ids may name external references, provided the exception is anchored in the
# package by at least one reference that resolves.
EXTERNAL_CATEGORIES = ("external_movement_without_ledger_entry", "provider_credit_not_booked",
                       "location_outside_inventory")

# The fields that identify the line an R13 statement reports (§4.13): a correction replaces a statement of
# the same line, for the same licence, product line, channel and currency.
LINE_FIELDS = ("licence_ref", "product_line", "channel", "currency")

# The two formulas of §4.13 whose terms are fields of the statement itself: the formula in words, the fields
# added and the fields subtracted. A bonus field the line does not carry counts as zero. The third formula,
# profile, is the profile's own and is not applied here.
GGR_FORMULAS = {
    "all_in": ("(stakes_cash + stakes_bonus - stakes_refunded) - (winnings_cash + winnings_bonus)",
               ("stakes_cash", "stakes_bonus"), ("stakes_refunded", "winnings_cash", "winnings_bonus")),
    "cash_only": ("stakes_cash - stakes_refunded - winnings_cash",
                  ("stakes_cash",), ("stakes_refunded", "winnings_cash")),
}
BONUS_FIELDS = ("stakes_bonus", "winnings_bonus")

Rec = namedtuple("Rec", "data file line type")

JSON_WHITESPACE = " \t\r\n"             # the only white space JSON permits around a value (RFC 8259 §2)
BOM = "\ufeff"                           # byte order mark


def _real_day(value):
    """False for a string shaped as a date or timestamp whose day does not exist in its month, such as
    2026-02-29 or 2026-11-31. Anything else passes: the pattern of the type judges its shape."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2}))?", value) \
        if isinstance(value, str) else None
    if not m:
        return True                                                 # reported by the pattern
    year, month, day = map(int, m.groups()[:3])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return True                                                 # reported by the pattern
    return day <= (31, 29 if isleap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]


# Applied to the date and date-time types of common.schema.json only, never to free text that merely
# looks like a date. No other format is asserted.
FORMATS = FormatChecker(formats=())
FORMATS.checks("date")(_real_day)
FORMATS.checks("date-time")(_real_day)


class SchemaError(Exception):
    """The schema directory does not hold the CTRES schema files."""


class Schemas:
    """The CTRES JSON Schema, loaded into a local registry so that every $ref resolves offline."""

    def __init__(self, schema_dir=None):
        d = Path(schema_dir) if schema_dir else SCHEMA_DIR
        if (d / "schema" / "manifest.schema.json").is_file():   # root of a ctres-standard/schema checkout
            d = d / "schema"
        needed = ["manifest.schema.json", "common.schema.json", "stream/event.schema.json",
                  "stream/checkpoint.schema.json"] + [f for f, _ in RECORDS.values()]
        if missing := [f for f in needed if not (d / f).is_file()]:
            raise SchemaError(f"{d} does not hold the CTRES schema files (missing {', '.join(missing)})")
        docs = {p.relative_to(d).as_posix(): json.loads(p.read_text(encoding="utf-8")) for p in d.rglob("*.schema.json")}
        registry = Registry().with_resources(
            (s["$id"], Resource(contents=s, specification=DRAFT202012)) for s in docs.values())
        self.dir = d
        self.manifest = Draft202012Validator(docs["manifest.schema.json"], registry=registry, format_checker=FORMATS)
        self.records = {t: Draft202012Validator(docs[f], registry=registry, format_checker=FORMATS)
                        for t, (f, _) in RECORDS.items()}
        # The stream event envelope without its record dispatch (the allOf), so that the envelope is one check
        # (STM-01) and the record inside it another (STM-04), reported against the schema of its record type.
        envelope = copy.deepcopy(docs["stream/event.schema.json"])
        envelope.pop("allOf", None)
        self.envelope = Draft202012Validator(envelope, registry=registry, format_checker=FORMATS)
        self.checkpoint = Draft202012Validator(docs["stream/checkpoint.schema.json"], registry=registry, format_checker=FORMATS)
        common = docs["common.schema.json"]["$defs"]
        # Patterns of the decimal and timestamp types: a schema error under one of them is STR-06.
        self.format_patterns = {common[k]["pattern"] for k in ("decimal", "non_negative_decimal", "datetime", "date")}
        # Fields each record type defines, and the fields each rail module adds (§6).
        self.fields = {t: set(docs["payment.schema.json" if t in ("R3", "R4") else f]["properties"])
                       for t, (f, _) in RECORDS.items()}
        modules = docs["rail_modules.schema.json"]
        self.rail_module = modules["x-ctres-rail-to-module"]
        self.module_fields = {k: set(v.get("properties", {})) for k, v in modules["$defs"].items()}

    def undefined_fields(self, rtype, record):
        """Fields of a record that neither its record type nor the rail module applying to it defines.
        Computed here because a failing rail-module branch makes JSON Schema report that module's
        own fields as unevaluated, which would misreport permitted fields as undefined."""
        def value(key):
            return record.get(key) if isinstance(record.get(key), str) else None
        module = (f"transaction_{self.rail_module.get(value('rail'))}" if rtype in ("R3", "R4") else
                  "location_virtual_asset" if rtype == "R1" and value("location_type") == "crypto_wallet" else
                  "check_virtual_asset" if rtype == "R5" and value("check_type") == "blockchain_analytics" else None)
        allowed = self.fields[rtype] | self.module_fields.get(module, set())     # no module: R2, R6 to R14
        return [k for k in record if k not in allowed]


# ------------------------------------------------------------------ helpers

def _no_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    if dupes := sorted({k for k in keys if keys.count(k) > 1}):
        raise ValueError(f"field name repeated in one object: {', '.join(dupes)}")
    return dict(pairs)


def _no_constant(name):
    raise ValueError(f"{name} is not a JSON value")


def loads(text):
    """Strict JSON: no repeated field names, no NaN or Infinity. Errors are raised as ValueError."""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constant)
    except RecursionError:
        raise ValueError("values are nested too deeply to be read") from None


def parse_dt(value):
    """An ISO 8601 timestamp with an explicit offset as an aware datetime; None if it is not one."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})", value)
    if not m:
        return None
    seconds = min(int(m.group(2)), 59)                                       # a leap second counts as :59
    fraction = (m.group(3) or "0")[:6].ljust(6, "0")
    offset = "+00:00" if m.group(4) == "Z" else m.group(4)
    try:
        return datetime.fromisoformat(f"{m.group(1)}:{seconds:02d}.{fraction}{offset}")
    except ValueError:
        return None


def parse_date(value):
    """A calendar date YYYY-MM-DD as a date; None if it is not one."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _decimal(value):
    """A decimal string (§8.2) as a Decimal, exactly; None for anything else."""
    return Decimal(value) if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value) else None


def parse_duration(value):
    """An ISO 8601 duration in weeks, days, hours, minutes and seconds (PT60S, PT5M, P1D) as a timedelta; None if
    it is not one. Years and months are not accepted: they have no fixed length."""
    m = DURATION.fullmatch(value) if isinstance(value, str) else None
    if not m:
        return None
    weeks, days, hours, minutes, seconds = (float(g) if g else 0 for g in m.groups())
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


def _ranges(numbers):
    """Consecutive runs of sorted integers in words: '4', '4 to 6', '4 to 6 and 9'."""
    runs, start, prev = [], None, None
    for n in list(numbers) + [None]:
        if start is None:
            start = prev = n
        elif n is not None and n == prev + 1:
            prev = n
        else:
            runs.append(str(start) if start == prev else f"{start} to {prev}")
            start = prev = n
    return runs[0] if len(runs) == 1 else ", ".join(runs[:-1]) + " and " + runs[-1]


def _json(value):
    """A value as it appears in a finding: a string as it is, anything else as compact JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _path(parts):
    return "/".join(str(p) for p in parts) or None


def _find(node, target, at=()):
    """Path of the object `target` inside `node`, by identity."""
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for key, value in items:
        if value is target:
            return at + (key,)
        if (found := _find(value, target, at + (key,))) is not None:
            return found
    return None


def classify(err, patterns):
    """STR-05 for an enumeration error, STR-06 for a decimal or timestamp error, STR-04 otherwise.
    An anyOf error (for example a timestamp or not_recorded) is judged by the errors of its branches."""
    errors = [err, *err.context]
    if any(e.validator == "enum" for e in errors):
        return "STR-05"
    if any(isinstance(e.schema, dict) and e.schema.get("pattern") in patterns for e in errors):
        return "STR-06"
    return "STR-04"


def describe(err, record):
    """(field path, message) for a schema error, in words a reader can act on."""
    field = _path(err.absolute_path)
    if err.validator == "format" or (err.validator in ("anyOf", "oneOf") and isinstance(err.instance, str)
                                     and any(e.validator == "format" for e in err.context)):
        return field, f"{err.instance!r} is not a calendar date"
    if isinstance(err.schema, dict) and isinstance(err.schema.get("x-ctres-message"), str):
        return field, err.schema["x-ctres-message"]        # the rule in words, as the schema states it
    if err.schema is False:                    # a field the schema excludes for this direction, kind or status
        field = _path(_find(record, err.instance) or ())
        return field, "field not permitted for this record (excluded by its direction, kind or status)"
    if err.validator in ("anyOf", "oneOf") and all(
            isinstance(b, dict) and "required" in b and set(b) <= {"required", "properties"}
            and all(v is False for v in b.get("properties", {}).values()) for b in err.validator_value):
        # Branches that each require fields and may exclude the others' (the sides of an R6 movement; the
        # gaming day or the period of an R14 row).
        names = " or ".join(" and ".join(b["required"]) for b in err.validator_value)
        return field, ("exactly one of " if err.validator == "oneOf" else "at least one of ") + names + " is required"
    if err.validator == "required" and (m := re.match(r"'(.+)' is a required property$", err.message)):
        return _path([*err.absolute_path, m.group(1)]), "required field is missing"
    msg = err.message
    return field, msg if len(msg) <= 200 else msg[:197] + "..."


# ------------------------------------------------------------------ validation

def validate(package_dir, schema_dir=None, reconcile=None, max_latency=None):
    """Run every check over the package directory and return the result as a dict. With reconcile, the path of
    an NDJSON events file, the stream checks run over that file and the package is reconciled with it (REC-01 to
    REC-04); max_latency, an ISO 8601 duration, then also applies STM-07 to the stream."""
    pkg = Path(package_dir)
    schemas = Schemas(schema_dir)
    rules = RULES + (STREAM_RULES + RECONCILE_RULES if reconcile is not None else [])
    hits = {r[0]: [] for r in rules}
    notes = {r[0]: set() for r in rules}
    ran = {r[0]: True for r in rules}

    def rid(rec):
        value = rec.data.get(RECORDS[rec.type][1])
        return value if isinstance(value, str) else None

    def fail(rule, detail, rec=None, file=None, line=None, field=None, severity=None):
        """Record a finding. For a record, its file, line and identifier are taken from it. A finding carries the
        severity of its check unless the check downgrades it (a reference not resolved by level, §10)."""
        record = None
        if rec is not None:
            file, line, record = rec.file, rec.line, rid(rec)
            detail = f"{record}: {detail}" if record else detail
        hits[rule].append({"file": file, "line": line, "record": record, "field": field, "detail": detail,
                           "severity": severity or SEVERITY[rule]})

    # ------------------------------------------------------------ manifest
    # STR-08: manifest.json is present, is JSON, and validates against the manifest schema
    mpath = pkg / "manifest.json"
    manifest_bytes, manifest = None, None
    if not mpath.is_file():
        fail("STR-08", "manifest.json is not in the package", file="manifest.json")
    else:
        try:
            manifest_bytes = mpath.read_bytes()
        except OSError as exc:
            fail("STR-08", f"manifest.json cannot be read ({exc.strerror or exc})", file="manifest.json")
    fingerprint = hashlib.sha256(manifest_bytes).hexdigest() if manifest_bytes is not None else None
    if manifest_bytes is not None:
        try:
            text = manifest_bytes.decode("utf-8")
            if text.startswith(BOM):                               # reported, then read without it
                fail("STR-08", "manifest.json begins with a byte order mark (U+FEFF), which a JSON text "
                     "must not carry (RFC 8259 §8.1)", file="manifest.json")
                text = text[1:]
            manifest = loads(text)
        except ValueError as exc:                                  # includes UnicodeDecodeError
            fail("STR-08", f"manifest.json is not valid JSON: {exc}", file="manifest.json")
        if manifest is not None and not isinstance(manifest, dict):
            fail("STR-08", "manifest.json is not a JSON object", file="manifest.json")
    if not isinstance(manifest, dict):
        for r in rules:                                             # nothing else can run
            ran[r[0]] = r[0] == "STR-08"
        return _result(pkg, schemas, schema_dir, fingerprint, None, hits, notes, ran, rules)

    try:
        for err in sorted(schemas.manifest.iter_errors(manifest), key=lambda e: (list(map(str, e.absolute_path)), e.message)):
            field, msg = describe(err, manifest)
            fail("STR-08", f"{field + ': ' if field else ''}{msg}", file="manifest.json", field=field)
    except RecursionError:
        fail("STR-08", "manifest.json: values are nested too deeply to be validated", file="manifest.json")

    entries, listed = [], set()
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    for i, f in enumerate(files):
        if not isinstance(f, dict) or not isinstance(f.get("file"), str):
            continue                                                # reported by the schema above
        if f["file"] in listed:
            fail("STR-08", f"{f['file']} is listed more than once", file="manifest.json", field=f"files/{i}")
        elif SAFE_FILE.match(f["file"]):                           # other names are reported above, never opened
            listed.add(f["file"])
            entries.append(f)

    # ------------------------------------------------------------ files and records
    data = {t: [] for t in RECORDS}       # record type -> [Rec]
    present = set()                       # record types whose files were read
    first_seen = {t: {} for t in RECORDS}  # record type -> {identifier: (file, line)}
    root = pkg.resolve()
    for f in entries:
        name, rtype = f["file"], f.get("record_type")
        path = pkg / name
        declared_hash = f.get("sha256") if isinstance(f.get("sha256"), str) else None
        declared_count = f.get("record_count")
        if isinstance(declared_count, bool) or not isinstance(declared_count, int):
            declared_count = None             # a missing or malformed hash or count is reported by STR-08 alone

        # STR-01: the file is present, inside the package, and readable
        if not path.is_file():
            fail("STR-01", f"{name} is listed in the manifest but is not in the package", file=name)
            continue
        if path.resolve().parent != root:
            fail("STR-01", f"{name} is a link to a file outside the package; it was not read", file=name)
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            fail("STR-01", f"{name} is listed in the manifest but cannot be read ({exc.strerror or exc})", file=name)
            continue

        # STR-02: the file is the one the manifest was sealed with
        digest = hashlib.sha256(raw).hexdigest()
        if declared_hash is not None and digest != declared_hash.lower():
            fail("STR-02", f"{name}: SHA-256 of the file is {digest}; the manifest states {declared_hash}", file=name)

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail("STR-04", f"{name}: not valid UTF-8 ({exc.reason} at byte {exc.start})", file=name)
            continue
        if text.startswith(BOM):                                   # reported once, then read without it
            fail("STR-04", f"{name}: the file begins with a byte order mark (U+FEFF), which a JSON text must "
                 "not carry (RFC 8259 §8.1)", file=name, line=1)
            text = text[1:]

        if f.get("format") == "csv" or name.endswith(".csv"):
            # STR-03 for CSV (header row excluded); records in CSV are not parsed by validator-lite
            try:
                rows = [r for r in csv.reader(io.StringIO(text, newline="")) if r]
            except csv.Error as exc:
                fail("STR-04", f"{name}: not valid CSV ({exc})", file=name)
                continue
            held = max(len(rows) - 1, 0)
            if declared_count is not None and held != declared_count:
                fail("STR-03", f"{name}: the manifest declares {declared_count} records, the file holds {held}", file=name)
            notes["STR-04"].add(f"{name}: CSV file; its records were not validated (validator-lite reads JSON Lines)")
            continue

        # JSON Lines: records separated by \n (a \r before it is JSON white space); blank lines are skipped
        lines = [(n, s.strip(JSON_WHITESPACE)) for n, s in enumerate(text.split("\n"), 1) if s.strip(JSON_WHITESPACE)]

        # STR-03: the record count matches the manifest
        if declared_count is not None and len(lines) != declared_count:
            fail("STR-03", f"{name}: the manifest declares {declared_count} records, the file holds {len(lines)}", file=name)
        if not isinstance(rtype, str) or rtype not in RECORDS:
            continue                                                # unknown record type: reported by STR-08
        present.add(rtype)
        validator, idf, seen = schemas.records[rtype], RECORDS[rtype][1], first_seen[rtype]

        for n, line in lines:
            # STR-04: each line is a JSON object
            try:
                obj = loads(line)
            except ValueError as exc:
                fail("STR-04", f"not valid JSON ({exc})", file=name, line=n)
                continue
            if not isinstance(obj, dict):
                fail("STR-04", "not a JSON object", file=name, line=n)
                continue
            rec = Rec(obj, name, n, rtype)
            data[rtype].append(rec)

            # STR-04 / STR-05 / STR-06: the record validates against the schema of its type. A timestamp or
            # date whose day does not exist (2026-11-31), which the pattern alone admits, is STR-06.
            try:
                errors = sorted(validator.iter_errors(obj), key=lambda e: (list(map(str, e.absolute_path)), e.message))
                for err in errors:
                    if err.validator == "unevaluatedProperties" and not err.absolute_path:
                        if extra := schemas.undefined_fields(rtype, obj):
                            fail("STR-04", f"not defined for this record: {', '.join(extra)}", rec,
                                 field=extra[0] if len(extra) == 1 else None)
                        continue
                    field, msg = describe(err, obj)
                    fail(classify(err, schemas.format_patterns), f"{field + ': ' if field else ''}{msg}", rec, field=field)
            except RecursionError:
                fail("STR-04", "values are nested too deeply to be validated", rec)

            # STR-07: record identifiers are unique within the record type, across its files
            key = obj.get(idf)
            if isinstance(key, str):
                if key in seen:
                    at = f"line {seen[key][1]}" if seen[key][0] == name else f"{seen[key][0]} line {seen[key][1]}"
                    fail("STR-07", f"{idf} repeated; first on {at}", rec, field=idf)
                else:
                    seen[key] = (name, n)

    # STR-01 (note): data files in the package that the manifest does not list are not sealed and not read
    for p in sorted(pkg.iterdir()):
        if p.name not in listed and SAFE_FILE.match(p.name) and p.is_file():
            notes["STR-01"].add(f"{p.name} is in the package but not listed in the manifest; it was not read")

    # ------------------------------------------------------------ conformance level
    # STR-09: the record types the declared level requires are listed in the manifest (that each listed file is
    # present and readable is STR-01), and R14 where an R13 line is a venue line. The levels are those of §10 of
    # v1.1; in a 1.0 package the field keeps its v1.0 meaning, and a value outside the enumeration is STR-08.
    declared, version = manifest.get("conformance_level_declared"), manifest.get("standard_version")
    level = declared if version == "1.1" and declared in LEVELS else None
    if level is None:
        ran["STR-09"] = False
        if declared is None:
            why = "the manifest declares no conformance level"
        elif version == "1.0" and declared in ("level_1", "level_2", "level_3"):
            why = (f"the package declares standard_version 1.0, under which conformance_level_declared {declared} "
                   "is a delivery level of v1.0, not a level of §10 of v1.1")
        elif version not in ("1.0", "1.1"):
            why = "the manifest's standard_version is not readable (reported by STR-08)"
        else:
            why = f"conformance_level_declared {declared!r} is not a level of §10 (reported by STR-08)"
        notes["STR-09"].add(f"not run: {why}")
    else:
        name, required = LEVELS[level]
        listed_types = {f.get("record_type") for f in entries}
        for rtype in sorted(required, key=lambda t: int(t[1:])):
            if rtype not in listed_types:
                fail("STR-09", f"{rtype} is required at {level} ({name}) but the manifest lists no {rtype} file",
                     file="manifest.json", field="files")
        venue_lines = [rid(r) or "a statement without statement_id" for r in data["R13"] if r.data.get("channel") == "venue"]
        if level != "level_1" and venue_lines and "R14" not in listed_types:
            fail("STR-09", f"R14 is required at {level} ({name}) because an R13 line has channel venue "
                 f"({', '.join(venue_lines[:3])}{', ...' if len(venue_lines) > 3 else ''}) but the manifest lists "
                 "no R14 file", file="manifest.json", field="files")

    # ------------------------------------------------------------ referential
    def strings(values):
        return {v for v in values if isinstance(v, str)}

    index = {t: strings(r.data.get(RECORDS[t][1]) for r in data[t]) for t in RECORDS}
    downgraded = set()

    def unresolved(rule, key, rtypes):
        """A reference to record types the package does not carry. Where a level is declared and it requires none
        of the absent types, the reference is an identifier in the operator's own systems, present in the record
        and not resolved within the package (§10): one advisory finding per field and check. Otherwise, as for a
        package without a level, a note: the package may be partial or sampled (§8.1)."""
        absent = [t for t in rtypes if t not in present]
        if level is not None and not any(t in LEVELS[level][1] for t in absent):
            kinds = sorted(absent, key=lambda t: int(t[1:]))
            named = kinds[0] if len(kinds) == 1 else ", ".join(kinds[:-1]) + " and " + kinds[-1]
            verb = "is" if len(kinds) == 1 else "are"
            detail = f"{key} - not resolved: {named} {verb} not required at {level} and {verb} not in the package"
            if (rule, detail) not in downgraded:
                downgraded.add((rule, detail))
                fail(rule, detail, field=key, severity="advisory")
        else:
            notes[rule].add(f"{key} not resolved: the package carries no {', '.join(absent)} file")

    def ref(rule, rec, field, value, rtype):
        """True if value identifies a record of rtype; a finding if not; None if the package carries no rtype
        (noted, or an advisory finding where the declared level does not require rtype)."""
        if not isinstance(value, str):
            return None
        if rtype not in present:
            unresolved(rule, re.sub(r'/[0-9]+$', '', field), (rtype,))
            return None
        if value in index[rtype]:
            return True
        fail(rule, f"{field} {value} is not in {rtype}", rec, field=field)
        return False

    def as_list(value):
        return value if isinstance(value, list) else []

    payments = data["R3"] + data["R4"]

    # REF-01: funds locations are in R1; each side of a movement is in R1 or R10
    for rec in payments:
        ref("REF-01", rec, "location_id", rec.data.get("location_id"), "R1")
    for rec in data["R7"]:
        if rec.data.get("kind") == "location":
            ref("REF-01", rec, "location_id", rec.data.get("location_id"), "R1")
    for rec in data["R11"]:
        for i, loc in enumerate(as_list(rec.data.get("covers_location_ids"))):
            ref("REF-01", rec, f"covers_location_ids/{i}", loc, "R1")
    for rec in data["R6"]:                         # that at least one side is a location is STR-04 (schema anyOf)
        for side in ("source", "destination"):
            ref("REF-01", rec, f"{side}_location_id", rec.data.get(f"{side}_location_id"), "R1")
            ref("REF-01", rec, f"{side}_provider_id", rec.data.get(f"{side}_provider_id"), "R10")

    # REF-02: check references resolve to R5 decisions; supersedes chains do not loop
    for rec in payments:
        for i, check in enumerate(as_list(rec.data.get("check_ids"))):     # not_recorded is not a list
            ref("REF-02", rec, f"check_ids/{i}", check, "R5")
    supersedes = {r.data.get("check_id"): r.data.get("supersedes") for r in data["R5"]
                  if isinstance(r.data.get("check_id"), str) and isinstance(r.data.get("supersedes"), str)}
    for rec in data["R5"]:
        cid = rec.data.get("check_id")
        if ref("REF-02", rec, "supersedes", rec.data.get("supersedes"), "R5") and isinstance(cid, str):
            seen, cur = {cid}, supersedes[cid]
            while cur in supersedes and cur not in seen:
                seen.add(cur)
                cur = supersedes[cur]
            if cur == cid:
                fail("REF-02", f"the supersedes chain returns to {cid}", rec, field="supersedes")

    # REF-03: instruments used by payments are in the R2 register
    for rec in payments:
        ref("REF-03", rec, "instrument_id", rec.data.get("instrument_id"), "R2")
        for i, inst in enumerate(as_list(rec.data.get("source_instrument_ids"))):
            ref("REF-03", rec, f"source_instrument_ids/{i}", inst, "R2")

    # REF-04: each rail payment is booked once across R3 and R4
    booked = {}
    for rec in payments:
        key = tuple(rec.data.get(k) for k in ("rail_reference_type", "provider_id", "rail_reference"))
        if not all(isinstance(k, str) for k in key):
            continue                                                # missing parts are reported by STR-04
        if key in booked:
            first = booked[key]
            fail("REF-04", f"{key[0]} {key[2]} ({key[1]}) is already booked by {rid(first) or 'another record'} "
                 f"({first.file} line {first.line})", rec, field="rail_reference")
        else:
            booked[key] = rec

    # REF-05: providers are in the R10 register
    for rtype in ("R1", "R3", "R4", "R11"):
        for rec in data[rtype]:
            ref("REF-05", rec, "provider_id", rec.data.get("provider_id"), "R10")
    for rec in data["R2"]:
        detail = rec.data.get("instrument_detail")
        for name in ("mobile_operator_id", "voucher_issuer_id"):
            if isinstance(detail, dict):
                ref("REF-05", rec, f"instrument_detail/{name}", detail.get(name), "R10")

    # REF-06: statements, exceptions, incidents and report references point at records that exist
    for rec in data["R7"]:
        for i, exc_id in enumerate(as_list(rec.data.get("exception_ids"))):
            ref("REF-06", rec, f"exception_ids/{i}", exc_id, "R8")
    for rec in data["R8"]:
        ref("REF-06", rec, "source_statement_id", rec.data.get("source_statement_id"), "R7")
    related = [rec for t in ("R8", "R9", "R12") for rec in data[t] if as_list(rec.data.get("related_record_ids"))]
    if related and any(t not in present for t in RELATED_TYPES):
        unresolved("REF-06", "related_record_ids", RELATED_TYPES)
    elif related:
        # A related record is a record of any type, or a rail reference, ledger entry, authority reference
        # or transaction hash carried by R3, R4 or R6.
        anchors = set().union(*index.values()) | strings(
            r.data.get(k) for r in payments + data["R6"]
            for k in ("rail_reference", "ledger_entry_ref", "authority_reference", "tx_hash"))
        anchors.discard("not_recorded")
        for rec in related:
            refs = [(i, x) for i, x in enumerate(as_list(rec.data.get("related_record_ids"))) if isinstance(x, str)]
            missing = [(i, x) for i, x in refs if x not in anchors]
            if rec.type == "R8" and rec.data.get("category") in EXTERNAL_CATEGORIES:
                statement = rec.data.get("source_statement_id")
                anchored = len(missing) < len(refs) or (isinstance(statement, str) and statement in index["R7"])
                missing = [] if anchored else missing
            for i, x in missing:
                fail("REF-06", f"related record {x} is not in the package", rec, field=f"related_record_ids/{i}")

    # REF-07 and REF-09 compare dates with the manifest period; neither runs without a usable period
    start, end = parse_dt(manifest.get("period_start")), parse_dt(manifest.get("period_end"))
    unusable = ("the manifest period is not readable" if start is None or end is None else
                "the manifest period ends before it starts" if end < start else None)
    for rule in ("REF-07", "REF-09"):
        if unusable:
            ran[rule] = False
            notes[rule].add(f"not run: {unusable}")
    span = None if unusable else f"the period {manifest['period_start']} to {manifest['period_end']}"

    # REF-07: transactions are dated inside the manifest period (credited_at; else settled_at, initiated_at)
    if span:
        for rec in payments:
            field = next((k for k in ("credited_at", "settled_at", "initiated_at") if parse_dt(rec.data.get(k))), None)
            if field and not start <= parse_dt(rec.data[field]) <= end:
                fail("REF-07", f"{field} {rec.data[field]} is outside {span}", rec, field=field)

    # REF-08: attestation references resolve to an R11 attestation that covers the transaction's location
    attestations = {r.data.get("attestation_id"): r.data for r in data["R11"] if isinstance(r.data.get("attestation_id"), str)}
    for rec in payments:
        att, loc = rec.data.get("attestation_ref"), rec.data.get("location_id")
        if ref("REF-08", rec, "attestation_ref", att, "R11") and isinstance(loc, str) \
                and loc not in as_list(attestations[att].get("covers_location_ids")):
            fail("REF-08", f"attestation {att} does not cover funds location {loc}", rec, field="attestation_ref")

    # REF-09: statement periods and gaming days lie within the manifest period. A gaming day is a calendar date,
    # compared with the dates of the period boundaries, each in the offset the manifest states for it.
    if span:
        for rec in data["R13"] + data["R14"]:
            for key in ("period_start", "period_end"):
                if (t := parse_dt(rec.data.get(key))) is not None and not start <= t <= end:
                    fail("REF-09", f"{key} {rec.data[key]} is outside {span}", rec, field=key)
            if (day := parse_date(rec.data.get("gaming_day"))) is not None and not start.date() <= day <= end.date():
                fail("REF-09", f"gaming_day {rec.data['gaming_day']} is outside {span}", rec, field="gaming_day")

    # REF-10: a correction names the statement it replaces: another statement of the same line, where the package
    # carries it. A statement the package does not carry may belong to an earlier package: noted, not reported.
    statements = {rid(r): r.data for r in data["R13"] if rid(r)}
    corrects = {s: d["corrects_statement_id"] for s, d in statements.items()
                if isinstance(d.get("corrects_statement_id"), str)}
    for rec in data["R13"]:
        target, sid = rec.data.get("corrects_statement_id"), rid(rec)
        if not isinstance(target, str):
            continue                                                # a period statement, or STR-04
        if target not in index["R13"]:
            notes["REF-10"].add(f"corrects_statement_id {target} not resolved: the package does not carry the "
                                "statement it replaces, which may belong to an earlier package")
        elif target == sid:
            fail("REF-10", "names itself as the statement it replaces", rec, field="corrects_statement_id")
        elif differs := [k for k in LINE_FIELDS if statements[target].get(k) != rec.data.get(k)]:
            fail("REF-10", f"corrects_statement_id {target} is a statement of another line: " + "; ".join(
                f"{k} {statements[target].get(k)}, not {rec.data.get(k)}" for k in differs), rec,
                field="corrects_statement_id")
        elif sid is not None:                                       # corrections of corrections: no loop
            seen, cur = {sid}, target
            while cur in corrects and cur not in seen:
                seen.add(cur)
                cur = corrects[cur]
            if cur == sid:
                fail("REF-10", f"the corrects_statement_id chain returns to {sid}", rec, field="corrects_statement_id")

    # REF-11: venue counts cite a venue an R1 location carries, and bank the drop to an R6 movement or an R1 location
    venues = strings(r.data.get("venue_id") for r in data["R1"])
    for rec in data["R14"]:
        venue = rec.data.get("venue_id")
        if isinstance(venue, str) and venue not in venues:
            if "R1" not in present:
                unresolved("REF-11", "venue_id", ("R1",))
            elif not venues:
                notes["REF-11"].add("venue_id not resolved: no R1 location carries venue_id")
            else:
                fail("REF-11", f"venue_id {venue} is carried by no R1 location", rec, field="venue_id")
        drop = rec.data.get("drop_deposit_ref")
        if isinstance(drop, str) and not any(drop in index[t] for t in ("R6", "R1") if t in present):
            if any(t not in present for t in ("R6", "R1")):
                unresolved("REF-11", "drop_deposit_ref", ("R6", "R1"))
            else:
                fail("REF-11", f"drop_deposit_ref {drop} is neither an R6 movement nor an R1 location", rec,
                     field="drop_deposit_ref")

    # REF-12: the authority's own figure on a statement cites the R12 report reference that carries it
    for rec in data["R13"]:
        figure = rec.data.get("authority_figure_ref")
        if isinstance(figure, dict):
            ref("REF-12", rec, "authority_figure_ref/report_reference_id", figure.get("report_reference_id"), "R12")

    # REF-13: the declared gross gaming revenue follows the formula the statement names, applied exactly to the
    # statement's own fields. This is the statement's internal consistency, not its reconciliation to R3, R4
    # and R7 (the money bridge), which needs the profile's tolerance and belongs to the conformance suite.
    for rec in data["R13"]:
        if rec.data.get("ggr_formula") == "profile":
            notes["REF-13"].add("statements with ggr_formula profile are not tested: the formula is the profile's")
        if not (formula := GGR_FORMULAS.get(rec.data.get("ggr_formula"))):
            continue
        text, plus, minus = formula
        amounts = {k: _decimal(rec.data.get(k, "0" if k in BONUS_FIELDS else None)) for k in plus + minus}
        declared = _decimal(rec.data.get("ggr_declared"))
        if declared is None or None in amounts.values():
            continue                                                # malformed amounts are STR-04 or STR-06
        expected = sum(amounts[k] for k in plus) - sum(amounts[k] for k in minus)
        if declared != expected:
            fail("REF-13", f"ggr_declared {rec.data['ggr_declared']} differs from the {rec.data['ggr_formula']} "
                 f"formula on the statement's own fields: {text} = {expected}", rec, field="ggr_declared")

    # REF-14: bet events cite a venue an R1 location carries, resolved as REF-11 resolves a venue count's venue
    for rec in data["R15"]:
        venue = rec.data.get("venue_id")
        if isinstance(venue, str) and venue not in venues:
            if "R1" not in present:
                unresolved("REF-14", "venue_id", ("R1",))
            elif not venues:
                notes["REF-14"].add("venue_id not resolved: no R1 location carries venue_id")
            else:
                fail("REF-14", f"venue_id {venue} is carried by no R1 location", rec, field="venue_id")

    # ------------------------------------------------------------ reconciliation with the stream
    stream = None
    if reconcile is not None:
        stream = _read_stream(Path(reconcile), schemas, hits, notes, ran, max_latency)
        _reconcile(stream, manifest, data, index, present, level, hits, notes)

    return _result(pkg, schemas, schema_dir, fingerprint, manifest, hits, notes, ran, rules, stream)


# ------------------------------------------------------------------ streams (§8.4)

Event = namedtuple("Event", "data line raw stream sequence rtype op rid")


class Stream:
    """What a stream file holds, once read: the events that count (one per stream and sequence, the first of any
    repeat), the final state of each record, the checkpoints, and the lines each checkpoint covers."""

    def __init__(self, path, digest):
        self.path, self.fingerprint = path, digest
        self.lines = 0                       # non-blank lines
        self.events = []                     # Event, in file order, repeats excluded
        self.final = {}                      # (record type, identifier) -> Event with the latest state
        self.checkpoints = []                # (Event, checkpoint record) for every valid checkpoint event
        self.streams = {}                    # stream_id -> {"lines": {sequence: (line, raw, is checkpoint)}, ...}
        self.types = {}                      # record type -> number of events
        self.licences = set()
        self.max_latency = None

    def summary(self):
        return {"path": str(self.path), "fingerprint": self.fingerprint, "lines": self.lines,
                "events": len(self.events), "checkpoints": len(self.checkpoints),
                "streams": {s: {"first_sequence": info["first"], "last_sequence": info["last"],
                                "events": info["events"], "checkpoints": info["checkpoints"]}
                            for s, info in self.streams.items()},
                "record_types": {t: self.types[t] for t in sorted(self.types, key=lambda t: (t == "checkpoint", int(t[1:]) if t[1:].isdigit() else 0))},
                "max_latency": self.max_latency}


def validate_stream(events_path, schema_dir=None, max_latency=None):
    """Run the stream checks STM-01 to STM-07 over an NDJSON events file and return the result as a dict.
    max_latency is an ISO 8601 duration (PT60S); without it STM-07 is not run."""
    path = Path(events_path)
    schemas = Schemas(schema_dir)
    hits = {r[0]: [] for r in STREAM_RULES}
    notes = {r[0]: set() for r in STREAM_RULES}
    ran = {r[0]: True for r in STREAM_RULES}
    stream = _read_stream(path, schemas, hits, notes, ran, max_latency)
    return _result(None, schemas, schema_dir, None, None, hits, notes, ran, STREAM_RULES, stream)


def _read_stream(path, schemas, hits, notes, ran, max_latency):
    """Read an events file and apply STM-01 to STM-07, recording findings in hits; return the Stream."""
    latency = None
    if max_latency is not None:
        if (latency := parse_duration(max_latency)) is None:
            raise ValueError(f"{max_latency!r} is not an ISO 8601 duration in weeks, days, hours, minutes and seconds")
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise SchemaError(f"{path} cannot be read ({exc.strerror or exc})") from None
    stream = Stream(path, hashlib.sha256(raw_bytes).hexdigest())
    stream.max_latency = max_latency
    name = path.name

    def fail(rule, detail, ev=None, line=None, field=None, severity=None):
        """A finding on an event: its line, its record identifier, and the sequence in the detail."""
        record = None
        if ev is not None:
            line, record = ev.line, ev.rid
            detail = f"sequence {ev.sequence}" + (f" ({record})" if record else "") + f": {detail}"
        hits[rule].append({"file": name, "line": line, "record": record, "field": field, "detail": detail,
                           "severity": severity or SEVERITY[rule]})

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail("STM-01", f"{name}: not valid UTF-8 ({exc.reason} at byte {exc.start})")
        for rule in ("STM-02", "STM-03", "STM-04", "STM-05", "STM-06", "STM-07"):
            ran[rule] = False
            notes[rule].add("not run: the file is not valid UTF-8")
        return stream
    if text.startswith(BOM):
        fail("STM-01", f"{name}: the file begins with a byte order mark (U+FEFF), which a JSON text must not carry "
             "(RFC 8259 §8.1)", line=1)
        text = text[1:]
    if latency is None:
        ran["STM-07"] = False
        notes["STM-07"].add("not run: no maximum latency given (--max-latency)")

    seen = {}                                     # (stream_id, sequence) -> (line, raw)
    created = set()                               # (stream_id, record type, identifier) with an op create seen
    no_anchor = set()
    for n, line in enumerate(text.split("\n"), 1):
        raw = line[:-1] if line.endswith("\r") else line     # the line as transmitted, the line ending aside
        stripped = raw.strip(JSON_WHITESPACE)
        if not stripped:
            continue
        stream.lines += 1

        # STM-01: the line is a JSON object that validates against the envelope
        try:
            obj = loads(stripped)
        except ValueError as exc:
            fail("STM-01", f"not valid JSON ({exc})", line=n)
            continue
        if not isinstance(obj, dict):
            fail("STM-01", "not a JSON object", line=n)
            continue
        sid, seq, rtype, op, record = (obj.get(k) for k in ("stream_id", "sequence", "record_type", "op", "record"))
        usable = isinstance(sid, str) and isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1
        idf = RECORDS[rtype][1] if rtype in RECORDS else None
        rid = record.get(idf) if idf and isinstance(record, dict) and isinstance(record.get(idf), str) else None
        ev = Event(obj, n, raw, sid if usable else None, seq if usable else None, rtype, op, rid)
        for err in sorted(schemas.envelope.iter_errors(obj), key=lambda e: (list(map(str, e.absolute_path)), e.message)):
            field, msg = describe(err, obj)
            if err.validator == "additionalProperties" and (m := re.match(r"Additional properties are not allowed \((.+) (?:was|were) unexpected\)$", err.message)):
                field, msg = None, f"not defined for the envelope: {m.group(1).replace(chr(39), '')}"
            fail("STM-01", f"{field + ': ' if field else ''}{msg}", ev if usable else None, line=n, field=field)
        if rtype == "checkpoint" and op in ("update", "void"):
            fail("STM-01", f"op {op} is not permitted on a checkpoint event: a checkpoint carries op create",
                 ev if usable else None, line=n, field="op")
        if not usable:
            continue                                                # no stream or sequence: nothing to track

        # STM-03: a repeated (stream, sequence) is a redelivery when identical, a conflict when not; either way
        # the first copy stands and this one is not processed further
        if (sid, seq) in seen:
            first_line, first_raw = seen[(sid, seq)]
            if raw == first_raw:
                fail("STM-03", f"repeats line {first_line} with identical content: a redelivery, ignored", ev,
                     severity="advisory")
            else:
                fail("STM-03", f"repeats line {first_line} with different content", ev)
            continue
        seen[(sid, seq)] = (n, raw)
        info = stream.streams.setdefault(sid, {"lines": {}, "first": seq, "last": seq, "events": 0, "checkpoints": 0,
                                               "last_line": n})
        # STM-02: sequences increase from line to line without gaps; the first event of a stream sets its start
        if seq in info["lines"]:
            pass
        elif seq < info["last"] and info["events"]:
            fail("STM-02", f"follows sequence {info['last']} (line {info['last_line']}) of stream {sid}: sequences "
                 "do not increase", ev, field="sequence")
        elif seq > info["last"] + 1 and info["events"]:
            missing = _ranges(range(info["last"] + 1, seq))
            fail("STM-02", f"sequence{'s' if seq - info['last'] > 2 else ''} {missing} of stream {sid} "
                 f"{'are' if seq - info['last'] > 2 else 'is'} missing between line {info['last_line']} "
                 f"(sequence {info['last']}) and line {n}", ev, field="sequence")
        info["lines"][seq] = (n, raw, rtype == "checkpoint")
        info["first"], info["last"], info["last_line"] = min(info["first"], seq), max(info["last"], seq), n
        info["events"] += 1
        stream.events.append(ev)
        stream.types[rtype if isinstance(rtype, str) else "?"] = stream.types.get(rtype if isinstance(rtype, str) else "?", 0) + 1
        if isinstance(obj.get("licence_number"), str):
            stream.licences.add(obj["licence_number"])

        # STM-04: the record validates against the schema of its type; a void carries the identifier
        if not isinstance(record, dict) or op not in ("create", "update", "void") or \
                (rtype not in RECORDS and rtype != "checkpoint"):
            continue                                                # reported by STM-01
        if rtype == "checkpoint":
            errors = sorted(schemas.checkpoint.iter_errors(record), key=lambda e: (list(map(str, e.absolute_path)), e.message))
            for err in errors:
                field, msg = describe(err, record)
                field = f"record/{field}" if field else "record"
                fail("STM-04", f"{field}: {msg}", ev, field=field)
            if not errors and op == "create":
                stream.checkpoints.append((ev, record))
                info["checkpoints"] += 1
            continue
        if op == "void":
            if rid is None:
                fail("STM-04", f"op void: the record carries no {idf}, the identifier of an {rtype} record", ev,
                     field=f"record/{idf}")
        else:
            try:
                for err in sorted(schemas.records[rtype].iter_errors(record), key=lambda e: (list(map(str, e.absolute_path)), e.message)):
                    if err.validator == "unevaluatedProperties" and not err.absolute_path:
                        if extra := schemas.undefined_fields(rtype, record):
                            fail("STM-04", f"not defined for this record: {', '.join(extra)}", ev,
                                 field=f"record/{extra[0]}" if len(extra) == 1 else "record")
                        continue
                    field, msg = describe(err, record)
                    field = f"record/{field}" if field else "record"
                    fail("STM-04", f"{field}: {msg}", ev, field=field)
            except RecursionError:
                fail("STM-04", "values are nested too deeply to be validated", ev, field="record")
        if rid is None:
            continue                                                # no identifier: STM-04 (or STM-01) said so
        # STM-06: an update or void names a record an earlier event created
        key = (sid, rtype, rid)
        if op == "create":
            created.add(key)
        elif key not in created:
            fail("STM-06", f"op {op} names an {rtype} record no earlier event of stream {sid} created (the create "
                 "may predate the file)", ev, field=f"record/{idf}")
            created.add(key)
        stream.final[(rtype, rid)] = ev

        # STM-07: the event is emitted within the maximum latency of its anchor
        if latency is None:
            continue
        if rtype not in ANCHORS:
            no_anchor.add(rtype)
            continue
        anchor = next((k for k in ANCHORS[rtype] if parse_dt(record.get(k))), None)
        emitted = parse_dt(obj.get("emitted_at"))
        if anchor and emitted is not None and emitted - parse_dt(record[anchor]) > latency:
            late = emitted - parse_dt(record[anchor])
            fail("STM-07", f"emitted_at {obj['emitted_at']} is {late} after {anchor} {record[anchor]}, more than the "
                 f"maximum latency {max_latency}", ev, field="emitted_at")

    for rtype in sorted(no_anchor, key=lambda t: int(t[1:])):
        notes["STM-07"].add(f"{rtype} events are not tested: {rtype} is streamed on creation and change and has no "
                            "anchor timestamp")

    # STM-05: each checkpoint matches the events it covers; days with events but no checkpoint are advisory
    covered = {sid: [] for sid in stream.streams}
    for ev, cp in stream.checkpoints:
        sid, first, last, count = cp["stream_id"], cp["first_sequence"], cp["last_sequence"], cp["event_count"]
        if sid != ev.stream:
            fail("STM-05", f"the checkpoint names stream {sid} but was emitted on stream {ev.stream}", ev,
                 field="record/stream_id")
        if cp["licence_number"] != ev.data.get("licence_number"):
            fail("STM-05", f"the checkpoint names licence {cp['licence_number']} but the event licence "
                 f"{ev.data.get('licence_number')}", ev, field="record/licence_number")
        if last < first - 1:
            fail("STM-05", f"last_sequence {last} is below first_sequence {first}", ev, field="record/last_sequence")
            continue
        if count != last - first + 1:
            fail("STM-05", f"event_count {count} differs from last_sequence − first_sequence + 1 = {last - first + 1}",
                 ev, field="record/event_count")
        lines = stream.streams.get(sid, {"lines": {}})["lines"]
        if missing := [s for s in range(first, last + 1) if s not in lines]:
            fail("STM-05", f"sequence{'s' if len(missing) > 1 else ''} {_ranges(missing)} of stream {sid}, covered "
                 f"by the checkpoint, {'were' if len(missing) > 1 else 'was'} not seen; chain_hash not recomputed",
                 ev, field="record/chain_hash")
        else:
            digest = hashlib.sha256(b"".join(lines[s][1].encode("utf-8") + b"\n" for s in range(first, last + 1)
                                             if not lines[s][2])).hexdigest()
            if digest != cp["chain_hash"]:
                fail("STM-05", f"chain_hash {cp['chain_hash']} is not the SHA-256 of the event lines {first} to "
                     f"{last} of stream {sid} as transmitted, {digest}", ev, field="record/chain_hash")
        covered.setdefault(sid, []).append((first, last))
    for sid, info in stream.streams.items():
        days = {}
        for ev in stream.events:
            if ev.stream == sid and ev.rtype != "checkpoint" and not any(a <= ev.sequence <= b for a, b in covered[sid]):
                emitted = ev.data.get("emitted_at")
                day = emitted[:10] if isinstance(emitted, str) and parse_dt(emitted) else "an unreadable date"
                days.setdefault(day, []).append(ev.sequence)
        for day, seqs in sorted(days.items()):
            fail("STM-05", f"stream {sid}: {len(seqs)} event{'s' if len(seqs) != 1 else ''} of {day} (sequence"
                 f"{'s' if len(seqs) != 1 else ''} {_ranges(sorted(seqs))}) {'are' if len(seqs) != 1 else 'is'} "
                 "covered by no checkpoint", line=stream.streams[sid]["lines"][seqs[-1]][0], severity="advisory")
    return stream


def _reconcile(stream, manifest, data, index, present, level, hits, notes):
    """REC-01 to REC-04: the package against the final state of the stream and its checkpoints."""
    name = stream.path.name

    def fail(rule, detail, file=None, line=None, record=None, field=None, severity=None):
        hits[rule].append({"file": file, "line": line, "record": record, "field": field, "detail": detail,
                           "severity": severity or SEVERITY[rule]})

    def rid(rec):
        value = rec.data.get(RECORDS[rec.type][1])
        return value if isinstance(value, str) else None

    streamed = {rtype for rtype, _ in stream.final}

    # REC-01: every live final state is in the package; interim statements are superseded by the period statement
    absent, interim = set(), 0
    for (rtype, key), ev in stream.final.items():
        if ev.op == "void":
            continue
        if rtype == "R13" and ev.data["record"].get("statement_kind") == "interim":
            interim += 1
            continue
        if rtype not in present:
            absent.add(rtype)
        elif key not in index[rtype]:
            fail("REC-01", f"sequence {ev.sequence} ({key}): the final state of this {rtype} record is not in the "
                 "package", file=name, line=ev.line, record=key, field=f"record/{RECORDS[rtype][1]}")
    for rtype in sorted(absent, key=lambda t: int(t[1:])):
        if level is not None and rtype not in LEVELS[level][1]:
            fail("REC-01", f"{rtype} records - not reconciled: {rtype} is not required at {level} and is not in the "
                 "package", severity="advisory")
        else:
            notes["REC-01"].add(f"{rtype} records not reconciled: the package carries no {rtype} file")
    if interim:
        notes["REC-01"].add(f"{interim} R13 interim statement{'s are' if interim != 1 else ' is'} superseded by the "
                            "period statement and not expected in the package")

    # REC-02 and REC-03: every package record of a streamed type was streamed, and equals its final state
    for rtype in RECORDS:
        if rtype not in present:
            continue
        if rtype not in streamed:
            if data[rtype]:
                notes["REC-02"].add(f"{rtype} is not streamed: its records are not reconciled")
            continue
        for rec in data[rtype]:
            key = rid(rec)
            if key is None:
                continue                                            # STR-04
            ev = stream.final.get((rtype, key))
            if ev is None:
                fail("REC-02", f"{key}: never streamed", file=rec.file, line=rec.line, record=key)
            elif ev.op == "void":
                fail("REC-03", f"{key}: withdrawn by op void (sequence {ev.sequence}) but carried by the package",
                     file=rec.file, line=rec.line, record=key)
            elif rec.data != ev.data["record"]:
                fail("REC-03", f"{key}: differs from the final streamed state (sequence {ev.sequence}): "
                     + _diff(rec.data, ev.data["record"]), file=rec.file, line=rec.line, record=key)

    # REC-04: the manifest's checkpoints are the stream's, one for one and field by field
    listed = manifest.get("stream_checkpoints")
    listed = [cp for cp in listed if isinstance(cp, dict)] if isinstance(listed, list) else []

    def key_of(cp):
        return cp.get("stream_id"), cp.get("first_sequence"), cp.get("last_sequence")

    def words(cp):
        return f"stream {cp.get('stream_id')}, sequences {cp.get('first_sequence')} to {cp.get('last_sequence')}"

    in_stream = {key_of(cp): (ev, cp) for ev, cp in stream.checkpoints}
    in_manifest = {key_of(cp): i for i, cp in enumerate(listed)}
    for i, cp in enumerate(listed):
        found = in_stream.get(key_of(cp))
        if found is None:
            fail("REC-04", f"stream_checkpoints/{i} ({words(cp)}): the stream carries no such checkpoint",
                 file="manifest.json", field=f"stream_checkpoints/{i}")
        elif cp != found[1]:
            fail("REC-04", f"stream_checkpoints/{i} ({words(cp)}) differs from the checkpoint the stream carries "
                 f"(sequence {found[0].sequence}): " + _diff(cp, found[1], "manifest", "stream"),
                 file="manifest.json", field=f"stream_checkpoints/{i}")
    for key, (ev, cp) in in_stream.items():
        if key not in in_manifest:
            fail("REC-04", f"sequence {ev.sequence}: the checkpoint ({words(cp)}) is not listed in the manifest's "
                 f"stream_checkpoints{', which the manifest does not carry' if 'stream_checkpoints' not in manifest else ''}",
                 file=name, line=ev.line, field="record")


def _diff(ours, theirs, here="package", there="stream", limit=6):
    """Field-level differences between two records, in words."""
    absent = object()
    keys = [k for k in list(ours) + [k for k in theirs if k not in ours]
            if ours.get(k, absent) != theirs.get(k, absent)]
    parts = []
    for k in keys[:limit]:
        a, b = ours.get(k, absent), theirs.get(k, absent)
        if a is absent:
            parts.append(f"{k} absent from the {here}, {_json(b)} in the {there}")
        elif b is absent:
            parts.append(f"{k} {_json(a)} in the {here}, absent from the {there}")
        else:
            parts.append(f"{k} {_json(a)} in the {here}, {_json(b)} in the {there}")
    if len(keys) > limit:
        parts.append(f"and {len(keys) - limit} more field{'s' if len(keys) - limit != 1 else ''}")
    return "; ".join(parts)


def _result(pkg, schemas, schema_dir, fingerprint, manifest, hits, notes, ran, rules, stream=None):
    checks = []
    for rule_id, cls, severity, basis, requirement, failure in rules:
        findings = hits[rule_id]
        checks.append({"id": rule_id, "class": cls, "severity": severity, "basis": basis,
                       "requirement": requirement, "failure": failure,
                       "status": "not_run" if not ran[rule_id] else "fail" if findings else "pass",
                       "findings": findings, "notes": sorted(notes[rule_id])})
    blocking = sum(f["severity"] == "blocking" for c in checks for f in c["findings"])
    advisory = sum(f["severity"] == "advisory" for c in checks for f in c["findings"])
    keys = ("package_id", "licence_number", "licensee", "profile_id", "profile_version",
            "period_start", "period_end", "standard_version", "conformance_level_declared", "synthetic")
    result = {
        "validator": "ctres-validator-lite",
        "validator_version": __version__,
        "standard_version": STANDARD_VERSION,
        "schema_version": None if schema_dir else SCHEMA_VERSION,
        "schema_dir": str(schemas.dir) if schema_dir else None,
    }
    if pkg is not None:
        result.update({"package": str(pkg), "fingerprint": fingerprint,
                       "manifest": {k: manifest.get(k) for k in keys} if manifest is not None else None})
    if stream is not None:
        result["stream"] = stream.summary()
    not_checked = ("Reconciliation of statement totals against the records behind them, including the money "
                   "bridge of §4.13 between R13 and R3, R4 and R7, the agreement of R14 counts with the R13 "
                   "venue line and with the bankings in R6 and R7, and the agreement of R13 lines with the R15 bets "
                   "behind them; whether an R13 jurisdiction_category is in the profile's taxonomy; and the profile "
                   "conformance and completeness classes of §11. These belong to the CTRES conformance suite, "
                   f"available on request: {CONFORMANCE_SUITE}")
    if pkg is None:
        not_checked = ("The latency of each record type against the profile's own latency parameter (one maximum "
                       "applies to every event with --max-latency); the agreement of the stream with the period "
                       "package, which --reconcile tests; and the profile conformance and completeness classes of "
                       f"§11, which belong to the CTRES conformance suite, available on request: {CONFORMANCE_SUITE}")
    result.update({
        "result": "fail" if blocking else "pass",
        "summary": {"checks": len(checks),
                    "passed": sum(c["status"] == "pass" for c in checks),
                    "failed": sum(c["status"] == "fail" for c in checks),
                    "not_run": sum(c["status"] == "not_run" for c in checks),
                    "blocking_findings": blocking, "advisory_findings": advisory},
        "checks": checks,
        "not_checked": not_checked,
    })
    return result
