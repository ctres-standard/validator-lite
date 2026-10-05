"""
CTRES validator-lite: the Structural and Referential classes of validation (CTRES v1.0, §11).

A package is a directory holding manifest.json and one JSON Lines file per record type (§8.2).
Each check has an identifier, a class, a severity and the section of the Standard it rests on, so
that any finding can be traced and argued. Profile conformance, completeness and the agreement of
statement totals with the records behind them are not checked here: they depend on profile
parameters, tolerances and materiality, and belong to the CTRES conformance suite.

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
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from . import SCHEMA_VERSION, STANDARD_VERSION, __version__

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"   # vendored copy of ctres-standard/schema
CONFORMANCE_SUITE = "https://ctres.org/validator"

# id, class, severity, basis in CTRES v1.0, what the check requires, what a failure means.
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
        allowed = self.fields[rtype] | self.module_fields.get(module, set())
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
            isinstance(b, dict) and list(b) == ["required"] for b in err.validator_value):
        names = ", ".join(n for b in err.validator_value for n in b["required"])
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

    def fail(rule, detail, rec=None, file=None, line=None, field=None):
        """Record a finding. For a record, its file, line and identifier are taken from it."""
        record = None
        if rec is not None:
            file, line, record = rec.file, rec.line, rid(rec)
            detail = f"{record}: {detail}" if record else detail
        hits[rule].append({"file": file, "line": line, "record": record, "field": field, "detail": detail})

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

    # ------------------------------------------------------------ referential
    def strings(values):
        return {v for v in values if isinstance(v, str)}

    index = {t: strings(r.data.get(RECORDS[t][1]) for r in data[t]) for t in RECORDS}

    def ref(rule, rec, field, value, rtype):
        """True if value identifies a record of rtype; a finding if not; None (noted) if the package carries no rtype."""
        if not isinstance(value, str):
            return None
        if rtype not in present:
            notes[rule].add(f"{re.sub(r'/[0-9]+$', '', field)} not resolved: the package carries no {rtype} file")
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
    if related and (absent := [t for t in RELATED_TYPES if t not in present]):
        notes["REF-06"].add(f"related_record_ids not resolved: the package carries no {', '.join(absent)} file")
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

    # REF-07: transactions are dated inside the manifest period (credited_at; else settled_at, initiated_at)
    start, end = parse_dt(manifest.get("period_start")), parse_dt(manifest.get("period_end"))
    if start is None or end is None:
        ran["REF-07"] = False
        notes["REF-07"].add("not run: the manifest period is not readable")
    elif end < start:
        ran["REF-07"] = False
        notes["REF-07"].add("not run: the manifest period ends before it starts")
    else:
        for rec in payments:
            field = next((k for k in ("credited_at", "settled_at", "initiated_at") if parse_dt(rec.data.get(k))), None)
            if field and not start <= parse_dt(rec.data[field]) <= end:
                fail("REF-07", f"{field} {rec.data[field]} is outside the period "
                     f"{manifest['period_start']} to {manifest['period_end']}", rec, field=field)

    # REF-08: attestation references resolve to an R11 attestation that covers the transaction's location
    attestations = {r.data.get("attestation_id"): r.data for r in data["R11"] if isinstance(r.data.get("attestation_id"), str)}
    for rec in payments:
        att, loc = rec.data.get("attestation_ref"), rec.data.get("location_id")
        if ref("REF-08", rec, "attestation_ref", att, "R11") and isinstance(loc, str) \
                and loc not in as_list(attestations[att].get("covers_location_ids")):
            fail("REF-08", f"attestation {att} does not cover funds location {loc}", rec, field="attestation_ref")

    return _result(pkg, schemas, schema_dir, fingerprint, manifest, hits, notes, ran)


def _result(pkg, schemas, schema_dir, fingerprint, manifest, hits, notes, ran):
    checks = []
    for rule_id, cls, severity, basis, requirement, failure in RULES:
        findings = hits[rule_id]
        checks.append({"id": rule_id, "class": cls, "severity": severity, "basis": basis,
                       "requirement": requirement, "failure": failure,
                       "status": "not_run" if not ran[rule_id] else "fail" if findings else "pass",
                       "findings": findings, "notes": sorted(notes[rule_id])})
    blocking = sum(len(c["findings"]) for c in checks if c["severity"] == "blocking")
    advisory = sum(len(c["findings"]) for c in checks if c["severity"] == "advisory")
    keys = ("package_id", "licence_number", "licensee", "profile_id", "profile_version",
            "period_start", "period_end", "standard_version", "synthetic")
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
        "not_checked": ("Reconciliation of statement totals against the records behind them, and the profile "
                        "conformance and completeness classes of §11, belong to the CTRES conformance suite, "
                        f"available on request: {CONFORMANCE_SUITE}"),
    }
