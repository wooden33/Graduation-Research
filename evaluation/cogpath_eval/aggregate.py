"""Turn extracted class results into class-level and project-level CSVs.

Two aggregation conventions exist and they give **different numbers**, so both are
produced explicitly rather than one being chosen silently:

* the **unweighted mean of per-project averages** -- every project counts once.
  This is what ``paper/tables/*.tex`` reports (e.g. CogPath 53.14 / 44.41).
* the **class-weighted mean** -- every class counts once.  For the same run this
  gives 53.18 / 45.71, because large projects such as Lang and Math dominate.

Both schemas are frozen to match the pipeline that produced the checked-in CSVs;
``--extended`` adds columns rather than changing existing ones.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

CLASS_LEVEL_BASE = ("project", "class", "complexity")
CLASS_LEVEL_TAIL = ("final_line", "final_branch", "final_iter")

PROJECT_LEVEL_COLUMNS = (
    "project",
    "num_classes",
    "avg_complexity",
    "avg_final_line",
    "avg_final_branch",
    "max_line",
    "min_line",
    "max_branch",
    "min_branch",
    "std_line",
    "std_branch",
    "classes_with_coverage",
)
PROJECT_LEVEL_EXTENDED_COLUMNS = PROJECT_LEVEL_COLUMNS + (
    "project_id",
    "median_line",
    "median_branch",
)

SUMMARY_COLUMNS = (
    "scope",
    "n_projects",
    "n_classes",
    "mean_of_project_means_line",
    "mean_of_project_means_branch",
    "class_weighted_line",
    "class_weighted_branch",
)


# --------------------------------------------------------------------------- #
# Value normalisation
# --------------------------------------------------------------------------- #


def _present(value: Any) -> bool:
    """True when a value is present (``None``, ``""`` and whitespace are not).

    Deliberately *not* truthiness: the original code tested the raw CSV string, so
    ``"0.0"`` counted as present while a float ``0.0`` would not have.  Testing
    presence keeps the two input types (CSV strings and numeric records)
    equivalent.
    """
    return value is not None and str(value).strip() != ""


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    number = _to_float(value)
    return None if number is None else int(number)


# --------------------------------------------------------------------------- #
# Class level
# --------------------------------------------------------------------------- #


def class_level_columns(max_iterations: int, extended: bool = False) -> List[str]:
    columns = list(CLASS_LEVEL_BASE)
    if extended:
        columns.append("project_id")
    for index in range(max_iterations):
        columns.extend(["iter_{}_line".format(index), "iter_{}_branch".format(index)])
    columns.extend(CLASS_LEVEL_TAIL)
    return columns


def class_level_rows(
    records: Iterable[Any], max_iterations: int, extended: bool = False
) -> List[Dict[str, Any]]:
    """Build class-level rows from :class:`~cogpath_eval.extract.ClassResult` objects."""
    rows: List[Dict[str, Any]] = []
    for record in records:
        row: Dict[str, Any] = {
            "project": record.project,
            "class": record.class_name,
            "complexity": record.complexity,
        }
        if extended:
            row["project_id"] = getattr(record, "project_id", "")
        for index in range(max_iterations):
            point = record.iteration(index)
            # None (iteration never reached, --fill raw) becomes an empty cell.
            row["iter_{}_line".format(index)] = None if point is None else point[0]
            row["iter_{}_branch".format(index)] = None if point is None else point[1]
        row["final_line"] = record.final_line
        row["final_branch"] = record.final_branch
        row["final_iter"] = record.final_iter
        rows.append(row)
    return rows


def write_class_level(
    path: Path, rows: Sequence[Mapping[str, Any]], max_iterations: int, extended: bool = False
) -> None:
    _write_csv(path, class_level_columns(max_iterations, extended), rows)


# --------------------------------------------------------------------------- #
# Project level
# --------------------------------------------------------------------------- #


def read_class_level(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def project_level_rows(
    class_rows: Sequence[Mapping[str, Any]], extended: bool = False
) -> List[Dict[str, Any]]:
    """Aggregate class-level rows by project.

    ``class_rows`` may come from a class-level CSV (string values) or directly
    from :func:`class_level_rows` (numeric values).
    """
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in class_rows:
        project = str(row.get("project", "")).strip()
        if project:
            grouped[project].append(row)

    def _project_id(rows: Sequence[Mapping[str, Any]]) -> str:
        """The full subject id, when the class-level rows recorded it."""
        ids = {str(r.get("project_id", "")).strip() for r in rows}
        ids.discard("")
        return sorted(ids)[0] if len(ids) == 1 else ""

    results: List[Dict[str, Any]] = []
    for project in sorted(grouped):
        classes = grouped[project]
        valid = [row for row in classes if _present(row.get("final_line"))]
        if not valid:
            continue

        final_lines = [value for value in (_to_float(r.get("final_line")) for r in valid) if value is not None]
        final_branches = [value for value in (_to_float(r.get("final_branch")) for r in valid) if value is not None]
        complexities = [value for value in (_to_float(r.get("complexity")) for r in valid) if value is not None]

        stats: Dict[str, Any] = {
            "project": project,
            "num_classes": len(valid),
            "avg_complexity": mean(complexities) if complexities else 0,
            "avg_final_line": mean(final_lines) if final_lines else 0,
            "avg_final_branch": mean(final_branches) if final_branches else 0,
            "max_line": max(final_lines) if final_lines else 0,
            "min_line": min(final_lines) if final_lines else 0,
            "max_branch": max(final_branches) if final_branches else 0,
            "min_branch": min(final_branches) if final_branches else 0,
            # Sample standard deviation across the classes of this project --
            # dispersion between classes, not across repetitions.
            "std_line": stdev(final_lines) if len(final_lines) > 1 else 0,
            "std_branch": stdev(final_branches) if len(final_branches) > 1 else 0,
            "classes_with_coverage": sum(1 for value in final_lines if value > 0),
        }
        if extended:
            stats["project_id"] = _project_id(valid)
            stats["median_line"] = median(final_lines) if final_lines else 0
            stats["median_branch"] = median(final_branches) if final_branches else 0
        results.append(stats)

    return results


def project_level_columns(extended: bool = False) -> List[str]:
    return list(PROJECT_LEVEL_EXTENDED_COLUMNS if extended else PROJECT_LEVEL_COLUMNS)


def write_project_level(
    path: Path, rows: Sequence[Mapping[str, Any]], extended: bool = False
) -> None:
    _write_csv(path, project_level_columns(extended), rows)


# --------------------------------------------------------------------------- #
# Overall summary
# --------------------------------------------------------------------------- #


def overall_summary(project_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Summarise a project-level table under **both** aggregation conventions."""
    line_means: List[float] = []
    branch_means: List[float] = []
    total_classes = 0
    weighted_line = 0.0
    weighted_branch = 0.0

    for row in project_rows:
        count = _to_int(row.get("num_classes")) or 0
        line = _to_float(row.get("avg_final_line")) or 0.0
        branch = _to_float(row.get("avg_final_branch")) or 0.0
        line_means.append(line)
        branch_means.append(branch)
        total_classes += count
        weighted_line += line * count
        weighted_branch += branch * count

    return {
        "scope": "overall",
        "n_projects": len(project_rows),
        "n_classes": total_classes,
        "mean_of_project_means_line": mean(line_means) if line_means else 0,
        "mean_of_project_means_branch": mean(branch_means) if branch_means else 0,
        "class_weighted_line": (weighted_line / total_classes) if total_classes else 0,
        "class_weighted_branch": (weighted_branch / total_classes) if total_classes else 0,
    }


def write_overall_summary(path: Path, summary: Mapping[str, Any]) -> None:
    _write_csv(path, list(SUMMARY_COLUMNS), [summary])


# --------------------------------------------------------------------------- #
# CSV helper
# --------------------------------------------------------------------------- #


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    """Write a CSV exactly the way the original pipeline did.

    ``newline=""`` keeps the line terminator under the csv module's control
    (``\\r\\n``), which is what the checked-in CSVs contain, and values are written
    with ``str()`` rather than rounded so that regenerated files are
    byte-identical to the published ones.
    """
    path = Path(path)
    if path.parent and str(path.parent):
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})
