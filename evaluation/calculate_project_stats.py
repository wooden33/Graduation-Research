#!/usr/bin/env python3
"""Aggregate a class-level coverage CSV into per-project statistics.

Deprecated: this is now a thin wrapper around :mod:`cogpath_eval`; the
implementation lives in the package so both levels share one definition of the
aggregation.

Prefer::

    python collect_results.py project-level --input class.csv --output project.csv

The legacy invocation still works, including the optional ``--output`` (without
it, the statistics are only printed)::

    python calculate_project_stats.py --input class.csv --output project.csv
"""

import sys

from cogpath_eval.cli import main

if __name__ == "__main__":
    print(
        "note: calculate_project_stats.py is deprecated; prefer "
        "`python collect_results.py project-level ...`",
        file=sys.stderr,
    )
    sys.exit(main(["project-level"] + sys.argv[1:]))
