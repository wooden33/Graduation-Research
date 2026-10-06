"""Run provenance for CogPath.

Every run now writes a small, self-describing record next to its results::

    result-files/<report_label>/
    ├── config.resolved.json   # the effective configuration, exactly as used
    ├── run_meta.json          # how/where/when it ran, and what it depended on
    └── run_summary.json       # what it produced

Why this exists
---------------
The only provenance CogPath used to emit was the *result directory name*, which
is composed from the runtime flags (``cogpath.py``).  That name is ambiguous
(the suffix records what was *enabled*, not what the paper column means) and it
is not a record: two runs with the same flags are indistinguishable, and the
config file itself is mutated in place by the evaluation harness, so the
configuration behind a given result could not be recovered afterwards.

Writing the resolved configuration and its dependencies into the result
directory makes each run independently auditable, and lets the evaluation
pipeline read metadata instead of inferring it from directory names.

Everything here is best-effort: a provenance failure must never break a run.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

RESOLVED_CONFIG_NAME = "config.resolved.json"
RUN_META_NAME = "run_meta.json"
RUN_SUMMARY_SUFFIX = "_run_summary.json"

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Any) -> Optional[str]:
    """Hash a file, or return ``None`` if it is not readable."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(path: Any, payload: Mapping[str, Any]) -> bool:
    """Write JSON via a temp file + rename so a reader never sees a partial file."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
        )
        try:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Environment / dependency capture
# --------------------------------------------------------------------------- #


def git_info(repo_dir: Any = None) -> Dict[str, Any]:
    """Capture the commit and dirty state of the checkout that produced a run."""
    repo = str(repo_dir or _REPO_ROOT)
    info: Dict[str, Any] = {"repo": repo, "commit": None, "branch": None, "dirty": None}

    def _git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", "-C", repo, *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode != 0:
                return None
            return out.stdout.strip()
        except Exception:
            return None

    info["commit"] = _git("rev-parse", "HEAD")
    info["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
    status = _git("status", "--porcelain")
    if status is not None:
        info["dirty"] = bool(status)
        if status:
            # Keep the record small but useful.
            info["dirty_files"] = status.splitlines()[:50]
    return info


def package_versions() -> Dict[str, Optional[str]]:
    """Versions of the packages whose behaviour affects results."""
    from importlib import metadata

    versions: Dict[str, Optional[str]] = {}
    for name in ("litellm", "openai", "jinja2", "dynaconf", "numpy", "tree-sitter", "PyYAML"):
        try:
            versions[name] = metadata.version(name)
        except Exception:
            versions[name] = None
    return versions


def prompt_template_hashes() -> Dict[str, Optional[str]]:
    """Hash every shipped prompt template.

    Prompts are data, and editing one changes results without changing any code,
    so their hashes belong in the run record.
    """
    base = Path(__file__).resolve().parent / "prompt_templates"
    hashes: Dict[str, Optional[str]] = {}
    try:
        for path in sorted(base.rglob("*.toml")):
            hashes[str(path.relative_to(base))] = sha256_file(path)
    except Exception:
        pass
    return hashes


def dataset_info(dataset_path: Any) -> Dict[str, Any]:
    info: Dict[str, Any] = {"path": str(dataset_path), "sha256": None, "n_rows": None}
    info["sha256"] = sha256_file(dataset_path)
    try:
        with open(dataset_path, "r", encoding="utf-8-sig") as handle:
            info["n_rows"] = max(0, sum(1 for _ in handle) - 1)  # minus header
    except OSError:
        pass
    return info


def environment_info() -> Dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": package_versions(),
    }


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


def build_run_meta(
    config: Mapping[str, Any],
    extra: Optional[Mapping[str, Any]] = None,
    dataset_path: Any = None,
) -> Dict[str, Any]:
    """Assemble the run record.

    Args:
        config: the effective (validated) configuration.
        extra: runner-supplied identity, e.g. ``study``/``variant``/``model``.
        dataset_path: class list used by the run, if any.
    """
    resolved = {k: config[k] for k in sorted(config)}
    meta: Dict[str, Any] = {
        "cogpath_run_meta_version": 1,
        "generated_at": utc_now(),
        "resolved_config": resolved,
        "config_hash": sha256_text(json.dumps(resolved, sort_keys=True, default=str)),
        "git": git_info(),
        "environment": environment_info(),
        "prompt_template_hashes": prompt_template_hashes(),
    }
    if dataset_path:
        meta["dataset"] = dataset_info(dataset_path)
    if extra:
        meta["run"] = {k: extra[k] for k in sorted(extra)}
    return meta


def read_extra_meta(provenance_file: Optional[str]) -> Dict[str, Any]:
    """Read the runner-supplied metadata blob, tolerating absence or corruption."""
    if not provenance_file:
        return {}
    try:
        with open(provenance_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_run_provenance(
    report_dir: Any,
    config: Mapping[str, Any],
    provenance_file: Optional[str] = None,
    dataset_path: Any = None,
) -> Dict[str, str]:
    """Write ``config.resolved.json`` and ``run_meta.json`` into a result directory.

    Returns a mapping of artefact name to the path written (empty on failure).
    """
    written: Dict[str, str] = {}
    try:
        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        extra = read_extra_meta(provenance_file)
        meta = build_run_meta(config, extra=extra, dataset_path=dataset_path)
        resolved = meta["resolved_config"]

        resolved_path = report_dir / RESOLVED_CONFIG_NAME
        meta_path = report_dir / RUN_META_NAME

        if write_json_atomic(resolved_path, resolved):
            written[RESOLVED_CONFIG_NAME] = str(resolved_path)
        if write_json_atomic(meta_path, meta):
            written[RUN_META_NAME] = str(meta_path)
    except Exception:
        # Provenance is diagnostics, never a reason to lose a run.
        pass
    return written


def summarise_results(test_results: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Derive pass/fail/token totals from the per-test result list."""
    summary = {
        "tests_total": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_info": 0,
        "failures_by_reason": {},
        # INFO rows carry the token count in `exit_code` (see cogpath.py).
        "tokens_total": 0,
    }
    reasons: Dict[str, int] = {}
    for result in test_results or []:
        status = str(result.get("status", "")).upper()
        if status == "INFO":
            summary["tests_info"] += 1
            # INFO rows carry the token count in `exit_code` (see cogpath.py).
            try:
                summary["tokens_total"] += int(result.get("exit_code") or 0)
            except (TypeError, ValueError):
                pass
            continue
        summary["tests_total"] += 1
        if status == "PASS":
            summary["tests_passed"] += 1
        else:
            summary["tests_failed"] += 1
            reason = str(result.get("reason", "") or "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
    summary["failures_by_reason"] = reasons
    return summary


def write_run_summary(
    report_dir: Any,
    stem: str,
    test_results: List[Mapping[str, Any]],
    coverage: Optional[Mapping[str, Any]] = None,
    iterations: Optional[int] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """Write ``<stem>_run_summary.json`` into a result directory.

    One result directory holds every class of a configuration, so the summary is
    named after the report it belongs to -- a single ``run_summary.json`` would be
    overwritten by each successive class.
    """
    written: Dict[str, str] = {}
    try:
        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = {
            "cogpath_run_summary_version": 1,
            "generated_at": utc_now(),
            "report": stem,
            "iterations": iterations,
        }
        payload.update(summarise_results(test_results))
        if coverage:
            payload["coverage"] = dict(coverage)
        if extra:
            payload["extra"] = {k: extra[k] for k in sorted(extra)}
        name = "{}{}".format(stem, RUN_SUMMARY_SUFFIX) if stem else "run_summary.json"
        path = report_dir / name
        if write_json_atomic(path, payload):
            written[name] = str(path)
    except Exception:
        pass
    return written
