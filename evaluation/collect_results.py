#!/usr/bin/env python3
"""Convenience entry point for the result-analysis pipeline.

Equivalent to ``python -m cogpath_eval ...``.  Generates the two CSVs the project
uses as its final results:

**class level** -- one row per class::

    project,class,complexity,iter_0_line,iter_0_branch,...,final_line,final_branch,final_iter

**project level** -- one row per project::

    project,num_classes,avg_complexity,avg_final_line,avg_final_branch,
    max_line,min_line,max_branch,min_branch,std_line,std_branch,classes_with_coverage

Examples::

    # both levels for one run
    python collect_results.py all \\
        --label control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_bs \\
        --out-dir cogpath_results/cogpath --name qwen3-coder_30b_constraints_bs

    # re-aggregate an existing class-level CSV (no HTML parsing needed)
    python collect_results.py project-level --input class.csv --output project_class.csv

    # discover which runs exist and what configuration each recorded
    python collect_results.py runs

See ``cogpath_eval/`` for the implementation.
"""

import sys

from cogpath_eval.cli import main

if __name__ == "__main__":
    sys.exit(main())
