# Changelog

Versions follow `MAJOR.MINOR.PATCH`, where `MAJOR.MINOR` is the version of the Standard implemented. See [CONTRIBUTING.md](CONTRIBUTING.md#versioning).

## 1.1.0 — 4 November 2026

Implements CTRES v1.1: the record model of v1.0 extended for gaming revenue and the operator's levy, and the conformance levels of §10 defined by scope. A package produced under 1.0 is validated unchanged and keeps `standard_version` `1.0`.

### Added

* Record types R13 Gaming Revenue Statement and R14 Venue Count (§4.13, §4.14). STR-04 to STR-07 apply to them as to every record type, including the R14 condition that a row carries either `gaming_day` or `period_start` and `period_end`; STR-08 applies the 1.1 manifest schema, under which a package that lists an R13 or R14 file declares `standard_version` `1.1`.
* Referential checks REF-09 to REF-13: every R13 statement period and every R14 gaming day or period lies within the manifest period (REF-09); a correction names the statement it replaces, another statement of the same line where the package carries it, and is noted, not reported, where the statement may belong to an earlier package (REF-10); a venue count cites a venue an R1 location carries and banks its drop to an R6 movement or an R1 location (REF-11); an authority figure cites a report reference in R12 (REF-12); and, advisory, `ggr_declared` follows the formula the statement names, `all_in` or `cash_only`, on the statement's own fields, in exact decimal arithmetic (REF-13). REF-09 is not run when REF-07 is not run.
* Structural check STR-09 (§10; Annex D): every record type the declared conformance level requires is listed in the manifest, one finding per missing type, and R14 at `level_2` and above where any R13 line has `channel` `venue`. The levels are defined by scope: `level_1` Return (R13), `level_2` Evidence (+ R3, R4, R7), `level_3` Custody (+ R1, R2, R6, R10, R11), `level_4` Supervision (+ R5, R8, R9, R12); any record type may be included at any level. Where the manifest declares no level, STR-09 is not run and says so in a note. In a package that declares `standard_version` `1.0`, `conformance_level_declared` keeps its v1.0 meaning, a delivery level: STR-09 is not run and references are resolved as before.
* References resolved by level (§10): a reference to a record type the declared level does not require and the package does not carry is reported as one advisory finding per field and check, for example `instrument_id — not resolved: R2 is not required at level_2 and is not in the package`, by REF-01, REF-02, REF-03, REF-05, REF-06, REF-08, REF-11 and REF-12. Where the type's file is in the package the reference is blocking as before, and where no level is declared, or the level requires the type, the check notes the unresolved reference as before. Each finding in the JSON output now carries its own `severity`, `blocking_findings` and `advisory_findings` count findings by it, and the text report shows a check whose findings are all advisory as advisory.
* The result line of the text report states the declared level, `declared level_2 (Evidence)`, or `level not declared`; the JSON output's `manifest` carries `conformance_level_declared`.
* `demo/clean` is a 1.1 package declaring `level_4`: 74 records across R1 to R14, with two online gaming revenue lines whose GGR is the sum swept to the operational account, the venue line of a land-based venue, and one gaming day's count there with the cage float in R1. `demo/level1` (the manifest and R13, `level_1`) and `demo/level2` (R3, R4, R7, R13 and R14, `level_2`) are the same data cut down to the record types their level requires; both pass, with one and ten advisory findings for references the level does not resolve. `demo/defects` adds one defect for each of REF-09, REF-10, REF-12 and REF-13. The clean 1.0 package of release 1.0.1 is kept unchanged under `tests/fixtures/clean_1_0`, and the tests show that it passes.
* STR-04 states in words that exactly one of two sets of fields is required, as on an R14 row, instead of quoting the record.

### Changed

* Bundled schema 1.1.0: 19 schemas, `$id` under `https://ctres.org/schema/1.1/`. `STANDARD_VERSION` is `1.1`, and the `standard_version` of the JSON output says so. Among the conditions of that release which STR-04 and STR-05 report: a slot row's meters unless `meter_source` is `not_recorded`, the drop and fills of a slot row that wins by `slot_drop_formula`, a `win_formula` that fits the unit type, and `bonus_granted` and `bonus_expired` behind `stakes_bonus` or `winnings_bonus`; R13 carries `venue_id` and `player_location`, and `stakes_basis` accepts `accrual_at_result`; the manifest's `conformance_level_declared` is `level_1` to `level_4`.
* The former `level_1` to `level_3` of v1.0 (Records, Structured, Continuous) described delivery maturity and are replaced by the scope levels of §10; delivery is the manifest `submission_mode` of §8.1, which validator-lite does not test.
* The `not_checked` text, and the README, name what stays with the conformance suite: the money bridge of §4.13 between R13 and R3, R4 and R7; the agreement of R14 counts with the R13 venue line and with the bankings in R6 and R7; whether `jurisdiction_category` is in the profile's taxonomy.
* The demonstration profile is XJ-EXAMPLE 1.1.0 (fictional). R13 records in the demonstration packages carry the core fields of §4.13 first, as the schema lists them.

## 1.0.1 — 3 November 2026

- Bundled schema 1.0.1 (descriptions only). No change to the checks.

## 1.0.0 — 2026-10-05

Draft for consultation. First release, implementing the Structural and Referential classes of §11 of CTRES v1.0, universal edition (2 October 2026).

### Added

* Structural checks STR-01 to STR-08: files present, SHA-256 and record counts as in the manifest, records valid against the schema of their record type, enumerations, decimal strings, timestamps with an explicit offset and real calendar dates, record identifiers unique within each record type, and a valid manifest.
* Referential checks REF-01 to REF-08: funds locations and movement sides, check decisions and supersession, instruments, single booking of each rail reference, providers, links from statements, exceptions, incidents and report references, transactions inside the manifest period (advisory), and provider attestations.
* `ctres-validate` command: a text report grouped by class, JSON output with `--json`, the package fingerprint, and exit status 0, 1 or 2.
* A copy of the CTRES JSON Schema, release 1.0.0, and `scripts/sync_schema.py` to update it.
* Synthetic demonstration packages `demo/clean` and `demo/defects`, generated by `scripts/make_demo.py`.
* Tests using the standard library `unittest` module, and a GitHub Actions workflow that runs them.
