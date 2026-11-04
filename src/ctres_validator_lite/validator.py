"""
CTRES validator-lite: the Structural and Referential classes of validation (CTRES v1.1, §11).

A package is a directory holding manifest.json and one JSON Lines file per record type (§8.2).
Each check has an identifier, a class, a severity and the section of the Standard it rests on, so
that any finding can be traced and argued. Profile conformance, completeness and the agreement of
statement totals with the records behind them (including the money bridge of §4.13) are not checked
here: they depend on profile parameters, tolerances and materiality, and belong to the CTRES
conformance suite. Where the manifest declares a conformance level (§10), the record types the level requires
must be present (STR-09), and a reference to a record type the level does not require and the package does not
carry is reported as advisory rather than resolved. Packages produced under CTRES v1.0 are validated unchanged.

Import:  from ctres_validator_lite import validate  ->  result dict (see README, "JSON output")
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from calendar import isleap
from collections import namedtuple
from datetime import date, datetime
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
}

SEVERITY = {r[0]: r[2] for r in RULES}

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
        needed = ["manifest.schema.json", "common.schema.json"] + [f for f, _ in RECORDS.values()]
        if missing := [f for f in needed if not (d / f).is_file()]:
            raise SchemaError(f"{d} does not hold the CTRES schema files (missing {', '.join(missing)})")
        docs = {p.relative_to(d).as_posix(): json.loads(p.read_text(encoding="utf-8")) for p in d.rglob("*.schema.json")}
        registry = Registry().with_resources(
            (s["$id"], Resource(contents=s, specification=DRAFT202012)) for s in docs.values())
        self.dir = d
        self.manifest = Draft202012Validator(docs["manifest.schema.json"], registry=registry, format_checker=FORMATS)
        self.records = {t: Draft202012Validator(docs[f], registry=registry, format_checker=FORMATS)
                        for t, (f, _) in RECORDS.items()}
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

def validate(package_dir, schema_dir=None):
    """Run every check over the package directory and return the result as a dict."""
    pkg = Path(package_dir)
    schemas = Schemas(schema_dir)
    hits = {r[0]: [] for r in RULES}
    notes = {r[0]: set() for r in RULES}
    ran = {r[0]: True for r in RULES}

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
        for r in RULES:                                             # nothing else can run
            ran[r[0]] = r[0] == "STR-08"
        return _result(pkg, schemas, schema_dir, fingerprint, None, hits, notes, ran)

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
            detail = f"{key} — not resolved: {named} {verb} not required at {level} and {verb} not in the package"
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

    return _result(pkg, schemas, schema_dir, fingerprint, manifest, hits, notes, ran)


def _result(pkg, schemas, schema_dir, fingerprint, manifest, hits, notes, ran):
    checks = []
    for rule_id, cls, severity, basis, requirement, failure in RULES:
        findings = hits[rule_id]
        checks.append({"id": rule_id, "class": cls, "severity": severity, "basis": basis,
                       "requirement": requirement, "failure": failure,
                       "status": "not_run" if not ran[rule_id] else "fail" if findings else "pass",
                       "findings": findings, "notes": sorted(notes[rule_id])})
    blocking = sum(f["severity"] == "blocking" for c in checks for f in c["findings"])
    advisory = sum(f["severity"] == "advisory" for c in checks for f in c["findings"])
    keys = ("package_id", "licence_number", "licensee", "profile_id", "profile_version",
            "period_start", "period_end", "standard_version", "conformance_level_declared", "synthetic")
    return {
        "validator": "ctres-validator-lite",
        "validator_version": __version__,
        "standard_version": STANDARD_VERSION,
        "schema_version": None if schema_dir else SCHEMA_VERSION,
        "schema_dir": str(schemas.dir) if schema_dir else None,
        "package": str(pkg),
        "fingerprint": fingerprint,
        "manifest": {k: manifest.get(k) for k in keys} if manifest is not None else None,
        "result": "fail" if blocking else "pass",
        "summary": {"checks": len(checks),
                    "passed": sum(c["status"] == "pass" for c in checks),
                    "failed": sum(c["status"] == "fail" for c in checks),
                    "not_run": sum(c["status"] == "not_run" for c in checks),
                    "blocking_findings": blocking, "advisory_findings": advisory},
        "checks": checks,
        "not_checked": ("Reconciliation of statement totals against the records behind them, including the money "
                        "bridge of §4.13 between R13 and R3, R4 and R7 and the agreement of R14 counts with the R13 "
                        "venue line and with the bankings in R6 and R7; whether an R13 jurisdiction_category is in "
                        "the profile's taxonomy; and the profile conformance and completeness classes of §11. These "
                        f"belong to the CTRES conformance suite, available on request: {CONFORMANCE_SUITE}"),
    }
