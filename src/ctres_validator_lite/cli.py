"""Command line:

    ctres-validate <package_dir> [--json] [--schema-dir DIR] [--reconcile EVENTS] [--max-latency DURATION]
    ctres-validate --stream EVENTS [--json] [--schema-dir DIR] [--max-latency DURATION]

Exit status: 0 when there are no blocking findings, 1 when there are, 2 on a usage error or when the
validation could not be completed.
"""
import argparse
import json
import sys
from pathlib import Path

from . import STANDARD_VERSION, __version__
from .validator import LEVELS, SchemaError, parse_duration, validate, validate_stream

SHOWN = 20          # findings printed per check in the text report; --json carries all of them
CLASSES = ("structural", "referential", "stream", "reconciliation")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ctres-validate",
        description=f"Structural and Referential validation (CTRES v{STANDARD_VERSION}, §11) of a CTRES package "
                    "directory; with --stream, validation of a stream of events (§8.4); with --reconcile, "
                    "reconciliation of the package with the stream that carried its records.",
        epilog="Exit status: 0 no blocking findings, 1 blocking findings, 2 usage error or validation not completed.")
    parser.add_argument("package_dir", nargs="?", help="directory holding manifest.json and the JSON Lines record files")
    parser.add_argument("--stream", metavar="EVENTS",
                        help="validate the NDJSON events file EVENTS (STM-01 to STM-07) instead of a package")
    parser.add_argument("--reconcile", metavar="EVENTS",
                        help="also validate the stream in EVENTS and reconcile the package with it (REC-01 to REC-04)")
    parser.add_argument("--max-latency", metavar="DURATION",
                        help="maximum delay from a record's anchor timestamp to its event, as an ISO 8601 duration "
                             "such as PT60S (STM-07); with --stream or --reconcile")
    parser.add_argument("--json", action="store_true", help="write the result as JSON to standard output")
    parser.add_argument("--schema-dir", metavar="DIR",
                        help="use the CTRES schema files in DIR instead of the copy bundled with validator-lite")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:                     # argparse exits 2 on a usage error, 0 for --help
        return exc.code if isinstance(exc.code, int) else 2

    def usage(message):
        print(f"ctres-validate: error: {message}", file=sys.stderr)
        return 2

    if args.stream is None and args.package_dir is None:
        return usage("a package directory or --stream EVENTS is required")
    if args.stream is not None and args.package_dir is not None:
        return usage("--stream validates a stream on its own; to test a package against a stream, use --reconcile EVENTS")
    if args.stream is not None and args.reconcile is not None:
        return usage("--stream and --reconcile cannot be combined")
    if args.max_latency is not None and args.stream is None and args.reconcile is None:
        return usage("--max-latency applies with --stream or --reconcile")
    if args.max_latency is not None and parse_duration(args.max_latency) is None:
        return usage(f"--max-latency {args.max_latency}: not an ISO 8601 duration in weeks, days, hours, minutes and "
                     "seconds (for example PT60S, PT5M or P1D)")
    if args.package_dir is not None and not Path(args.package_dir).is_dir():
        return usage(f"{args.package_dir} is not a directory")
    for events in (args.stream, args.reconcile):
        if events is not None and not Path(events).is_file():
            return usage(f"{events} is not a file")
    try:
        if args.stream is not None:
            result = validate_stream(args.stream, args.schema_dir, args.max_latency)
        else:
            result = validate(args.package_dir, args.schema_dir, args.reconcile, args.max_latency)
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
    m = res.get("manifest") or {}
    s = res.get("stream")
    if "package" in res:
        print(f"CTRES validator-lite {res['validator_version']}: Structural and Referential validation "
              f"(CTRES v{STANDARD_VERSION}, §11)" + (", reconciled with a stream (§8.4)" if s else ""))
        print(f"package      {res['package']}")
        if m:
            print(f"package id   {m.get('package_id')}")
            print(f"licence      {m.get('licence_number')}, {m.get('licensee')}")
            print(f"profile      {m.get('profile_id')} {m.get('profile_version')}")
            print(f"period       {m.get('period_start')} to {m.get('period_end')}")
        if s:
            print(f"stream       {s['path']}: {stream_text(s)}")
        print(f"fingerprint  {'SHA-256 ' + res['fingerprint'] if res['fingerprint'] else 'none (no manifest.json)'}")
    else:
        print(f"CTRES validator-lite {res['validator_version']}: Stream validation (CTRES v{STANDARD_VERSION}, §8.4)")
        print(f"stream       {s['path']}")
        print(f"events       {stream_text(s)}")
        if s["record_types"]:
            print(f"record types {', '.join(f'{t} {n}' for t, n in s['record_types'].items())}")
        print(f"fingerprint  SHA-256 {s['fingerprint']}")
    print(f"schema       {'bundled copy, release ' + res['schema_version'] if res['schema_version'] else res['schema_dir']}")
    if m.get("synthetic") is True:
        print("synthetic    yes: the manifest declares that the package holds synthetic data")
    if s:
        print(f"max latency  {s['max_latency'] if s['max_latency'] else 'not set: STM-07 not run'}")

    for cls in CLASSES:
        checks = [c for c in res["checks"] if c["class"] == cls]
        if not checks:
            continue
        count = {st: sum(c["status"] == st for c in checks) for st in ("pass", "fail", "not_run")}
        print(f"\n{cls.capitalize()}: {len(checks)} checks, {count['pass']} passed, {count['fail']} failed"
              + (f", {count['not_run']} not run" if count["not_run"] else ""))
        for c in checks:
            if c["status"] == "fail":
                n = len(c["findings"])
                blocking = sum(f["severity"] == "blocking" for f in c["findings"])
                # A blocking check whose findings are all advisory (references not resolved by level) reads as advisory.
                severity = "blocking" if blocking else "advisory"
                count = f"{n} finding{'s' * (n != 1)}" + (f" ({n - blocking} advisory)" if 0 < blocking < n else "")
                print(f"  {c['id']}  FAIL  {severity:<8}  {count}  {c['failure']} ({c['basis']})")
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

    summary = res["summary"]
    verdict = ("PASS: no blocking findings" if res["result"] == "pass"
               else f"FAIL: {summary['blocking_findings']} blocking findings")
    if "package" not in res:
        tail = stream_text(s)
    elif s:
        tail = f"{level_text(m)}; reconciled with {s['path']} ({stream_text(s, short=True)})"
    else:
        tail = level_text(m)
    print(f"\nResult: {verdict}, {summary['advisory_findings']} advisory; {tail}.")
    print(f"Not checked by validator-lite: {res['not_checked']}")


def stream_text(s, short=False):
    """The events, streams and checkpoints of a stream file, for the header and the result line."""
    n, c = s["events"], s["checkpoints"]
    streams = s["streams"]
    if short:
        return f"{n} event{'s' * (n != 1)}, {c} checkpoint{'s' * (c != 1)}"
    named = "; ".join(f"{sid}, sequences {i['first_sequence']} to {i['last_sequence']}" for sid, i in streams.items())
    return (f"{n} event{'s' * (n != 1)} in {len(streams)} stream{'s' * (len(streams) != 1)}"
            + (f" ({named})" if named else "") + f", {c} checkpoint{'s' * (c != 1)}")


def level_text(m):
    """The conformance level the manifest declares (§10), for the summary line."""
    declared = m.get("conformance_level_declared")
    if declared is None:
        return "level not declared"
    if m.get("standard_version") == "1.1" and declared in LEVELS:
        return f"declared {declared} ({LEVELS[declared][0]})"
    if m.get("standard_version") == "1.0":
        return f"declared {declared} (a delivery level of CTRES v1.0, not tested)"
    return f"declared {declared!r}, which is not a level of §10"
