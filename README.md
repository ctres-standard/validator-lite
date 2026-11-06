# CTRES validator-lite

validator-lite checks a package in the **Common Transaction Reporting and Evidence Standard (CTRES) v1.1**, the universal edition of 2 October 2026 (v1.0) extended with the gaming revenue statement R13, the venue count R14 and the bet event R15 (§4.13, §4.14, §4.15), against the **Structural** and **Referential** classes of validation defined in §11 of the Standard:

* **Structural**: is the package well formed?
* **Referential**: does the package hold together?

It also checks a **stream** (§8.4), the second cadence of v1.1 in which the same records travel one event per line as they occur, with a checkpoint per gaming day, and it **reconciles** a package with the stream that carried its records:

* **Stream**: is the stream well formed, in sequence, and sealed by its checkpoints?
* **Reconciliation**: does the package agree with the stream?

It is a Python command-line tool and library. It reads a package directory, applies the [CTRES JSON Schema](https://github.com/ctres-standard/schema) to every record, resolves the references between records, and reports each finding against a numbered check with its severity and the section of the Standard it rests on. Where the manifest declares a conformance level (§10: `level_1` Return, `level_2` Evidence, `level_3` Custody, `level_4` Supervision), it checks that the record types of the level are present and resolves references by level. A package produced under CTRES v1.0 is validated unchanged; it keeps `standard_version` `1.0` in its manifest.

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
| STR-09 | Structural | blocking | §10; Annex D | Every record type the declared conformance level requires is listed in the manifest and present; at `level_2` and above, R14 where any R13 line has `channel` `venue`. Not run where the manifest declares no level. |
| REF-01 | Referential | blocking | §4.1; §4.6; §4.7; §4.11 | Every funds location referenced by R3, R4, R7 or R11 is in R1; each side of an R6 movement is a location in R1 or a provider in R10. |
| REF-02 | Referential | blocking | §4.3; §4.5 | Every `check_ids` entry on R3 and R4, and every R5 `supersedes` reference, resolves to an R5 check decision; `supersedes` chains do not loop. |
| REF-03 | Referential | blocking | §4.2; §4.3; §4.4 | Every `instrument_id` on R3 and R4, and every `source_instrument_ids` entry, is an instrument in R2. |
| REF-04 | Referential | blocking | §4.3; §11 | Each rail reference, taken with its `rail_reference_type` and `provider_id`, is booked once across R3 and R4. |
| REF-05 | Referential | blocking | §4.10; §4.1; §4.3; §4.11; §6 | Every `provider_id` on R1, R3, R4 and R11, and every provider named in an R2 `instrument_detail`, is in R10. |
| REF-06 | Referential | blocking | §4.7; §4.8; §4.9; §4.12 | R7 `exception_ids` resolve to R8; R8 `source_statement_id` resolves to R7; `related_record_ids` on R8, R9 and R12 resolve to a record or a rail reference in the package. |
| REF-07 | Referential | advisory | §8.2; §8.1 | R3 and R4 transactions are dated inside the period stated in the manifest. |
| REF-08 | Referential | blocking | §4.7; §4.11 | Every `attestation_ref` on R3 and R4 resolves to an R11 attestation that covers the transaction's funds location. |
| REF-09 | Referential | blocking | §4.13; §4.14; §8.2 | Every R13 statement period, and every R14 gaming day or period, lies within the period stated in the manifest. |
| REF-10 | Referential | blocking | §4.13 | Every R13 correction's `corrects_statement_id` names the statement it replaces: another R13 statement of the same licence, product line, channel and currency, where the package carries it. |
| REF-11 | Referential | blocking | §4.14; §4.1; §4.6 | Every R14 `venue_id` is carried by an R1 location, and every R14 `drop_deposit_ref` is an R6 movement or an R1 location. |
| REF-12 | Referential | blocking | §4.13; §4.12 | Every `authority_figure_ref` on an R13 statement cites a report reference in R12. |
| REF-13 | Referential | advisory | §4.13 | `ggr_declared` on each R13 statement equals the formula the statement names, `all_in` or `cash_only`, applied to the statement's own stakes and winnings, exactly. |
| REF-14 | Referential | blocking | §4.15; §4.1 | Every R15 `venue_id` is carried by an R1 location. |
| STM-01 | Stream | blocking | §8.4 | Every line is a JSON object that validates against the stream event envelope: `stream_id`, `sequence`, `emitted_at`, `licence_number`, `standard_version`, `record_type`, `op` and `record` present and well formed, no undefined fields; a checkpoint event carries `op` `create`. |
| STM-02 | Stream | blocking | §8.4 | Within each stream, sequence numbers are strictly increasing from line to line, without gaps. |
| STM-03 | Stream | blocking | §8.4 | No `(stream_id, sequence)` pair repeats; a repeat with identical bytes is a redelivery, ignored and reported as advisory, a repeat with different bytes a conflict. |
| STM-04 | Stream | blocking | §8.4 | The record of each event validates against the schema of its `record_type`, or against the checkpoint schema for `record_type` `checkpoint`; with `op` `void` the record carries at least the record's identifier. |
| STM-05 | Stream | blocking | §8.4 | Each checkpoint's `first_sequence`, `last_sequence` and `event_count` match the events of its stream, and its `chain_hash` is the SHA-256 of those event lines as transmitted; a gaming day with events but no checkpoint is advisory. |
| STM-06 | Stream | advisory | §8.4 | An event with `op` `update` or `void` names a record identifier an earlier event of the stream created; advisory, since the create may predate the file. |
| STM-07 | Stream | blocking | §8.4 | Where a maximum latency is given (`--max-latency`), each event is emitted no later than that duration after its record's anchor timestamp. Not run otherwise. |
| REC-01 | Reconciliation | blocking | §8.4; §11 | Every record whose final streamed state is live, its last event an `op` `create` or `update`, is in the package. |
| REC-02 | Reconciliation | blocking | §8.4; §11 | Every package record of a record type the stream carries was streamed. |
| REC-03 | Reconciliation | blocking | §8.4; §11 | Each package record equals the final streamed state of the record, field by field; a record the stream withdrew with `op` `void` is not in the package. |
| REC-04 | Reconciliation | blocking | §8.4; §11 | The manifest's `stream_checkpoints` are the checkpoints the stream carries, one for one and field by field. |

A blocking finding means the package, or the stream, does not pass. An advisory finding is reported for attention and does not change the result. REF-07, REF-13 and STM-06 are advisory checks; a blocking check also reports an advisory finding for a reference to a record type the declared level does not require and the package does not carry (see below), for a redelivered event (STM-03), for a day without a checkpoint (STM-05), and for streamed records of a type the level does not require and the package does not carry (REC-01). The Structural and Referential checks run on a package; the Stream checks run on an events file (`--stream`); a reconciliation run (`--reconcile`) applies all four classes.

### How the checks are applied

* **STR-04, STR-05 and STR-06** apply the JSON Schema of the record type named in the manifest (`record_type`), so the file name does not decide which schema is used. Each schema error is reported once: an error on an enumeration is STR-05; an error on a decimal, timestamp or date type is STR-06; every other error is STR-04. Lines that are not JSON, objects that repeat a field name, and `NaN` or `Infinity` are STR-04. Where a record must carry exactly one of two sets of fields, as an R14 row carries either `gaming_day` or `period_start` and `period_end`, STR-04 says so in those words.
* **Undefined fields.** A record may carry only the fields its record type defines, plus the fields of the rail module that applies to it (§6): a card deposit cannot carry `tx_hash`. validator-lite names the undefined fields itself rather than relying on the schema's report, because a record that fails a rail-module condition would otherwise also have that module's permitted fields reported as undefined.
* **STR-06** also rejects a timestamp or date whose day does not exist in its month, such as 31 November, which the schema's pattern alone admits. It applies to fields of the schema's date and timestamp types only, never to free text that resembles a date. The same check on the manifest is reported as STR-08.
* **Reading files.** Records are separated by `\n`; a `\r` before it (Windows line endings) is JSON white space and is accepted, and blank lines are skipped. Other white space around a record, such as a no-break space, is not JSON and is STR-04. A file or manifest that begins with a byte order mark is reported once (STR-04, or STR-08 for the manifest), since a JSON text must not carry one (RFC 8259 §8.1); the rest of it is then read as usual. A listed file that cannot be read, or that is a link to a file outside the package directory, is STR-01 and is not read. A data file in the package that the manifest does not list is not read, and the STR-01 note names it.
* **Manifest entries.** Where a `files` entry lacks its `sha256` or `record_count`, or gives one of the wrong type, STR-08 reports it and STR-02 or STR-03 is not applied to that file.
* **STR-09** applies the conformance levels of §10, which are defined by scope: `level_1` Return requires R13; `level_2` Evidence adds R3, R4 and R7, and R14 where any R13 line has `channel` `venue`; `level_3` Custody adds R1, R2, R6, R10 and R11; `level_4` Supervision adds R5, R8, R9 and R12. Any record type may be included at any level; the level fixes the minimum set. STR-09 tests the manifest's file list, one finding per missing record type; that each listed file is present is STR-01. Where the manifest declares no level, STR-09 is not run and says so in a note; a value outside the enumeration is STR-08. The levels are those of v1.1: in a package that declares `standard_version` `1.0`, `conformance_level_declared` keeps its v1.0 meaning (a delivery level), STR-09 is not run, and references are resolved as for a package without a level.
* **References resolve within the package, by level.** Where the package carries no file of the record type a reference points to, that reference is not resolved. Where the manifest declares a level that does not require that record type, the identifier is the operator's own, present in the record and not resolved within the package (§10): the check reports one **advisory** finding per field, such as `instrument_id - not resolved: R2 is not required at level_2 and is not in the package`, and the package can still pass. Where no level is declared, or the level requires the type (which STR-09 then reports), the check says so in a note instead, so that a partial or sampled package (§8.1) is not reported for records it was never meant to hold. Where the type's file is in the package, a reference that does not resolve is blocking, whatever the level. This applies to every cross-type reference: REF-01, REF-02, REF-03, REF-05, REF-06, REF-08, REF-11 and REF-12. `related_record_ids` are resolved only when the package carries R1 to R8 and R10, and are advisory where every absent type is one the level does not require. The statement an R13 correction replaces is treated as before: where the package does not carry it, REF-10 notes the reference rather than reporting it, since the statement may belong to an earlier package.
* **REF-01 and REF-05** divide the references to R1 and R10 between them: REF-01 covers where money is held and moves (funds locations, and both sides of an R6 movement, whether a location or a provider); REF-05 covers who handles it (every `provider_id` field, and the mobile operator or voucher issuer named in an R2 instrument). That at least one side of an R6 movement is a location is a schema condition, reported as STR-04.
* **REF-04** treats two bookings as the same payment when `rail_reference_type`, `provider_id` and `rail_reference` are all equal, whether the bookings are deposits, withdrawals or one of each.
* **REF-06.** A related record is any record identifier in the package, or a `rail_reference`, `ledger_entry_ref`, `authority_reference` or `tx_hash` carried by R3, R4 or R6. Three R8 categories concern, by definition, something absent from the records: `external_movement_without_ledger_entry`, `provider_credit_not_booked` and `location_outside_inventory`. An exception in one of these categories may name external references, such as a bank statement line, provided at least one of its references resolves in the package.
* **REF-07** dates a transaction by `credited_at`, the moment the player account moved (§4.3), or, where that is `not_recorded`, by `settled_at` and then `initiated_at`. It is not run when the manifest period ends before it starts.
* **REF-09** compares each boundary of an R13 or R14 period with the manifest period as instants, so an offset that differs from the manifest's is not a finding. An R14 `gaming_day` is a calendar date: it is inside the period when it lies between the dates of the manifest's `period_start` and `period_end`, each taken in the offset the manifest states for it. REF-09 is not run when REF-07 is not run.
* **REF-10** reports a correction that names itself, a correction chain that returns to its start, or a statement of another line, where the line is the licence, product line, channel and currency of §4.13. A correction of a correction is accepted. The statement a correction replaces is not otherwise compared with it.
* **REF-11** resolves `venue_id` only when the package carries R1 and at least one R1 location carries `venue_id`; otherwise it says so in a note. `drop_deposit_ref` is resolved against R6 `movement_id` and R1 `location_id` together, and noted when the package carries neither file or only one of them and the reference is not in it.
* **REF-13** is the statement's internal consistency, not its reconciliation to other records. It recomputes `ggr_declared` from the statement's own fields in exact decimal arithmetic, with no tolerance: under `all_in`, (`stakes_cash` + `stakes_bonus` − `stakes_refunded`) − (`winnings_cash` + `winnings_bonus`), a bonus field the line does not carry counting as zero; under `cash_only`, `stakes_cash` − `stakes_refunded` − `winnings_cash`. A statement whose `ggr_formula` is `profile` is not tested, since the formula is the profile's, and a note says so. The money bridge of §4.13, which ties the statement to R3, R4 and R7, is not checked (see below).
* **R15 Bet Event** (§4.15), the Wagering module, is a record type like any other in a package (file `R15_bet_events.jsonl`; only the final state of each bet appears): STR-04 to STR-07 apply, among them the conditions of the schema that a bet whose `status` is `settled`, `void` or `cashed_out` carries `settled_at`, that a `void` bet carries `void_reason`, and that an `open` bet carries neither and carries `winnings` only as zero (reported in the schema's own words, `winnings is absent or zero while status is open`). No conformance level requires R15 (STR-09 never asks for it); a profile may. **REF-14** resolves a bet's `venue_id` against R1 as REF-11 resolves a venue count's, by level. The agreement of an R13 line with the bets behind it is not checked (see below).
* **Streams (STM-01 to STM-07)** read an NDJSON events file (§8.4): one event per line, each an envelope around a record. Lines are separated by `\n`; a `\r` before it is not part of the line. Blank lines are skipped. STM-01 validates the envelope alone (the published `stream/event.schema.json` without its record dispatch) and reports a line that is not JSON, not an object, or a checkpoint event with an `op` other than `create`; the record inside is STM-04, validated against the schema of the event's `record_type` as a package record would be (with `op` `void`, only that the record carries the identifier of its type, `tx_id` for R3 and so on). Sequences are tracked per `stream_id`; the first event of a stream in the file sets its start, so a file may begin mid-stream. A repeated `(stream_id, sequence)` is STM-03, the first copy stands and the repeat is not processed further; a sequence that goes backwards without repeating, or that leaves a gap, is STM-02, with the missing range in the message. STM-05 takes every valid checkpoint event and checks `event_count` = `last_sequence` − `first_sequence` + 1, that every sequence of the range was seen, and that `chain_hash` equals the SHA-256 of the UTF-8 bytes of the covered lines as transmitted, each followed by `\n`, checkpoint events excluded, in sequence order; a checkpoint for a period without events carries `event_count` 0 and `last_sequence` one below `first_sequence`. Events of a stream and day (the date of `emitted_at`, as written) that no checkpoint covers are one advisory finding per stream and day. STM-06 keys records by stream, record type and identifier. STM-07 runs only with `--max-latency`, an ISO 8601 duration in weeks, days, hours, minutes and seconds (`PT60S`, `PT5M`, `P1D`; years and months are refused, since they have no fixed length), one maximum for every event; the anchor is the record's own timestamp: R3 `credited_at` (else `settled_at`, then `initiated_at`); R4 `paid_at`, else `requested_at`; R5 `performed_at`; R6 `executed_at`; R8 `raised_at`; R9 `detected_at`; R15 `settled_at` where the event reports it, else `placed_at`; R7, R13 and R14 `period_end`. R1, R2, R10, R11 and R12, streamed on creation and change, and checkpoint events have no anchor and are noted, not tested. A stream result carries no package fingerprint; the SHA-256 of the events file stands in its place.
* **Reconciliation (REC-01 to REC-04)** runs with `<package_dir> --reconcile EVENTS`: the package checks, the stream checks over `EVENTS`, then the agreement of the two. The final state of a record is its last event in the file, by stream, record type and identifier; with `op` `void` the record is withdrawn. REC-01 reports a live final state absent from the package, by sequence and line of the events file; R13 `interim` statements are superseded by the period statement and are not expected in the package (a note counts them). Where the package carries no file of a streamed record type, the records of that type are not reconciled: one advisory finding where the declared level does not require the type (`R5 records - not reconciled: R5 is not required at level_2 and is not in the package`), a note otherwise, as for references by level. REC-02 reports a package record of a streamed type that no event carries, and notes record types the package carries that the stream does not (`R7 is not streamed`). REC-03 compares each package record with its final streamed state as JSON values, field by field, and names the fields that differ, the package's value and the stream's; a withdrawn record the package still carries is REC-03 too. REC-04 matches the manifest's `stream_checkpoints` with the stream's checkpoint events by stream and sequence range, then field by field, and reports a manifest entry the stream does not carry, a stream checkpoint the manifest does not list, and a pair that differs. The events file should cover the package period and no more; records of other periods would be reported as absent from the package.

## What it does not check

validator-lite does not test whether **statement totals agree with the records behind them**, one of the Referential examples in §11. That covers the money bridge of §4.13, which ties an R13 statement to the deposits, withdrawals, player balances and open-bet liability in R3, R4 and R7; the agreement of the R14 rows of a venue with the R13 venue line; the agreement of the drop in R14 with the bankings in R6 and R7; and the agreement of an R13 line with the R15 bets of that line aggregated under the profile's recognition (§4.15). Nor does it test whether an R13 `jurisdiction_category` is a category of the profile's product taxonomy, which §11 also lists under the Referential class but which needs the profile, or the latency of each record type against the profile's own `latency` parameter (`--max-latency` applies one maximum to every event); profiles are published in human-readable form only (Annex B). And it implements neither of the other two classes of §11:

* **Profile conformance**: does the evidence show the control operated under this jurisdiction's rules?
* **Completeness**: is anything missing that should be there?

Each of these depends on rules that the Standard deliberately leaves to each authority: the jurisdiction profile, the tolerances that separate a rounding difference from a discrepancy, the materiality thresholds that make an exception reportable, and the severities of individual checks. Under §11 they are maintained separately as a versioned **conformance suite**, so that a package can be tested against a named suite version and a named profile version and the result reproduced later. The conformance suite is available on request: <https://ctres.org/validator>.

validator-lite also does not verify a manifest signature (`signature_file`, §8.2) or a checkpoint `signature` (§8.4), and it does not parse records in CSV files (§8.2 permits CSV at Level 1): for a CSV file it checks presence, hash and record count (the CSV rows after the header row, so that a quoted value spanning lines counts once), and states in a note that the records were not validated. It does not speak the reference transport of `stream/openapi.yaml`; it reads an events file that was received, or replayed, through it.

A package that passes validator-lite has passed the Structural and Referential classes. That is not a claim of conformance: "CTRES Conformant" describes an implementation tested against a published conformance suite version (§13).

## Installation

validator-lite requires Python 3.10 or later and the `jsonschema` package (4.18 or later). Install a tagged release from the repository:

```sh
pip install "git+https://github.com/ctres-standard/validator-lite@v1.1.0"
```

or, from a checkout:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```sh
ctres-validate <package_dir> [--json] [--schema-dir DIR] [--reconcile EVENTS] [--max-latency DURATION]
ctres-validate --stream EVENTS [--json] [--schema-dir DIR] [--max-latency DURATION]
```

| Option | Effect |
|---|---|
| `--stream EVENTS` | Validate the NDJSON events file `EVENTS` (STM-01 to STM-07) instead of a package. |
| `--reconcile EVENTS` | With a package: also validate the stream in `EVENTS` and reconcile the package with it (REC-01 to REC-04). |
| `--max-latency DURATION` | With `--stream` or `--reconcile`: run STM-07 with this maximum, an ISO 8601 duration such as `PT60S`, `PT5M` or `P1D`. |
| `--json` | Write the result as JSON to standard output instead of the text report. |
| `--schema-dir DIR` | Use the CTRES schema files in `DIR` (a checkout of ctres-standard/schema, or its `schema/` directory) instead of the copy bundled with validator-lite. |

| Exit status | Meaning |
|---|---|
| 0 | No blocking findings. Advisory findings may be present. |
| 1 | One or more blocking findings. |
| 2 | Usage error: wrong arguments, the package directory or the events file does not exist, the duration is malformed, or the schema directory does not hold the CTRES schema files. Also used if the validation cannot be completed, so that a failure of the tool is never read as a finding. |

`python -m ctres_validator_lite` is equivalent to `ctres-validate`.

### Streams

A stream is an NDJSON file: one event per line, each an envelope (`stream_id`, `sequence`, `emitted_at`, `licence_number`, `standard_version`, `record_type`, `op`, `record`, optionally `profile_id` and `reason`) around a record exactly as it would appear in a package, or around the checkpoint of a gaming day (`record_type` `checkpoint`), as `stream/event.schema.json` and `stream/checkpoint.schema.json` of the CTRES JSON Schema define them (§8.4). The file may hold several streams and may begin mid-stream.

```sh
ctres-validate --stream events.ndjson                         # STM-01 to STM-06
ctres-validate --stream events.ndjson --max-latency PT60S     # and STM-07
ctres-validate package/ --reconcile events.ndjson             # the package, the stream, and REC-01 to REC-04
```

### Package layout

A package is a directory holding `manifest.json` and one JSON Lines file per record type: UTF-8, one JSON object per line, lines separated by `\n` (§8.2). The manifest lists every file with its record type, record count and SHA-256. File names are free; the demonstration packages use `R1_funds_locations.jsonl` to `R14_venue_counts.jsonl`. File names in the manifest must be plain names inside the package directory; any other name is reported under STR-08 and never opened.

### Text report

The report states the package, the licence, the profile and the period, then the **package fingerprint**: the SHA-256 of `manifest.json`, which a receipt can quote to prove which package was submitted (§8.2). Checks follow, grouped by class, with up to 20 findings each; a check whose findings are all advisory is shown as advisory. The result line states the conformance level the manifest declares, or that none is declared. An extract for `demo/defects`:

```text
fingerprint  SHA-256 93dd351cd6eeacef326512eef6e3331c10917d0e9a7e696b7118d01d65e62fe1
schema       bundled copy, release 1.1.0
synthetic    yes: the manifest declares that the package holds synthetic data

Structural: 9 checks, 6 passed, 3 failed
  STR-01  pass  Every file named in the manifest is present in the package
  STR-02  FAIL  blocking  1 finding  A file differs from the file the manifest was sealed with (§8.2; §3 Deterministic and verifiable)
          R6_internal_movements.jsonl: SHA-256 of the file is a6c20244...; the manifest states 06157da6...
  ...
  STR-09  pass  Every record type the declared conformance level requires is listed in the manifest and present; at level_2 and above, R14 where any R13 line has channel venue

Referential: 13 checks, 6 passed, 7 failed
  ...
  REF-04  FAIL  blocking  1 finding  The same rail payment is booked more than once (§4.3; §11 Referential)
          R3_deposits.jsonl line 13: D-2026-11-0013: acquirer_reference 74999991000000000000003 (PSP-01) is already booked by D-2026-11-0003 (R3_deposits.jsonl line 3)
  ...
  REF-13  FAIL  advisory  1 finding  Statements declare a gross gaming revenue that does not follow their own formula (§4.13)
          R13_gaming_revenue_statements.jsonl line 2: GRS-2026-11-XJ-DEMO-0001-CASINO-ONLINE-EUR: ggr_declared 150.00 differs from the cash_only formula on the statement's own fields: stakes_cash - stakes_refunded - winnings_cash = 140.00

Result: FAIL: 9 blocking findings, 1 advisory; declared level_4 (Supervision).
```

And for `demo/level2`, a level_2 package that carries R3, R4, R7, R13 and R14 and nothing else, so that its references to the Custody and Supervision modules are advisory:

```text
Referential: 13 checks, 5 passed, 8 failed
  ...
  REF-03  FAIL  advisory  2 findings  Payments refer to instruments that are not in the R2 register (§4.2; §4.3; §4.4)
          instrument_id - not resolved: R2 is not required at level_2 and is not in the package
          source_instrument_ids - not resolved: R2 is not required at level_2 and is not in the package
  ...

Result: PASS: no blocking findings, 10 advisory; declared level_2 (Evidence).
```

For a stream, the header states the events file, the events, streams and checkpoints it holds, the record types, the SHA-256 of the file, and the maximum latency applied; the result line states the events and checkpoints. An extract for `demo/stream/events.ndjson` with `--max-latency PT60S`:

```text
CTRES validator-lite 1.1.0: Stream validation (CTRES v1.1, §8.4)
stream       demo/stream/events.ndjson
events       26 events in 1 stream (XJ/DEMO/0001:all, sequences 1 to 26), 1 checkpoint
record types R3 4, R4 2, R5 6, R13 3, R15 10, checkpoint 1
fingerprint  SHA-256 a2ae4c50572042658e443b5ec9ce3f08dc88df1b2c01c3cce3575dabd57eed23
schema       bundled copy, release 1.1.0
max latency  PT60S

Stream: 7 checks, 7 passed, 0 failed
  STM-01  pass  Every line is a JSON object that validates against the stream event envelope: ...
  ...

Result: PASS: no blocking findings, 0 advisory; 26 events in 1 stream (XJ/DEMO/0001:all, sequences 1 to 26), 1 checkpoint.
```

A reconciliation run prints the package header with a `stream` line, then the Structural, Referential, Stream and Reconciliation classes. An extract for `demo/stream/package --reconcile demo/stream/events.ndjson`:

```text
Reconciliation: 4 checks, 3 passed, 1 failed
  REC-01  FAIL  advisory  1 finding  Streamed records are absent from the package (§8.4; §11)
          R5 records - not reconciled: R5 is not required at level_2 and is not in the package
          note: 1 R13 interim statement is superseded by the period statement and not expected in the package
  REC-02  pass  Every package record of a record type the stream carries was streamed
          note: R7 is not streamed: its records are not reconciled
  REC-03  pass  Each package record equals the final streamed state of the record, field by field; a record the stream withdrew with op void is not in the package
  REC-04  pass  The manifest's stream_checkpoints are the checkpoints the stream carries, one for one and field by field

Result: PASS: no blocking findings, 7 advisory; declared level_2 (Evidence); reconciled with demo/stream/events.ndjson (26 events, 1 checkpoint).
```

Findings on a stream name the events file and line, the sequence and, where the record has one, its identifier: `events.ndjson line 5: sequence 6 (D-2026-11-0022): sequence 5 of stream XJ/DEMO/0001:all is missing between line 4 (sequence 4) and line 5`.

### JSON output

With `--json`, the result is one JSON object, written in UTF-8 whatever the console encoding. Its shape is stable within a major version, and its content is deterministic: the same package and schema give the same output, byte for byte.

| Key | Content |
|---|---|
| `validator`, `validator_version` | `ctres-validator-lite` and its version. |
| `standard_version` | Version of the Standard implemented (`1.1`). The version the package was produced under is `manifest.standard_version`. |
| `schema_version`, `schema_dir` | Release of the bundled schema, or `null` and the directory given with `--schema-dir`. |
| `package`, `fingerprint` | The package directory as given, and the SHA-256 of `manifest.json` (`null` if there is none). Absent from a stream result. |
| `manifest` | `package_id`, `licence_number`, `licensee`, `profile_id`, `profile_version`, `period_start`, `period_end`, `standard_version`, `conformance_level_declared`, `synthetic`, as stated in the manifest. Absent from a stream result. |
| `stream` | In a stream or reconciliation result: `path` (the events file as given), `fingerprint` (the SHA-256 of the file), `lines`, `events` (one per stream and sequence, repeats excluded), `checkpoints`, `streams` (per `stream_id`: `first_sequence`, `last_sequence`, `events`, `checkpoints`), `record_types` (events per type) and `max_latency` (the duration applied, or `null`). |
| `result` | `pass` or `fail`. |
| `summary` | `checks`, `passed`, `failed`, `not_run`, `blocking_findings`, `advisory_findings`. Findings are counted by their own severity. |
| `checks` | One object per check, in the order of the table above (a stream result holds the Stream checks alone; a reconciliation result all four classes): `id`, `class` (`structural`, `referential`, `stream` or `reconciliation`), `severity`, `basis`, `requirement`, `failure`, `status` (`pass`, `fail` or `not_run`), `findings` and `notes`. Each finding has `file`, `line`, `record` (the record identifier), `field` (a path such as `check_ids/0`, or `record/tx_id` inside a stream event), `detail` and `severity` (the check's severity, or `advisory` where the check downgrades it); any of the first four may be `null`. |
| `not_checked` | What validator-lite does not check, and where those checks are maintained. |

A check is `not_run` only when its input is unusable: every check except STR-08 when there is no readable manifest, STR-09 when the manifest declares no conformance level or the package was produced under v1.0, REF-07 and REF-09 when the manifest period cannot be read or ends before it starts, STM-07 when no maximum latency is given, and STM-02 to STM-07 when the events file is not UTF-8.

### Python

```python
from ctres_validator_lite import validate, validate_stream

result = validate("path/to/package")                              # the same dict as --json
result = validate("path/to/package", reconcile="events.ndjson")   # with --reconcile
result = validate_stream("events.ndjson", max_latency="PT60S")    # --stream, with --max-latency
blocking = result["summary"]["blocking_findings"]
```

## Demonstration packages

Four synthetic CTRES v1.1 packages for a fictional operator under a fictional licence and profile, and the stream of one gaming day with its package, generated from the same data by `scripts/make_demo.py`, which reproduces them byte for byte. [demo/README.md](demo/README.md) describes each and lists the expected findings. The clean 1.0 package of release 1.0.1 is kept unchanged under `tests/fixtures/clean_1_0/`.

| Package | Declared level | Content | Records | `ctres-validate` |
|---|---|---|---|---|
| `demo/clean/` | `level_4` Supervision | Record types R1 to R14: four rails (card, bank transfer by instant payment, mobile money, virtual assets), two online gaming revenue lines, the venue line of a land-based venue and one gaming day's count there. | 74 | PASS, no findings; exit status 0 |
| `demo/level1/` | `level_1` Return | The manifest and R13 only. | 3 | PASS, 1 advisory finding: the sports line's `authority_figure_ref` points at R12, which the level does not require; exit status 0 |
| `demo/level2/` | `level_2` Evidence | R3, R4, R7 and R13, with R14 because the venue line makes it required. | 26 | PASS, 10 advisory findings: the references to the Custody and Supervision modules, which the level does not require; exit status 0 |
| `demo/defects/` | `level_4` Supervision | The clean package with ten deliberate defects, one for each of STR-02, STR-04, STR-05, REF-02, REF-03, REF-04, REF-09, REF-10, REF-12 and REF-13. | 76 | FAIL, 9 blocking and 1 advisory finding; exit status 1 |
| `demo/stream/events.ndjson` | - | The stream of the gaming day 14 November 2026: the R5 checks, R3 deposits, R4 withdrawals and R15 bets of the day as they occur (seven bets, among them an update to settled, a void and a cash-out), an R13 interim statement at noon, the day's two R13 period statements at the cut-off, and the checkpoint of the day. | 26 events | `--stream`: PASS, no findings (STM-07 not run without `--max-latency`; passes with `PT60S`); exit status 0 |
| `demo/stream/package/` | `level_2` Evidence | The package of the same day: R3, R4, R7, R13 and R15 (the final state of each bet), with the checkpoint in the manifest's `stream_checkpoints`. | 22 | `--reconcile demo/stream/events.ndjson`: PASS, 7 advisory findings: the level_2 references, and the R5 checks the stream carries and the level does not require; exit status 0 |

```sh
ctres-validate demo/clean      # exit status 0
ctres-validate demo/level1     # exit status 0
ctres-validate demo/level2     # exit status 0
ctres-validate demo/defects    # exit status 1
ctres-validate --stream demo/stream/events.ndjson                        # exit status 0
ctres-validate demo/stream/package --reconcile demo/stream/events.ndjson # exit status 0
```

## Schema

validator-lite carries a copy of the schema files of [ctres-standard/schema](https://github.com/ctres-standard/schema) under `src/ctres_validator_lite/schema/`, so that it runs without network access. `SCHEMA_VERSION` in `src/ctres_validator_lite/__init__.py` states the release copied. To update the copy from a checkout of the schema repository:

```sh
python scripts/sync_schema.py ../schema
```

The script copies the files byte for byte (`schema/`, `schema/records/` and `schema/stream/`, every `*.schema.json`), checks that every `$id` lies under the version path of the release, and updates `SCHEMA_VERSION`. The copy includes `profile.schema.json`, the structure of a jurisdiction profile, which validator-lite does not use; it does not include `stream/openapi.yaml`, the reference transport, which is documentation.

## Tests

The tests use the standard library `unittest` module only:

```sh
python -m unittest discover -s tests -v
```

They check that the clean package passes, that each defect is reported by its check, that every check reports a change made to a copy of the clean package, that valid variations (`not_recorded` values, omitted optional fields, a provider on one side of a movement, a correction of a statement the package carries, a gaming day on a boundary date of the period) are not reported, that each conformance level requires its record types and no more and that STR-09 is not run without a declared level, that a reference to a record type the level does not require is advisory and otherwise unchanged, that the level packages pass, that the 1.0 package under `tests/fixtures/clean_1_0/` passes unchanged and that a 1.0 package which lists an R13 file is rejected by the manifest schema, that malformed files (byte order marks, unreadable files, links outside the package, deep nesting) are reported rather than stopping the run, that the JSON output keeps its shape, that the demonstration packages and the stream are reproducible, and, where ctres-standard/schema is checked out next to this repository, that the bundled schema matches it. For R15 and the stream they check the conditions of a bet (winnings while open, `settled_at`, `void_reason`), REF-14 by level, that the demonstration stream passes and the package reconciles with it, and that each of STM-01 to STM-07 and REC-01 to REC-04 reports a change made to a copy of the stream or the package and nothing else: a line that is not JSON, a missing or undefined envelope field, sequence 0, an unknown record type or operation, a gap, sequences that go backwards, a redelivery and a conflicting repeat, an invalid record, a void without its identifier, a checkpoint whose count or hash is wrong or that covers sequences never seen, a day without a checkpoint, an update of a record no event created, events emitted too late, a streamed record absent from the package, a package record never streamed, a package record that differs from its final state or that the stream withdrew, and a manifest whose checkpoints differ from the stream's, with the exit status of each run. The same tests run on every push and pull request (`.github/workflows/test.yml`).

## Comments

Comments are welcome from authorities, operators, payment providers, auditors and anyone else.

* Open an issue at <https://github.com/ctres-standard/validator-lite/issues>, or
* write to <hello@ctres.org>.

Comments on the text of the Standard belong in [ctres-standard/spec](https://github.com/ctres-standard/spec), and comments on the schema in [ctres-standard/schema](https://github.com/ctres-standard/schema). See [CONTRIBUTING.md](CONTRIBUTING.md) for how changes are proposed.

Maintained by the editor of the Standard (see <https://ctres.org/governance/>).

## Licence

validator-lite, its bundled copy of the schema, the demonstration packages and the tests are licensed under the [Apache License, Version 2.0](LICENSE). The text of the Standard is licensed separately under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
