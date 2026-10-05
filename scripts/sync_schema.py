#!/usr/bin/env python3
"""Copy the CTRES JSON Schema into this package.

validator-lite carries a copy of the schema files of ctres-standard/schema under
src/ctres_validator_lite/schema/, so that it runs without network access. This script replaces
that copy with the schema files of a checkout of ctres-standard/schema and records the release
in SCHEMA_VERSION (src/ctres_validator_lite/__init__.py).

Usage:  python scripts/sync_schema.py [SOURCE] [--version X.Y.Z]

SOURCE is the root of a ctres-standard/schema checkout (default: ../schema). The version defaults
to the latest release heading ("## X.Y.Z") in SOURCE/CHANGELOG.md. Files are copied byte for byte.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "ctres_validator_lite" / "schema"
INIT = ROOT / "src" / "ctres_validator_lite" / "__init__.py"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", nargs="?", default=str(ROOT.parent / "schema"))
    ap.add_argument("--version", help="schema release, MAJOR.MINOR.PATCH")
    args = ap.parse_args(argv)

    source = Path(args.source).resolve() / "schema"
    if not (source / "manifest.schema.json").is_file():
        sys.exit(f"sync_schema: {source} does not hold the CTRES schema files")

    version = args.version
    if version is None:
        found = re.search(r"^## (\d+\.\d+\.\d+)", (source.parent / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
        if not found:
            sys.exit("sync_schema: no release heading in CHANGELOG.md; pass --version")
        version = found.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"sync_schema: {version!r} is not MAJOR.MINOR.PATCH")

    # Every $id must lie under the MAJOR.MINOR path of the release, and match the file's own path.
    base = "https://ctres.org/schema/" + ".".join(version.split(".")[:2]) + "/"
    files = sorted(source.rglob("*.schema.json"))
    for path in files:
        rel = path.relative_to(source).as_posix()
        if json.loads(path.read_text(encoding="utf-8")).get("$id") != base + rel:
            sys.exit(f"sync_schema: {rel}: $id is not {base + rel}")

    # Replace the vendored copy.
    for old in TARGET.rglob("*.schema.json"):
        old.unlink()
    for path in files:
        dest = TARGET / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)

    text = INIT.read_text(encoding="utf-8")
    text, n = re.subn(r'^SCHEMA_VERSION = "[^"]*"$', f'SCHEMA_VERSION = "{version}"', text, flags=re.M)
    if n != 1:
        sys.exit("sync_schema: SCHEMA_VERSION line not found in __init__.py")
    INIT.write_text(text, encoding="utf-8")
    print(f"copied {len(files)} schema files from {source} (release {version}) to {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
