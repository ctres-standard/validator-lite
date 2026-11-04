"""Tests for validator-lite (standard library unittest; no other test dependency).

Run:  python -m unittest discover -s tests -v

The demonstration packages under demo/ are the fixtures. Each check test copies demo/clean into a
temporary directory, makes one change, reseals the manifest unless the change is to the seal
itself, and asserts that exactly the expected check reports it. demo/level1 and demo/level2 are the
same data cut down to the record types of their conformance level (§10). tests/fixtures/clean_1_0
is the clean package of release 1.0.1, unchanged, to show that a CTRES v1.0 package still passes.
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
LEVEL1, LEVEL2 = ROOT / "demo" / "level1", ROOT / "demo" / "level2"
CLEAN_1_0 = ROOT / "tests" / "fixtures" / "clean_1_0"
RULE_IDS = [r[0] for r in RULES]
R13, R14 = "R13_gaming_revenue_statements.jsonl", "R14_venue_counts.jsonl"
SPORTS, CASINO = "GRS-2026-11-XJ-DEMO-0001-SPORTS-ONLINE-EUR", "GRS-2026-11-XJ-DEMO-0001-CASINO-ONLINE-EUR"
FLOOR = "GRS-2026-11-XJ-DEMO-0001-CASINO-FLOOR-V-DEMO-01-EUR"
SLOT = "VC-2026-11-14-V-DEMO-01-SM-0001"
# The advisory findings a level_2 package made of the clean data carries: references to record types the
# level does not require, not resolved within the package (§10), one per field and check.
LEVEL2_ADVISORY = {"REF-01": 1, "REF-02": 1, "REF-03": 2, "REF-05": 1, "REF-06": 1, "REF-08": 1, "REF-11": 2, "REF-12": 1}


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

    def set_level(self, level):
        """Declare a conformance level in the manifest, or none."""
        m = self.manifest()
        if level is None:
            m.pop("conformance_level_declared", None)
        else:
            m["conformance_level_declared"] = level
        self.write_manifest(m)

    def remove(self, *rtypes):
        """Take record types out of the package: their files and their manifest entries."""
        m = self.manifest()
        for f in m["files"]:
            if f["record_type"] in rtypes:
                (self.pkg / f["file"]).unlink()
        m["files"] = [f for f in m["files"] if f["record_type"] not in rtypes]
        self.write_manifest(m)

    def assertOnly(self, result, expected):
        """Exactly the checks in `expected` ({id: number of findings}) report findings."""
        self.assertEqual({k: len(v) for k, v in failed(result).items()}, expected,
                         json.dumps(failed(result), indent=1))

    def assertAdvisory(self, result, expected):
        """Exactly the checks in `expected` report findings, all of them advisory, and the package passes."""
        self.assertOnly(result, expected)
        self.assertTrue(all(f["severity"] == "advisory" for fs in failed(result).values() for f in fs))
        self.assertEqual(result["result"], "pass")
        self.assertEqual(result["summary"]["blocking_findings"], 0)
        self.assertEqual(result["summary"]["advisory_findings"], sum(expected.values()))

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
        self.assertEqual([f["record_type"] for f in m["files"]], [f"R{i}" for i in range(1, 15)])
        self.assertEqual(m["standard_version"], "1.1")
        self.assertEqual(m["conformance_level_declared"], "level_4")
        self.assertTrue(all(f["record_count"] >= 1 for f in m["files"]))
        self.assertTrue(40 <= sum(f["record_count"] for f in m["files"]) <= 80)
        rails = {json.loads(x)["rail"] for x in (CLEAN / "R3_deposits.jsonl").read_text().splitlines()}
        self.assertEqual(rails, {"card", "bank_transfer", "mobile_money", "virtual_asset"})
        kinds = [json.loads(x)["kind"] for x in (CLEAN / "R7_reconciliation_statements.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(kinds), ["coverage", "location"])
        channels = [json.loads(x)["channel"] for x in (CLEAN / R13).read_text().splitlines()]
        self.assertEqual(channels, ["online", "online", "venue"])

    def test_level_packages_pass_with_only_references_not_resolved_by_level(self):
        # level_1: the manifest and R13 alone; the sports statement's authority figure points at R12, which the
        # level does not require: advisory, not blocking.
        res = validate(LEVEL1)
        m = json.loads((LEVEL1 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((m["conformance_level_declared"], [f["record_type"] for f in m["files"]]), ("level_1", ["R13"]))
        self.assertEqual(res["result"], "pass")
        self.assertEqual({k: len(v) for k, v in failed(res).items()}, {"REF-12": 1})
        self.assertEqual(failed(res)["REF-12"][0], {
            "file": None, "line": None, "record": None, "field": "authority_figure_ref/report_reference_id",
            "detail": "authority_figure_ref/report_reference_id — not resolved: R12 is not required at level_1 and "
                      "is not in the package", "severity": "advisory"})
        self.assertEqual(res["summary"], {"checks": 22, "passed": 21, "failed": 1, "not_run": 0,
                                          "blocking_findings": 0, "advisory_findings": 1})
        self.assertEqual(check(res, "STR-09")["status"], "pass")
        # level_2: the core, with R14 because the clean R13 has a venue line; every reference to the Custody and
        # Supervision modules is an advisory finding, one per field and check.
        res = validate(LEVEL2)
        m = json.loads((LEVEL2 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((m["conformance_level_declared"], [f["record_type"] for f in m["files"]]),
                         ("level_2", ["R3", "R4", "R7", "R13", "R14"]))
        self.assertEqual(res["result"], "pass")
        self.assertEqual({k: len(v) for k, v in failed(res).items()}, LEVEL2_ADVISORY)
        for f in (f for fs in failed(res).values() for f in fs):
            self.assertEqual((f["severity"], f["file"], f["line"], f["record"]), ("advisory", None, None, None))
            self.assertRegex(f["detail"], r"^[a-z_/]+ — not resolved: R\d+( and R\d+)? (is|are) not required at level_2 "
                                          r"and (is|are) not in the package$")
        self.assertEqual([f["detail"] for f in failed(res)["REF-11"]], [
            "venue_id — not resolved: R1 is not required at level_2 and is not in the package",
            "drop_deposit_ref — not resolved: R1 and R6 are not required at level_2 and are not in the package"])
        self.assertEqual(res["summary"]["blocking_findings"], 0)
        self.assertEqual(res["summary"]["advisory_findings"], 10)
        self.assertTrue(all(not c["notes"] for c in res["checks"]))
        for package in (LEVEL1, LEVEL2):
            code, out, _ = run_cli(str(package))
            self.assertEqual(code, 0)
            self.assertIn("Result: PASS: no blocking findings", out)
        self.assertIn("Result: PASS: no blocking findings, 10 advisory; declared level_2 (Evidence).", run_cli(str(LEVEL2))[1])
        self.assertIn("Result: PASS: no blocking findings, 1 advisory; declared level_1 (Return).", run_cli(str(LEVEL1))[1])

    def test_level_packages_are_cut_from_the_clean_data(self):
        for package in (LEVEL1, LEVEL2):
            for path in package.iterdir():
                if path.name != "manifest.json":
                    self.assertEqual(path.read_bytes(), (CLEAN / path.name).read_bytes(), path.name)

    def test_each_defect_is_detected_by_its_check(self):
        res = validate(DEFECTS)
        expected = {   # check id -> (field, text the finding must contain)
            "STR-02": (None, "R6_internal_movements.jsonl"),
            "STR-04": ("fx_source", "D-2026-11-0002"),
            "STR-05": ("payout_status", "I-MM-1006"),
            "REF-02": ("check_ids/0", "C-2026-11-9999"),
            "REF-03": ("instrument_id", "I-BANK-9999"),
            "REF-04": ("rail_reference", "D-2026-11-0013"),
            "REF-09": ("period_end", SPORTS),
            "REF-10": ("corrects_statement_id", "a statement of another line"),
            "REF-12": ("authority_figure_ref/report_reference_id", "RR-2026-11-9999"),
            "REF-13": ("ggr_declared", "stakes_cash - stakes_refunded - winnings_cash = 140.00"),
        }
        found = failed(res)
        self.assertEqual(set(found), set(expected))
        for rule_id, (field, text) in expected.items():
            self.assertEqual(len(found[rule_id]), 1, rule_id)
            self.assertEqual(found[rule_id][0]["field"], field, rule_id)
            self.assertIn(text, found[rule_id][0]["detail"], rule_id)
        self.assertEqual(res["result"], "fail")
        self.assertEqual(res["summary"]["blocking_findings"], 9)
        self.assertEqual(res["summary"]["advisory_findings"], 1)

    def test_defects_documented_in_make_demo_match_the_findings(self):
        documented = {rule_id for rule_id, _ in load_make_demo().DEFECTS}
        self.assertEqual(documented, set(failed(validate(DEFECTS))))

    def test_demo_packages_are_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            load_make_demo().build(tmp)
            for package in ("clean", "level1", "level2", "defects"):
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
        self.assertIn("Result: FAIL: 9 blocking findings, 1 advisory; declared level_4 (Supervision).", out)
        self.assertIn("https://ctres.org/validator", out)

    def test_summary_line_states_the_declared_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "pkg"
            shutil.copytree(CLEAN, pkg)
            m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
            del m["conformance_level_declared"]
            (pkg / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
            self.assertIn("Result: PASS: no blocking findings, 0 advisory; level not declared.", run_cli(str(pkg))[1])
            self.assertIn("STR-09  not run", run_cli(str(pkg))[1])
        self.assertIn("declared level_2 (a delivery level of CTRES v1.0, not tested).", run_cli(str(CLEAN_1_0))[1])

    def test_text_report_shows_a_check_with_advisory_findings_as_advisory(self):
        code, out, _ = run_cli(str(LEVEL2))
        self.assertEqual(code, 0)
        self.assertIn("REF-03  FAIL  advisory  2 findings", out)
        self.assertIn("          instrument_id — not resolved: R2 is not required at level_2 and is not in the package", out)
        self.assertNotIn("blocking  ", out.split("\nReferential:")[1])

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
                                                 "standard_version", "conformance_level_declared", "synthetic"])
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
                self.assertEqual(list(f), ["file", "line", "record", "field", "detail", "severity"])
                self.assertEqual(f["severity"], c["severity"])      # nothing is downgraded in demo/defects

    def test_json_output_lists_nine_structural_and_thirteen_referential_checks(self):
        res = json.loads(run_cli(str(CLEAN), "--json")[1])
        self.assertEqual([c["id"] for c in res["checks"]],
                         [f"STR-0{i}" for i in range(1, 10)] + [f"REF-{i:02d}" for i in range(1, 14)])
        self.assertEqual(res["summary"], {"checks": 22, "passed": 22, "failed": 0, "not_run": 0,
                                          "blocking_findings": 0, "advisory_findings": 0})
        self.assertEqual(res["standard_version"], "1.1")
        self.assertEqual(res["manifest"]["standard_version"], "1.1")
        self.assertEqual(res["manifest"]["conformance_level_declared"], "level_4")
        self.assertEqual({c["id"]: c["severity"] for c in res["checks"] if c["id"] > "REF-08"},
                         {"REF-09": "blocking", "REF-10": "blocking", "REF-11": "blocking", "REF-12": "blocking",
                          "REF-13": "advisory"} | {f"STR-0{i}": "blocking" for i in range(1, 10)})
        self.assertIn("money bridge", res["not_checked"])

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
        self.assertEqual(check(res, "REF-09")["status"], "not_run")

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


class ConformanceLevel(PackageCase):
    """STR-09: the record types the declared level requires are in the package (§10; Annex D)."""

    def test_str09_record_type_the_level_requires_is_missing(self):
        self.remove("R9")                                            # level_4 requires the Supervision module
        res = self.validate()
        self.assertOnly(res, {"STR-09": 1})
        self.assertEqual(failed(res)["STR-09"][0], {
            "file": "manifest.json", "line": None, "record": None, "field": "files", "severity": "blocking",
            "detail": "R9 is required at level_4 (Supervision) but the manifest lists no R9 file"})
        self.assertEqual(res["result"], "fail")
        self.assertEqual(run_cli(str(self.pkg))[0], 1)

    def test_str09_one_finding_per_missing_type_in_record_order(self):
        self.remove("R12", "R2", "R5")
        res = self.validate()
        self.assertEqual(set(failed(res)), {"STR-09"})
        self.assertEqual([f["detail"].split(" is required")[0] for f in failed(res)["STR-09"]], ["R2", "R5", "R12"])

    def test_str09_each_level_requires_its_minimum_set(self):
        minimum = {"level_1": {"R13"}, "level_2": {"R3", "R4", "R7", "R13"},
                   "level_3": {"R1", "R2", "R3", "R4", "R6", "R7", "R10", "R11", "R13"},
                   "level_4": {f"R{i}" for i in range(1, 14)}}
        for level, required in minimum.items():
            with self.subTest(level=level):
                shutil.rmtree(self.pkg)
                shutil.copytree(CLEAN, self.pkg)
                self.set_level(level)
                self.remove(*(t for t in [f"R{i}" for i in range(1, 15)] if t not in required and t != "R14"))
                self.assertEqual(check(self.validate(), "STR-09")["status"], "pass", level)
                for rtype in sorted(required):
                    shutil.rmtree(self.pkg)
                    shutil.copytree(CLEAN, self.pkg)
                    self.set_level(level)
                    self.remove(rtype)
                    res = self.validate()
                    self.assertEqual(len(failed(res).get("STR-09", [])), 1, (level, rtype))
                    self.assertIn(f"{rtype} is required at {level}", failed(res)["STR-09"][0]["detail"])

    def test_str09_extra_record_types_are_allowed_at_any_level(self):
        self.set_level("level_1")                                    # every record type, at the lowest level
        res = self.validate()
        self.assertOnly(res, {})
        self.assertEqual(check(res, "STR-09")["status"], "pass")
        self.assertTrue(all(not c["notes"] for c in res["checks"]))   # every reference resolves: nothing downgraded

    def test_str09_r14_required_from_level_2_where_an_r13_line_is_a_venue_line(self):
        self.set_level("level_2")
        self.remove("R14")
        res = self.validate()
        self.assertOnly(res, {"STR-09": 1})
        self.assertEqual(failed(res)["STR-09"][0]["detail"],
                         f"R14 is required at level_2 (Evidence) because an R13 line has channel venue ({FLOOR}) "
                         "but the manifest lists no R14 file")
        self.edit(R13, lambda rs: [r.update(channel="online") for r in rs if r["channel"] == "venue"])
        self.assertOnly(self.validate(), {})                         # no venue line: R14 is not required

    def test_str09_r14_not_required_at_level_1(self):
        self.set_level("level_1")
        self.remove("R14")
        self.assertOnly(self.validate(), {})

    def test_str09_not_run_without_a_declared_level(self):
        self.set_level(None)
        self.remove("R9")                                            # nothing requires it any more
        res = self.validate()
        self.assertOnly(res, {})
        self.assertEqual(check(res, "STR-09")["status"], "not_run")
        self.assertEqual(check(res, "STR-09")["notes"], ["not run: the manifest declares no conformance level"])
        self.assertEqual(res["summary"]["not_run"], 1)
        self.assertEqual(run_cli(str(self.pkg))[0], 0)

    def test_str09_not_run_for_a_level_outside_the_enumeration(self):
        self.set_level("level_5")
        res = self.validate()
        self.assertOnly(res, {"STR-08": 1})
        self.assertEqual(failed(res)["STR-08"][0]["field"], "conformance_level_declared")
        self.assertEqual(check(res, "STR-09")["status"], "not_run")
        self.assertIn("not a level of §10", " ".join(check(res, "STR-09")["notes"]))

    def test_str09_tests_the_manifest_listing_and_str01_the_file(self):
        (self.pkg / "R9_incidents.jsonl").unlink()                   # listed, required at level_4, not present
        self.assertOnly(self.validate(), {"STR-01": 1})


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
        self.set_level(None)                                         # a partial package that declares no level
        self.remove("R4")
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
        self.assertEqual(check(res, "REF-09")["status"], "not_run")
        self.assertEqual(res["summary"]["not_run"], 2)

    def test_ref08_attestation_does_not_exist(self):
        def change(rs):
            self.record(rs, "tx_id", "D-2026-11-0011")["attestation_ref"] = "ATT-NOWHERE"
        self.edit("R3_deposits.jsonl", change)
        self.assertOnly(self.validate(), {"REF-08": 1})

    def test_ref08_attestation_does_not_cover_the_location(self):
        self.edit("R11_provider_attestations.jsonl", lambda rs: rs[0].update(covers_location_ids=["L-PSP-01-BAL"]))
        self.assertOnly(self.validate(), {"REF-08": 5})


class ReferencesByLevel(PackageCase):
    """A reference to a record type the declared level does not require, where the package does not carry
    the type, is an identifier in the operator's own systems: reported as advisory, not resolved (§10).
    Where the type is in the package, or no level is declared, nothing changes."""

    def test_reference_to_a_type_the_level_does_not_require_is_advisory(self):
        self.set_level("level_2")
        self.remove("R2")
        res = self.validate()
        self.assertAdvisory(res, {"REF-03": 2, "REF-06": 1})           # REF-06: related_record_ids may name R2 too
        self.assertEqual(failed(res)["REF-06"][0]["detail"],
                         "related_record_ids — not resolved: R2 is not required at level_2 and is not in the package")
        self.assertEqual(failed(res)["REF-03"], [
            {"file": None, "line": None, "record": None, "field": "instrument_id", "severity": "advisory",
             "detail": "instrument_id — not resolved: R2 is not required at level_2 and is not in the package"},
            {"file": None, "line": None, "record": None, "field": "source_instrument_ids", "severity": "advisory",
             "detail": "source_instrument_ids — not resolved: R2 is not required at level_2 and is not in the package"}])
        self.assertEqual(check(res, "REF-03")["notes"], [])
        self.assertEqual(run_cli(str(self.pkg))[0], 0)

    def test_reference_is_blocking_where_the_type_is_in_the_package_whatever_the_level(self):
        self.set_level("level_2")
        self.edit("R3_deposits.jsonl", lambda rs: rs[0].update(instrument_id="I-NOWHERE"))
        res = self.validate()
        self.assertOnly(res, {"REF-03": 1})
        self.assertEqual(failed(res)["REF-03"][0]["severity"], "blocking")
        self.assertEqual(res["result"], "fail")

    def test_reference_is_noted_not_reported_where_no_level_is_declared(self):
        self.set_level(None)
        self.remove("R2")
        res = self.validate()
        self.assertOnly(res, {})
        self.assertEqual(check(res, "REF-03")["notes"], ["instrument_id not resolved: the package carries no R2 file",
                                                        "source_instrument_ids not resolved: the package carries no R2 file"])

    def test_reference_to_a_type_the_level_requires_is_noted_and_str09_reports_the_type(self):
        self.set_level("level_3")
        self.remove("R2")
        res = self.validate()
        self.assertOnly(res, {"STR-09": 1})
        self.assertIn("instrument_id not resolved: the package carries no R2 file", check(res, "REF-03")["notes"])

    def test_level_3_package_resolves_custody_and_leaves_supervision_advisory(self):
        self.set_level("level_3")
        self.remove("R5", "R8", "R9", "R12")
        res = self.validate()
        self.assertAdvisory(res, {"REF-02": 1, "REF-06": 1, "REF-12": 1})
        self.assertEqual([f["detail"] for f in failed(res)["REF-02"]],
                         ["check_ids — not resolved: R5 is not required at level_3 and is not in the package"])

    def test_related_records_advisory_where_none_of_the_absent_types_is_required(self):
        self.set_level("level_2")                                    # R12 included voluntarily at level_2
        self.remove("R1", "R2", "R5", "R6", "R8", "R9", "R10", "R11")
        res = self.validate()
        self.assertIn("related_record_ids — not resolved: R1, R2, R5, R6, R8 and R10 are not required at level_2 "
                      "and are not in the package", [f["detail"] for f in failed(res)["REF-06"]])
        self.assertEqual(res["result"], "pass")
        self.assertEqual(res["summary"]["blocking_findings"], 0)

    def test_related_records_noted_where_an_absent_type_is_required(self):
        self.set_level("level_3")
        self.remove("R1", "R5", "R8", "R9")                          # R1 is required at level_3; R5 and R8 are not
        res = self.validate()
        self.assertOnly(res, {"STR-09": 1, "REF-02": 1, "REF-06": 1})
        self.assertEqual([f["field"] for f in failed(res)["REF-06"]], ["exception_ids"])   # related_record_ids: noted
        self.assertIn("related_record_ids not resolved: the package carries no R1, R5, R8 file", check(res, "REF-06")["notes"])
        self.assertIn("location_id not resolved: the package carries no R1 file", check(res, "REF-01")["notes"])

    def test_one_advisory_finding_per_field_and_check(self):
        self.set_level("level_2")
        self.remove("R1", "R2", "R5", "R6", "R8", "R9", "R10", "R11", "R12")
        res = self.validate()
        self.assertAdvisory(res, LEVEL2_ADVISORY)
        self.assertEqual(sorted(f["field"] for f in failed(res)["REF-11"]), ["drop_deposit_ref", "venue_id"])

    def test_venue_reference_advisory_at_level_2_and_drop_resolved_in_r6(self):
        self.set_level("level_2")
        self.remove("R1")                                            # R6 stays: the drop banking still resolves
        res = self.validate()
        self.assertAdvisory(res, {"REF-01": 4, "REF-06": 1, "REF-11": 1})
        self.assertEqual([f["field"] for f in failed(res)["REF-01"]],
                         ["location_id", "covers_location_ids", "source_location_id", "destination_location_id"])
        self.assertEqual(failed(res)["REF-11"][0]["detail"],
                         "venue_id — not resolved: R1 is not required at level_2 and is not in the package")


# ------------------------------------------------------------------ gaming revenue and venue counts (v1.1)

class RevenueAndVenueChecks(PackageCase):
    """R13 gaming revenue statements and R14 venue counts: the checks added in 1.1, and the structural
    checks as they apply to the two record types."""

    def test_ref09_statement_period_outside_the_manifest_period(self):
        self.edit(R13, lambda rs: self.record(rs, "statement_id", SPORTS).update(period_start="2026-10-31T00:00:00+01:00"))
        res = self.validate()
        self.assertOnly(res, {"REF-09": 1})
        self.assertEqual(failed(res)["REF-09"][0]["field"], "period_start")
        self.assertEqual(res["result"], "fail")

    def test_ref09_statement_period_is_compared_offset_aware(self):
        # 2026-10-31T23:00:00Z is the manifest's 2026-11-01T00:00:00+01:00: inside the period
        self.edit(R13, lambda rs: self.record(rs, "statement_id", SPORTS).update(period_start="2026-10-31T23:00:00Z"))
        self.assertOnly(self.validate(), {})

    def test_ref09_gaming_day_outside_the_manifest_period(self):
        self.edit(R14, lambda rs: rs[0].update(gaming_day="2026-12-01"))
        res = self.validate()
        self.assertOnly(res, {"REF-09": 1})
        self.assertEqual(failed(res)["REF-09"][0]["field"], "gaming_day")
        self.assertIn("gaming_day 2026-12-01 is outside the period", failed(res)["REF-09"][0]["detail"])

    def test_ref09_gaming_days_on_the_boundary_dates_are_inside(self):
        def change(rs):
            rs[0]["gaming_day"], rs[1]["gaming_day"] = "2026-11-01", "2026-11-30"
        self.edit(R14, change)
        self.assertOnly(self.validate(), {})

    def test_ref09_venue_count_period_outside_the_manifest_period(self):
        def change(rs):
            del rs[0]["gaming_day"]
            rs[0].update(period_start="2026-11-14T06:00:00+01:00", period_end="2026-12-01T05:59:59+01:00")
        self.edit(R14, change)
        res = self.validate()
        self.assertOnly(res, {"REF-09": 1})
        self.assertEqual(failed(res)["REF-09"][0]["field"], "period_end")

    def test_ref10_correction_that_names_itself(self):
        def change(rs):
            self.record(rs, "statement_id", CASINO).update(statement_kind="correction", corrects_statement_id=CASINO,
                                                            correction_reason="Re-settlement")
        self.edit(R13, change)
        res = self.validate()
        self.assertOnly(res, {"REF-10": 1})
        self.assertIn("names itself", failed(res)["REF-10"][0]["detail"])

    def test_ref10_correction_of_a_statement_of_another_line(self):
        def change(rs):
            self.record(rs, "statement_id", CASINO).update(statement_kind="correction", corrects_statement_id=SPORTS,
                                                            correction_reason="Re-settlement")
        self.edit(R13, change)
        res = self.validate()
        self.assertOnly(res, {"REF-10": 1})
        self.assertIn("product_line SPORTS-PREMATCH-LIVE, not CASINO-SLOTS", failed(res)["REF-10"][0]["detail"])

    def test_ref10_corrections_that_replace_each_other(self):
        def change(rs):
            rs[0].update(statement_kind="correction", corrects_statement_id=rs[1]["statement_id"],
                         correction_reason="x", product_line=rs[1]["product_line"])
            rs[1].update(statement_kind="correction", corrects_statement_id=rs[0]["statement_id"], correction_reason="y")
        self.edit(R13, change)
        res = self.validate()
        self.assertOnly(res, {"REF-10": 2})
        self.assertIn("chain returns to", failed(res)["REF-10"][0]["detail"])

    def test_ref10_statement_the_package_does_not_carry_is_noted_not_reported(self):
        def change(rs):
            self.record(rs, "statement_id", CASINO).update(
                statement_kind="correction", corrects_statement_id="GRS-2026-10-XJ-DEMO-0001-CASINO-ONLINE-EUR",
                correction_reason="Jackpot revaluation")
        self.edit(R13, change)
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("may belong to an earlier package", " ".join(check(res, "REF-10")["notes"]))

    def test_ref10_correction_of_a_statement_of_the_same_line(self):
        def change(rs):
            correction = dict(self.record(rs, "statement_id", CASINO))
            correction.update(statement_id=CASINO + "-C1", statement_kind="correction", corrects_statement_id=CASINO,
                              correction_reason="Re-settlement", winnings_cash="2822.00", ggr_declared="128.00")
            rs.append(correction)
        self.edit(R13, change)
        self.assertOnly(self.validate(), {})

    def test_ref11_venue_no_r1_location_carries(self):
        self.edit(R14, lambda rs: rs[2].update(venue_id="V-NOWHERE"))
        res = self.validate()
        self.assertOnly(res, {"REF-11": 1})
        self.assertEqual(failed(res)["REF-11"][0]["field"], "venue_id")

    def test_ref11_venue_not_resolved_where_no_r1_location_carries_venue_id(self):
        self.edit("R1_funds_locations.jsonl", lambda rs: [r.pop("venue_id", None) for r in rs])
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("no R1 location carries venue_id", " ".join(check(res, "REF-11")["notes"]))

    def test_ref11_drop_banked_to_a_movement_that_does_not_exist(self):
        self.edit(R14, lambda rs: rs[1].update(drop_deposit_ref="M-NOWHERE"))
        res = self.validate()
        self.assertOnly(res, {"REF-11": 1})
        self.assertEqual(failed(res)["REF-11"][0]["field"], "drop_deposit_ref")

    def test_ref11_drop_banked_to_an_r1_cash_float(self):
        self.edit(R14, lambda rs: [r.update(drop_deposit_ref="L-VENUE-01-FLOAT") for r in rs])
        self.assertOnly(self.validate(), {})

    def test_ref11_drop_not_resolved_in_a_package_without_r6(self):
        self.set_level(None)
        self.remove("R6")
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("carries no R6 file", " ".join(check(res, "REF-11")["notes"]))

    def test_ref12_authority_figure_cites_a_report_reference_that_does_not_exist(self):
        def change(rs):
            self.record(rs, "statement_id", SPORTS)["authority_figure_ref"]["report_reference_id"] = "RR-NOWHERE"
        self.edit(R13, change)
        res = self.validate()
        self.assertOnly(res, {"REF-12": 1})
        self.assertEqual(failed(res)["REF-12"][0]["field"], "authority_figure_ref/report_reference_id")

    def test_ref12_not_resolved_in_a_package_without_r12(self):
        self.set_level(None)
        self.remove("R12")
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("carries no R12 file", " ".join(check(res, "REF-12")["notes"]))

    def test_ref13_all_in_formula_not_followed_is_advisory(self):
        self.edit(R13, lambda rs: self.record(rs, "statement_id", SPORTS).update(ggr_declared="211.00"))
        res = self.validate()
        self.assertOnly(res, {"REF-13": 1})
        self.assertEqual(res["result"], "pass")
        self.assertEqual(res["summary"]["advisory_findings"], 1)
        self.assertIn("(stakes_cash + stakes_bonus - stakes_refunded) - (winnings_cash + winnings_bonus) = 210.00",
                      failed(res)["REF-13"][0]["detail"])
        self.assertEqual(run_cli(str(self.pkg))[0], 0)

    def test_ref13_cash_only_formula_leaves_bonus_play_out(self):
        # The casino line carries bonus stakes and winnings; all_in would give 155.00, cash_only gives 140.00.
        self.edit(R13, lambda rs: self.record(rs, "statement_id", CASINO).update(ggr_declared="155.00"))
        self.assertOnly(self.validate(), {"REF-13": 1})

    def test_ref13_all_in_without_bonus_fields_counts_them_as_zero(self):
        def change(rs):
            r = self.record(rs, "statement_id", SPORTS)
            for k in ("stakes_bonus", "winnings_bonus", "bonus_granted", "bonus_expired", "bonus_measurement"):
                del r[k]
            r["ggr_declared"] = "150.00"                         # (4800 - 60) - 4590
        self.edit(R13, change)
        self.assertOnly(self.validate(), {})

    def test_ref13_arithmetic_is_exact(self):
        self.edit(R13, lambda rs: self.record(rs, "statement_id", SPORTS).update(ggr_declared="210.0"))
        self.assertOnly(self.validate(), {})
        self.edit(R13, lambda rs: self.record(rs, "statement_id", SPORTS).update(ggr_declared="210.001"))
        self.assertOnly(self.validate(), {"REF-13": 1})

    def test_ref13_negative_gross_gaming_revenue(self):
        self.edit(R13, lambda rs: self.record(rs, "statement_id", CASINO).update(winnings_cash="3000.00", ggr_declared="-50.00"))
        self.assertOnly(self.validate(), {})

    def test_ref13_profile_formula_is_not_tested(self):
        self.edit(R13, lambda rs: self.record(rs, "statement_id", SPORTS).update(ggr_formula="profile", ggr_declared="1.00"))
        res = self.validate()
        self.assertOnly(res, {})
        self.assertIn("ggr_formula profile", " ".join(check(res, "REF-13")["notes"]))

    def test_str04_venue_count_with_both_a_gaming_day_and_a_period(self):
        self.edit(R14, lambda rs: rs[0].update(period_start="2026-11-14T06:00:00+01:00", period_end="2026-11-15T05:59:59+01:00"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["detail"],
                         f"{SLOT}: exactly one of gaming_day or period_start and period_end is required")

    def test_str04_venue_count_with_neither_a_gaming_day_nor_a_period(self):
        self.edit(R14, lambda rs: rs[0].pop("gaming_day"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertIn("exactly one of gaming_day or period_start and period_end", failed(res)["STR-04"][0]["detail"])

    def test_str04_fields_the_unit_type_requires_or_excludes(self):
        def change(rs):
            del rs[0]["meters_end"]                               # a slot machine row needs both meter sets
            rs[1]["hard_count"] = "1.00"                          # a table row carries no count-room totals
        self.edit(R14, change)
        res = self.validate()
        self.assertOnly(res, {"STR-04": 2})
        self.assertEqual([f["field"] for f in failed(res)["STR-04"]], ["meters_end", "hard_count"])

    def test_str04_slot_row_without_meters_where_the_source_left_no_record(self):
        def change(rs):
            rs[0].pop("meters_start"), rs[0].pop("meters_end")      # no meter: the row wins by the drop formula
            rs[0].update(meter_source="not_recorded", win_formula="slot_drop_formula", drop_cash="74.00", fills="0.00")
        self.edit(R14, change)
        self.assertOnly(self.validate(), {})

    def test_str04_slot_row_by_the_drop_formula_without_drop_and_fills(self):
        self.edit(R14, lambda rs: rs[0].update(win_formula="slot_drop_formula"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 2})
        self.assertEqual([f["field"] for f in failed(res)["STR-04"]], ["drop_cash", "fills"])

    def test_str05_win_formula_that_does_not_fit_the_unit_type(self):
        def change(rs):
            rs[0]["win_formula"] = "table_drop_formula"             # a slot machine row
            rs[1]["win_formula"] = "slot_meter_formula"             # a table row
            rs[2]["win_formula"] = "table_drop_formula"             # a venue_total row names any formula
        self.edit(R14, change)
        res = self.validate()
        self.assertOnly(res, {"STR-05": 2})
        self.assertEqual([(f["record"], f["field"]) for f in failed(res)["STR-05"]],
                         [(SLOT, "win_formula"), ("VC-2026-11-14-V-DEMO-01-T-01", "win_formula")])

    def test_str04_bonus_stakes_without_the_bonus_bridge(self):
        self.edit(R13, lambda rs: [self.record(rs, "statement_id", SPORTS).pop(k) for k in ("bonus_granted", "bonus_expired")])
        res = self.validate()
        self.assertEqual(set(failed(res)), {"STR-04"})
        self.assertTrue(all("is a dependency of" in f["detail"] for f in failed(res)["STR-04"]))

    def test_statement_with_venue_id_and_player_location(self):
        def change(rs):
            self.record(rs, "statement_id", SPORTS).update(channel="venue", venue_id="V-DEMO-01")
            self.record(rs, "statement_id", CASINO).update(player_location="XJ", stakes_basis="accrual_at_result")
        self.edit(R13, change)
        self.assertOnly(self.validate(), {})
        self.edit(R13, lambda rs: self.record(rs, "statement_id", CASINO).update(player_location="Example"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["field"], "player_location")

    def test_str04_period_statement_with_a_correction_field(self):
        self.edit(R13, lambda rs: rs[0].update(corrects_statement_id="GRS-X"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["field"], "corrects_statement_id")

    def test_str04_undefined_field_on_a_statement(self):
        self.edit(R13, lambda rs: rs[0].update(ngr_declared="1.00"))
        res = self.validate()
        self.assertOnly(res, {"STR-04": 1})
        self.assertEqual(failed(res)["STR-04"][0]["detail"], f"{SPORTS}: not defined for this record: ngr_declared")

    def test_str05_and_str06_on_the_new_record_types(self):
        self.edit(R13, lambda rs: rs[0].update(ggr_formula="net"))
        self.edit(R14, lambda rs: rs[0].update(gaming_day="2026-11-31"))
        res = self.validate()
        self.assertOnly(res, {"STR-05": 1, "STR-06": 1})

    def test_str07_repeated_statement_and_count_identifiers(self):
        self.edit(R13, lambda rs: rs.append(dict(rs[0])))
        self.edit(R14, lambda rs: rs.append(dict(rs[0])))
        res = self.validate()
        self.assertOnly(res, {"STR-07": 2})
        self.assertEqual([f["record"] for f in failed(res)["STR-07"]], [SPORTS, SLOT])


# ------------------------------------------------------------------ packages produced under CTRES v1.0

class Packages10(unittest.TestCase):
    """A package produced under CTRES v1.0 (tests/fixtures/clean_1_0, the clean package of release 1.0.1)
    is validated unchanged; one that lists an R13 file must declare standard_version 1.1."""

    def test_1_0_package_passes_with_no_findings(self):
        # The fixture declares level_2 in its v1.0 meaning, a delivery level: STR-09 is not run, nothing is
        # downgraded, and every other check passes without a note.
        res = validate(CLEAN_1_0)
        self.assertEqual(res["result"], "pass")
        self.assertEqual(failed(res), {})
        self.assertTrue(all(c["status"] == "pass" and not c["notes"] for c in res["checks"] if c["id"] != "STR-09"))
        self.assertEqual(check(res, "STR-09")["status"], "not_run")
        self.assertEqual(check(res, "STR-09")["notes"], [
            "not run: the package declares standard_version 1.0, under which conformance_level_declared level_2 is a "
            "delivery level of v1.0, not a level of §10 of v1.1"])
        self.assertEqual(res["summary"]["not_run"], 1)
        self.assertEqual(res["manifest"]["standard_version"], "1.0")
        self.assertEqual(res["manifest"]["conformance_level_declared"], "level_2")
        self.assertEqual(res["standard_version"], "1.1")
        m = json.loads((CLEAN_1_0 / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([f["record_type"] for f in m["files"]], [f"R{i}" for i in range(1, 13)])
        self.assertEqual(run_cli(str(CLEAN_1_0))[0], 0)

    def test_1_0_package_that_lists_an_r13_file_fails_the_manifest_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "pkg"
            shutil.copytree(CLEAN_1_0, pkg)
            records = [json.loads(x) for x in (CLEAN / R13).read_text(encoding="utf-8").splitlines() if x.strip()]
            records = [r for r in records if r["channel"] != "venue"]   # the 1.0 package carries no R14 for a venue line
            for r in records:
                r.pop("authority_figure_ref", None)              # the 1.0 package carries no levy return in R12
            text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
            (pkg / R13).write_text(text, encoding="utf-8")
            m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
            m["files"].append({"file": R13, "record_type": "R13", "record_count": len(records), "sha256": sha256(text)})
            (pkg / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
            res = validate(pkg)
            self.assertEqual({k: len(v) for k, v in failed(res).items()}, {"STR-08": 1})
            self.assertEqual(failed(res)["STR-08"][0]["field"], "standard_version")
            self.assertIn("1.1", failed(res)["STR-08"][0]["detail"])
            m["standard_version"] = "1.1"
            (pkg / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
            self.assertEqual(failed(validate(pkg)), {})


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
