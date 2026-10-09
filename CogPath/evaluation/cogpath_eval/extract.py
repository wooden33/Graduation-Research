"""Extract per-class coverage results from a CogPath run directory.

Two sources exist and **they are not interchangeable**:

``<Class>_<prompt>_test_results.html``
    The tool's report.  Its ``g_N`` INFO rows are written after the generation
    phase and *before* the repair phase, so ``g_N`` is the pre-repair coverage of
    iteration *N*.  This is the series every published number was built from, and
    it is therefore the default source.

``<Class>_<prompt>_test_results_path_history.json``
    The iteration history, recorded at the *end* of each iteration, i.e.
    post-repair.  Measured on a real run, 76 of 319 comparable
    (class, iteration) pairs differ from the HTML series — the JSON values are
    consistently ahead.  So the JSON sidecar must not be used as a drop-in
    replacement for the HTML series.

Because of that, ``--source`` defaults to ``html`` (exactly reproducing the
published pipeline), and the sidecar is used only when explicitly requested:

``html``  HTML only — the default, and what the checked-in CSVs contain.
``auto``  HTML, falling back to the sidecar for a missing ``final`` value.
``json``  The sidecar only.  Convenient, but **not comparable** to published
          numbers, because its series is shifted by the repair phase.

Note on parsing: the report HTML is *not* well-formed, because
``report_generator.py`` renders LLM-generated Java source without HTML escaping,
so a generic like ``List<String>`` emits a raw ``<String>`` tag.  The extractor
below therefore reproduces the regex/positional scan used by the original
pipeline rather than a real HTML parse, so that numbers stay identical.  Fixing
the escaping in ``report_generator.py`` would allow a proper parser here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .dataset import ClassList, ClassSpec

DEFAULT_MAX_ITERATIONS = 8
DEFAULT_SOURCE = "html"
DEFAULT_MISSING = "carry-forward"
SOURCES = ("html", "auto", "json")
MISSING_POLICIES = ("carry-forward", "raw")

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_STATUS_RE = re.compile(r"status-(\w+)")
_TAG_RE = re.compile(r"<[^>]+>")
_ITER_LABEL_RE = re.compile(r"^g_(\d+)$")
# `<Class>_<prompt>_test_results.html`, and the doubled variant seen in some trees.
_REPORT_RE = re.compile(r"^(?P<cls>.+)_(?P<prompt>[A-Za-z0-9.+-]+)_test_results\.html$")
_REPORT_DOUBLED_RE = re.compile(
    r"^(?P<cls>.+)_(?P<prompt>[A-Za-z0-9.+-]+)_(?P=prompt)_test_results\.html$"
)


@dataclass(frozen=True)
class ClassResult:
    """Per-class outcome for one run.

    ``project`` is the label written to the CSVs (short by default, to match the
    published tables); ``project_id`` is always the full Defects4J subject id.
    """

    project: str
    project_id: str
    class_name: str
    complexity: Optional[int]
    iterations: Tuple[Optional[Tuple[float, float]], ...]
    final_line: Optional[float]
    final_branch: Optional[float]
    final_iter: int
    source: str = DEFAULT_SOURCE
    conflicts: Tuple[str, ...] = ()

    def iteration(self, index: int) -> Optional[Tuple[float, float]]:
        """Coverage at iteration ``index``, or ``None`` when it was not reached.

        ``None`` means the run stopped before that iteration; it is written as an
        empty CSV cell under ``--fill raw``.
        """
        return self.iterations[index] if index < len(self.iterations) else None


@dataclass
class RunResult:
    """Everything extracted from one run directory."""

    run_dir: Path
    prompt_type: str
    max_iterations: int
    source: str
    records: List[ClassResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_reports: List[str] = field(default_factory=list)
    extra_reports: List[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.records)


# --------------------------------------------------------------------------- #
# HTML report
# --------------------------------------------------------------------------- #


def parse_html_coverage(html: str) -> Dict[str, Tuple[float, float]]:
    """Map ``status == INFO`` row labels to ``(line, branch)`` coverage.

    The special key ``"final"`` holds the run's final coverage: the pipeline
    writes it either as an INFO row with an empty label, or (older trees) as a row
    literally labelled ``final``.

    Rows that do not yield two parseable coverage numbers are skipped, which
    mirrors the original implementation.
    """
    coverage: Dict[str, Tuple[float, float]] = {}

    for row in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row)
        if len(cells) < 6:
            continue

        status_match = _STATUS_RE.search(cells[0])
        status = status_match.group(1) if status_match else cells[0].strip()
        label = _TAG_RE.sub("", cells[1]).strip()

        try:
            line = float(_TAG_RE.sub("", cells[4]).strip())
            branch = float(_TAG_RE.sub("", cells[5]).strip())
        except (ValueError, IndexError):
            continue

        # Only the aggregated INFO rows matter; PASS/FAIL rows repeat a label.
        if label.startswith("g_") and status != "INFO":
            continue

        if not label:
            if status == "INFO":
                coverage["final"] = (line, branch)
            continue

        coverage[label] = (line, branch)

    return coverage


def final_iteration_index(coverage: Dict[str, Tuple[float, float]]) -> int:
    """Highest ``g_N`` index present, or ``-1`` when there is none."""
    highest = -1
    for label in coverage:
        match = _ITER_LABEL_RE.match(label)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def class_name_from_report(filename: str, prompt_type: Optional[str] = None) -> Optional[str]:
    """Derive the class name from a report file name.

    With ``prompt_type`` given, the original anchored patterns are used verbatim.
    Without it, the class is the longest prefix that leaves a single prompt token
    before ``_test_results.html``.
    """
    if prompt_type:
        doubled = re.match(
            rf"^(?P<cls>.+?)_{re.escape(prompt_type)}_{re.escape(prompt_type)}_test_results\.html$",
            filename,
        )
        if doubled:
            return doubled.group("cls")
        single = re.match(
            rf"^(?P<cls>.+?)_{re.escape(prompt_type)}_test_results\.html$", filename
        )
        return single.group("cls") if single else None

    doubled = _REPORT_DOUBLED_RE.match(filename)
    if doubled:
        return doubled.group("cls")
    generic = _REPORT_RE.match(filename)
    return generic.group("cls") if generic else None


# --------------------------------------------------------------------------- #
# JSON sidecar
# --------------------------------------------------------------------------- #


def parse_path_history(path: Path) -> Tuple[Optional[float], Optional[float], Tuple[Tuple[float, float], ...]]:
    """Read ``final_*`` and the per-iteration series from a path-history sidecar.

    The series is **post-repair**, unlike the HTML one.  Returns
    ``(final_line, final_branch, iterations)``.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None, None, ()

    final_line = payload.get("final_line_coverage")
    final_branch = payload.get("final_branch_coverage")
    history = payload.get("detailed_path_history") or []

    iterations: List[Tuple[float, float]] = []
    for entry in history:
        line = entry.get("line_coverage")
        branch = entry.get("branch_coverage")
        if line is None or branch is None:
            continue
        iterations.append((float(line), float(branch)))

    return final_line, final_branch, tuple(iterations)


# --------------------------------------------------------------------------- #
# One class
# --------------------------------------------------------------------------- #


def read_class_result(
    report_path: Path,
    spec: ClassSpec,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    source: str = DEFAULT_SOURCE,
    project_names: str = "short",
    missing: str = DEFAULT_MISSING,
) -> ClassResult:
    """Extract one class's result, using the requested source.

    ``missing`` decides what happens for an iteration the run never reached:

    ``carry-forward``  repeat the final coverage (the current pipeline's rule; it
                       keeps a constant sample size across the curve, at the cost
                       of attributing a later measurement to an earlier iteration)
    ``raw``            leave the cell empty, so per-iteration averages are taken
                       over however many classes actually reached that iteration
    """
    if source not in SOURCES:
        raise ValueError("unknown source {!r} (choose from {})".format(source, ", ".join(SOURCES)))

    html_coverage: Dict[str, Tuple[float, float]] = {}
    if source in ("html", "auto"):
        try:
            html_coverage = parse_html_coverage(report_path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            html_coverage = {}

    history_path = report_path.with_name(
        report_path.name.replace("_test_results.html", "_test_results_path_history.json")
    )
    json_final: Tuple[Optional[float], Optional[float]] = (None, None)
    json_iterations: Tuple[Tuple[float, float], ...] = ()
    if source in ("auto", "json") and history_path.exists():
        jl, jb, json_iterations = parse_path_history(history_path)
        json_final = (jl, jb)

    # Resolve the final coverage and the series according to the source policy.
    conflicts: List[str] = []
    if source == "json":
        final_line, final_branch = json_final
        points: List[Optional[Tuple[float, float]]] = list(json_iterations)
        final_iter = len(points) - 1 if points else -1
        resolved_source = "json"
    else:
        html_final = html_coverage.get("final")
        final_line, final_branch = html_final if html_final else (None, None)
        final_iter = final_iteration_index(html_coverage)
        resolved_source = "html"

        if source == "auto" and final_line is None and json_final[0] is not None:
            final_line, final_branch = json_final
            resolved_source = "html+json"

        if source == "auto" and html_final and json_final[0] is not None:
            if (round(html_final[0], 2), round(html_final[1], 2)) != (
                round(float(json_final[0]), 2),
                round(float(json_final[1]), 2),
            ):
                conflicts.append(
                    "final coverage differs: html={} json={}".format(
                        (html_final[0], html_final[1]), json_final
                    )
                )

        # Build the iteration series, applying the missing-iteration policy.
        fill_line = final_line if final_line else 0
        fill_branch = final_branch if final_branch else 0
        points = []
        for index in range(max_iterations):
            point = html_coverage.get("g_{}".format(index))
            if point is not None:
                points.append(point)
            elif missing == "carry-forward":
                points.append((fill_line, fill_branch))
            else:
                points.append(None)

    if source == "json":
        fill_line = final_line if final_line else 0
        fill_branch = final_branch if final_branch else 0
        while len(points) < max_iterations:
            points.append((fill_line, fill_branch) if missing == "carry-forward" else None)
        points = points[:max_iterations]

    return ClassResult(
        project=spec.project if project_names == "full" else spec.label,
        project_id=spec.project,
        class_name=spec.class_name,
        complexity=spec.complexity,
        iterations=tuple(points),
        final_line=final_line,
        final_branch=final_branch,
        final_iter=final_iter,
        source=resolved_source,
        conflicts=tuple(conflicts),
    )


# --------------------------------------------------------------------------- #
# A whole run directory
# --------------------------------------------------------------------------- #


def report_files(run_dir: Path, prompt_type: Optional[str] = None) -> List[Path]:
    """All report files in a run directory, sorted by class name."""
    run_dir = Path(run_dir)
    run_metadata_path = run_dir / "run.json"
    if run_metadata_path.is_file():
        try:
            run_metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run_metadata = {}
        if run_metadata.get("schema_version") == 1:
            found = []
            for state_path in sorted(run_dir.glob("tasks/*/*/state.json")):
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if state.get("status") != "completed" or state.get("exit_code") != 0:
                    continue
                path = Path(state.get("report_path", ""))
                if path.is_file() and class_name_from_report(path.name, prompt_type):
                    found.append(path)
            return found

    found = []
    for path in sorted(run_dir.rglob("*_test_results.html")):
        if class_name_from_report(path.name, prompt_type):
            found.append(path)
    return found


def detect_prompt_type(run_dir: Path) -> str:
    """Infer the prompt token from the report file names in a directory."""
    for path in report_files(run_dir):
        match = _REPORT_RE.match(path.name)
        if match:
            return match.group("prompt")
    return "control"


def read_run(
    run_dir: Path,
    class_list: ClassList,
    prompt_type: Optional[str] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    source: str = DEFAULT_SOURCE,
    project_names: str = "short",
    missing: str = DEFAULT_MISSING,
) -> RunResult:
    """Extract every class in ``run_dir`` that appears in the work list.

    Rows are emitted in report-filename order, which is what the original
    pipeline did (``sorted(os.listdir(...))``) and therefore what the checked-in
    CSVs contain.  Sorting by project instead would reorder the file.
    """
    if project_names not in ("short", "full"):
        raise ValueError("project_names must be 'short' or 'full'")
    if missing not in MISSING_POLICIES:
        raise ValueError("missing must be one of {}".format(", ".join(MISSING_POLICIES)))
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError("not a directory: {}".format(run_dir))

    prompt = prompt_type or detect_prompt_type(run_dir)
    result = RunResult(
        run_dir=run_dir, prompt_type=prompt, max_iterations=max_iterations, source=source
    )

    seen: set = set()
    for path in report_files(run_dir, prompt):
        class_name = class_name_from_report(path.name, prompt)
        if not class_name:
            result.extra_reports.append(path.name)
            continue
        spec = class_list.by_class(class_name)
        if spec is None:
            # Either not part of the work list, or an ambiguous name.
            result.extra_reports.append(path.name)
            continue
        seen.add(class_name)
        record = read_class_result(
            path,
            spec,
            max_iterations=max_iterations,
            source=source,
            project_names=project_names,
            missing=missing,
        )
        result.records.append(record)

        if record.conflicts:
            for conflict in record.conflicts:
                result.warnings.append("{}: {}".format(class_name, conflict))
        reached = [i for i, point in enumerate(record.iterations) if point is not None]
        highest = max(reached, default=-1)
        if record.final_iter >= max_iterations:
            result.warnings.append(
                "{}: run reached iteration {} but only the first {} are exported; "
                "raise --max-iterations to keep the full curve".format(
                    class_name, record.final_iter, max_iterations
                )
            )
        elif highest == -1:
            result.warnings.append("{}: no iteration rows found".format(class_name))

    for spec in class_list:
        if spec.class_name not in seen:
            result.missing_reports.append(spec.class_name)

    return result
