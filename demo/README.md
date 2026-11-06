# Demonstration packages

Four synthetic CTRES v1.1 packages for trying validator-lite, and the stream of one gaming day with its package. Their values are illustrative, like the examples in Annex C of the Standard. They describe a fictional operator, licence and profile in **XJ**, an ISO 3166-1 user-assigned code used here for a fictional jurisdiction. No value is drawn from any operator, player, provider or authority, and every manifest sets `"synthetic": true`.

All are generated from the same data by [`scripts/make_demo.py`](../scripts/make_demo.py), which reproduces them byte for byte:

```sh
python scripts/make_demo.py
```

| Package | Declared conformance level (§10) | Record types | Records | Result |
|---|---|---|---|---|
| [`demo/clean`](#democlean) | `level_4` Supervision | R1 to R14 | 74 | PASS, no findings |
| [`demo/level1`](#demolevel1) | `level_1` Return | R13 | 3 | PASS, 1 advisory finding |
| [`demo/level2`](#demolevel2) | `level_2` Evidence | R3, R4, R7, R13, R14 | 26 | PASS, 10 advisory findings |
| [`demo/defects`](#demodefects) | `level_4` Supervision | R1 to R14, with ten defects | 76 | FAIL, 9 blocking and 1 advisory |
| [`demo/stream/events.ndjson`](#demostream) | - (a stream, §8.4) | R3, R4, R5, R13, R15 events and a checkpoint | 26 events | `--stream`: PASS, no findings |
| [`demo/stream/package`](#demostream) | `level_2` Evidence | R3, R4, R7, R13, R15 | 22 | `--reconcile`: PASS, 7 advisory findings |

The clean package as release 1.0.1 wrote it, a CTRES v1.0 package without R13 and R14, is kept unchanged under [`tests/fixtures/clean_1_0`](../tests/fixtures/clean_1_0); the tests show that it still passes. Its manifest declares `level_2` in the v1.0 meaning of the field, a delivery level, so STR-09 is not run on it.

## demo/clean

| Item | Value |
|---|---|
| Operator | Example Operator Ltd (SYNTHETIC) |
| Licence | XJ/DEMO/0001, issued by Example Gambling Authority (fictional) |
| Profile | XJ-EXAMPLE 1.1.0 (fictional) |
| Period | 2026-11-01T00:00:00+01:00 to 2026-11-30T23:59:59+01:00 |
| Submission mode | Periodic package; declared conformance level `level_4` Supervision; `standard_version` 1.1 |
| Reporting currency | EUR |
| Rails | Card; bank transfer by instant payment; mobile money; virtual assets (USDT on Ethereum, held in a provider's pooled wallet) |
| Venue | V-DEMO-01, a land-based venue whose cage float is an R1 location |

| File | Record type | Records | Content |
|---|---|---|---|
| `R1_funds_locations.jsonl` | R1 Funds Location | 6 | Player-funds and operational bank accounts, a card acquirer balance, a mobile money collection account, a pooled virtual-asset wallet at a provider (custody model `omnibus_at_provider`), and the cage float of venue V-DEMO-01, which carries `venue_id`. |
| `R2_payment_instrument_links.jsonl` | R2 Payment Instrument Link | 8 | Two instruments on each of the four rails, with holder verification. |
| `R3_deposits.jsonl` | R3 Deposit | 12 | Three deposits per rail. Mobile money deposits carry an excise tax line; virtual-asset deposits are on chain and off chain, with an attestation reference. |
| `R4_withdrawals.jsonl` | R4 Withdrawal | 6 | Payouts on every rail, each to the instrument that funded the account. |
| `R5_check_decisions.jsonl` | R5 Check Decision | 20 | One check before each payment, and a source-of-funds review in which an analyst's decision supersedes an automated step-up. |
| `R6_internal_movements.jsonl` | R6 Internal Movement | 5 | Settlements into the player-funds account, a sweep of the month's online gaming revenue to the operational account with a justification, a transfer from a provider into the pooled wallet, and the banking of the venue's counted drop. |
| `R7_reconciliation_statements.jsonl` | R7 Reconciliation Statement | 2 | One location statement for the player-funds bank account and one coverage statement. |
| `R8_exceptions.jsonl` | R8 Exception | 1 | The unexplained difference on the location statement, still under review. It names the bank statement line, which by definition has no record in the package. |
| `R9_incidents.jsonl` | R9 Incident | 1 | A mobile money disruption, notified and closed. |
| `R10_provider_register.jsonl` | R10 Provider Register | 4 | Card acquirer, bank, mobile money operator and virtual-asset service provider. |
| `R11_provider_attestations.jsonl` | R11 Provider Attestation | 1 | The virtual-asset provider's attestation for the pooled wallet. |
| `R12_report_references.jsonl` | R12 Report Reference | 2 | The remittance of the excise tax withheld on mobile money deposits, and the month's levy return, which the sports statement cites for the authority's figure. |
| `R13_gaming_revenue_statements.jsonl` | R13 Gaming Revenue Statement | 3 | Three lines for the month, each with the core fields of §4.13 first. Two online lines: sports betting, formula `all_in`, with bonus play and an open-bet liability at each cut-off, (4800.00 + 320.00 − 60.00) − (4590.00 + 260.00) = 210.00; casino, formula `cash_only`, its bonus play carried but outside the formula, 2950.00 − 0.00 − 2810.00 = 140.00. Their GGR, 350.00, is the amount swept to the operational account by M-2026-11-0003. The third is the venue line of V-DEMO-01 (`channel` `venue`, `venue_id`), formula `cash_only`, 48360.00 − 0.00 − 32240.00 = 16120.00: the month's win on the floor, of which R14 counts one gaming day. All three self-assess a levy at 20%. |
| `R14_venue_counts.jsonl` | R14 Venue Count | 3 | The count of one gaming day at V-DEMO-01: a slot machine with its meter set at the start and the end (win by the meter formula, 74.00), a table with inventories, fills, credits and drop (win by the drop formula, 732.00), and the venue total with the count-room figures and a variance of −2.00 against the units. Each row banks its drop to M-2026-11-0005. |

The package holds 74 records. `ctres-validate demo/clean` reports no findings and exits with status 0:

```text
Result: PASS: no blocking findings, 0 advisory; declared level_4 (Supervision).
```

## demo/level1

The manifest and `R13_gaming_revenue_statements.jsonl` of `demo/clean`, nothing else: the minimum set of `level_1` Return (§10). The package identifier is `PKG-XJ-DEMO-0001-2026-11-LEVEL1`. Its three statements are checked for structure, for their periods (REF-09), for the correction rule (REF-10) and for their arithmetic (REF-13). The sports statement's `authority_figure_ref` cites a report reference in R12, which the level does not require and the package does not carry: REF-12 reports it as one advisory finding, not as a failure.

| Check | Expected finding |
|---|---|
| REF-12 (advisory) | `authority_figure_ref/report_reference_id - not resolved: R12 is not required at level_1 and is not in the package` |

`ctres-validate demo/level1` exits with status 0:

```text
Result: PASS: no blocking findings, 1 advisory; declared level_1 (Return).
```

## demo/level2

The R3, R4, R7 and R13 files of `demo/clean`, the core, and its R14 file, which `level_2` Evidence requires because the venue line of R13 has `channel` `venue` (§10). The package identifier is `PKG-XJ-DEMO-0001-2026-11-LEVEL2`. Every reference from these records to the Custody module (R1, R2, R6, R10, R11) and the Supervision module (R5, R8, R9, R12) is an identifier in the operator's own systems, present in the record and not resolved within the package: each check reports one advisory finding per field, ten in all, and the package passes.

| Check | Expected findings (all advisory) |
|---|---|
| REF-01 | `location_id - not resolved: R1 is not required at level_2 and is not in the package` |
| REF-02 | `check_ids - not resolved: R5 is not required at level_2 and is not in the package` |
| REF-03 | `instrument_id - not resolved: R2 is not required at level_2 and is not in the package`; `source_instrument_ids - not resolved: R2 is not required at level_2 and is not in the package` |
| REF-05 | `provider_id - not resolved: R10 is not required at level_2 and is not in the package` |
| REF-06 | `exception_ids - not resolved: R8 is not required at level_2 and is not in the package` |
| REF-08 | `attestation_ref - not resolved: R11 is not required at level_2 and is not in the package` |
| REF-11 | `venue_id - not resolved: R1 is not required at level_2 and is not in the package`; `drop_deposit_ref - not resolved: R1 and R6 are not required at level_2 and are not in the package` |
| REF-12 | `authority_figure_ref/report_reference_id - not resolved: R12 is not required at level_2 and is not in the package` |

`ctres-validate demo/level2` exits with status 0:

```text
Result: PASS: no blocking findings, 10 advisory; declared level_2 (Evidence).
```

Had the package left R14 out, STR-09 would report `R14 is required at level_2 (Evidence) because an R13 line has channel venue (GRS-2026-11-XJ-DEMO-0001-CASINO-FLOOR-V-DEMO-01-EUR) but the manifest lists no R14 file`, a blocking finding. Had it declared no level, the same unresolved references would be noted rather than reported, and STR-09 would not run.

## demo/defects

The clean package with ten deliberate defects. Nine were made before the manifest was sealed, so that each is reported by its own check alone; the tenth alters a file after sealing. The package identifier is `PKG-XJ-DEMO-0001-2026-11-DEFECTS`.

| Defect | Expected check | Expected finding (file, line: detail) |
|---|---|---|
| `R6_internal_movements.jsonl` altered after the manifest was sealed: the amount of M-2026-11-0003 changed from 350.00 to 3500.00. | STR-02 | `R6_internal_movements.jsonl`: SHA-256 of the file is a6c2024479a7f85451f9e059b0570ad93287bbf12717c2ffe3206f1bb52c5f55; the manifest states 06157da61a04614cbeddc6af802f13bda42274e0f5521de561fbd33fdd2648ce |
| Deposit D-2026-11-0002 lacks the mandatory field `fx_source`. | STR-04 | `R3_deposits.jsonl` line 2: D-2026-11-0002: fx_source: required field is missing |
| Instrument I-MM-1006 carries `payout_status` `enabled`, which is not in the enumeration. | STR-05 | `R2_payment_instrument_links.jsonl` line 6: I-MM-1006: payout_status: 'enabled' is not one of ['not_eligible', 'pending', 'active', 'revoked'] |
| Withdrawal W-2026-11-0002 refers to check decision C-2026-11-9999, which is not in R5. | REF-02 | `R4_withdrawals.jsonl` line 2: W-2026-11-0002: check_ids/0 C-2026-11-9999 is not in R5 |
| Deposit D-2026-11-0006 uses instrument I-BANK-9999, which is not in R2. | REF-03 | `R3_deposits.jsonl` line 6: D-2026-11-0006: instrument_id I-BANK-9999 is not in R2 |
| Deposit D-2026-11-0013, added, books the acquirer reference of D-2026-11-0003 a second time. | REF-04 | `R3_deposits.jsonl` line 13: D-2026-11-0013: acquirer_reference 74999991000000000000003 (PSP-01) is already booked by D-2026-11-0003 (R3_deposits.jsonl line 3) |
| The sports statement's `period_end` is moved to 2026-12-01T23:59:59+01:00, after the manifest period ends. | REF-09 | `R13_gaming_revenue_statements.jsonl` line 1: GRS-2026-11-XJ-DEMO-0001-SPORTS-ONLINE-EUR: period_end 2026-12-01T23:59:59+01:00 is outside the period 2026-11-01T00:00:00+01:00 to 2026-11-30T23:59:59+01:00 |
| A correction of the casino statement, GRS-2026-11-XJ-DEMO-0001-CASINO-ONLINE-EUR-C1, is added; it names the sports statement as the statement it replaces. | REF-10 | `R13_gaming_revenue_statements.jsonl` line 4: GRS-2026-11-XJ-DEMO-0001-CASINO-ONLINE-EUR-C1: corrects_statement_id GRS-2026-11-XJ-DEMO-0001-SPORTS-ONLINE-EUR is a statement of another line: product_line SPORTS-PREMATCH-LIVE, not CASINO-SLOTS |
| The sports statement cites report reference RR-2026-11-9999 for the authority's figure, which is not in R12. | REF-12 | `R13_gaming_revenue_statements.jsonl` line 1: GRS-2026-11-XJ-DEMO-0001-SPORTS-ONLINE-EUR: authority_figure_ref/report_reference_id RR-2026-11-9999 is not in R12 |
| The casino statement declares `ggr_declared` 150.00, where its own `cash_only` formula gives 140.00. | REF-13 (advisory) | `R13_gaming_revenue_statements.jsonl` line 2: GRS-2026-11-XJ-DEMO-0001-CASINO-ONLINE-EUR: ggr_declared 150.00 differs from the cash_only formula on the statement's own fields: stakes_cash - stakes_refunded - winnings_cash = 140.00 |

`ctres-validate demo/defects` reports these nine blocking findings and one advisory finding, and no others, and exits with status 1. The test suite asserts exactly this (`tests/test_validator.py`).

```text
Result: FAIL: 9 blocking findings, 1 advisory; declared level_4 (Supervision).
```

The package fingerprint of `demo/defects`, the SHA-256 of its `manifest.json`, is `93dd351cd6eeacef326512eef6e3331c10917d0e9a7e696b7118d01d65e62fe1`.

## demo/stream

The stream (§8.4) of one gaming day, **14 November 2026**, for the same operator, licence and profile, and the package of that day. The stream is one for every record type, `XJ/DEMO/0001:all`, sequences 1 to 26. The day's payments are new rows for the month's players, instruments and rails (deposits D-2026-11-0021 to 0024, withdrawals W-2026-11-0021 and 0022, checks C-2026-11-1001 to 1006), so that no identifier is shared with the monthly packages; the day's bets are seven (R15), and the day's revenue lines (R13) aggregate them. Each event is emitted shortly after its anchor timestamp: a check one second after `performed_at`, a payment two seconds after `credited_at` or `paid_at`, a bet two seconds after `placed_at` or `settled_at`, the interim statement 31 seconds after its cut-off, the period statements 20 seconds after the day's; `--max-latency PT60S` passes.

| Sequence | Event | Content |
|---|---|---|
| 1 to 23 | R5, R3, R4 and R15 events, in the order they occur | Six R5 checks, each a second before its payment; four R3 deposits (card, bank transfer, mobile money, virtual asset on chain) and two R4 withdrawals (card, bank transfer); ten R15 events for seven bets: a sports bet placed open (3) and updated to `settled` (13), a slot round created `settled` (4), a sports bet placed open (7) and updated to `void` (12), two more slot rounds created settled (11, 15), a sports bet placed open (21) and updated to `cashed_out` (23), and a sports bet placed open (22) that is still open at the cut-off. |
| 8 | R13 `interim` | The sports line at noon, `statement_kind` `interim`: the two bets placed so far, stakes 120.00, nothing settled, superseded by the period statement. |
| 24, 25 | R13 `period` | The day's two period statements, at the cut-off: casino slots, `all_in`, (17.00 + 5.00 − 0.00) − (11.50 + 0.00) = 10.50; sports, `cash_only`, 165.00 − 100.00 (the void) − 60.00 = 5.00, with the open bet of 15.00 as `open_liability_end`. Both self-assess a levy at 20%. |
| 26 | checkpoint | `first_sequence` 1, `last_sequence` 25, `event_count` 25, `chain_hash` the SHA-256 of lines 1 to 25 each followed by a line feed, generated 31 seconds after the cut-off. |

`demo/stream/package` is the `level_2` package of the same day, identifier `PKG-XJ-DEMO-0001-2026-11-14-STREAM`, period 2026-11-14T00:00:00+01:00 to 2026-11-14T23:59:59+01:00: `R3_deposits.jsonl` (4), `R4_withdrawals.jsonl` (2), `R7_reconciliation_statements.jsonl` (the day's coverage statement, with the open bet among the liabilities), `R13_gaming_revenue_statements.jsonl` (the two period statements) and `R15_bet_events.jsonl` (the final state of each of the seven bets: four `settled`, one `void`, one `cashed_out`, one `open`), with the checkpoint listed in the manifest's `stream_checkpoints`. No R13 line has `channel` `venue`, so R14 is not required.

`ctres-validate --stream demo/stream/events.ndjson` reports no findings (STM-07 is not run without `--max-latency`) and exits with status 0:

```text
Result: PASS: no blocking findings, 0 advisory; 26 events in 1 stream (XJ/DEMO/0001:all, sequences 1 to 26), 1 checkpoint.
```

`ctres-validate demo/stream/package --reconcile demo/stream/events.ndjson` applies the package checks, the stream checks and REC-01 to REC-04. The package passes with seven advisory findings, all of the kinds the level packages show: the references the level does not resolve, and the R5 checks the stream carries and the package, which the level does not require to carry R5, does not.

| Check | Expected findings (all advisory) |
|---|---|
| REF-01 | `location_id - not resolved: R1 is not required at level_2 and is not in the package` |
| REF-02 | `check_ids - not resolved: R5 is not required at level_2 and is not in the package` |
| REF-03 | `instrument_id - not resolved: R2 is not required at level_2 and is not in the package`; `source_instrument_ids - not resolved: R2 is not required at level_2 and is not in the package` |
| REF-05 | `provider_id - not resolved: R10 is not required at level_2 and is not in the package` |
| REF-08 | `attestation_ref - not resolved: R11 is not required at level_2 and is not in the package` |
| REC-01 | `R5 records - not reconciled: R5 is not required at level_2 and is not in the package`; and a note: `1 R13 interim statement is superseded by the period statement and not expected in the package` |
| REC-02 | no finding; a note: `R7 is not streamed: its records are not reconciled` |

```text
Result: PASS: no blocking findings, 7 advisory; declared level_2 (Evidence); reconciled with demo/stream/events.ndjson (26 events, 1 checkpoint).
```

Had a bet been left out of the package, REC-01 would report `sequence 22 (B-2026-11-14-0007): the final state of this R15 record is not in the package`; had its winnings differed, REC-03 would report `B-2026-11-14-0001: differs from the final streamed state (sequence 13): winnings 37.00 in the package, 36.00 in the stream`; had the manifest's checkpoint carried another hash, REC-04 would report it field by field. The test suite exercises each (`tests/test_validator.py`).
