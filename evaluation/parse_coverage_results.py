#!/usr/bin/env python3
"""Write the per-class coverage CSV for one run directory.

Deprecated: this is now a thin wrapper that maps the old flags onto
:mod:`cogpath_eval`.  The implementation lives in the package so that the
class-level and project-level steps share a single parser.

Prefer::

    python collect_results.py class-level --label <run> --output out.csv

The legacy invocation still works::

    python parse_coverage_results.py --result-dir <run-dir> --class-list data/class_list.csv \\
        --output out.csv --prompt-type control --max-iterations 8
"""

import sys

from cogpath_eval.cli import main
from cogpath_eval.extract import parse_html_coverage as parse_coverage_from_html  # noqa: F401

__all__ = ["parse_coverage_from_html", "main"]


def _translate(argv):
    """Map legacy flags onto the ``class-level`` subcommand."""
    translated = ["class-level"]
    has_output = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--result-dir":
            translated.append("--run-dir")
        elif token in ("--output", "-o"):
            has_output = True
            translated.append(token)
        else:
            translated.append(token)
        index += 1

    if not has_output:
        # The old script defaulted the output name.
        translated.extend(["--output", "coverage_statistics.csv"])
    return translated


if __name__ == "__main__":
    print(
        "note: parse_coverage_results.py is deprecated; prefer "
        "`python collect_results.py class-level ...`",
        file=sys.stderr,
    )
    sys.exit(main(_translate(sys.argv[1:])))
