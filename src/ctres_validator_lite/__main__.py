"""python -m ctres_validator_lite <package_dir> [--json] [--schema-dir DIR]"""
import sys

from .cli import main

sys.exit(main())
