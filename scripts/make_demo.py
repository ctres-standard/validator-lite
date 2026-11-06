#!/usr/bin/env python3
"""Write the synthetic demonstration packages demo/clean, demo/level1, demo/level2 and demo/defects, and the
stream of one gaming day, demo/stream/events.ndjson, with its package demo/stream/package.

Usage:  python scripts/make_demo.py [OUT_DIR]        (default: demo/)

Everything describes a fictional operator, licence and profile in the fictional jurisdiction XJ (an
ISO 3166-1 user-assigned code), from the same synthetic data. Every value is invented. demo/clean is
a CTRES v1.1 package with record types R1 to R14 (standard_version 1.1, R13 gaming revenue statements
and R14 venue counts included) that declares level_4 and passes every check of validator-lite.
demo/level1 (manifest + R13, level_1) and demo/level2 (manifest + R3, R4, R7, R13 and R14, level_2)
are the same data cut down to the record types their level requires (LEVEL_PACKAGES); both pass.
demo/defects is the clean package with the deliberate defects listed in DEFECTS (and in demo/README.md).
demo/stream/events.ndjson is the stream (§8.4) of the gaming day 14 November 2026 for the same operator:
the R5 checks, R3 deposits, R4 withdrawals and R15 bet events of the day as they occur, an R13 interim
statement at noon, the day's R13 period statements at the cut-off, and the checkpoint of the day;
demo/stream/package is the level_2 package of that day (R3, R4, R7, R13, R15, with the checkpoint in the
manifest's stream_checkpoints), so that the stream passes --stream and the package passes --reconcile
against it. The output is byte-for-byte reproducible. The 1.0 package that earlier releases of this
script wrote is kept unchanged under tests/fixtures/clean_1_0.
"""
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERIOD_START, PERIOD_END = "2026-11-01T00:00:00+01:00", "2026-11-30T23:59:59+01:00"
OPERATOR = "Example Operator Ltd (SYNTHETIC)"
AUTHORITY = "Example Gambling Authority (fictional)"
LICENCE, PROFILE = "XJ/DEMO/0001", "XJ-EXAMPLE"
SCOPE = "demo-brand"                      # player_ref_scope
CET, UTC = timezone(timedelta(hours=1)), timezone.utc
USDT_EUR = D("0.92")                      # reporting-currency rate for USDT-ERC20, and the account rate
ATTESTATION = "ATT-2026-11-VASP-01"
SPORTS, CASINO = "GRS-2026-11-XJ-DEMO-0001-SPORTS-ONLINE-EUR", "GRS-2026-11-XJ-DEMO-0001-CASINO-ONLINE-EUR"
VENUE, FLOAT, BANKING = "V-DEMO-01", "L-VENUE-01-FLOAT", "M-2026-11-0005"   # the venue, its cage float, its drop banking
FLOOR = f"GRS-2026-11-XJ-DEMO-0001-CASINO-FLOOR-{VENUE}-EUR"                 # the venue line of R13

FILES = {"R1": "R1_funds_locations.jsonl", "R2": "R2_payment_instrument_links.jsonl",
         "R3": "R3_deposits.jsonl", "R4": "R4_withdrawals.jsonl", "R5": "R5_check_decisions.jsonl",
         "R6": "R6_internal_movements.jsonl", "R7": "R7_reconciliation_statements.jsonl",
         "R8": "R8_exceptions.jsonl", "R9": "R9_incidents.jsonl", "R10": "R10_provider_register.jsonl",
         "R11": "R11_provider_attestations.jsonl", "R12": "R12_report_references.jsonl",
         "R13": "R13_gaming_revenue_statements.jsonl", "R14": "R14_venue_counts.jsonl", "R15": "R15_bet_events.jsonl"}

# The core fields of an R13 statement, first in every statement (§4.13); the conditional and optional fields follow.
R13_CORE = ("statement_id", "statement_kind", "licence_ref", "product_line", "channel", "period_start", "period_end",
            "currency", "stakes_basis", "winnings_basis", "stakes_cash", "stakes_refunded", "winnings_cash",
            "ggr_declared", "ggr_formula", "prepared_by", "reviewed_by", "evidence_ref")

# The level packages (§10): directory -> (conformance level declared, record types the level requires, which the
# package carries). R14 is required at level_2 because the clean R13 has a venue line; level_1 needs R13 alone.
LEVEL_PACKAGES = {"level1": ("level_1", ("R13",)), "level2": ("level_2", ("R3", "R4", "R7", "R13", "R14"))}

# Rail -> provider, funds location, rail reference type, currency, time zone, R5 check performed before money moves.
RAILS = {
    "card": ("PSP-01", "L-PSP-01-BAL", "acquirer_reference", "EUR", CET,
             ("fraud", "transaction", "Fraud screening service FRD-01 (fictional)", "provider", "low")),
    "bank_transfer": ("BANK-01", "L-BANK-PF-01", "instant_payment_e2e_id", "EUR", CET,
                      ("sanctions", "player", "Consolidated sanctions list via SCR-01 (fictional)", "provider", "no_match")),
    "mobile_money": ("MMO-01", "L-MMO-01-COL", "operator_receipt", "EUR", CET,
                     ("self_exclusion", "player", "XJ self-exclusion register (fictional)", "authority_system", "no_match")),
    "virtual_asset": ("VASP-01", "L-VASP-01-POOL", "transaction_hash", "USDT-ERC20", UTC,
                      ("blockchain_analytics", "address", "Analytics provider BAP-01 (fictional)", "provider", "low")),
}

# n, rail, player, instrument, day, hour, minute, amount, on chain (virtual assets only)
DEPOSITS = [
    (1, "card", "P-1001", "I-CARD-1001", 3, 19, 2, "120.00", None),
    (2, "card", "P-1002", "I-CARD-1002", 8, 21, 15, "75.00", None),
    (3, "card", "P-1001", "I-CARD-1001", 15, 18, 40, "200.00", None),
    (4, "bank_transfer", "P-1003", "I-BANK-1003", 4, 12, 5, "500.00", None),
    (5, "bank_transfer", "P-1004", "I-BANK-1004", 12, 9, 30, "1500.00", None),
    (6, "bank_transfer", "P-1003", "I-BANK-1003", 21, 20, 11, "250.00", None),
    (7, "mobile_money", "P-1005", "I-MM-1005", 5, 7, 45, "40.00", None),
    (8, "mobile_money", "P-1006", "I-MM-1006", 10, 13, 20, "60.00", None),
    (9, "mobile_money", "P-1005", "I-MM-1005", 18, 19, 55, "25.00", None),
    (10, "virtual_asset", "P-1007", "I-VA-1007", 6, 10, 12, "300.000000", True),
    (11, "virtual_asset", "P-1008", "I-VA-1008", 14, 15, 3, "150.000000", False),
    (12, "virtual_asset", "P-1007", "I-VA-1007", 25, 8, 47, "500.000000", True),
]
WITHDRAWALS = [
    (1, "card", "P-1001", "I-CARD-1001", 20, 10, 0, "100.00", None),
    (2, "bank_transfer", "P-1003", "I-BANK-1003", 9, 16, 30, "400.00", None),
    (3, "bank_transfer", "P-1004", "I-BANK-1004", 26, 11, 5, "900.00", None),
    (4, "mobile_money", "P-1006", "I-MM-1006", 16, 18, 22, "30.00", None),
    (5, "virtual_asset", "P-1007", "I-VA-1007", 27, 9, 14, "250.000000", True),
    (6, "virtual_asset", "P-1008", "I-VA-1008", 28, 17, 40, "100.000000", False),
]

DEFECTS = [   # check id, what was done; applied to demo/defects only
    ("STR-02", "R6_internal_movements.jsonl altered after the manifest was sealed: M-2026-11-0003 amount 350.00 -> 3500.00"),
    ("STR-04", "D-2026-11-0002 lacks the mandatory field fx_source"),
    ("STR-05", "I-MM-1006 carries payout_status 'enabled', which is not in the enumeration"),
    ("REF-02", "W-2026-11-0002 refers to check decision C-2026-11-9999, which is not in R5"),
    ("REF-03", "D-2026-11-0006 uses instrument I-BANK-9999, which is not in R2"),
    ("REF-04", "D-2026-11-0013 books the acquirer reference of D-2026-11-0003 a second time"),
    ("REF-09", f"{SPORTS} period_end moved to 2026-12-01T23:59:59+01:00, after the manifest period ends"),
    ("REF-10", f"{CASINO}-C1, a correction added, names the sports statement as the statement it replaces"),
    ("REF-12", f"{SPORTS} cites report reference RR-2026-11-9999 for the authority's figure, which is not in R12"),
    ("REF-13", f"{CASINO} declares ggr 150.00 where its cash_only formula gives 140.00"),
]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ts(dt):
    return dt.isoformat().replace("+00:00", "Z")


def q(value, places="0.01"):
    return str(D(value).quantize(D(places)))


def fees(ccy):
    zero = "0.000000" if ccy == "USDT-ERC20" else "0.00"
    return {"currency_or_asset": ccy, "rail": zero, "provider": zero, "network": zero}


def address(player):
    return "0x" + sha(f"synthetic-address-{player}")[:40]


# ------------------------------------------------------------------ registers: R10, R1, R2

def providers():
    def provider(pid, name, role, licence, dd, **extra):
        return {"provider_id": pid, "legal_name": name, "provider_role": role,
                "authorising_authority": "Example Central Bank (fictional)", "licence_ref": licence,
                "authorisation_country": "XJ", "regulator_notification_status": "notified",
                "due_diligence_completed_at": dd, "next_review_at": dd.replace("2026", "2027"),
                "data_locations": ["XJ"], **extra, "evidence_ref": f"DD-{pid}-2026"}
    return [
        provider("PSP-01", "Example Card Acquiring Ltd (fictional)", "acquirer", "XJ-CB-ACQ-0101", "2026-02-10"),
        provider("BANK-01", "Example Bank plc (fictional)", "bank", "XJ-CB-BNK-0007", "2026-01-20"),
        provider("MMO-01", "Example Mobile Money Ltd (fictional)", "mobile_money_operator", "XJ-CB-MMO-0003", "2026-03-02"),
        provider("VASP-01", "Example Virtual Asset Services Ltd (fictional)", "virtual_asset_service_provider",
                 "XJ-CB-VASP-0011", "2026-01-12", travel_rule_capable=True),
    ]


def locations():
    def location(lid, ltype, purpose, provider, masked, ccy, protection, custody, venue=None, **extra):
        return {"location_id": lid, **({"venue_id": venue} if venue else {}), "location_type": ltype,
                "purpose_class": purpose, **({"provider_id": provider} if provider else {}),
                "identifier_masked": masked, "currency_or_asset": ccy, "protection_mechanism": protection,
                "custody_model": custody, "controlling_entity": OPERATOR, "location_jurisdiction": "XJ",
                "opened_at": "2026-01-05T09:00:00+01:00", "ownership_evidence_ref": f"DOC-OWN-{lid}", **extra}
    return [
        location("L-BANK-PF-01", "bank_account", "player_funds", "BANK-01", "XJ00 **** **** **** 4401", "EUR",
                 "segregated_account", "direct"),
        location("L-BANK-OPS-01", "bank_account", "operational", "BANK-01", "XJ00 **** **** **** 4402", "EUR",
                 "none", "direct"),
        location("L-PSP-01-BAL", "provider_balance", "player_funds", "PSP-01", "Merchant balance ****0101", "EUR",
                 "segregated_account", "hybrid"),
        location("L-MMO-01-COL", "mobile_money_collection", "player_funds", "MMO-01", "Pay-bill ***901", "EUR",
                 "segregated_account", "direct"),
        location("L-VASP-01-POOL", "crypto_wallet", "player_funds", "VASP-01", "Pooled account VASP-01/****", "USDT-ERC20",
                 "segregated_account", "omnibus_at_provider", chain="ethereum", temperature="hot",
                 key_control_model="provider_managed"),
        location(FLOAT, "cash_float", "operational", None, f"Cage float, venue {VENUE}", "EUR", "none", "direct",
                 venue=VENUE),
    ]


def instruments():
    def link(iid, player, rail, detail, method, verified_by, day, **extra):
        return {"instrument_id": iid, "player_ref": player, "player_ref_scope": SCOPE, "rail": rail,
                "instrument_detail": detail, **extra, "holder_match": "match", "holder_verification_method": method,
                "verified_at": f"2026-10-{day:02d}T10:00:00+01:00", "verified_by": verified_by, "payout_status": "active"}
    return [
        link("I-CARD-1001", "P-1001", "card", {"bin": "49999901", "last_four": "1001", "card_token": "TKN-DEMO-1001"},
             "issuer_check", "PSP-01", 12, funding_type="debit", issuer_country="XJ"),
        link("I-CARD-1002", "P-1002", "card", {"bin": "52999902", "last_four": "1002"},
             "issuer_check", "PSP-01", 14, funding_type="debit", issuer_country="XJ"),
        link("I-BANK-1003", "P-1003", "bank_transfer", {"account_number_masked": "XJ00 **** **** **** 1003", "scheme": "xj_instant"},
             "bank_name_check", "BANK-01", 15),
        link("I-BANK-1004", "P-1004", "bank_transfer", {"account_number_masked": "XJ00 **** **** **** 1004",
             "scheme": "xj_instant", "instant_payment_key_type": "national_id"}, "instant_payment_directory", "BANK-01", 18),
        link("I-MM-1005", "P-1005", "mobile_money", {"phone_number_hash": sha("synthetic-phone-P-1005"), "mobile_operator_id": "MMO-01"},
             "mobile_operator_kyc", "MMO-01", 20),
        link("I-MM-1006", "P-1006", "mobile_money", {"phone_number_hash": sha("synthetic-phone-P-1006"), "mobile_operator_id": "MMO-01"},
             "mobile_operator_kyc", "MMO-01", 21),
        link("I-VA-1007", "P-1007", "virtual_asset", {"chain": "ethereum", "address": address("P-1007"),
             "unique_deposit_address": False, "link_source": "player_declared"}, "signed_message", "wallet-verification-service", 22),
        link("I-VA-1008", "P-1008", "virtual_asset", {"chain": "ethereum", "address": address("P-1008"),
             "unique_deposit_address": False, "link_source": "provider_supplied"}, "provider_attestation", "VASP-01", 23),
    ]


# ------------------------------------------------------------------ payments and checks: R3, R4, R5

def payments(deposit_rows=DEPOSITS, withdrawal_rows=WITHDRAWALS, check_start=0):
    """R3, R4 and R5 for the rows given: the month's (the default) or the stream day's, whose check
    identifiers continue from check_start so that the two sets never share one."""
    deposits, withdrawals, checks = [], [], []

    def check(subject_type, subject_ref, ctype, register, party, result, at, decision="allow", by="automated", **extra):
        cid = f"C-2026-11-{check_start + len(checks) + 1:04d}"
        rec = {"check_id": cid, "subject_type": subject_type, "subject_ref": subject_ref}
        if subject_type == "player":
            rec["subject_ref_scope"] = SCOPE
        rec.update({"check_type": ctype, "register_or_provider": register, "version": "2026-11",
                    "performed_by_party": party, "performed_at": ts(at), "result_class": result, "decision": decision,
                    "decided_by": by, **extra, "evidence_ref": f"EV-{cid}"})
        checks.append(rec)
        return cid

    def payment(direction, n, rail, player, instrument, day, hour, minute, amount, on_chain):
        provider, location, ref_type, ccy, tz, (ctype, subject, register, party, result) = RAILS[rail]
        dep = direction == "deposit"
        tx_id = f"{'D' if dep else 'W'}-2026-11-{n:04d}"
        t0 = datetime(2026, 11, day, hour, minute, tzinfo=tz)
        va = rail == "virtual_asset"
        if va and not on_chain:
            ref_type, rail_ref = "provider_reference", f"VASP01-INV-{'D' if dep else 'W'}{n:06d}"
        elif va:
            rail_ref = "0x" + sha(f"synthetic-tx-{tx_id}")
        else:
            rail_ref = {"card": f"7499999{1 if dep else 2}{n:015d}",
                        "bank_transfer": f"E99999999{t0:%Y%m%d%H%M}{1 if dep else 2}{n:010d}",
                        "mobile_money": f"XJM{'D' if dep else 'W'}{n:07d}"}[rail]
        rate = USDT_EUR if va else D(1)
        reporting = q(D(amount) * rate)

        # Times: a deposit is checked, then credited; a withdrawal is debited on request, checked, approved, paid.
        reviewed = dep and n == 5                         # source-of-funds review: step-up, then allow by an analyst
        if dep:
            initiated, checked = t0, t0 + timedelta(seconds=1)
            settled = t0 + timedelta(minutes=2, seconds=30) if on_chain else t0 + timedelta(seconds=3)
            credited = t0 + timedelta(minutes=30 if reviewed else 5 if on_chain else 0, seconds=4)
        else:
            credited, checked = t0, t0 + timedelta(seconds=30)
            approved, initiated = t0 + timedelta(minutes=2), t0 + timedelta(minutes=3)
            settled = t0 + timedelta(minutes=5 if on_chain else 3, seconds=5)

        subject_ref = {"transaction": tx_id, "player": player, "address": address(player)}[subject]
        extra = {"exposure_categories": ["exchange"]} if ctype == "blockchain_analytics" else {}
        check_ids = [check(subject, subject_ref, ctype, register, party, result, checked, **extra)]
        if reviewed:
            first = check("player", player, "source_of_funds", "Source-of-funds review (operator)", "operator", "medium",
                          t0 + timedelta(seconds=2), decision="step_up")
            check_ids.append(check("player", player, "source_of_funds", "Source-of-funds review (operator)", "operator",
                                   "low", t0 + timedelta(minutes=25), by="analyst", supersedes=first))

        rec = {"tx_id": tx_id, "player_ref": player, "player_ref_scope": SCOPE, "direction": direction, "rail": rail,
               "instrument_id": instrument, "provider_id": provider, "rail_reference_type": ref_type,
               "rail_reference": rail_ref, "amount": amount, "currency_or_asset": ccy, "amount_reporting_ccy": reporting,
               "fx_rate": str(rate), "fx_source": "VASP-01 reference rate" if va else "same_as_reporting_currency"}
        if va:
            rec.update({"chain": "ethereum", "off_chain_movement": not on_chain})
            if on_chain:
                rec.update({"tx_hash": rail_ref, "block_time": ts(settled), "confirmations": 12,
                            "counterparty_address": address(player), "counterparty_type": "unhosted"})
        rec.update({"initiated_at": ts(initiated), "settled_at": ts(settled), "credited_at": ts(credited)})
        if not dep:
            rec.update({"requested_at": ts(t0), "approved_by": "rule:auto-payout-v1", "approved_at": ts(approved),
                        "paid_at": ts(settled)})
        credited_amount = D(reporting)
        rec["account_currency"] = "EUR"
        if va:
            rec["account_fx_rate"] = str(USDT_EUR)
        if dep and rail == "mobile_money":
            tax = q(D(amount) * D("0.05"))
            credited_amount -= D(tax)
            rec["tax_lines"] = [{"type": "excise_on_deposit", "rate": "0.05", "amount": tax,
                                 "authority": "Example Revenue Service (fictional)", "due_at": "2026-12-10",
                                 "remittance_ref": "TR-XJ-2026-11-01"}]
        rec.update({"credited_amount": str(credited_amount if dep else -credited_amount),
                    "ledger_entry_ref": f"LE-{tx_id}", "fees": fees(ccy), "check_ids": check_ids})
        if dep:
            rec["limit_check"] = "within_limit"
        rec.update({"outcome": "accepted", "location_id": location})
        if va:
            rec["attestation_ref"] = ATTESTATION
        if not dep:
            rec.update({"destination_rule": "same_instrument", "source_instrument_ids": [instrument]})
        return rec

    for row in deposit_rows:
        deposits.append(payment("deposit", *row))
    for row in withdrawal_rows:
        withdrawals.append(payment("withdrawal", *row))
    return deposits, withdrawals, checks


# ------------------------------------------------------------------ movements, statements and the rest

def movements(deps, wds):
    def total(recs, rail):
        return sum((D(r["amount"]) for r in recs if r["rail"] == rail), D(0))

    def movement(n, purpose, src, dst, amount, ccy, day, approver, crosses=False, ref=None, **extra):
        approved = datetime(2026, 11, day, 6, 0, tzinfo=CET)
        rec = {"movement_id": f"M-2026-11-{n:04d}", **src, **dst, "purpose": purpose, "crosses_purpose_class": crosses,
               **extra, "approved_by": approver, "approved_at": ts(approved),
               "executed_at": ts(approved + timedelta(hours=3)),
               "rail_reference": ref or f"BANK-01-TRF-202611{day:02d}-{n:04d}",
               "rail_reference_type": "provider_reference", "amount": amount, "currency_or_asset": ccy, "fees": fees(ccy)}
        return rec

    card_net = total(deps, "card") - total(wds, "card")
    return [
        movement(1, "settlement", {"source_location_id": "L-PSP-01-BAL"}, {"destination_location_id": "L-BANK-PF-01"},
                 q(card_net), "EUR", 22, "rule:daily-settlement-v1"),
        movement(2, "settlement", {"source_location_id": "L-MMO-01-COL"}, {"destination_location_id": "L-BANK-PF-01"},
                 "90.00", "EUR", 23, "rule:daily-settlement-v1"),
        movement(3, "sweep", {"source_location_id": "L-BANK-PF-01"}, {"destination_location_id": "L-BANK-OPS-01"},
                 "350.00", "EUR", 24, "head_of_payments", crosses=True, justification_ref="GGR-2026-11"),
        movement(4, "liquidity", {"source_provider_id": "VASP-01"}, {"destination_location_id": "L-VASP-01-POOL"},
                 "1000.000000", "USDT-ERC20", 2, "treasury_manager", ref="VASP01-TRF-000044"),
        movement(5, "sweep", {"source_location_id": FLOAT}, {"destination_location_id": "L-BANK-OPS-01"},
                 "1213.00", "EUR", 16, "venue_controller", ref="BANK-01-CIT-20261116-0005"),   # the count of 14 November
    ]


def statements(deps, wds, movs):
    loc = "L-BANK-PF-01"
    inflow = sum((D(r["amount"]) for r in deps if r["location_id"] == loc), D(0)) + \
        sum((D(m["amount"]) for m in movs if m.get("destination_location_id") == loc), D(0))
    outflow = sum((D(r["amount"]) for r in wds if r["location_id"] == loc), D(0)) + \
        sum((D(m["amount"]) for m in movs if m.get("source_location_id") == loc), D(0))
    opening = D("48000.00")
    closing_ledger = opening + inflow - outflow
    delta = D("25.00")                                   # an unexplained credit, owned by E-2026-11-0001
    common = {"period_start": PERIOD_START, "period_end": PERIOD_END, "currency_or_asset": "EUR"}
    return [
        {"statement_id": "REC-2026-11-L-BANK-PF-01", "kind": "location", **common, "location_id": loc,
         "external_source_type": "bank_statement", "opening_balance_external": q(opening),
         "closing_balance_external": q(closing_ledger + delta), "opening_balance_ledger": q(opening),
         "closing_balance_ledger": q(closing_ledger), "inflow_total": q(inflow), "outflow_total": q(outflow),
         "fees_total": "0.00", "unexplained_delta": q(delta), "unexplained_delta_reporting_ccy": q(delta),
         "exception_ids": ["E-2026-11-0001"], "evidence_refs": ["STMT-BANK-01-2026-11"],
         "prepared_by": "finance_ops", "reviewed_by": "compliance_officer"},
        {"statement_id": "COV-2026-11-XJ-DEMO-0001", "kind": "coverage", **common,
         "player_balances_total": "61250.40", "pending_withdrawals_total": "1200.00", "player_liability_total": "62450.40",
         "funds_held": {"segregated_account": "64980.00"}, "in_transit_total": "310.00", "shortfall": "0.00",
         "prepared_by": "finance_ops", "reviewed_by": "compliance_officer"},
    ]


def others(deps):
    exception = {"exception_id": "E-2026-11-0001", "category": "external_movement_without_ledger_entry",
                 "raised_at": "2026-11-24T02:00:00+01:00", "raised_by": "automated_reconciliation",
                 "source_statement_id": "REC-2026-11-L-BANK-PF-01",
                 "related_record_ids": ["L-BANK-PF-01", "BANK-01-STMT-20261123-0187"],
                 "amount": "25.00", "currency_or_asset": "EUR", "amount_reporting_ccy": "25.00",
                 "status": "under_review", "age_days": 6, "owner": "finance_ops"}
    incident = {"incident_id": "INC-2026-11-0001", "category": "rail_disruption",
                "detected_at": "2026-11-17T08:30:00+01:00", "notified_at": "2026-11-17T12:10:00+01:00",
                "deadline_at": "2026-11-18T08:30:00+01:00", "authority": AUTHORITY, "channel": "regulator_portal",
                "channel_name": "EGA incident portal (fictional)", "related_record_ids": ["MMO-01", "L-MMO-01-COL"],
                "status": "closed", "description": "Mobile money collection unavailable for three hours; no payment was lost."}
    attestation = {"attestation_id": ATTESTATION, "provider_id": "VASP-01", "period_start": "2026-10-31T23:00:00Z",
                   "period_end": "2026-11-30T22:59:59Z", "currency_or_asset": "USDT-ERC20", "opening_balance": "4200.000000",
                   "total_credited": "1950.000000", "total_debited": "350.000000", "balance_held_for_operator": "5800.000000",
                   "reference_scheme": "Provider references VASP01-INV-<D|W><sequence> and transaction hashes, carried in "
                                       "rail_reference of R3 and R4.",
                   "covers_location_ids": ["L-VASP-01-POOL"],
                   "signed_by": "Example Virtual Asset Services Ltd (fictional), finance director",
                   "signed_at": "2026-12-03T10:00:00Z", "evidence_ref": "ATT-VASP-01-2026-11.pdf"}
    report = {"report_reference_id": "RR-2026-11-0001", "report_type": "tax_remittance",
              "destination_authority": "Example Revenue Service (fictional)", "channel": "other",
              "channel_name": "XJ revenue e-filing (fictional)", "profile_rule_ref": "XJ-EXAMPLE@1.1.0#tax-excise-deposit",
              "related_record_ids": [r["tx_id"] for r in deps if r["rail"] == "mobile_money"],
              "deadline_at": "2026-12-10T23:59:59+01:00", "filed_at": "2026-12-04T10:00:00+01:00",
              "receipt_ref": "XJ-RS-ACK-000118"}
    levy_return = {"report_reference_id": "RR-2026-11-0002", "report_type": "levy_return",
                   "destination_authority": "Example Revenue Service (fictional)", "channel": "other",
                   "channel_name": "XJ revenue e-filing (fictional)", "profile_rule_ref": "XJ-EXAMPLE@1.1.0#levy-return-monthly",
                   "related_record_ids": [SPORTS, CASINO], "deadline_at": "2026-12-15T23:59:59+01:00",
                   "filed_at": "2026-12-05T09:30:00+01:00", "receipt_ref": "XJ-RS-ACK-000142"}
    return [exception], [incident], [attestation], [report, levy_return]


# ------------------------------------------------------------------ gaming revenue and venue counts: R13, R14

def revenue():
    """Three lines for the month, each with the core fields of §4.13 first. Two online lines: sports, all_in,
    (4800 + 320 - 60) - (4590 + 260) = 210.00; casino, cash_only, 2950 - 0 - 2810 = 140.00, its bonus play carried
    but outside the formula. Their GGR, 350.00, is the amount swept to the operational account by M-2026-11-0003
    (justification GGR-2026-11). The third is the venue line of VENUE: cash_only, 48360 - 0 - 32240 = 16120.00,
    the month's win on the floor, of which the count of 14 November (R14) shows one gaming day."""
    def line(statement_id, product_line, channel, basis, stakes, refunded, winnings, ggr, formula, evidence, **rest):
        return {"statement_id": statement_id, "statement_kind": "period", "licence_ref": "XJ/DEMO/0001",
                "product_line": product_line, "channel": channel, "period_start": PERIOD_START,
                "period_end": PERIOD_END, "currency": "EUR", "stakes_basis": "placed", "winnings_basis": basis,
                "stakes_cash": stakes, "stakes_refunded": refunded, "winnings_cash": winnings,
                "ggr_declared": ggr, "ggr_formula": formula, "prepared_by": "finance_ops",
                "reviewed_by": "compliance_officer", "evidence_ref": evidence, **rest}
    return [
        line(SPORTS, "SPORTS-PREMATCH-LIVE", "online", "paid", "4800.00", "60.00", "4590.00", "210.00", "all_in",
             "RPT-PLATFORM-GGR-2026-11-SPORTS", jurisdiction_category="betting",
             stakes_bonus="320.00", winnings_bonus="260.00", bonus_granted="150.00", bonus_expired="20.00",
             bonus_measurement="per_round", open_liability_start="60.00", open_liability_end="85.00",
             bets_count=1240, active_players=8,
             levy_base_declared="210.00", levy_rate="0.20", levy_amount_declared="42.00",
             authority_figure_ref={"report_reference_id": "RR-2026-11-0002", "figure": "ggr", "amount": "210.00"}),
        line(CASINO, "CASINO-SLOTS", "online", "credited", "2950.00", "0.00", "2810.00", "140.00", "cash_only",
             "RPT-PLATFORM-GGR-2026-11-CASINO", jurisdiction_category="casino_games",
             stakes_bonus="180.00", winnings_bonus="165.00", bonus_granted="120.00", bonus_expired="15.00",
             bonus_measurement="allocated_from_wallet_totals", rounds_count=5320, active_players=6,
             levy_base_declared="140.00", levy_rate="0.20", levy_amount_declared="28.00"),
        line(FLOOR, "CASINO-FLOOR", "venue", "paid", "48360.00", "0.00", "32240.00", "16120.00", "cash_only",
             f"RPT-VENUE-WIN-2026-11-{VENUE}", jurisdiction_category="casino_games", venue_id=VENUE,
             levy_base_declared="16120.00", levy_rate="0.20", levy_amount_declared="3224.00"),
    ]


def counts():
    """The count of one gaming day at the venue whose cage float is the R1 location FLOAT: a slot machine
    (win by meters: 865 in - 741 out - 50 hand paid - 0 cancelled = 74.00), a table (2890 + 400 + 942 - 2500
    - 1000 = 732.00) and the venue total (count room 12.00 + 1201.00 against a drop of 273.00 + 942.00 by
    the units: variance -2.00; win 806.00). The counted drop, 1213.00, is banked by BANKING."""
    def row(unit_type, unit_id, source, prepared_by, **fields):
        return {"count_id": f"VC-2026-11-14-{VENUE}-{unit_id if unit_type != 'venue_total' else 'TOTAL'}",
                "venue_id": VENUE, "gaming_day": "2026-11-14", "unit_type": unit_type, "unit_id": unit_id,
                "currency": "EUR", "meter_source": source, **fields, "drop_deposit_ref": BANKING,
                "prepared_by": prepared_by, "reviewed_by": "venue_controller"}
    meters = {"coin_in": "184256.00", "coin_out": "170123.00", "jackpots_hand_paid": "3240.00",
              "cancelled_credits": "512.00", "bill_in": "61230.00", "ticket_in": "8821.00", "ticket_out": "40512.00",
              "games_played": 221045}
    meters_end = {**meters, "coin_in": "185121.00", "coin_out": "170864.00", "jackpots_hand_paid": "3290.00",
                  "bill_in": "61445.00", "ticket_in": "8879.00", "ticket_out": "40688.00", "games_played": 221489}
    return [
        row("slot_machine", "SM-0001", "electronic", "slot_operations", meters_start=meters, meters_end=meters_end,
            win_declared="74.00", win_formula="slot_meter_formula"),
        row("table", "T-01", "manual_read", "table_games_supervisor", opening_inventory="2500.00",
            closing_inventory="2890.00", fills="1000.00", credits="400.00", drop_cash="942.00", drop_markers="0.00",
            win_declared="732.00", win_formula="table_drop_formula"),
        row("venue_total", VENUE, "electronic", "count_room", hard_count="12.00", soft_count="1201.00",
            count_variance="-2.00", win_declared="806.00", win_formula="profile"),
    ]


def records():
    deps, wds, checks = payments()
    movs = movements(deps, wds)
    r8, r9, r11, r12 = others(deps)
    return {"R1": locations(), "R2": instruments(), "R3": deps, "R4": wds, "R5": checks, "R6": movs,
            "R7": statements(deps, wds, movs), "R8": r8, "R9": r9, "R10": providers(), "R11": r11, "R12": r12,
            "R13": revenue(), "R14": counts()}


def apply_defects(recs):
    def find(rtype, key, value):
        return next(r for r in recs[rtype] if r[key] == value)
    del find("R3", "tx_id", "D-2026-11-0002")["fx_source"]                            # STR-04
    find("R2", "instrument_id", "I-MM-1006")["payout_status"] = "enabled"              # STR-05
    find("R4", "tx_id", "W-2026-11-0002")["check_ids"] = ["C-2026-11-9999"]            # REF-02
    find("R3", "tx_id", "D-2026-11-0006")["instrument_id"] = "I-BANK-9999"             # REF-03
    twice = copy.deepcopy(find("R3", "tx_id", "D-2026-11-0003"))                       # REF-04
    twice.update({"tx_id": "D-2026-11-0013", "ledger_entry_ref": "LE-D-2026-11-0013"})
    recs["R3"].append(twice)
    sports, casino = find("R13", "statement_id", SPORTS), find("R13", "statement_id", CASINO)
    restated = copy.deepcopy(casino)                                                  # REF-10: a correction
    restated.update({"statement_id": f"{CASINO}-C1", "statement_kind": "correction", "winnings_cash": "2822.00",
                     "ggr_declared": "128.00", "evidence_ref": "RPT-PLATFORM-GGR-2026-11-CASINO-C1",
                     "levy_base_declared": "128.00", "levy_amount_declared": "25.60"})
    correction = {**{k: restated[k] for k in R13_CORE},                               # core first, as in §4.13
                  "corrects_statement_id": SPORTS, "correction_reason": "Void after settlement: 14 rounds settled on "
                  "2026-11-29 were voided on 2026-12-03 after the period statement was filed; winnings_cash is restated.",
                  **{k: v for k, v in restated.items() if k not in R13_CORE}}
    recs["R13"].append(correction)
    sports["period_end"] = "2026-12-01T23:59:59+01:00"                                 # REF-09
    sports["authority_figure_ref"]["report_reference_id"] = "RR-2026-11-9999"          # REF-12
    casino["ggr_declared"] = "150.00"                                                  # REF-13


# ------------------------------------------------------------------ writing

def write(out, recs, package_id, level, tamper=None, period=(PERIOD_START, PERIOD_END), stream_checkpoints=None):
    """Write one file per record type in recs, in R1 to R15 order, sealed in a manifest that declares level and
    covers period; with stream_checkpoints, the manifest lists them (§8.4)."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    entries = []
    for rtype, name in FILES.items():
        if rtype not in recs:
            continue
        text = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in recs[rtype])
        (out / name).write_text(text, encoding="utf-8")
        entries.append({"file": name, "record_type": rtype, "record_count": len(recs[rtype]), "sha256": sha(text)})
    manifest = {"standard": "CTRES", "standard_version": "1.1", "package_id": package_id,
                "licence_number": LICENCE, "licensing_authority": AUTHORITY, "licensee": OPERATOR,
                "profile_id": PROFILE, "profile_version": "1.1.0", "period_start": period[0],
                "period_end": period[1], "submission_mode": "periodic_package", "reporting_currency": "EUR",
                "conformance_level_declared": level, "records_start_date": "2026-01-05", "files": entries,
                "generating_software": "ctres-validator-lite demonstration generator (scripts/make_demo.py)",
                "generating_software_version": "1.1.0",
                **({"stream_checkpoints": stream_checkpoints} if stream_checkpoints else {}), "synthetic": True}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if tamper:                                     # STR-02: a file altered after the manifest was sealed
        name, old, new = tamper
        path = out / name
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1, old
        path.write_text(text.replace(old, new), encoding="utf-8")


# ------------------------------------------------------------------ the stream of one gaming day (§8.4)

DAY = 14                                                                      # 14 November 2026, the day R14 counts
DAY_START, DAY_END = f"2026-11-{DAY}T00:00:00+01:00", f"2026-11-{DAY}T23:59:59+01:00"
STREAM_ID = f"{LICENCE}:all"                                                  # one stream for every record type
SPORTS_DAY = f"GRS-2026-11-{DAY}-XJ-DEMO-0001-SPORTS-ONLINE-EUR"
CASINO_DAY = f"GRS-2026-11-{DAY}-XJ-DEMO-0001-CASINO-ONLINE-EUR"
INTERIM_CUT = (12, 0, 0)                                                      # the interim statement at noon

# The day's payments: the same players, instruments and rails as the month's; identifiers from 21 so that the
# two sets never share one. n, rail, player, instrument, day, hour, minute, amount, on chain.
STREAM_DEPOSITS = [
    (21, "card", "P-1001", "I-CARD-1001", DAY, 9, 12, "50.00", None),
    (22, "bank_transfer", "P-1004", "I-BANK-1004", DAY, 11, 40, "300.00", None),
    (23, "mobile_money", "P-1005", "I-MM-1005", DAY, 13, 5, "20.00", None),
    (24, "virtual_asset", "P-1007", "I-VA-1007", DAY, 16, 20, "100.000000", True),
]
STREAM_WITHDRAWALS = [
    (21, "card", "P-1001", "I-CARD-1001", DAY, 18, 30, "80.00", None),
    (22, "bank_transfer", "P-1004", "I-BANK-1004", DAY, 20, 15, "250.00", None),
]

# The day's bets (R15): n, player, product line, cash stake, placed at (h, m, s), outcome as (status, settled at,
# cash winnings) or None while the bet is still open at the cut-off, and the other fields of the bet. A slot
# round settles within seconds and is emitted once, settled; a sports bet is emitted open and updated when it
# settles, is voided or is cashed out.
BETS = [
    (1, "P-1001", "SPORTS-PREMATCH-LIVE", "20.00", (9, 30, 12), ("settled", (15, 45, 8), "36.00"),
     {"game_ref": "EVT-20261114-0007:match_winner", "odds": "1.80"}),
    (2, "P-1003", "CASINO-SLOTS", "5.00", (10, 2, 41), ("settled", (10, 2, 44), "0.00"),
     {"stake_bonus": "5.00", "winnings_bonus": "0.00", "game_ref": "GAME-SLOT-0113"}),
    (3, "P-1004", "SPORTS-PREMATCH-LIVE", "100.00", (11, 50, 3), ("void", (14, 0, 0), None),
     {"void_reason": "Event cancelled; stake returned", "game_ref": "EVT-20261114-0012:match_winner", "odds": "2.05"}),
    (4, "P-1005", "CASINO-SLOTS", "2.00", (13, 10, 0), ("settled", (13, 10, 3), "7.50"), {"game_ref": "GAME-SLOT-0088"}),
    (5, "P-1006", "CASINO-SLOTS", "10.00", (17, 22, 10), ("settled", (17, 22, 13), "4.00"), {"game_ref": "GAME-SLOT-0113"}),
    (6, "P-1007", "SPORTS-PREMATCH-LIVE", "30.00", (20, 30, 50), ("cashed_out", (22, 10, 15), "24.00"),
     {"game_ref": "EVT-20261114-0021:match_winner", "odds": "2.10"}),
    (7, "P-1003", "SPORTS-PREMATCH-LIVE", "15.00", (21, 0, 5), None,
     {"game_ref": "EVT-20261115-0003:match_winner", "odds": "3.25"}),
]


def day_time(hms):
    return datetime(2026, 11, DAY, *hms, tzinfo=CET)


def bet_record(n, player, line, stake, placed, outcome, extra, as_of=None):
    """The R15 record of a bet as of a moment (its final state where as_of is None), fields in the order of
    §4.15: the core first."""
    bet_id = f"B-2026-11-{DAY}-{n:04d}"
    settled = outcome is not None and (as_of is None or day_time(outcome[1]) <= as_of)
    rec = {"bet_id": bet_id, "player_ref": player, "player_ref_scope": SCOPE, "product_line": line, "channel": "online",
           "currency": "EUR", "stake": stake, "placed_at": ts(day_time(placed)),
           "status": outcome[0] if settled else "open"}
    ledger = [f"LE-{bet_id}-S"]                                               # the stake debit
    if "stake_bonus" in extra:
        rec["stake_bonus"] = extra["stake_bonus"]
    if settled:
        status, at, winnings = outcome
        if winnings is not None:
            rec["winnings"] = winnings
            if "winnings_bonus" in extra:
                rec["winnings_bonus"] = extra["winnings_bonus"]
        rec["settled_at"] = ts(day_time(at))
        if status == "void":
            rec["void_reason"] = extra["void_reason"]
            ledger.append(f"LE-{bet_id}-R")                                   # the stake returned
        elif D(winnings) > 0:
            ledger.append(f"LE-{bet_id}-W")                                   # the winnings credit
    rec["jurisdiction_category"] = "betting" if line.startswith("SPORTS") else "casino_games"
    rec["game_ref"] = extra["game_ref"]
    if "odds" in extra:
        rec["odds"] = extra["odds"]
    rec.update({"ledger_entry_refs": ledger, "evidence_ref": f"BET-LOG-2026-11-{DAY}"})
    return rec


def bets():
    """The final state of every bet of the day, in bet order (the package), and the bet events of the stream as
    (anchor time, op, record): one create per bet, at placement with the open state or, for a round settled
    within seconds, at settlement with the final state; one update per later settlement, void or cash-out."""
    final, events = [], []
    for n, player, line, stake, placed, outcome, extra in BETS:
        final.append(bet_record(n, player, line, stake, placed, outcome, extra))
        placed_at = day_time(placed)
        if outcome and day_time(outcome[1]) - placed_at <= timedelta(seconds=10):
            events.append((day_time(outcome[1]), "create", final[-1]))
            continue
        events.append((placed_at, "create", bet_record(n, player, line, stake, placed, outcome, extra, as_of=placed_at)))
        if outcome:
            events.append((day_time(outcome[1]), "update", final[-1]))
    return final, events


def day_line(statement_id, kind, line, basis, formula, cut, evidence, levy):
    """An R13 line of the day for a product line, aggregated from the bets as of the cut-off under the profile's
    recognition (stakes when placed, winnings when settled): the core fields of §4.13 first."""
    as_of = day_time(cut)
    rows = [bet_record(*b, as_of=as_of) for b in BETS if b[2] == line and day_time(b[4]) <= as_of]
    total = lambda key, rows=rows: sum((D(r.get(key, "0")) for r in rows), D(0))      # noqa: E731
    stakes, bonus = total("stake"), total("stake_bonus")
    refunded = sum((D(r["stake"]) for r in rows if r["status"] == "void"), D(0))
    winnings, winnings_bonus = total("winnings"), total("winnings_bonus")
    ggr = (stakes + bonus - refunded) - (winnings + winnings_bonus) if formula == "all_in" else stakes - refunded - winnings
    rec = {"statement_id": statement_id, "statement_kind": kind, "licence_ref": LICENCE, "product_line": line,
           "channel": "online", "period_start": DAY_START, "period_end": ts(as_of - timedelta(seconds=1)) if kind == "interim" else DAY_END,
           "currency": "EUR", "stakes_basis": "placed", "winnings_basis": basis, "stakes_cash": q(stakes),
           "stakes_refunded": q(refunded), "winnings_cash": q(winnings), "ggr_declared": q(ggr), "ggr_formula": formula,
           "prepared_by": "finance_ops" if kind == "period" else "platform_interim_job",
           "reviewed_by": "compliance_officer" if kind == "period" else "not_recorded",
           "evidence_ref": evidence, "jurisdiction_category": "betting" if line.startswith("SPORTS") else "casino_games"}
    if any("stake_bonus" in r for r in rows):
        rec.update({"stakes_bonus": q(bonus), "winnings_bonus": q(winnings_bonus), "bonus_granted": q(bonus),
                    "bonus_expired": "0.00", "bonus_measurement": "per_round"})
    if line.startswith("SPORTS"):
        rec.update({"open_liability_start": "0.00",
                    "open_liability_end": q(sum((D(r["stake"]) for r in rows if r["status"] == "open"), D(0))),
                    "bets_count": len(rows)})
    else:
        rec["rounds_count"] = len(rows)
    rec["active_players"] = len({r["player_ref"] for r in rows})
    if levy:
        rec.update({"levy_base_declared": q(ggr), "levy_rate": "0.20", "levy_amount_declared": q(ggr * D("0.20"))})
    return rec


def day_statements():
    """The interim statement at noon (the sports line so far, superseded at the cut-off) and the two period
    statements of the day, which the package carries."""
    interim = day_line(f"{SPORTS_DAY}-INTERIM-1200", "interim", "SPORTS-PREMATCH-LIVE", "paid", "cash_only", INTERIM_CUT,
                       f"RPT-PLATFORM-GGR-2026-11-{DAY}-SPORTS-1200", levy=False)
    period = [day_line(SPORTS_DAY, "period", "SPORTS-PREMATCH-LIVE", "paid", "cash_only", (23, 59, 59),
                       f"RPT-PLATFORM-GGR-2026-11-{DAY}-SPORTS", levy=True),
              day_line(CASINO_DAY, "period", "CASINO-SLOTS", "credited", "all_in", (23, 59, 59),
                       f"RPT-PLATFORM-GGR-2026-11-{DAY}-CASINO", levy=True)]
    return interim, period


def day_coverage(final):
    """The day's coverage statement (R7), the open bets at the cut-off among the liabilities."""
    open_bets = sum((D(r["stake"]) for r in final if r["status"] == "open"), D(0))
    balances = D("61480.90")
    return {"statement_id": f"COV-2026-11-{DAY}-XJ-DEMO-0001", "kind": "coverage", "period_start": DAY_START,
            "period_end": DAY_END, "currency_or_asset": "EUR", "player_balances_total": q(balances),
            "pending_withdrawals_total": "0.00", "open_bets_total": q(open_bets),
            "player_liability_total": q(balances + open_bets), "funds_held": {"segregated_account": "64980.00"},
            "in_transit_total": "92.00", "shortfall": "0.00", "prepared_by": "finance_ops", "reviewed_by": "compliance_officer"}


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stream_events(deps, wds, checks, bet_events, interim, period):
    """The events of the day in emission order, one line each, and the checkpoint that seals them. An event is
    emitted shortly after its anchor: a check one second after performed_at, a payment two seconds after
    credited_at or paid_at, a bet two seconds after placed_at or settled_at, the interim statement 31 seconds
    after its cut-off, the period statements 20 seconds after the day's, all within a latency of PT60S."""
    items = []
    for c in checks:
        items.append((parse_ts(c["performed_at"]) + timedelta(seconds=1), 0, "R5", "create", c))
    for d in deps:
        items.append((parse_ts(d["credited_at"]) + timedelta(seconds=2), 1, "R3", "create", d))
    for w in wds:
        items.append((parse_ts(w["paid_at"]) + timedelta(seconds=2), 1, "R4", "create", w))
    for anchor, op, rec in bet_events:
        items.append((anchor + timedelta(seconds=2), 2, "R15", op, rec))
    items.append((parse_ts(interim["period_end"]) + timedelta(seconds=31), 3, "R13", "create", interim))
    for line in period:
        items.append((parse_ts(line["period_end"]) + timedelta(seconds=20), 3, "R13", "create", line))
    items.sort(key=lambda i: (i[0], i[1], json.dumps(i[4], sort_keys=True)))
    lines = []
    for n, (emitted, _, rtype, op, rec) in enumerate(items, 1):
        event = {"stream_id": STREAM_ID, "sequence": n, "emitted_at": ts(emitted), "licence_number": LICENCE,
                 "standard_version": "1.1", "profile_id": PROFILE, "record_type": rtype, "op": op, "record": rec}
        lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    checkpoint = {"stream_id": STREAM_ID, "licence_number": LICENCE, "period_start": DAY_START, "period_end": DAY_END,
                  "first_sequence": 1, "last_sequence": len(lines), "event_count": len(lines),
                  "chain_hash": sha("".join(line + "\n" for line in lines)),
                  "generated_at": ts(parse_ts(DAY_END) + timedelta(seconds=31))}
    event = {"stream_id": STREAM_ID, "sequence": len(lines) + 1, "emitted_at": checkpoint["generated_at"],
             "licence_number": LICENCE, "standard_version": "1.1", "profile_id": PROFILE, "record_type": "checkpoint",
             "op": "create", "record": checkpoint}
    lines.append(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return lines, checkpoint


def write_stream(out):
    """demo/stream: events.ndjson, the stream of the day, and package/, the level_2 package of the same day."""
    deps, wds, checks = payments(STREAM_DEPOSITS, STREAM_WITHDRAWALS, check_start=1000)
    final, bet_events = bets()
    interim, period = day_statements()
    lines, checkpoint = stream_events(deps, wds, checks, bet_events, interim, period)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "events.ndjson").write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    write(out / "package", {"R3": deps, "R4": wds, "R7": [day_coverage(final)], "R13": period, "R15": final},
          f"PKG-XJ-DEMO-0001-2026-11-{DAY}-STREAM", "level_2", period=(DAY_START, DAY_END), stream_checkpoints=[checkpoint])


def build(out_dir):
    out_dir = Path(out_dir)
    recs = records()
    write(out_dir / "clean", recs, "PKG-XJ-DEMO-0001-2026-11", "level_4")
    for name, (level, types) in LEVEL_PACKAGES.items():
        write(out_dir / name, {t: recs[t] for t in types}, f"PKG-XJ-DEMO-0001-2026-11-{name.upper()}", level)
    defective = records()
    apply_defects(defective)
    write(out_dir / "defects", defective, "PKG-XJ-DEMO-0001-2026-11-DEFECTS", "level_4",
          tamper=("R6_internal_movements.jsonl", '"amount":"350.00"', '"amount":"3500.00"'))
    write_stream(out_dir / "stream")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo"
    build(target)
    print(f"wrote {target / 'clean'}, {target / 'level1'}, {target / 'level2'}, {target / 'defects'} and {target / 'stream'}")
