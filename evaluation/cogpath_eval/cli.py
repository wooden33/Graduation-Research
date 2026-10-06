"""Command line interface for the result-analysis pipeline.

    python -m cogpath_eval class-level   --label control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_bs --output out.csv
    python -m cogpath_eval project-level --input out.csv --output project_out.csv
    python -m cogpath_eval all           --label <run> --out-dir cogpath_results/cogpath --name <slug>
    python -m cogpath_eval runs

``project-level`` reads a class-level **CSV**, not a run directory, so a stored
class-level table can be re-aggregated without re-parsing 130 reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import aggregate, extract
from .dataset import ClassList
from .paths import DEFAULT_CLASS_LIST, RESULT_FILES


def resolve_run_dir(value: str, result_root: Optional[Path] = None) -> Path:
    """Accept either a path to a run directory or a label under ``result-files/``."""
    candidate = Path(value)
    if candidate.is_dir():
        return candidate.resolve()
    root = Path(result_root) if result_root else RESULT_FILES
    candidate = root / value
    if candidate.is_dir():
        return candidate.resolve()
    raise SystemExit(
        "no such run directory: {!r} (looked at {!r} and {!r})".format(value, value, str(candidate))
    )


def _load_class_list(path: Optional[str]) -> ClassList:
    class_list = ClassList.load(Path(path) if path else DEFAULT_CLASS_LIST)
    ambiguous = class_list.ambiguous_classes()
    if ambiguous:
        # Never guess: an ambiguous name would silently move coverage between
        # projects. Results for those classes are skipped and reported.
        print(
            "WARNING: {} class name(s) appear in more than one project and will be "
            "skipped: {}".format(len(ambiguous), ", ".join(sorted(ambiguous)[:5])),
            file=sys.stderr,
        )
    return class_list


def _print_run_summary(run: extract.RunResult, class_list: ClassList) -> None:
    print("run dir        : {}".format(run.run_dir))
    print("prompt type    : {}".format(run.prompt_type))
    print("source         : {}".format(run.source))
    print("max iterations : {}".format(run.max_iterations))
    print("classes parsed : {}/{}".format(len(run.records), len(class_list)))
    if run.missing_reports:
        print("missing reports: {} (e.g. {})".format(
            len(run.missing_reports), ", ".join(run.missing_reports[:5])))
    if run.extra_reports:
        print("unmatched files: {} (e.g. {})".format(
            len(run.extra_reports), ", ".join(run.extra_reports[:3])))
    for warning in run.warnings[:10]:
        print("WARNING: {}".format(warning), file=sys.stderr)
    if len(run.warnings) > 10:
        print("... and {} more warnings".format(len(run.warnings) - 10), file=sys.stderr)


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #


def cmd_class_level(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.label or args.run_dir, args.result_files)
    class_list = _load_class_list(args.class_list)

    run = extract.read_run(
        run_dir,
        class_list,
        prompt_type=args.prompt_type,
        max_iterations=args.max_iterations,
        source=args.source,
        project_names=args.project_names,
        missing=args.fill,
    )

    rows = aggregate.class_level_rows(run.records, args.max_iterations, extended=args.extended)
    aggregate.write_class_level(args.output, rows, args.max_iterations, extended=args.extended)

    if not args.quiet:
        _print_run_summary(run, class_list)
        print("wrote          : {} ({} rows)".format(args.output, len(rows)))

    if args.strict and (run.missing_reports or run.warnings):
        print("STRICT: failing because the run is incomplete or conflicted", file=sys.stderr)
        return 1
    return 0


def cmd_project_level(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit("no such class-level CSV: {}".format(input_path))

    class_rows = aggregate.read_class_level(input_path)
    rows = aggregate.project_level_rows(class_rows, extended=args.extended)
    if args.output:
        aggregate.write_project_level(args.output, rows, extended=args.extended)

    summary = aggregate.overall_summary(rows)
    if args.summary_out:
        aggregate.write_overall_summary(args.summary_out, summary)

    if not args.quiet:
        print("input          : {} ({} class rows)".format(input_path, len(class_rows)))
        print("{:<16}{:>8}{:>12}{:>14}".format("project", "classes", "avg line", "avg branch"))
        print("-" * 50)
        for row in rows:
            print(
                "{:<16}{:>8}{:>12.2f}{:>14.2f}".format(
                    row["project"], row["num_classes"], row["avg_final_line"], row["avg_final_branch"]
                )
            )
        print("-" * 50)
        print("projects                          : {}".format(summary["n_projects"]))
        print("classes                           : {}".format(summary["n_classes"]))
        print(
            "mean of project means (paper)     : {:.2f} line / {:.2f} branch".format(
                summary["mean_of_project_means_line"], summary["mean_of_project_means_branch"]
            )
        )
        print(
            "class-weighted mean (different!)  : {:.2f} line / {:.2f} branch".format(
                summary["class_weighted_line"], summary["class_weighted_branch"]
            )
        )
        if args.output:
            print("wrote          : {} ({} rows)".format(args.output, len(rows)))
        if args.summary_out:
            print("wrote          : {}".format(args.summary_out))
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.label or args.run_dir, args.result_files)
    class_list = _load_class_list(args.class_list)

    run = extract.read_run(
        run_dir,
        class_list,
        prompt_type=args.prompt_type,
        max_iterations=args.max_iterations,
        source=args.source,
        project_names=args.project_names,
        missing=args.fill,
    )

    name = args.name or run_dir.name
    out_dir = Path(args.out_dir)
    class_out = Path(args.class_output) if args.class_output else out_dir / "{}.csv".format(name)
    project_out = (
        Path(args.project_output) if args.project_output else out_dir / "project_{}.csv".format(name)
    )

    class_rows = aggregate.class_level_rows(run.records, args.max_iterations, extended=args.extended)
    aggregate.write_class_level(class_out, class_rows, args.max_iterations, extended=args.extended)

    project_rows = aggregate.project_level_rows(class_rows, extended=args.extended)
    aggregate.write_project_level(project_out, project_rows, extended=args.extended)

    summary = aggregate.overall_summary(project_rows)
    summary_out = Path(args.summary_out) if args.summary_out else out_dir / "summary_{}.csv".format(name)
    aggregate.write_overall_summary(summary_out, summary)

    if not args.quiet:
        _print_run_summary(run, class_list)
        print("wrote          : {} ({} class rows)".format(class_out, len(class_rows)))
        print("wrote          : {} ({} projects)".format(project_out, len(project_rows)))
        print(
            "overall        : {:.2f} line / {:.2f} branch (mean of project means)".format(
                summary["mean_of_project_means_line"], summary["mean_of_project_means_branch"]
            )
        )
        print("wrote          : {}".format(summary_out))

    if args.strict and (run.missing_reports or run.warnings):
        print("STRICT: failing because the run is incomplete or conflicted", file=sys.stderr)
        return 1
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    root = Path(args.result_files) if args.result_files else RESULT_FILES
    if not root.is_dir():
        raise SystemExit("no result-files directory at {}".format(root))

    rows: List[dict] = []
    for directory in sorted(p for p in root.rglob("*") if p.is_dir()):
        reports = list(directory.glob("*_test_results.html"))
        if not reports:
            continue
        meta_path = directory / "run_meta.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        resolved = meta.get("resolved_config", {}) or {}
        run_info = meta.get("run", {}) or {}
        rows.append(
            {
                "label": str(directory.relative_to(root)),
                "reports": len(reports),
                "recorded": bool(meta),
                "study": run_info.get("study"),
                "variant": run_info.get("variant"),
                "model": resolved.get("model") or run_info.get("model"),
                "cs": resolved.get("use_constraints"),
                "bs": resolved.get("use_backward_slice"),
                "repair": resolved.get("fix_type"),
            }
        )

    if not rows:
        print("no result directories with reports under {}".format(root))
        return 0

    print(
        "{:<58}{:>8}{:>9}  {}".format("label", "reports", "recorded", "configuration")
    )
    print("-" * 110)
    for row in rows:
        if row["recorded"]:
            config = "cs={} bs={} fix={!r} variant={}".format(
                row["cs"], row["bs"], row["repair"], row["variant"]
            )
        else:
            # No run_meta.json: the configuration is NOT recoverable from the name.
            config = "(no run_meta.json -- configuration not recorded)"
        print("{:<58}{:>8}{:>9}  {}".format(row["label"], row["reports"], row["recorded"], config))
    print("\n{} run directories".format(len(rows)))
    print(
        "Tip: a directory without run_meta.json predates recorded provenance; "
        "see experiments/legacy_map.yaml for the inferred configuration."
    )
    return 0


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cogpath_eval",
        description="Generate class-level and project-level coverage CSVs from CogPath runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_run_selection(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--label", "-l", help="Run directory label under result-files/")
        sp.add_argument("--run-dir", help="Explicit path to a run directory")
        sp.add_argument("--result-files", help="Override the result-files/ root")
        sp.add_argument("--class-list", help="Work list CSV (default: data/class_list.csv)")
        sp.add_argument("--prompt-type", help="Prompt token in the file names (default: auto)")
        sp.add_argument(
            "--max-iterations", type=int, default=extract.DEFAULT_MAX_ITERATIONS,
            help="How many iteration columns to export (default: %(default)s)",
        )
        sp.add_argument(
            "--source", choices=extract.SOURCES, default=extract.DEFAULT_SOURCE,
            help="Where to read coverage from (default: %(default)s; 'json' is NOT "
                 "comparable to published numbers)",
        )
        sp.add_argument(
            "--project-names", choices=("short", "full"), default="short",
            help="Use the short project label (default, as published) or the full "
                 "subject id such as JacksonDatabind-112f",
        )
        sp.add_argument(
            "--fill", choices=extract.MISSING_POLICIES, default=extract.DEFAULT_MISSING,
            help="What to write for an iteration the run never reached: "
                 "'carry-forward' repeats the final value (default), 'raw' leaves it "
                 "empty (matches the older 3-iteration CSVs in cogpath_results/)",
        )
        sp.add_argument("--quiet", "-q", action="store_true")
        sp.add_argument(
            "--strict", action="store_true",
            help="Exit non-zero if any class is missing or a source conflict was found",
        )

    sp = sub.add_parser("class-level", help="Write the per-class coverage CSV")
    add_run_selection(sp)
    sp.add_argument("--output", "-o", required=True, help="Output CSV path")
    sp.add_argument("--extended", action="store_true", help="Also emit the project_id column")
    sp.set_defaults(func=cmd_class_level)

    sp = sub.add_parser("project-level", help="Aggregate a class-level CSV by project")
    sp.add_argument("--input", "-i", required=True, help="Class-level CSV")
    sp.add_argument("--output", "-o", help="Output project CSV path (optional: prints only)")
    sp.add_argument("--extended", action="store_true", help="Add median columns")
    sp.add_argument("--summary-out", help="Also write the overall summary CSV")
    sp.add_argument("--quiet", "-q", action="store_true")
    sp.set_defaults(func=cmd_project_level)

    sp = sub.add_parser("all", help="Class-level and project-level in one pass")
    add_run_selection(sp)
    sp.add_argument("--out-dir", default=".", help="Directory for the generated CSVs")
    sp.add_argument("--name", help="Base name (default: the run directory name)")
    sp.add_argument("--class-output", help="Override the class-level CSV path")
    sp.add_argument("--project-output", help="Override the project-level CSV path")
    sp.add_argument("--summary-out", help="Override the summary CSV path")
    sp.add_argument("--extended", action="store_true", help="Add median columns to the project CSV")
    sp.set_defaults(func=cmd_all)

    sp = sub.add_parser("runs", help="List result directories and their recorded configuration")
    sp.add_argument("--result-files", help="Override the result-files/ root")
    sp.set_defaults(func=cmd_runs)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except FileNotFoundError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
