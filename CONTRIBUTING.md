# Contributing

Thank you for reviewing validator-lite. This document describes how changes are proposed and accepted.

## Where a change belongs

* **The text of the Standard is the source of truth.** A change to the record model belongs first in [ctres-standard/spec](https://github.com/ctres-standard/spec), then in [ctres-standard/schema](https://github.com/ctres-standard/schema). validator-lite follows the schema through `scripts/sync_schema.py`; the bundled copy is not edited by hand.
* **A check that contradicts the text** is a defect. Report it here, quoting the check identifier and the section of the Standard.
* **New checks** are accepted here only if they belong to the Structural or Referential class of §11 and can be decided from the package and the schema alone, with no tolerance, threshold, materiality level or profile parameter. A check that needs any of these belongs to the conformance suite, which is maintained separately (§11) and is not accepted into this repository. This includes reconciliation of statement totals against the records behind them.
* **Jurisdiction profiles** are maintained by the editor with the authorities concerned (§5, §13) and are not accepted into this repository. Corrections to a profile go to the editor at <hello@ctres.org>.

## How to propose a change

1. Open an issue describing the problem, the check or section concerned, and the change proposed. For small corrections a pull request alone is enough.
2. Pull requests are reviewed by the editor. A change to what a check accepts or rejects is published for comment before it is adopted (§13).

## Requirements for a pull request

* `python -m unittest discover -s tests` passes.
* Every check has an entry in `RULES` (`src/ctres_validator_lite/validator.py`) with an identifier, a class, a severity (`blocking` or `advisory`), the section of the Standard it rests on, the requirement and the failure, and the block that implements it opens with a one-line comment naming the identifier.
* Identifiers are never reused. A withdrawn check keeps its identifier out of use.
* Every check is covered by a test that changes a copy of `demo/clean` and asserts that exactly that check reports the change.
* The demonstration packages are changed only through `scripts/make_demo.py`, and regenerated with it. Their data is synthetic: no personal data, and no real operator, player, provider or jurisdiction.
* The table in `README.md` and the change log in `CHANGELOG.md` are updated.
* Code depends on the standard library and `jsonschema` only.
* Text is in English, in a plain and precise register.

## Versioning

The version is `MAJOR.MINOR.PATCH`. `MAJOR.MINOR` follows the version of the Standard implemented. A patch release corrects a defect; it does not add a check or change what a check accepts, except to correct a check that contradicts the text. The shape of the JSON output changes only with a major version.

## Licence of contributions

Unless you state otherwise, any contribution you submit for inclusion in this repository is licensed under the Apache License, Version 2.0, as set out in section 5 of the [License](LICENSE).

## Contact

General enquiries and comments that cannot be made public: <hello@ctres.org>. The repository is maintained by the editor of the Standard (see <https://ctres.org/governance/>).
