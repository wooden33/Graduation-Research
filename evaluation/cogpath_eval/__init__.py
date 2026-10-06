"""Result analysis for CogPath: parse runs, then emit class- and project-level CSVs.

The package is deliberately standard-library only so it can run anywhere the
result trees exist, without the tool's LLM/Java dependencies.

Public API::

    from cogpath_eval import ClassList, read_run, class_level_rows, project_level_rows

    class_list = ClassList.load()
    run = read_run("result-files/control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_bs", class_list)
    rows = class_level_rows(run.records, max_iterations=8)
    projects = project_level_rows(rows)
"""

from __future__ import annotations

from .aggregate import (
    CLASS_LEVEL_BASE,
    CLASS_LEVEL_TAIL,
    PROJECT_LEVEL_COLUMNS,
    PROJECT_LEVEL_EXTENDED_COLUMNS,
    SUMMARY_COLUMNS,
    class_level_columns,
    class_level_rows,
    overall_summary,
    project_level_columns,
    project_level_rows,
    read_class_level,
    write_class_level,
    write_overall_summary,
    write_project_level,
)
from .dataset import ClassList, ClassSpec
from .extract import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MISSING,
    DEFAULT_SOURCE,
    MISSING_POLICIES,
    SOURCES,
    ClassResult,
    RunResult,
    class_name_from_report,
    parse_html_coverage,
    parse_path_history,
    read_class_result,
    read_run,
)
from .paths import DEFAULT_CLASS_LIST, EVAL_DIR, REPO_ROOT, RESULT_FILES, RESULTS_DIR

__version__ = "1.0.0"

__all__ = [
    "ClassList",
    "ClassSpec",
    "ClassResult",
    "RunResult",
    "class_level_columns",
    "class_level_rows",
    "class_name_from_report",
    "overall_summary",
    "parse_html_coverage",
    "parse_path_history",
    "project_level_columns",
    "project_level_rows",
    "read_class_level",
    "read_class_result",
    "read_run",
    "write_class_level",
    "write_overall_summary",
    "write_project_level",
    "CLASS_LEVEL_BASE",
    "CLASS_LEVEL_TAIL",
    "PROJECT_LEVEL_COLUMNS",
    "PROJECT_LEVEL_EXTENDED_COLUMNS",
    "SUMMARY_COLUMNS",
    "DEFAULT_CLASS_LIST",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MISSING",
    "DEFAULT_SOURCE",
    "MISSING_POLICIES",
    "EVAL_DIR",
    "REPO_ROOT",
    "RESULT_FILES",
    "RESULTS_DIR",
    "SOURCES",
]
