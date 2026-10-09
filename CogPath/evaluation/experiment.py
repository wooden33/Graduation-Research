#!/usr/bin/env python3
"""Manifest-driven experiment runner for CogPath.

The problem this replaces
-------------------------
Ablation runs used to be produced by hand-editing ``src/cogpath/config.ini``
between sweeps.  The driver scripts only wrote *some* keys, and their
``fill_config`` *merged* into the existing file, so every unset key silently
inherited whatever the previous run had left behind.  The only record of what
actually ran was the result directory name -- which encodes what was *enabled*
rather than what the paper column means.  Three published columns ended up not
matching their captions as a result.

What this does instead
----------------------
* **Declarative manifests** (``experiments/studies/*.yaml``) name their variants
  after the paper's columns and state every ablation factor explicitly.
* **Resolution** turns ``base + factor levels + model overrides`` into a flat,
  validated configuration -- ``resolve`` prints it, ``run --dry-run`` shows it
  without side effects.
* **No mutation of the tracked config.** Each class gets its own config written
  into the run directory and passed with ``--config``.
* **Provenance** is written by the tool into the result directory, and this
  runner appends a line per class to ``runs_index.jsonl``.
* **``verify``** refuses to let an incomplete run become a paper column.

Usage
-----
    python experiment.py list    --study experiments/studies/rq2_ablation.yaml
    python experiment.py resolve --study experiments/studies/rq2_ablation.yaml \\
                                 --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0
    python experiment.py run     --study experiments/studies/rq2_ablation.yaml \\
                                 --variant cogpath --model ollama/qwen3-coder:30b-a3b-q8_0 --dry-run
    python experiment.py run     --study ... --variant cogpath
    python experiment.py verify  --study experiments/studies/rq2_ablation.yaml
    python experiment.py backfill

See ``experiments/README.md`` for the manifest schema.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
RESULT_FILES = REPO_ROOT / "result-files"
RUNS_INDEX = EVAL_DIR / "runs_index.jsonl"
DEFAULT_DATASET = EVAL_DIR / "data" / "class_list.csv"
STUDIES_DIR = EVAL_DIR / "experiments" / "studies"

# The tool's config/label/provenance helpers are stdlib-only and the package
# resolves its heavy submodules lazily, so these imports stay cheap.
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(EVAL_DIR))

from cogpath.config_validation import (  # noqa: E402
    ConfigError,
    normalise_and_validate,
)
from cogpath.run_label import report_label  # noqa: E402
from subject_config import subject_config  # noqa: E402

# Placeholder subject values so a variant can be validated before any class is
# selected.  They are only ever used for validation, never written to disk.
_PLACEHOLDER_SUBJECT = {
    "project_directory": "<project>",
    "source_code_file": "<source>.java",
    "test_code_file": "<test>.java",
    "code_coverage_report_path": "<project>/target/jacoco/jacoco.csv",
    "test_execution_command": "mvn test",
}

# Keys that describe a *subject* rather than an experiment.  They are resolved per
# class and must not be set in a manifest.
SUBJECT_KEYS = frozenset(_PLACEHOLDER_SUBJECT) | {
    "report_filepath",
    "result_directory",
    "test_file_output_path",
    "test_dependency_command",
    "test_code_command_dir",
    "included_files",
    "junit_version",
    "maximum_iterations",
}

MANIFEST_KEYS = frozenset({"study", "description", "extends", "fixed", "factors", "variants", "models", "dataset", "repetitions"})


# --------------------------------------------------------------------------- #
# Manifest loading and resolution
# --------------------------------------------------------------------------- #


def load_manifest(path: Path) -> Dict[str, Any]:
    """Load a manifest from YAML or JSON."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SystemExit(
                "PyYAML is required to read {}; install it (it is in cogpath-env.yml) "
                "or write the manifest as .json".format(path)
            )
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("Manifest {} must contain a mapping at the top level".format(path))
    unknown = sorted(set(data) - MANIFEST_KEYS)
    if unknown:
        raise SystemExit("Manifest {} has unknown top-level keys: {}".format(path, unknown))
    return data


def load_study(path: Path, _seen: Optional[set] = None) -> Dict[str, Any]:
    """Load a study, merging any ``extends`` chain.

    Later (more specific) manifests win.  ``factors``, ``variants`` and ``models``
    are merged per name rather than replaced wholesale.
    """
    path = path.resolve()
    _seen = _seen or set()
    if path in _seen:
        raise SystemExit("Manifest 'extends' cycle detected at {}".format(path))
    _seen.add(path)

    manifest = load_manifest(path)
    merged: Dict[str, Any] = {
        "study": manifest.get("study") or path.stem,
        "description": manifest.get("description", ""),
        "fixed": {},
        "factors": {},
        "variants": {},
        "models": {},
        "dataset": manifest.get("dataset"),
        "repetitions": manifest.get("repetitions", 1),
    }

    extends = manifest.get("extends")
    if extends:
        parent = load_study((path.parent / extends), _seen)
        for key in ("fixed", "factors", "variants", "models"):
            merged[key].update(parent.get(key) or {})
        if not merged["dataset"]:
            merged["dataset"] = parent.get("dataset")
        if manifest.get("repetitions") is None:
            merged["repetitions"] = parent.get("repetitions", 1)

    for key in ("fixed", "factors", "variants", "models"):
        if manifest.get(key):
            if not isinstance(manifest[key], dict):
                raise SystemExit("`{}` in {} must be a mapping".format(key, path))
            merged[key].update(manifest[key])

    merged["_path"] = str(path)
    return merged


def dataset_path_for(study: Mapping[str, Any], override: Optional[str] = None) -> Path:
    if override:
        return Path(override).resolve()
    if study.get("dataset"):
        candidate = Path(str(study["dataset"]))
        return candidate if candidate.is_absolute() else (EVAL_DIR / candidate).resolve()
    return DEFAULT_DATASET


def resolve_variant(
    study: Mapping[str, Any],
    variant: str,
    model: str,
    dataset_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Resolve ``base + factor levels + model overrides`` into a flat config.

    This is a pure function of the manifest (plus the dataset path), so it can be
    inspected and tested without touching the filesystem or the network.
    """
    variants = study.get("variants") or {}
    factors = study.get("factors") or {}
    models = study.get("models") or {}

    if variant not in variants:
        raise SystemExit(
            "Unknown variant {!r}. Available: {}".format(variant, ", ".join(sorted(variants)))
        )
    if models and model not in models:
        # Not fatal: any litellm model id is allowed, it just has no overrides.
        pass

    cfg: Dict[str, Any] = {}
    cfg.update(study.get("fixed") or {})

    for factor_name, level in (variants[variant] or {}).items():
        if factor_name not in factors:
            raise SystemExit(
                "Variant {!r} sets unknown factor {!r}. Known factors: {}".format(
                    variant, factor_name, ", ".join(sorted(factors))
                )
            )
        levels = factors[factor_name] or {}
        if level not in levels:
            raise SystemExit(
                "Variant {!r}: factor {!r} has no level {!r}. Available: {}".format(
                    variant, factor_name, level, ", ".join(sorted(levels))
                )
            )
        cfg.update(levels[level] or {})

    for key, value in (models.get(model) or {}).items():
        if value is not None:
            cfg[key] = value

    cfg["model"] = model
    if dataset_path is not None:
        cfg["dataset_file"] = str(dataset_path)
    return cfg


def validate_variant(cfg: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Validate a variant-level config by filling placeholder subject values.

    Catches factor typos and contradictions before iterating 130 classes.
    """
    probe = dict(_PLACEHOLDER_SUBJECT)
    probe.update(cfg)
    resolved, warnings = normalise_and_validate(probe)
    # Drop the placeholders again: they are only there to satisfy the schema.
    for key in _PLACEHOLDER_SUBJECT:
        resolved.pop(key, None)
        probe.pop(key, None)
    resolved.pop("test_code_command_dir", None)
    return resolved, warnings


# --------------------------------------------------------------------------- #
# Dataset / class iteration
# --------------------------------------------------------------------------- #


def read_classes(dataset_path: Path) -> List[Dict[str, str]]:
    """Read the class list.

    The shipped CSV has a UTF-8 BOM, so it must be opened with ``utf-8-sig``.
    """
    with open(dataset_path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    out = []
    for row in rows:
        project = row.get("project") or row.get("\ufeffproject")
        if not project:
            continue
        out.append({"project": project, "class": row["class"], "complexity": row["complexity"]})
    return out


def iter_subject_files(dataset: Sequence[Mapping[str, str]]) -> Iterator[Tuple[str, Dict[str, Any], str]]:
    """Yield ``(project, src_file_object, max_complexity)`` for every class."""
    by_project: Dict[str, Dict[str, str]] = {}
    for row in dataset:
        by_project.setdefault(row["project"], {})[row["class"]] = row["complexity"]

    for project, classmap in by_project.items():
        index = EVAL_DIR / "defects4j-codefiles" / "{}-codefiles.json".format(project)
        if not index.exists():
            print("  ! missing index {}, skipping {} classes".format(index.name, len(classmap)))
            continue
        with open(index, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        objects = (
            data.get("src_test_exact_match", [])
            + data.get("src_test_fuzz_match", [])
            + data.get("src_without_tests", [])
        )
        for src_file in objects:
            name = src_file.get("src_name")
            if name in classmap:
                yield project, src_file, classmap[name]


# --------------------------------------------------------------------------- #
# Run index
# --------------------------------------------------------------------------- #


def append_index(entries: Iterable[Mapping[str, Any]]) -> int:
    RUNS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(RUNS_INDEX, "a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
            count += 1
    return count


def read_index() -> List[Dict[str, Any]]:
    if not RUNS_INDEX.exists():
        return []
    out = []
    with open(RUNS_INDEX, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_list(args: argparse.Namespace) -> int:
    study = load_study(Path(args.study))
    print("study      : {}".format(study["study"]))
    print("manifest   : {}".format(study["_path"]))
    if study.get("description"):
        print("description: {}".format(study["description"]))
    print("dataset    : {}".format(dataset_path_for(study, args.dataset)))
    print("\nfactors:")
    for name, levels in sorted((study.get("factors") or {}).items()):
        print("  {:22s} {}".format(name, ", ".join(sorted(levels))))
    print("\nvariants:")
    for name, spec in sorted((study.get("variants") or {}).items()):
        rendered = "  ".join("{}={}".format(k, v) for k, v in sorted(spec.items()))
        print("  {:22s} {}".format(name, rendered))
    print("\nmodels:")
    for name in sorted((study.get("models") or {})):
        print("  {}".format(name))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    study = load_study(Path(args.study))
    dataset = dataset_path_for(study, args.dataset)
    cfg = resolve_variant(study, args.variant, args.model, dataset)
    try:
        resolved, warnings = validate_variant(cfg)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = {
        "study": study["study"],
        "variant": args.variant,
        "model": args.model,
        "report_label": report_label(resolved),
        "result_root": str(RESULT_FILES / "runs" / _safe_slug(study["study"])),
        "config": resolved,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    for warning in warnings:
        print("WARNING: {}".format(warning), file=sys.stderr)
    return 0


def _write_config(path: Path, cfg: Mapping[str, Any]) -> None:
    parser = configparser.ConfigParser()
    parser["default"] = {k: ("" if v is None else str(v)) for k, v in cfg.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", str(value)).strip("-.")
    return slug or "item"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-{}".format(os.getpid()))
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def _copy_workspace_project(project: str, project_dir: str, run_dir: Path) -> Path:
    """Create one clean, run-local copy of a Defects4J project."""
    workspace = run_dir / "workspaces" / _safe_slug(project)
    if workspace.exists():
        return workspace
    source = (REPO_ROOT / project_dir).resolve()
    if not source.is_dir():
        raise FileNotFoundError("subject project directory not found: {}".format(source))
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        str(source), str(workspace),
        ignore=shutil.ignore_patterns(".git", "target", "*.class", ".idea", ".DS_Store", "*_backup"),
    )
    return workspace


def _remap_to_workspace(value: str, original_project_dir: str, workspace: Path) -> str:
    original_root = (REPO_ROOT / original_project_dir).resolve()
    original_path = Path(value)
    if not original_path.is_absolute():
        original_path = REPO_ROOT / original_path
    relative = original_path.resolve().relative_to(original_root)
    return str(workspace / relative)


def _prepare_task_snapshot(test_path: Path, task_dir: Path) -> Dict[str, Any]:
    """Save a task's original test file once and restore it before each attempt."""
    snapshot_path = task_dir / "input-test.snapshot"
    metadata_path = task_dir / "input-test.json"
    if not metadata_path.exists():
        existed = test_path.is_file()
        if existed:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(test_path), str(snapshot_path))
        metadata = {"path": str(test_path), "existed": existed}
        _atomic_json(metadata_path, metadata)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata["existed"]:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(snapshot_path), str(test_path))
    elif test_path.exists():
        test_path.unlink()
    return metadata


def cmd_run(args: argparse.Namespace) -> int:
    study = load_study(Path(args.study))
    dataset_path = dataset_path_for(study, args.dataset)
    dataset = read_classes(dataset_path)
    if not dataset:
        print("No classes in {}".format(dataset_path), file=sys.stderr)
        return 2

    variants = args.variant or sorted(study.get("variants") or {})
    models = args.model or sorted(study.get("models") or {})
    if not variants:
        print("No variants selected", file=sys.stderr)
        return 2
    if not models:
        print("No models selected (pass --model or list them in the manifest)", file=sys.stderr)
        return 2

    repetitions = args.repeat if args.repeat is not None else int(study.get("repetitions", 1))
    if repetitions < 1:
        print("Repetition count must be at least 1", file=sys.stderr)
        return 2

    planned: List[Tuple[str, str, int]] = [
        (variant, model, repetition)
        for variant in variants
        for model in models
        for repetition in range(repetitions)
    ]

    if (args.resume or args.run_dir) and len(planned) != 1:
        print("--resume/--run-dir requires exactly one variant/model/repetition combination", file=sys.stderr)
        return 2
    if args.resume and args.run_dir:
        print("Use either --resume or --run-dir, not both", file=sys.stderr)
        return 2

    indexed_tasks = list(iter_subject_files(dataset))
    indexed_keys = {"{}::{}".format(project, row["src_name"]) for project, row, _ in indexed_tasks}
    dataset_keys = {"{}::{}".format(row["project"], row["class"]) for row in dataset}
    if indexed_keys != dataset_keys:
        missing = sorted(dataset_keys - indexed_keys)
        print("Dataset/index mismatch: {} class(es) missing from subject indexes".format(len(missing)), file=sys.stderr)
        if missing:
            print("  missing examples: {}".format(", ".join(missing[:8])), file=sys.stderr)
        return 2

    print("study   : {}".format(study["study"]))
    print("dataset : {} ({} classes)".format(dataset_path, len(dataset)))
    print("plan    : {} variant/model/repetition combination(s)".format(len(planned)))

    total_ran = 0
    any_failed = False
    for variant, model, repetition in planned:
        raw_cfg = resolve_variant(study, variant, model, dataset_path)
        if args.prompt_type:
            raw_cfg["prompt_type"] = args.prompt_type
        if args.solver_model:
            raw_cfg["solver_model"] = args.solver_model
        try:
            validated, warnings = validate_variant(raw_cfg)
        except ConfigError as exc:
            print("\n[{} / {}] INVALID CONFIG".format(variant, model), file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 2

        prompt_type = str(validated.get("prompt_type", "control"))
        label = report_label(validated)
        selected_tasks = indexed_tasks[:args.limit] if args.limit else indexed_tasks
        identity = {
            "study": study["study"], "variant": variant, "model": model,
            "repetition": repetition,
            "manifest_sha256": _sha256(Path(study["_path"])),
            "dataset_sha256": _sha256(dataset_path),
            "resolved_config": validated,
            "planned_tasks": ["{}::{}".format(p, s["src_name"]) for p, s, _ in selected_tasks],
        }
        identity_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        if args.resume:
            run_dir = Path(args.resume).expanduser().resolve()
            run_json = run_dir / "run.json"
            if not run_json.is_file():
                print("No run.json found in resume directory: {}".format(run_dir), file=sys.stderr)
                return 2
            run_metadata = json.loads(run_json.read_text(encoding="utf-8"))
            if run_metadata.get("identity_sha256") != identity_hash:
                print("Resume configuration does not match this run; refusing to mix results", file=sys.stderr)
                return 2
        else:
            if args.run_dir:
                run_dir = Path(args.run_dir).expanduser().resolve()
            else:
                timestamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "{:06d}Z".format(
                    int(time.time() * 1000000) % 1000000
                )
                run_id = timestamp
                run_dir = (
                    RESULT_FILES / "runs" / _safe_slug(study["study"])
                    / _safe_slug(model) / _safe_slug(variant)
                    / "rep-{:03d}".format(repetition + 1) / run_id
                )
            if not args.dry_run:
                if run_dir.exists():
                    print("Run directory already exists; use --resume to continue it: {}".format(run_dir), file=sys.stderr)
                    return 2
                run_dir.mkdir(parents=True, exist_ok=False)
                shutil.copy2(study["_path"], run_dir / Path(study["_path"]).name)
                shutil.copy2(dataset_path, run_dir / "class_list.csv")
                _atomic_json(run_dir / "resolved-config.json", {
                    "study": study["study"], "variant": variant,
                    "model": model, "repetition": repetition, "config": validated,
                })
            run_metadata = {
                "schema_version": 1, "run_id": run_dir.name, "status": "planned",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "identity_sha256": identity_hash, "identity": identity,
                "report_label_legacy": label, "planned_count": len(selected_tasks),
                "completed_count": 0, "failed_count": 0,
            }
            if not args.dry_run:
                _atomic_json(run_dir / "run.json", run_metadata)

        print("\n=== {} / {} (repetition {}) ===".format(variant, model, repetition))
        print("  run dir    : {}".format(run_dir))
        print("  task count : {}".format(len(selected_tasks)))
        for warning in warnings:
            print("  WARNING: {}".format(warning))

        done = skipped = failed = 0
        if args.dry_run:
            for project, src_file, _ in selected_tasks:
                print("  [dry-run] {} :: tasks/{}/{}".format(
                    project, _safe_slug(project), _safe_slug(src_file["src_name"])
                ))
            continue

        run_metadata["status"] = "running"
        run_metadata["last_started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_json(run_dir / "run.json", run_metadata)

        for task_index, (project, src_file, max_cc) in enumerate(selected_tasks, start=1):
            class_name = src_file["src_name"]
            class_cfg = subject_config(
                src_file, project, max_cc, prompt_type,
            )
            class_cfg.update(validated)
            if "maximum_iterations" not in raw_cfg:
                # Historical behaviour: each class's iteration budget was its own
                # cyclomatic complexity, not a uniform value.  A manifest that sets
                # `maximum_iterations` (base.yaml does: 20, as the paper states)
                # overrides this, so the two protocols never mix silently.
                class_cfg["maximum_iterations"] = int(max_cc)
            task_dir = run_dir / "tasks" / _safe_slug(project) / _safe_slug(class_name)
            task_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir = task_dir / "artifacts"
            project_dir_rel = class_cfg["project_directory"]
            workspace = _copy_workspace_project(project, project_dir_rel, run_dir)
            for key in ("source_code_file", "test_code_file", "code_coverage_report_path"):
                class_cfg[key] = _remap_to_workspace(class_cfg[key], project_dir_rel, workspace)
            class_cfg["project_directory"] = str(workspace)
            class_cfg["test_code_command_dir"] = str(workspace)
            class_cfg["dataset_file"] = str(run_dir / "class_list.csv")
            report_file = class_cfg.get("report_filepath") or "{}_{}_test_results.html".format(
                class_name, prompt_type
            )
            state_path = task_dir / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
            previous_report = Path(state["report_path"]) if state.get("report_path") else None
            if (
                state.get("status") == "completed"
                and state.get("exit_code") == 0
                and previous_report is not None
                and previous_report.is_file()
                and not args.force
            ):
                skipped += 1
                print("  [{}/{}] skip {} ({})".format(task_index, len(selected_tasks), class_name, project))
                continue

            try:
                full_cfg, _ = normalise_and_validate(class_cfg)
            except ConfigError as exc:
                print("  ! {} has an invalid config:".format(class_name), file=sys.stderr)
                print(str(exc), file=sys.stderr)
                failed += 1
                continue

            attempt_number = int(state.get("attempt", 0)) + 1
            attempt_dir = task_dir / "attempts" / "{:03d}".format(attempt_number)
            artifacts_dir = attempt_dir / "artifacts"
            full_cfg["result_directory"] = str(artifacts_dir)
            full_cfg["provenance_file"] = str(attempt_dir / "provenance.json")
            config_file = attempt_dir / "config.ini"
            _prepare_task_snapshot(Path(full_cfg["test_code_file"]), task_dir)
            _write_config(config_file, full_cfg)
            task_state = {
                "project": project, "class": class_name, "status": "running",
                "attempt": attempt_number,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "config": str(config_file), "artifacts": str(artifacts_dir),
                "report_file": report_file, "report_path": str(artifacts_dir / report_file),
            }
            _atomic_json(state_path, task_state)
            started = time.time()
            print("  [{}/{}] run {} ({})".format(task_index, len(selected_tasks), class_name, project), flush=True)
            try:
                child_env = os.environ.copy()
                source_path = str(REPO_ROOT / "src")
                existing_pythonpath = child_env.get("PYTHONPATH", "")
                child_env["PYTHONPATH"] = source_path + (
                    os.pathsep + existing_pythonpath if existing_pythonpath else ""
                )
                child_env["COGPATH_LLM_USAGE_LOG"] = str(attempt_dir / "token-usage.jsonl")
                with open(attempt_dir / "stdout.log", "w", encoding="utf-8") as stdout_log, open(
                    attempt_dir / "stderr.log", "w", encoding="utf-8"
                ) as stderr_log:
                    proc = subprocess.run(
                        [sys.executable, "-m", "cogpath.main", "--config", str(config_file)],
                        cwd=str(REPO_ROOT), env=child_env,
                        stdout=stdout_log, stderr=stderr_log, text=True,
                    )
            except KeyboardInterrupt:
                task_state.update({
                    "status": "interrupted",
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
                _atomic_json(state_path, task_state)
                run_metadata.update({
                    "status": "interrupted",
                    "interrupted_task": "{}::{}".format(project, class_name),
                })
                _atomic_json(run_dir / "run.json", run_metadata)
                print("\nInterrupted. Resume with --resume {}".format(run_dir), file=sys.stderr)
                return 130

            if not args.quiet:
                stdout_text = (attempt_dir / "stdout.log").read_text(encoding="utf-8")
                stderr_text = (attempt_dir / "stderr.log").read_text(encoding="utf-8")
                if stdout_text:
                    print(stdout_text, end="" if stdout_text.endswith("\n") else "\n")
                if stderr_text:
                    print(stderr_text, end="" if stderr_text.endswith("\n") else "\n", file=sys.stderr)
            duration = round(time.time() - started, 2)
            report_path = artifacts_dir / report_file
            success = proc.returncode == 0 and report_path.is_file()
            task_state.update({
                "status": "completed" if success else "failed",
                "exit_code": proc.returncode,
                "report_exists": report_path.is_file(),
                "duration_s": duration,
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            summary_path = report_path.with_name(report_path.stem + "_run_summary.json")
            if summary_path.is_file():
                try:
                    task_state["metrics"] = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            _atomic_json(state_path, task_state)
            if not success:
                failed += 1
                print("  -> FAILED (exit {}, report {})".format(proc.returncode, report_path.is_file()))
            else:
                done += 1
            run_metadata["completed_count"] = done + skipped
            run_metadata["failed_count"] = failed
            _atomic_json(run_dir / "run.json", run_metadata)

        total_ran += done
        any_failed = any_failed or bool(failed)
        run_metadata["status"] = "completed" if done + skipped == len(selected_tasks) and not failed else "failed"
        run_metadata["completed_count"] = done + skipped
        run_metadata["failed_count"] = failed
        run_metadata["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_json(run_dir / "run.json", run_metadata)
        print(
            "\n  summary: completed={} skipped={} failed={}  run={}".format(
                done, skipped, failed, run_dir
            )
        )

    print("\nTotal classes run: {}".format(total_ran))
    return 1 if any_failed else 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Completeness gate: every planned class must have a result."""
    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        run_json = run_dir / "run.json"
        if not run_json.is_file():
            print("No run.json found in {}".format(run_dir), file=sys.stderr)
            return 2
        metadata = json.loads(run_json.read_text(encoding="utf-8"))
        expected = metadata.get("identity", {}).get("planned_tasks", [])
        incomplete = []
        for key in expected:
            project, class_name = key.split("::", 1)
            state_path = run_dir / "tasks" / _safe_slug(project) / _safe_slug(class_name) / "state.json"
            if not state_path.is_file():
                incomplete.append((key, "not started"))
                continue
            state = json.loads(state_path.read_text(encoding="utf-8"))
            report = Path(state.get("report_path", "")) if state.get("report_path") else None
            if state.get("status") != "completed" or state.get("exit_code") != 0 or report is None or not report.is_file():
                incomplete.append((key, state.get("status", "unknown")))
        print("run dir : {}".format(run_dir))
        print("status  : {}".format(metadata.get("status", "unknown")))
        print("tasks   : {}/{} complete".format(len(expected) - len(incomplete), len(expected)))
        if incomplete:
            for key, status in incomplete[:10]:
                print("  incomplete: {} ({})".format(key, status))
            if len(incomplete) > 10:
                print("  ... and {} more".format(len(incomplete) - 10))
            return 1
        return 0

    if not args.study:
        print("--study is required when --run-dir is not supplied", file=sys.stderr)
        return 2
    study = load_study(Path(args.study))
    dataset_path = dataset_path_for(study, args.dataset)
    dataset = read_classes(dataset_path)
    expected = {"{}::{}".format(row["project"], row["class"]) for row in dataset}

    variants = args.variant or sorted(study.get("variants") or {})
    models = args.model or sorted(study.get("models") or {})
    repetitions = args.repeat if args.repeat is not None else int(study.get("repetitions", 1))

    if not models:
        # Without this guard an empty model list would make every check below a
        # no-op and print a vacuous "VERIFY OK".
        print(
            "No models to verify: pass --model, or list the models under `models:` "
            "in the manifest.",
            file=sys.stderr,
        )
        return 2

    print("study    : {}".format(study["study"]))
    print("expected : {} classes per variant/model".format(len(expected)))

    incomplete = 0
    for variant in variants:
        for model in models:
            for repetition in range(repetitions):
                cfg = resolve_variant(study, variant, model, dataset_path)
                validated, _ = validate_variant(cfg)
                run_dir = RESULT_FILES / report_label(validated)
                if not run_dir.exists():
                    print("\n  MISSING  {} / {} rep{}: no directory {}".format(
                        variant, model, repetition, run_dir))
                    incomplete += 1
                    continue

                present = set()
                for html in run_dir.glob("*.html"):
                    stem = html.stem
                    for row in dataset:
                        if stem.startswith(row["class"] + "_"):
                            present.add("{}::{}".format(row["project"], row["class"]))
                            break

                missing = expected - present
                status = "OK      " if not missing else "PARTIAL "
                print("\n  {}{} / {} rep{}: {}/{} classes".format(
                    status, variant, model, repetition, len(present), len(expected)))
                if missing:
                    incomplete += 1
                    sample = sorted(missing)[:5]
                    print("           missing {} e.g. {}".format(len(missing), ", ".join(sample)))

    if incomplete:
        print("\nVERIFY FAILED: {} incomplete run(s). Do not publish these numbers.".format(incomplete))
        return 1
    print("\nVERIFY OK: every planned run is complete.")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Record provenance for existing result trees, marking it as inferred."""
    mapping_path = Path(args.legacy_map or (EVAL_DIR / "experiments" / "legacy_map.yaml"))
    if not mapping_path.exists():
        print("No legacy map at {}".format(mapping_path), file=sys.stderr)
        return 2
    if mapping_path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            print("PyYAML is required to read {}".format(mapping_path), file=sys.stderr)
            return 2
        spec = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    else:
        spec = json.loads(mapping_path.read_text(encoding="utf-8"))

    runs = spec.get("runs") or []
    entries: List[Dict[str, Any]] = []
    mapped_dirs = set()
    for run in runs:
        rel = str(run.get("dir", "")).strip("/")
        run_dir = RESULT_FILES / rel
        mapped_dirs.add(rel)
        if not run_dir.exists():
            print("  ! mapped directory does not exist: {}".format(run_dir))
            continue
        classes = sorted(p.stem for p in run_dir.glob("*.html"))
        print("  {} -> {} ({} reports)".format(rel, run.get("variant", "?"), len(classes)))
        for stem in classes:
            entries.append(
                {
                    "study": run.get("study", "legacy"),
                    "variant": run.get("variant"),
                    "model": run.get("model"),
                    "repetition": run.get("repetition", 0),
                    "class": stem.split("_")[0],
                    "project": run.get("project"),
                    "report_label": rel,
                    "result_dir": str(run_dir),
                    "report_file": stem + ".html",
                    "exit_code": None,
                    "status": "unknown",
                    "finished_at": None,
                    "provenance": "inferred",
                    "note": run.get("note", ""),
                }
            )

    unmapped = []
    for candidate in sorted(RESULT_FILES.rglob("*")):
        if candidate.is_dir() and any(candidate.glob("*.html")):
            rel = str(candidate.relative_to(RESULT_FILES))
            if not any(rel == d or rel.startswith(d + "/") for d in mapped_dirs):
                unmapped.append(rel)

    if entries and not args.dry_run:
        append_index(entries)

    print("\nmapped entries: {} ({})".format(len(entries), "written" if not args.dry_run else "dry-run"))
    if unmapped:
        print("unmapped result directories ({}):".format(len(unmapped)))
        for rel in unmapped[:20]:
            print("  - {}".format(rel))
        if len(unmapped) > 20:
            print("  ... and {} more".format(len(unmapped) - 20))
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--study", "-s", required=True, help="Path to a study manifest")
        sp.add_argument("--variant", "-v", action="append", help="Variant name (repeatable)")
        sp.add_argument("--model", "-m", action="append", help="Model id (repeatable)")
        sp.add_argument("--dataset", "-d", default=None, help="Override the class list CSV")
        sp.add_argument("--repeat", type=int, default=None, help="Override the repetition count")

    sp = sub.add_parser("list", help="Describe a study without running anything")
    sp.add_argument("--study", "-s", required=True)
    sp.add_argument("--dataset", "-d", default=None)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("resolve", help="Print the resolved config for one variant")
    sp.add_argument("--study", "-s", required=True)
    sp.add_argument("--variant", "-v", required=True)
    sp.add_argument("--model", "-m", required=True)
    sp.add_argument("--dataset", "-d", default=None)
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("run", help="Run one or more variants")
    add_common(sp)
    sp.add_argument("--dry-run", action="store_true", help="Show what would run, change nothing")
    sp.add_argument("--limit", type=int, default=None, help="Stop after N classes (smoke test)")
    sp.add_argument("--force", action="store_true", help="Re-run classes that already have results")
    sp.add_argument("--run-dir", default=None, help="Create this run directory (one configuration only)")
    sp.add_argument("--resume", default=None, help="Resume an existing run directory after identity validation")
    sp.add_argument("--prompt-type", default=None, help="Override the manifest prompt type")
    sp.add_argument("--solver-model", default=None, help="Override the Constraint-Hints model")
    sp.add_argument("--quiet", action="store_true", help="Capture the tool's stdout/stderr")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("verify", help="Completeness gate: fail if any planned class is missing")
    sp.add_argument("--study", "-s", required=False, help="Study manifest for legacy verification")
    sp.add_argument("--variant", "-v", action="append")
    sp.add_argument("--model", "-m", action="append")
    sp.add_argument("--dataset", "-d", default=None)
    sp.add_argument("--repeat", type=int, default=None)
    sp.add_argument("--run-dir", default=None, help="Verify one run directory created by `run`")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("backfill", help="Record provenance for existing result trees")
    sp.add_argument("--legacy-map", default=None)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_backfill)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
