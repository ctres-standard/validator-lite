"""Tests for validator-lite (standard library unittest; no other test dependency).

Run:  python -m unittest discover -s tests -v

The demonstration packages under demo/ are the fixtures. Each check test copies demo/clean into a
temporary directory, makes one change, reseals the manifest unless the change is to the seal
itself, and asserts that exactly the expected check reports it.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ctres_validator_lite import RULES, SCHEMA_VERSION, validate  # noqa: E402
from ctres_validator_lite.cli import main  # noqa: E402

CLEAN, DEFECTS = ROOT / "demo" / "clean", ROOT / "demo" / "defects"
RULE_IDS = [r[0] for r in RULES]


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def failed(result):
    """{check id: findings} for every check that reported something."""
    return {c["id"]: c["findings"] for c in result["checks"] if c["findings"]}


def check(result, rule_id):
    return next(c for c in result["checks"] if c["id"] == rule_id)


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


def load_make_demo():
    spec = importlib.util.spec_from_file_location("make_demo", ROOT / "scripts" / "make_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageCase(unittest.TestCase):
    """A fresh copy of demo/clean in self.pkg, with helpers to change it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pkg = self.tmp / "pkg"
        shutil.copytree(CLEAN, self.pkg)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def manifest(self):
        return json.loads((self.pkg / "manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, manifest):
        (self.pkg / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def write_raw(self, name, text, reseal=True):
        (self.pkg / name).write_text(text, encoding="utf-8")
        if reseal:
            m = self.manifest()
            for f in m["files"]:
                if f["file"] == name:
                    f["sha256"], f["record_count"] = sha256(text), sum(1 for x in text.split("\n") if x.strip())
            self.write_manifest(m)

    def edit(self, name, change, reseal=True):
        """Apply change(records) to a JSON Lines file, then reseal the manifest."""
        path = self.pkg / name
        records = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        change(records)
        self.write_raw(name, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records), reseal)

    def record(self, records, key, value):
        return next(r for r in records if r.get(key) == value)

    def assertOnly(self, result, expected):
        """Exactly the checks in `expected` ({id: number of findings}) report findings."""
        self.assertEqual({k: len(v) for k, v in failed(result).items()}, expected,
                         json.dumps(failed(result), indent=1))

    def validate(self):
        return validate(self.pkg)


# ------------------------------------------------------------------ demonstration packages

class DemoPackages(unittest.TestCase):

    def test_clean_package_passes_with_no_findings(self):
        res = validate(CLEAN)
        self.assertEqual(res["result"], "pass")
        self.assertEqual(failed(res), {})
        self.assertTrue(all(c["status"] == "pass" and not c["notes"] for c in res["checks"]))
        self.assertEqual(res["summary"]["blocking_findings"] + res["summary"]["advisory_findings"], 0)
        self.assertIs(res["manifest"]["synthetic"], True)

    def test_clean_package_covers_every_record_type_and_four_rails(self):
        m = json.loads((CLEAN / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([f["record_type"] for f in m["files"]], [f"R{i}" for i in range(1, 13)])
        self.assertTrue(all(f["record_count"] >= 1 for f in m["files"]))
        self.assertTrue(40 <= sum(f["record_count"] for f in m["files"]) <= 80)
        rails = {json.loads(x)["rail"] for x in (CLEAN / "R3_deposits.jsonl").read_text().splitlines()}
        self.assertEqual(rails, {"card", "bank_transfer", "mobile_money", "virtual_asset"})
        kinds = [json.loads(x)["kind"] for x in (CLEAN / "R7_reconciliation_statements.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(kinds), ["coverage", "location"])

    def test_each_defect_is_detected_by_its_check(self):
        res = validate(DEFECTS)
        expected = {   # check id -> (field, text the finding must contain)
            "STR-02": (None, "R6_internal_movements.jsonl"),
            "STR-04": ("fx_source", "D-2026-11-0002"),
            "STR-05": ("payout_status", "I-MM-1006"),
            "REF-02": ("check_ids/0", "C-2026-11-9999"),
            "REF-03": ("instrument_id", "I-BANK-9999"),
            "REF-04": ("rail_reference", "D-2026-11-0013"),
        }
        found = failed(res)
        self.assertEqual(set(found), set(expected))
        for rule_id, (field, text) in expected.items():
            self.assertEqual(len(found[rule_id]), 1, rule_id)
            self.assertEqual(found[rule_id][0]["field"], field, rule_id)
            self.assertIn(text, found[rule_id][0]["detail"], rule_id)
        self.assertEqual(res["result"], "fail")
        self.assertEqual(res["summary"]["blocking_findings"], 6)

    def test_defects_documented_in_make_demo_match_the_findings(self):
        documented = {rule_id for rule_id, _ in load_make_demo().DEFECTS}
        self.assertEqual(documented, set(failed(validate(DEFECTS))))

    def test_demo_packages_are_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            load_make_demo().build(tmp)
            for package in ("clean", "defects"):
                ours = sorted(p.name for p in (ROOT / "demo" / package).iterdir())
                theirs = sorted(p.name for p in (Path(tmp) / package).iterdir())
                self.assertEqual(ours, theirs)
                for name in ours:
                    self.assertEqual((ROOT / "demo" / package / name).read_bytes(),
                                     (Path(tmp) / package / name).read_bytes(), f"{package}/{name}")


# ------------------------------------------------------------------ command line and output

class CommandLine(unittest.TestCase):

    def test_exit_codes(self):
        self.assertEqual(run_cli(str(CLEAN))[0], 0)
        self.assertEqual(run_cli(str(DEFECTS))[0], 1)
        self.assertEqual(run_cli(str(ROOT / "no-such-package"))[0], 2)
        self.assertEqual(run_cli()[0], 2)
        self.assertEqual(run_cli(str(CLEAN), "--no-such-option")[0], 2)
        with tempfile.TemporaryDirectory() as empty:
            code, _, err = run_cli(str(CLEAN), "--schema-dir", empty)
            self.assertEqual(code, 2)
            self.assertIn("does not hold the CTRES schema files", err)

    def test_text_report_is_grouped_by_class_and_prints_the_fingerprint(self):
        code, out, _ = run_cli(str(DEFECTS))
        fingerprint = sha256((DEFECTS / "manifest.json").read_bytes())
        self.assertIn(f"fingerprint  SHA-256 {fingerprint}", out)
        self.assertLess(out.index("\nStructural:"), out.index("\nReferential:"))
        self.assertIn("REF-04  FAIL  blocking", out)
        self.assertIn("Result: FAIL: 6 blocking findings, 0 advisory.", out)
        self.assertIn("https://ctres.org/validator", out)

    def test_json_output_schema_is_stable(self):
        code, out, _ = run_cli(str(DEFECTS), "--json")
        self.assertEqual(code, 1)
        res = json.loads(out)
        self.assertEqual(list(res), ["validator", "validator_version", "standard_version", "schema_version",
                                     "schema_dir", "package", "fingerprint", "manifest", "result", "summary",
                                     "checks", "not_checked"])
        self.assertEqual(res["validator"], "ctres-validator-lite")
        self.assertEqual(res["schema_version"], SCHEMA_VERSION)
        self.assertEqual(res["fingerprint"], sha256((DEFECTS / "manifest.json").read_bytes()))
        self.assertEqual(list(res["manifest"]), ["package_id", "licence_number", "licensee", "profile_id",
                                                 "profile_version", "period_start", "period_end",
                                                 "standard_version", "synthetic"])
        self.assertEqual(list(res["summary"]), ["checks", "passed", "failed", "not_run",
                                                "blocking_findings", "advisory_findings"])
        self.assertEqual([c["id"] for c in res["checks"]], RULE_IDS)
        for c in res["checks"]:
            self.assertEqual(list(c), ["id", "class", "severity", "basis", "requirement", "failure",
                                       "status", "findings", "notes"])
            self.assertIn(c["class"], ("structural", "referential"))
            self.assertIn(c["severity"], ("blocking", "advisory"))
            self.assertIn(c["status"], ("pass", "fail", "not_run"))
            for f in c["findings"]:
                self.assertEqual(list(f), ["file", "line", "record", "field", "detail"])

    def test_json_output_is_deterministic(self):
        self.assertEqual(run_cli(str(DEFECTS), "--json")[1], run_cli(str(DEFECTS), "--json")[1])

    def test_output_is_utf8_whatever_the_console_encoding(self):
        # A record value outside the console code page must not stop the report part-way.
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "pkg"
            shutil.copytree(CLEAN, pkg)
            name = "R9_incidents.jsonl"
            record = json.loads((pkg / name).read_text(encoding="utf-8"))
            record["status"] = "中"
            text = json.dumps(record, ensure_ascii=False) + "\n"
            (pkg / name).write_text(text, encoding="utf-8")
            m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
            next(f for f in m["files"] if f["file"] == name)["sha256"] = sha256(text)
            (pkg / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="cp1252")
            done = subprocess.run([sys.executable, "-m", "ctres_validator_lite", str(pkg)], capture_output=True, env=env)
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertNotIn(b"Traceback", done.stderr)
            self.assertIn("'中' is not one of".encode("utf-8"), done.stdout)
            self.assertIn(b"Result: FAIL: 1 blocking findings", done.stdout)

    def test_validation_that_cannot_complete_exits_2_not_1(self):
        with mock.patch("ctres_validator_lite.cli.validate", side_effect=RuntimeError("disk vanished")):
            code, out, err = run_cli(str(CLEAN))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("validation could not be completed", err)

    def test_module_entry_point(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        done = subprocess.run([sys.executable, "-m", "ctres_validator_lite", str(CLEAN)],
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Result: PASS", done.stdout)


# ------------------------------------------------------------------ structural checks

class StructuralChecks(PackageCase):

    def test_str01_missing_file(self):
        (self.pkg / "R9_incidents.jsonl").unlink()
        self.assertOnly(self.validate(), {"STR-01": 1})

    def test_str02_file_altered_after_sealing(self):
        name = "R6_internal_movements.jsonl"
        text = (self.pkg / name).read_text(encoding="utf-8").replace('"amount":"90.00"', '"amount":"90.01"')
        self.write_raw(name, text, reseal=False)
        self.assertOnly(self.validate(), {"STR-02": 1})

    def test_str03_record_count_differs(self):
        m = self.manifest()
        m["files"][0]["record_count"] += 1
        self.write_manifest(m)
        self.assertOnly(self.validate(), {"STR-03": 1})

    def test_str04_undefined_field(self):
        self.edit("R10_provider_register.jsonl", lambda rs: rs[0].update(nickname="x"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["detail"], "PSP-01: not defined for this record: nickname")

    def test_str04_rail_module_field_on_another_rail(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(tx_hash="0xabc"))   # a card deposit
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["field"], "tx_hash")

    def test_str04_field_excluded_by_condition(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(paid_at="2026-11-03T19:02:09+01:00"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["field"], "paid_at")

    def test_str04_conditional_field_missing(self):
        def change(rs):   # an on-chain virtual-asset deposit must carry tx_hash
            del self.record(rs, "tx_id", "D-2026-11-0010")["tx_hash"]
        self.edit("R3_deposits.jsonl", change)
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["field"], "tx_hash")

    def test_str04_line_that_is_not_json(self):
        name = "R9_incidents.jsonl"
        self.write_raw(name, (self.pkg / name).read_text(encoding="utf-8") + "{not json\n")
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["line"], 2)

    def test_str04_repeated_field_name(self):
        name = "R9_incidents.jsonl"
        text = (self.pkg / name).read_text(encoding="utf-8")
        self.write_raw(name, text.replace('{"incident_id":', '{"status":"closed","incident_id":', 1))
        self.assertOnly(self.validate(), {"STR-04": 1})

    def test_str05_value_outside_enumeration_in_a_map_key(self):
        def change(rs):
            self.record(rs, "kind", "coverage")["funds_held"] = {"insurance": "1.00"}
        self.edit("R7_reconciliation_statements.jsonl", change)
        self.assertOnly(self.validate(), {"STR-05": 1})

    def test_str06_amount_as_json_number(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(amount=120.0))
        res = self.validate()
        self.assertOnly(res, {"STR-06": 1})
        self.assertEqual(failed(res)["STR-06"][0]["field"], "amount")

    def test_str06_timestamp_without_offset(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(credited_at="2026-11-03T19:02:04"))
        self.assertOnly(self.validate(), {"STR-06": 1})

    def test_str06_day_that_does_not_exist(self):
        self.edit("R9_incidents.jsonl", lambda rs: rs[0].update(detected_at="2026-11-31T08:30:00+01:00"))
        self.assertOnly(self.validate(), {"STR-06": 1})

    def test_str07_repeated_identifier(self):
        self.edit("R10_provider_register.jsonl", lambda rs: rs.append(dict(rs[0])))
        res = self.validate()
        self.assertOnly(res, {"STR-07": 1})
        self.assertEqual(failed(res)["STR-07"][0]["record"], "PSP-01")

    def test_str08_manifest_field_missing(self):
        m = self.manifest()
        del m["licensee"]
        self.write_manifest(m)
        self.assertOnly(self.validate(), {"STR-08": 1})

    def test_str08_manifest_period_on_a_day_that_does_not_exist(self):
        m = self.manifest()
        m["period_end"] = "2026-11-31T23:59:59+01:00"
        self.write_manifest(m)
        res = self.validate()
        self.assertOnly(res, {"STR-08": 1})
        self.assertEqual(check(res, "REF-07")["status"], "not_run")

    def test_str08_no_manifest_stops_every_other_check(self):
        (self.pkg / "manifest.json").unlink()
        res = self.validate()
        self.assertOnly(res, {"STR-08": 1})
        self.assertIsNone(res["fingerprint"])
        self.assertEqual({c["status"] for c in res["checks"] if c["id"] != "STR-08"}, {"not_run"})
        self.assertEqual(run_cli(str(self.pkg))[0], 1)

    def test_str08_file_listed_twice(self):
        m = self.manifest()
        m["files"].append(dict(m["files"][0]))
        self.write_manifest(m)
        self.assertOnly(self.validate(), {"STR-08": 1})

    def test_str01_file_that_cannot_be_read(self):
        path = self.pkg / "R9_incidents.jsonl"
        path.chmod(0)
        try:
            if os.access(path, os.R_OK):
                self.skipTest("file permissions are not enforced for this user or platform")
            res = self.validate()
            self.assertOnly(res, {"STR-01": 1})
            self.assertIn("cannot be read", failed(res)["STR-01"][0]["detail"])
        finally:
            path.chmod(0o644)

    def test_str01_link_to_a_file_outside_the_package_is_never_read(self):
        outside = self.tmp / "outside.jsonl"
        shutil.copyfile(self.pkg / "R9_incidents.jsonl", outside)
        (self.pkg / "R9_incidents.jsonl").unlink()
        try:
            os.symlink(outside, self.pkg / "R9_incidents.jsonl")
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        res = self.validate()
        self.assertOnly(res, {"STR-01": 1})
        self.assertIn("outside the package", failed(res)["STR-01"][0]["detail"])

    def test_str01_data_file_not_listed_in_the_manifest_is_noted(self):
        (self.pkg / "R5_late_additions.jsonl").write_text('{"check_id":"C-LATE"}\n', encoding="utf-8")
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("R5_late_additions.jsonl is in the package but not listed", " ".join(check(res, "STR-01")["notes"]))

    def test_str02_str03_not_reported_for_a_manifest_entry_without_hash_or_count(self):
        m = self.manifest()
        del m["files"][0]["record_count"]
        del m["files"][1]["sha256"]
        self.write_manifest(m)
        self.assertOnly(self.validate(), {"STR-08": 2})

    def test_str03_csv_records_are_counted_as_csv_rows(self):
        m = self.manifest()
        text = 'incident_id,description\r\nINC-1,"a description\r\non two lines"\r\n'
        (self.pkg / "R9_incidents.jsonl").unlink()
        (self.pkg / "R9_incidents.csv").write_text(text, encoding="utf-8", newline="")
        entry = next(f for f in m["files"] if f["record_type"] == "R9")
        entry.update(file="R9_incidents.csv", format="csv", record_count=1, sha256=sha256(text))
        self.write_manifest(m)
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("CSV file", " ".join(check(res, "STR-04")["notes"]))
        (self.pkg / "R9_incidents.csv").write_text("", encoding="utf-8")       # empty: no header, no record
        entry.update(record_count=0, sha256=sha256(""))
        self.write_manifest(m)
        self.assertOnly(self.validate(), {})

    def test_crlf_line_endings_are_accepted(self):
        for f in self.manifest()["files"]:
            text = (self.pkg / f["file"]).read_text(encoding="utf-8")
            self.write_raw(f["file"], text.replace("\n", "\r\n"))
        manifest = (self.pkg / "manifest.json").read_text(encoding="utf-8")
        (self.pkg / "manifest.json").write_bytes(manifest.replace("\n", "\r\n").encode("utf-8"))
        self.assertOnly(self.validate(), {})

    def test_str04_byte_order_mark_is_reported_once_and_the_records_are_still_read(self):
        name = "R10_provider_register.jsonl"
        self.write_raw(name, "\ufeff" + (self.pkg / name).read_text(encoding="utf-8"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["line"], 1)
        self.assertIn("byte order mark", failed(res)["STR-04"][0]["detail"])

    def test_str04_white_space_that_json_does_not_permit(self):
        name = "R9_incidents.jsonl"
        self.write_raw(name, (self.pkg / name).read_text(encoding="utf-8").replace("}\n", "}\u00a0\n"))
        self.assertOnly(self.validate(), {"STR-04": 1})

    def test_str04_deeply_nested_value_does_not_stop_validation(self):
        name = "R9_incidents.jsonl"
        line = (self.pkg / name).read_text(encoding="utf-8").rstrip("\n")
        depth = 20000
        self.write_raw(name, line[:-1] + ',"extra":' + '{"a":' * depth + "1" + "}" * depth + "}\n")
        res = self.validate()
        self.assertEqual(set(failed(res)), {"STR-04"})

    def test_str06_day_that_does_not_exist_where_not_recorded_is_also_permitted(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(credited_at="2026-11-31T19:02:04+01:00"))
        res = self.validate()
        self.assertOnly(res, {"STR-06": 1})
        self.assertIn("is not a calendar date", failed(res)["STR-06"][0]["detail"])

    def test_str06_leap_day_is_a_calendar_date(self):
        self.edit("R10_provider_register.jsonl", lambda rs: rs[0].update(next_review_at="2028-02-29"))
        self.assertOnly(self.validate(), {})

    def test_str06_free_text_that_resembles_a_date_is_not_a_date_field(self):
        self.edit("R9_incidents.jsonl", lambda rs: rs[0].update(description="2026-11-31"))
        self.assertOnly(self.validate(), {})

    def test_str07_identifier_repeated_in_two_files_of_one_record_type(self):
        name = "R9_incidents.jsonl"
        text = (self.pkg / name).read_text(encoding="utf-8")
        (self.pkg / "R9_incidents_2.jsonl").write_text(text, encoding="utf-8")
        m = self.manifest()
        m["files"].append({"file": "R9_incidents_2.jsonl", "record_type": "R9", "record_count": 1, "sha256": sha256(text)})
        self.write_manifest(m)
        res = self.validate()
        self.assertOnly(res, {"STR-07": 1})
        self.assertIn(f"first on {name} line 1", failed(res)["STR-07"][0]["detail"])

    def test_str08_byte_order_mark_in_the_manifest_does_not_stop_the_other_checks(self):
        (self.pkg / "manifest.json").write_bytes(b"\xef\xbb\xbf" + (self.pkg / "manifest.json").read_bytes())
        res = self.validate()
        self.assertOnly(res, {"STR-08": 1})
        self.assertEqual(res["summary"]["not_run"], 0)
        self.assertEqual(res["fingerprint"], sha256((self.pkg / "manifest.json").read_bytes()))

    def test_str08_file_name_outside_the_package_is_never_opened(self):
        (self.tmp / "outside.jsonl").write_text("{}\n", encoding="utf-8")
        m = self.manifest()
        m["files"].append({"file": "../outside.jsonl", "record_type": "R9", "record_count": 1,
                           "sha256": sha256("{}\n")})
        self.write_manifest(m)
        self.assertOnly(self.validate(), {"STR-08": 1})


# ------------------------------------------------------------------ referential checks

class ReferentialChecks(PackageCase):

    def test_ref01_location_not_in_r1(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(location_id="L-NOWHERE"))
        self.assertOnly(self.validate(), {"REF-01": 1})

    def test_ref01_movement_side_not_in_r10(self):
        def change(rs):
            self.record(rs, "movement_id", "M-2026-11-0004")["source_provider_id"] = "VASP-99"
        self.edit("R6_internal_movements.jsonl", change)
        self.assertOnly(self.validate(), {"REF-01": 1})

    def test_ref02_supersedes_chain_that_loops(self):
        def change(rs):
            later = next(r for r in rs if "supersedes" in r)
            self.record(rs, "check_id", later["supersedes"])["supersedes"] = later["check_id"]
        self.edit("R5_check_decisions.jsonl", change)
        res = self.validate()
        self.assertOnly(res, {"REF-02": 2})
        self.assertIn("supersedes chain returns", failed(res)["REF-02"][0]["detail"])

    def test_ref02_supersedes_unknown_decision(self):
        def change(rs):
            next(r for r in rs if "supersedes" in r)["supersedes"] = "C-NOWHERE"
        self.edit("R5_check_decisions.jsonl", change)
        self.assertOnly(self.validate(), {"REF-02": 1})

    def test_ref03_source_instrument_not_in_r2(self):
        self.edit("R4_withdrawals.jsonl", lambda rs: rs[0].update(source_instrument_ids=["I-NOWHERE"]))
        self.assertOnly(self.validate(), {"REF-03": 1})

    def test_ref04_reference_booked_by_a_deposit_and_a_withdrawal(self):
        deposit = json.loads((self.pkg / "R3_deposits.jsonl").read_text().splitlines()[0])
        self.edit("R4_withdrawals.jsonl", lambda rs: rs[0].update(rail_reference=deposit["rail_reference"]))
        self.assertOnly(self.validate(), {"REF-04": 1})

    def test_ref04_same_reference_from_another_provider_is_not_a_duplicate(self):
        deposit = json.loads((self.pkg / "R3_deposits.jsonl").read_text().splitlines()[0])
        self.edit("R4_withdrawals.jsonl", lambda rs: rs[1].update(rail_reference=deposit["rail_reference"],
                                                                rail_reference_type=deposit["rail_reference_type"]))
        self.assertOnly(self.validate(), {})

    def test_ref05_provider_not_in_r10(self):
        self.edit("R1_funds_locations.jsonl", lambda rs: rs[1].update(provider_id="BANK-99"))
        self.assertOnly(self.validate(), {"REF-05": 1})

    def test_ref05_mobile_operator_in_instrument_detail_not_in_r10(self):
        def change(rs):
            self.record(rs, "instrument_id", "I-MM-1005")["instrument_detail"]["mobile_operator_id"] = "MMO-99"
        self.edit("R2_payment_instrument_links.jsonl", change)
        self.assertOnly(self.validate(), {"REF-05": 1})

    def test_ref06_incident_points_at_a_record_that_does_not_exist(self):
        self.edit("R9_incidents.jsonl", lambda rs: rs[0].update(related_record_ids=["MMO-01", "L-NOWHERE"]))
        res = self.validate()
        self.assertOnly(res, {"REF-06": 1})
        self.assertEqual(failed(res)["REF-06"][0]["field"], "related_record_ids/1")

    def test_ref06_statement_points_at_an_exception_that_does_not_exist(self):
        def change(rs):
            self.record(rs, "kind", "location")["exception_ids"] = ["E-NOWHERE"]
        self.edit("R7_reconciliation_statements.jsonl", change)
        self.assertOnly(self.validate(), {"REF-06": 1})

    def test_ref06_external_reference_accepted_only_for_external_categories(self):
        # The demo exception names a bank statement line that by definition has no record.
        self.edit("R8_exceptions.jsonl", lambda rs: rs[0].update(category="amount_mismatch"))
        res = self.validate()
        self.assertOnly(res, {"REF-06": 1})
        self.assertIn("BANK-01-STMT-20261123-0187", failed(res)["REF-06"][0]["detail"])

    def test_ref06_not_resolved_in_a_partial_package(self):
        (self.pkg / "R4_withdrawals.jsonl").unlink()
        m = self.manifest()
        m["files"] = [f for f in m["files"] if f["record_type"] != "R4"]
        self.write_manifest(m)
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("carries no R4 file", " ".join(check(res, "REF-06")["notes"]))

    def test_ref07_transaction_outside_the_period_is_advisory(self):
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(credited_at="2026-12-01T00:00:04+01:00"))
        res = self.validate()
        self.assertOnly(res, {"REF-07": 1})
        self.assertEqual(res["result"], "pass")
        self.assertEqual(res["summary"]["advisory_findings"], 1)
        self.assertEqual(run_cli(str(self.pkg))[0], 0)

    def test_ref06_external_category_needs_one_reference_that_resolves(self):
        def change(rs):
            rs[0]["related_record_ids"] = [5, "BANK-01-STMT-20261123-0187"]   # 5 is STR-04, and anchors nothing
            del rs[0]["source_statement_id"]
        self.edit("R8_exceptions.jsonl", change)
        self.assertOnly(self.validate(), {"STR-04": 1, "REF-06": 1})

    def test_ref07_not_run_when_the_period_ends_before_it_starts(self):
        m = self.manifest()
        m["period_start"], m["period_end"] = m["period_end"], m["period_start"]
        self.write_manifest(m)
        res = self.validate()
        self.assertOnly(res, {})
        self.assertEqual(check(res, "REF-07")["status"], "not_run")
        self.assertIn("ends before it starts", " ".join(check(res, "REF-07")["notes"]))

    def test_ref08_attestation_does_not_exist(self):
        def change(rs):
            self.record(rs, "tx_id", "D-2026-11-0011")["attestation_ref"] = "ATT-NOWHERE"
        self.edit("R3_deposits.jsonl", change)
        self.assertOnly(self.validate(), {"REF-08": 1})

    def test_ref08_attestation_does_not_cover_the_location(self):
        self.edit("R11_provider_attestations.jsonl", lambda rs: rs[0].update(covers_location_ids=["L-PSP-01-BAL"]))
        self.assertOnly(self.validate(), {"REF-08": 5})


# ------------------------------------------------------------------ valid variations (no false positives)

class ValidVariations(PackageCase):
    """Changes that remain valid under the universal edition and must not be reported."""

    def test_not_recorded_where_the_schema_permits_it(self):
        def payments(rs):
            for r in rs:
                r.update(check_ids="not_recorded", ledger_entry_ref="not_recorded",
                         initiated_at="not_recorded", settled_at="not_recorded", credited_at="not_recorded")
        def movements(rs):
            for r in rs:
                r.update(rail_reference="not_recorded", approved_by="not_recorded", approved_at="not_recorded")
        self.edit("R3_deposits.jsonl", payments)
        self.edit("R6_internal_movements.jsonl", movements)
        self.assertOnly(self.validate(), {})

    def test_optional_and_conditional_fields_omitted(self):
        def instruments(rs):
            for r in rs:
                r["holder_match"] = "not_checked"
                for k in ("holder_verification_method", "verified_at", "verified_by", "issuer_country"):
                    r.pop(k, None)
        def providers(rs):
            for r in rs:
                r.pop("authorisation_country")
                r.pop("regulator_notification_status")
                r["data_locations"] = "not_recorded"
        def deposits(rs):
            for r in rs:
                r.pop("location_id")
                r.pop("limit_check", None)
        self.edit("R2_payment_instrument_links.jsonl", instruments)
        self.edit("R10_provider_register.jsonl", providers)
        self.edit("R3_deposits.jsonl", deposits)
        self.assertOnly(self.validate(), {})

    def test_movement_with_a_provider_on_one_side(self):
        def change(rs):
            r = self.record(rs, "movement_id", "M-2026-11-0003")
            del r["destination_location_id"]
            r["destination_provider_id"] = "BANK-01"
        self.edit("R6_internal_movements.jsonl", change)
        self.assertOnly(self.validate(), {})

    def test_off_chain_payment_at_an_omnibus_provider_without_a_transaction_hash(self):
        def change(rs):
            r = self.record(rs, "tx_id", "W-2026-11-0006")
            self.assertIs(r["off_chain_movement"], True)
            self.assertNotIn("tx_hash", r)
            r.pop("attestation_ref")
            r.pop("location_id")
        self.edit("R4_withdrawals.jsonl", change)
        self.assertOnly(self.validate(), {})


# ------------------------------------------------------------------ schema

class Schema(unittest.TestCase):

    def test_bundled_schema_matches_the_schema_repository(self):
        source = ROOT.parent / "schema" / "schema"
        if not source.is_dir():
            self.skipTest("ctres-standard/schema is not checked out next to this repository")
        bundled = ROOT / "src" / "ctres_validator_lite" / "schema"
        names = sorted(p.relative_to(source).as_posix() for p in source.rglob("*.schema.json"))
        self.assertEqual(names, sorted(p.relative_to(bundled).as_posix() for p in bundled.rglob("*.schema.json")))
        for name in names:
            self.assertEqual((source / name).read_bytes(), (bundled / name).read_bytes(), name)

    def test_schema_dir_option(self):
        source = ROOT.parent / "schema"
        if not (source / "schema" / "manifest.schema.json").is_file():
            self.skipTest("ctres-standard/schema is not checked out next to this repository")
        res = validate(CLEAN, schema_dir=source)
        self.assertEqual(res["result"], "pass")
        self.assertIsNone(res["schema_version"])


if __name__ == "__main__":
    unittest.main()
