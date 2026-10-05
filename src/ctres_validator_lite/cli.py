"""Command line: ctres-validate <package_dir> [--json] [--schema-dir DIR]

Exit status: 0 when there are no blocking findings, 1 when there are, 2 on a usage error or when the
validation could not be completed.
"""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .validator import SchemaError, validate

SHOWN = 20          # findings printed per check in the text report; --json carries all of them


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ctres-validate",
        description="Structural and Referential validation (CTRES v1.0, §11) of a CTRES package directory.",
        epilog="Exit status: 0 no blocking findings, 1 blocking findings, 2 usage error or validation not completed.")
    parser.add_argument("package_dir", help="directory holding manifest.json and the JSON Lines record files")
    parser.add_argument("--json", action="store_true", help="write the result as JSON to standard output")
    parser.add_argument("--schema-dir", metavar="DIR",
                        help="use the CTRES schema files in DIR instead of the copy bundled with validator-lite")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:                     # argparse exits 2 on a usage error, 0 for --help
        return exc.code if isinstance(exc.code, int) else 2

    if not Path(args.package_dir).is_dir():
        print(f"ctres-validate: error: {args.package_dir} is not a directory", file=sys.stderr)
        return 2
    try:
        result = validate(args.package_dir, args.schema_dir)
    except SchemaError as exc:
        print(f"ctres-validate: error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                      # never let a failure to validate read as status 1 (findings)
        print(f"ctres-validate: error: validation could not be completed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    # Record values may hold any Unicode character; write UTF-8 whatever the console or locale encoding
    # (a Windows code page would otherwise stop the report part-way with an encoding error).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)
    return 1 if result["result"] == "fail" else 0


def print_report(res):
    m = res["manifest"] or {}
    print(f"CTRES validator-lite {res['validator_version']}: Structural and Referential validation (CTRES v1.0, §11)")
    print(f"package      {res['package']}")
    if m:
        print(f"package id   {m.get('package_id')}")
        print(f"licence      {m.get('licence_number')}, {m.get('licensee')}")
        print(f"profile      {m.get('profile_id')} {m.get('profile_version')}")
        print(f"period       {m.get('period_start')} to {m.get('period_end')}")
    print(f"fingerprint  {'SHA-256 ' + res['fingerprint'] if res['fingerprint'] else 'none (no manifest.json)'}")
    print(f"schema       {'bundled copy, release ' + res['schema_version'] if res['schema_version'] else res['schema_dir']}")
    if m.get("synthetic") is True:
        print("synthetic    yes: the manifest declares that the package holds synthetic data")

    for cls in ("structural", "referential"):
        checks = [c for c in res["checks"] if c["class"] == cls]
        count = {s: sum(c["status"] == s for c in checks) for s in ("pass", "fail", "not_run")}
        print(f"\n{cls.capitalize()}: {len(checks)} checks, {count['pass']} passed, {count['fail']} failed"
              + (f", {count['not_run']} not run" if count["not_run"] else ""))
        for c in checks:
            if c["status"] == "fail":
                n = len(c["findings"])
                print(f"  {c['id']}  FAIL  {c['severity']:<8}  {n} finding{'s' * (n != 1)}  {c['failure']} ({c['basis']})")
                for f in c["findings"][:SHOWN]:
                    where = f"{f['file']} line {f['line']}" if f["line"] else f["file"]
                    prefix = "" if not where or f["detail"].startswith(f["file"]) else where + ": "
                    print(f"          {prefix}{f['detail']}")
                if n > SHOWN:
                    print(f"          ... and {n - SHOWN} more (use --json for every finding)")
            else:
                print(f"  {c['id']}  {'pass' if c['status'] == 'pass' else 'not run'}  {c['requirement']}")
            for note in c["notes"]:
                print(f"          note: {note}")

    s = res["summary"]
    verdict = "PASS: no blocking findings" if res["result"] == "pass" else f"FAIL: {s['blocking_findings']} blocking findings"
    print(f"\nResult: {verdict}, {s['advisory_findings']} advisory.")
    print(f"Not checked by validator-lite: {res['not_checked']}")
