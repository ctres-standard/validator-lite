# CTRES validator-lite

validator-lite checks a package in the **Common Transaction Reporting and Evidence Standard (CTRES) v1.0**, universal edition (2 October 2026), against the **Structural** and **Referential** classes of validation defined in §11 of the Standard:

* **Structural**: is the package well formed?
* **Referential**: does the package hold together?

It is a Python command-line tool and library. It reads a package directory, applies the [CTRES JSON Schema](https://github.com/ctres-standard/schema) to every record, resolves the references between records, and reports each finding against a numbered check with its severity and the section of the Standard it rests on.

Section references (§) are to the text of the Standard, published at <https://ctres.org> and in [ctres-standard/spec](https://github.com/ctres-standard/spec).

Status: the Standard is an open draft for consultation with authorities and industry; it is independent and carries no regulatory force. validator-lite has the same status.

## What it checks

| ID | Class | Severity | Basis | Requirement |
|---|---|---|---|---|
| STR-01 | Structural | blocking | §8.2 | Every file named in the manifest is present in the package. |
| STR-02 | Structural | blocking | §8.2; §3 | The SHA-256 of each file matches the hash recorded in the manifest. |
| STR-03 | Structural | blocking | §8.2 | Each file holds the number of records the manifest declares. |
| STR-04 | Structural | blocking | §4; Annex A | Each record is a JSON object that validates against the schema of its record type: mandatory fields present, conditional fields present where the record shows the condition, no undefined fields. |
| STR-05 | Structural | blocking | §4; Annex A | Enumerated fields carry values from the permitted list. |
| STR-06 | Structural | blocking | §8.2; §3 | Amounts are decimal strings; timestamps are ISO 8601 with an explicit offset; dates are calendar dates. |
| STR-07 | Structural | blocking | §4 | Record identifiers are unique within each record type, across every file that holds it. |
| STR-08 | Structural | blocking | §8.2 | `manifest.json` is present and validates against the manifest schema. |
| REF-01 | Referential | blocking | §4.1; §4.6; §4.7; §4.11 | Every funds location referenced by R3, R4, R7 or R11 is in R1; each side of an R6 movement is a location in R1 or a provider in R10. |
| REF-02 | Referential | blocking | §4.3; §4.5 | Every `check_ids` entry on R3 and R4, and every R5 `supersedes` reference, resolves to an R5 check decision; `supersedes` chains do not loop. |
| REF-03 | Referential | blocking | §4.2; §4.3; §4.4 | Every `instrument_id` on R3 and R4, and every `source_instrument_ids` entry, is an instrument in R2. |
| REF-04 | Referential | blocking | §4.3; §11 | Each rail reference, taken with its `rail_reference_type` and `provider_id`, is booked once across R3 and R4. |
| REF-05 | Referential | blocking | §4.10; §4.1; §4.3; §4.11; §6 | Every `provider_id` on R1, R3, R4 and R11, and every provider named in an R2 `instrument_detail`, is in R10. |
| REF-06 | Referential | blocking | §4.7; §4.8; §4.9; §4.12 | R7 `exception_ids` resolve to R8; R8 `source_statement_id` resolves to R7; `related_record_ids` on R8, R9 and R12 resolve to a record or a rail reference in the package. |
| REF-07 | Referential | advisory | §8.2; §8.1 | R3 and R4 transactions are dated inside the period stated in the manifest. |
| REF-08 | Referential | blocking | §4.7; §4.11 | Every `attestation_ref` on R3 and R4 resolves to an R11 attestation that covers the transaction's funds location. |

A blocking finding means the package does not pass. An advisory finding is reported for attention and does not change the result.

### How the checks are applied

* **STR-04, STR-05 and STR-06** apply the JSON Schema of the record type named in the manifest (`record_type`), so the file name does not decide which schema is used. Each schema error is reported once: an error on an enumeration is STR-05; an error on a decimal, timestamp or date type is STR-06; every other error is STR-04. Lines that are not JSON, objects that repeat a field name, and `NaN` or `Infinity` are STR-04.
* **Undefined fields.** A record may carry only the fields its record type defines, plus the fields of the rail module that applies to it (§6): a card deposit cannot carry `tx_hash`. validator-lite names the undefined fields itself rather than relying on the schema's report, because a record that fails a rail-module condition would otherwise also have that module's permitted fields reported as undefined.
* **STR-06** also rejects a timestamp or date whose day does not exist in its month, such as 31 November, which the schema's pattern alone admits. It applies to fields of the schema's date and timestamp types only, never to free text that resembles a date. The same check on the manifest is reported as STR-08.
* **Reading files.** Records are separated by `\n`; a `\r` before it (Windows line endings) is JSON white space and is accepted, and blank lines are skipped. Other white space around a record, such as a no-break space, is not JSON and is STR-04. A file or manifest that begins with a byte order mark is reported once (STR-04, or STR-08 for the manifest), since a JSON text must not carry one (RFC 8259 §8.1); the rest of it is then read as usual. A listed file that cannot be read, or that is a link to a file outside the package directory, is STR-01 and is not read. A data file in the package that the manifest does not list is not read, and the STR-01 note names it.
* **Manifest entries.** Where a `files` entry lacks its `sha256` or `record_count`, or gives one of the wrong type, STR-08 reports it and STR-02 or STR-03 is not applied to that file.
* **References resolve within the package.** Where the package carries no file of the record type a reference points to, that reference is not resolved and the check says so in a note. A package that carries only some record types, as a periodic package may (§8.1), is therefore not reported for records it was never meant to hold. For the same reason `related_record_ids` are resolved only when the package carries R1 to R8 and R10.
* **REF-01 and REF-05** divide the references to R1 and R10 between them: REF-01 covers where money is held and moves (funds locations, and both sides of an R6 movement, whether a location or a provider); REF-05 covers who handles it (every `provider_id` field, and the mobile operator or voucher issuer named in an R2 instrument). That at least one side of an R6 movement is a location is a schema condition, reported as STR-04.
* **REF-04** treats two bookings as the same payment when `rail_reference_type`, `provider_id` and `rail_reference` are all equal, whether the bookings are deposits, withdrawals or one of each.
* **REF-06.** A related record is any record identifier in the package, or a `rail_reference`, `ledger_entry_ref`, `authority_reference` or `tx_hash` carried by R3, R4 or R6. Three R8 categories concern, by definition, something absent from the records: `external_movement_without_ledger_entry`, `provider_credit_not_booked` and `location_outside_inventory`. An exception in one of these categories may name external references, such as a bank statement line, provided at least one of its references resolves in the package.
* **REF-07** dates a transaction by `credited_at`, the moment the player account moved (§4.3), or, where that is `not_recorded`, by `settled_at` and then `initiated_at`. It is not run when the manifest period ends before it starts.

## What it does not check

validator-lite does not test whether **statement totals agree with the records behind them**, the last example of the Referential class in §11, and it implements neither of the other two classes of §11:

* **Profile conformance**: does the evidence show the control operated under this jurisdiction's rules?
* **Completeness**: is anything missing that should be there?

Each of these depends on rules that the Standard deliberately leaves to each authority: the jurisdiction profile, the tolerances that separate a rounding difference from a discrepancy, the materiality thresholds that make an exception reportable, and the severities of individual checks. Under §11 they are maintained separately as a versioned **conformance suite**, so that a package can be tested against a named suite version and a named profile version and the result reproduced later. The conformance suite is available on request: <https://ctres.org/validator>.

validator-lite also does not verify a manifest signature (`signature_file`, §8.2), and it does not parse records in CSV files (§8.2 permits CSV at Level 1): for a CSV file it checks presence, hash and record count (the CSV rows after the header row, so that a quoted value spanning lines counts once), and states in a note that the records were not validated.

A package that passes validator-lite has passed the Structural and Referential classes. That is not a claim of conformance: "CTRES Conformant" describes an implementation tested against a published conformance suite version (§13).

## Installation

validator-lite requires Python 3.10 or later and the `jsonschema` package (4.18 or later). Install a tagged release from the repository:

```sh
pip install "git+https://github.com/ctres-standard/validator-lite@v1.0.0"
```

or, from a checkout:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```sh
ctres-validate <package_dir> [--json] [--schema-dir DIR]
```

| Option | Effect |
|---|---|
| `--json` | Write the result as JSON to standard output instead of the text report. |
| `--schema-dir DIR` | Use the CTRES schema files in `DIR` (a checkout of ctres-standard/schema, or its `schema/` directory) instead of the copy bundled with validator-lite. |

| Exit status | Meaning |
|---|---|
| 0 | No blocking findings. Advisory findings may be present. |
| 1 | One or more blocking findings. |
| 2 | Usage error: wrong arguments, the package directory does not exist, or the schema directory does not hold the CTRES schema files. Also used if the validation cannot be completed, so that a failure of the tool is never read as a finding. |

`python -m ctres_validator_lite` is equivalent to `ctres-validate`.

### Package layout

A package is a directory holding `manifest.json` and one JSON Lines file per record type: UTF-8, one JSON object per line, lines separated by `\n` (§8.2). The manifest lists every file with its record type, record count and SHA-256. File names are free; the demonstration packages use `R1_funds_locations.jsonl` to `R12_report_references.jsonl`. File names in the manifest must be plain names inside the package directory; any other name is reported under STR-08 and never opened.

### Text report

The report states the package, the licence, the profile and the period, then the **package fingerprint**: the SHA-256 of `manifest.json`, which a receipt can quote to prove which package was submitted (§8.2). Checks follow, grouped by class, with up to 20 findings each. An extract for `demo/defects`:

```text
fingerprint  SHA-256 7676849c47f14f7ef0e33931b330c5b7427374c481ccbd546a0d222e94956ea2
schema       bundled copy, release 1.0.0
synthetic    yes: the manifest declares that the package holds synthetic data

Structural: 8 checks, 5 passed, 3 failed
  STR-01  pass  Every file named in the manifest is present in the package
  STR-02  FAIL  blocking  1 finding  A file differs from the file the manifest was sealed with (§8.2; §3 Deterministic and verifiable)
          R6_internal_movements.jsonl: SHA-256 of the file is 579f62db…; the manifest states a38ae877…
  ...
Referential: 8 checks, 5 passed, 3 failed
  ...
  REF-04  FAIL  blocking  1 finding  The same rail payment is booked more than once (§4.3; §11 Referential)
          R3_deposits.jsonl line 13: D-2026-11-0013: acquirer_reference 74999991000000000000003 (PSP-01) is already booked by D-2026-11-0003 (R3_deposits.jsonl line 3)

Result: FAIL: 6 blocking findings, 0 advisory.
```

### JSON output

With `--json`, the result is one JSON object, written in UTF-8 whatever the console encoding. Its shape is stable within a major version, and its content is deterministic: the same package and schema give the same output, byte for byte.

| Key | Content |
|---|---|
| `validator`, `validator_version` | `ctres-validator-lite` and its version. |
| `standard_version` | Version of the Standard implemented (`1.0`). |
| `schema_version`, `schema_dir` | Release of the bundled schema, or `null` and the directory given with `--schema-dir`. |
| `package`, `fingerprint` | The package directory as given, and the SHA-256 of `manifest.json` (`null` if there is none). |
| `manifest` | `package_id`, `licence_number`, `licensee`, `profile_id`, `profile_version`, `period_start`, `period_end`, `standard_version`, `synthetic`, as stated in the manifest. |
| `result` | `pass` or `fail`. |
| `summary` | `checks`, `passed`, `failed`, `not_run`, `blocking_findings`, `advisory_findings`. |
| `checks` | One object per check, in the order of the table above: `id`, `class`, `severity`, `basis`, `requirement`, `failure`, `status` (`pass`, `fail` or `not_run`), `findings` and `notes`. Each finding has `file`, `line`, `record` (the record identifier), `field` (a path such as `check_ids/0`) and `detail`; any of the first four may be `null`. |
| `not_checked` | What validator-lite does not check, and where those checks are maintained. |

A check is `not_run` only when its input is unusable: every check except STR-08 when there is no readable manifest, and REF-07 when the manifest period cannot be read or ends before it starts.

### Python

```python
from ctres_validator_lite import validate

result = validate("path/to/package")          # the same dict as --json
blocking = result["summary"]["blocking_findings"]
```

## Demonstration packages

`demo/clean/` is a synthetic package for a fictional operator under a fictional licence and profile: 65 records across all twelve record types and four rails (card, bank transfer by instant payment, mobile money, virtual assets). It passes with no findings. `demo/defects/` is the same package with six deliberate defects, one for each of STR-02, STR-04, STR-05, REF-02, REF-03 and REF-04. [demo/README.md](demo/README.md) describes both and lists the expected findings.

```sh
ctres-validate demo/clean      # exit status 0
ctres-validate demo/defects    # exit status 1
```

The packages are generated by `scripts/make_demo.py`, which reproduces them byte for byte.

## Schema

validator-lite carries a copy of the schema files of [ctres-standard/schema](https://github.com/ctres-standard/schema) under `src/ctres_validator_lite/schema/`, so that it runs without network access. `SCHEMA_VERSION` in `src/ctres_validator_lite/__init__.py` states the release copied. To update the copy from a checkout of the schema repository:

```sh
python scripts/sync_schema.py ../schema
```

The script copies the files byte for byte, checks that every `$id` lies under the version path of the release, and updates `SCHEMA_VERSION`. The copy includes `profile.schema.json`, the structure of a jurisdiction profile, which validator-lite does not use.

## Tests

The tests use the standard library `unittest` module only:

```sh
python -m unittest discover -s tests -v
```

They check that the clean package passes, that each defect is reported by its check, that every check reports a change made to a copy of the clean package, that valid variations (`not_recorded` values, omitted optional fields, a provider on one side of a movement) are not reported, that malformed files (byte order marks, unreadable files, links outside the package, deep nesting) are reported rather than stopping the run, that the JSON output keeps its shape, that the demonstration packages are reproducible, and, where ctres-standard/schema is checked out next to this repository, that the bundled schema matches it. The same tests run on every push and pull request (`.github/workflows/test.yml`).

## Comments

Comments are welcome from authorities, operators, payment providers, auditors and anyone else.

* Open an issue at <https://github.com/ctres-standard/validator-lite/issues>, or
* write to <hello@ctres.org>.

Comments on the text of the Standard belong in [ctres-standard/spec](https://github.com/ctres-standard/spec), and comments on the schema in [ctres-standard/schema](https://github.com/ctres-standard/schema). See [CONTRIBUTING.md](CONTRIBUTING.md) for how changes are proposed.

Maintained by the editor of the Standard (see <https://ctres.org/governance/>).

## Licence

validator-lite, its bundled copy of the schema, the demonstration packages and the tests are licensed under the [Apache License, Version 2.0](LICENSE). The text of the Standard is licensed separately under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
