#!/usr/bin/env python3
"""Run one OpenHands test-generation case against an isolated Defects4J subject.

This is intentionally a one-case adapter, not a batch evaluation driver. It
copies the Maven subject into a run directory, lets OpenHands work only there,
then performs a final Maven/JaCoCo measurement and stores all raw logs.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


EVAL_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = EVAL_DIR.parent
SUBJECTS_DIR = REPO_DIR / "defects4j-subjects-notests"
CODEFILES_DIR = EVAL_DIR / "defects4j-codefiles"
PROFILE_FILE = REPO_DIR / "src" / "cogpath" / "model_profiles.ini"
LOCAL_PROFILE_FILE = REPO_DIR / "src" / "cogpath" / "model_profiles.local.ini"


def _model_profile(alias: str) -> Dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read([str(PROFILE_FILE), str(LOCAL_PROFILE_FILE)], encoding="utf-8")
    if not parser.has_section(alias):
        raise ValueError("Unknown model profile {!r} in {}".format(alias, PROFILE_FILE))
    section = parser[alias]
    env_name = section.get("api_key_env", "").strip()
    api_key = section.get("api_key", "").strip()
    if not api_key and env_name:
        api_key = os.environ.get(env_name, "")
    if not api_key:
        raise ValueError(
            "Profile {!r} needs api_key or a valid api_key_env setting".format(alias)
        )
    raw_params = section.get("litellm_params", "").strip()
    try:
        litellm_params = json.loads(raw_params) if raw_params else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid litellm_params for profile {!r}: {}".format(alias, exc))
    if not isinstance(litellm_params, dict):
        raise ValueError("litellm_params for profile {!r} must be a JSON object".format(alias))
    return {
        "alias": alias,
        "model": section.get("model", "").strip(),
        "base_url": section.get("api_base", "").strip(),
        "api_key_env": env_name,
        "api_key": api_key,
        "litellm_params": litellm_params,
    }


def _find_class(project: str, class_name: str) -> Dict[str, Any]:
    index = CODEFILES_DIR / "{}-codefiles.json".format(project)
    if not index.is_file():
        raise ValueError("No source index for project {}: {}".format(project, index))
    data = json.loads(index.read_text(encoding="utf-8"))
    for group in ("src_test_exact_match", "src_test_fuzz_match", "src_without_tests"):
        for item in data.get(group, []):
            if item.get("src_name") == class_name:
                return item
    raise ValueError("Class {!r} not found in project {}".format(class_name, project))


def _subject_paths(project: str, item: Dict[str, Any]) -> Tuple[Path, Path, Path]:
    project_dir = SUBJECTS_DIR / project
    if project == "Gson-16f":
        project_dir = project_dir / "gson"
    source_name = str(item["src_path"]).replace(
        "defects4j-subjects", "defects4j-subjects-notests"
    ).lstrip("../")
    source = (REPO_DIR / source_name).resolve()
    # Preserve the dataset's known source-layout exceptions.
    source_rel = source.relative_to(project_dir.resolve())
    parts = source_rel.parts
    if project == "JxPath-22f":
        if len(parts) < 4 or parts[:2] != ("src", "java"):
            raise ValueError("Unexpected JXPath source path: {}".format(source))
        test_rel = Path("src/test") / Path(*parts[2:-1]) / (str(item["src_name"]) + "Test.java")
    else:
        if len(parts) < 5 or parts[:3] != ("src", "main", "java"):
            raise ValueError("Unexpected source layout: {}".format(source))
        test_rel = Path("src/test/java") / Path(*parts[3:-1]) / (str(item["src_name"]) + "Test.java")
    return project_dir, source, project_dir / test_rel


def _task_text(project: str, class_name: str, source_rel: Path, test_rel: Path) -> str:
    test_class = test_rel.stem
    return """Create a JUnit 4 test suite for the Java class under test.

Project: {project}
Focal class: {source}
Required test file: {test}
Test class name: {test_class}

Goal: maximize line and branch coverage of the focal class with executable tests.
Work only in the required test file. Do not modify production sources, pom.xml,
build scripts, or other existing tests. Inspect the focal class and relevant
project APIs, then create the initial test suite promptly; avoid broad searches
through unrelated files. Add focused tests for distinct behaviors and edge cases.
Run the following command from this project root to compile and execute your
test and generate JaCoCo coverage, then inspect the focal class row in
target/jacoco/jacoco.csv and revise tests to cover feasible missed branches:

    mvn clean package -Dtest={test_class}

Do not claim success unless the command completes successfully. Keep the final
test self-contained and compatible with this project's existing dependencies.
""".format(project=project, source=source_rel.as_posix(), test=test_rel.as_posix(), test_class=test_class)


def _jacoco_metrics(report: Path, class_name: str) -> Dict[str, Any]:
    if not report.is_file():
        return {"jacoco_csv": str(report), "found": False}
    matches = []
    with report.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("CLASS") == class_name:
                matches.append(row)
    if not matches:
        return {"jacoco_csv": str(report), "found": False}
    totals = {key: sum(int(row[key]) for row in matches) for key in (
        "LINE_MISSED", "LINE_COVERED", "BRANCH_MISSED", "BRANCH_COVERED"
    )}
    line_total = totals["LINE_MISSED"] + totals["LINE_COVERED"]
    branch_total = totals["BRANCH_MISSED"] + totals["BRANCH_COVERED"]
    totals.update({
        "jacoco_csv": str(report),
        "found": True,
        "line_coverage": 100.0 * totals["LINE_COVERED"] / line_total if line_total else 0.0,
        "branch_coverage": 100.0 * totals["BRANCH_COVERED"] / branch_total if branch_total else 0.0,
    })
    return totals


def _surefire_metrics(project_dir: Path, test_class: str) -> Dict[str, Any]:
    reports = list((project_dir / "target" / "surefire-reports").glob("TEST-*.xml"))
    found = []
    for report in reports:
        try:
            root = ET.parse(str(report)).getroot()
        except ET.ParseError:
            continue
        if root.get("name", "").endswith("." + test_class) or root.get("name") == test_class:
            found.append(root)
    if not found:
        return {"report_found": False}
    return {
        "report_found": True,
        "tests": sum(int(node.get("tests", 0)) for node in found),
        "failures": sum(int(node.get("failures", 0)) for node in found),
        "errors": sum(int(node.get("errors", 0)) for node in found),
        "skipped": sum(int(node.get("skipped", 0)) for node in found),
    }


def _failing_test_cases(project_dir: Path, test_class: str) -> list[str]:
    names = []
    for report in (project_dir / "target" / "surefire-reports").glob("TEST-*.xml"):
        try:
            root = ET.parse(str(report)).getroot()
        except ET.ParseError:
            continue
        if not (root.get("name", "").endswith("." + test_class) or root.get("name") == test_class):
            continue
        for case in root.findall("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                names.append(case.get("name", "unknown"))
    return names


def _copy_subject(source: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns(".git", "target", "*.class", ".idea", ".DS_Store")
    shutil.copytree(source, destination, ignore=ignored)


def _agent_usage(run_dir: Path) -> Optional[Dict[str, Any]]:
    summary_path = run_dir / "openhands-summary.json"
    if not summary_path.is_file():
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        metrics = summary.get("stats", {}).get("usage_to_metrics", {}).get("openhands-agent", {})
        usage = metrics.get("accumulated_token_usage", {})
        costs = metrics.get("costs") or []
        return {
            "execution_status": summary.get("execution_status"),
            "request_count": len(metrics.get("token_usages") or []),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cache_read_tokens": usage.get("cache_read_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "reported_cost": metrics.get("accumulated_cost") if costs else None,
            "cost_available": bool(costs),
        }
    except (OSError, ValueError, TypeError):
        return None


def _python_from_openhands_cli() -> str:
    executable = shutil.which("openhands")
    if not executable:
        raise SystemExit(
            "OpenHands CLI not found. Set OPENHANDS_PYTHON or pass --openhands-python."
        )
    resolved = Path(executable).resolve()
    try:
        first_line = resolved.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        raise SystemExit(
            "Cannot infer OpenHands Python from {}; pass --openhands-python.".format(resolved)
        )
    if not first_line.startswith("#!"):
        raise SystemExit(
            "OpenHands launcher has no Python shebang: {}; pass --openhands-python.".format(resolved)
        )
    return first_line[2:].split()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Defects4J id, e.g. JacksonXml-5f")
    parser.add_argument("--class", dest="class_name", required=True, help="Focal Java class")
    parser.add_argument("--model-profile", default="deepseek-v4.1-flash")
    parser.add_argument("--openhands-python", default=os.environ.get("OPENHANDS_PYTHON"),
                        help="Python executable in the OpenHands uv tool environment")
    parser.add_argument("--runtime-image", default="maven:3.9.9-eclipse-temurin-8")
    parser.add_argument("--max-iterations", type=int, default=24)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--maven-timeout-seconds", type=int, default=900)
    parser.add_argument("--prepare-only", action="store_true", help="Copy subject and write task, but do not run the agent")
    parser.add_argument("--run-dir", type=Path, help="Optional explicit output directory")
    parser.add_argument("--repair-run-dir", type=Path,
                        help="Continue a prior failed case in its existing isolated workspace")
    args = parser.parse_args()

    item = _find_class(args.project, args.class_name)
    project_dir, source, test_file = _subject_paths(args.project, item)
    if not project_dir.is_dir() or not source.is_file():
        raise SystemExit("Subject or focal source is missing: {} / {}".format(project_dir, source))
    if not test_file.is_relative_to(project_dir):
        raise SystemExit("Resolved test path escaped subject root: {}".format(test_file))
    source_rel = source.relative_to(project_dir)
    test_rel = test_file.relative_to(project_dir)
    test_class = test_file.stem

    profile = None if args.prepare_only else _model_profile(args.model_profile)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.repair_run_dir:
        if args.run_dir or args.prepare_only:
            raise SystemExit("--repair-run-dir cannot be combined with --run-dir or --prepare-only")
        base_run_dir = args.repair_run_dir.resolve()
        base_metadata_path = base_run_dir / "run.json"
        if not base_metadata_path.is_file():
            raise SystemExit("Cannot repair run without run.json: {}".format(base_metadata_path))
        base_metadata = json.loads(base_metadata_path.read_text(encoding="utf-8"))
        if (base_metadata.get("project"), base_metadata.get("class")) != (args.project, args.class_name):
            raise SystemExit("Repair project/class do not match the prior run metadata")
        if base_metadata.get("model_profile") != args.model_profile:
            raise SystemExit("Repair model profile must match the prior run")
        workspace = base_run_dir / "workspace"
        if not workspace.is_dir() or not (workspace / test_rel).is_file():
            raise SystemExit("Prior run workspace or generated test is missing")
        run_dir = base_run_dir / "repairs" / stamp
        prior_tests = base_metadata.get("metrics", {}).get("tests", {})
        failing_tests = _failing_test_cases(workspace, test_class)
        repair_task = """Repair the generated test suite for {project}::{class_name}.

The existing test file is {test}. The last Maven run executed {test_count} tests
and reported {failure_count} assertion failures and {error_count} errors. The
failing methods are: {failing_tests}.

Work only in {test}. Do not edit production files, pom.xml, or other tests. Do
not create scratch Java programs, investigate repository history, or browse
unrelated source. Use the existing Surefire report and listed method names. Do
not inspect production implementations. First remove or correct only the listed
failing test methods; preserve every passing method. This is a validity repair
step, so report the number of removed tests. Run
`mvn clean package -Dtest={test_class}` immediately after the edit. If it still
fails, fix only the newly reported failing methods and rerun Maven. Once Maven
passes, report line and branch coverage for {class_name} from
target/jacoco/jacoco.csv. Do not add tests.
""".format(
            project=args.project, class_name=args.class_name,
            test=test_rel.as_posix(), test_class=test_class,
            test_count=prior_tests.get("tests", "unknown"),
            failure_count=prior_tests.get("failures", "unknown"),
            error_count=prior_tests.get("errors", "unknown"),
            failing_tests=", ".join(failing_tests[:30]) or "not listed",
        )
    else:
        if args.run_dir and args.run_dir.exists():
            raise SystemExit("Run directory already exists: {}".format(args.run_dir))
        base_run_dir = None
        workspace = None
        run_dir = args.run_dir or EVAL_DIR / "result-files" / "openhands" / args.project / args.class_name / stamp
        run_dir = run_dir.resolve()
        workspace = run_dir / "workspace"
        repair_task = None
    run_dir.mkdir(parents=True, exist_ok=False)
    if not args.repair_run_dir:
        _copy_subject(project_dir, workspace)
    (run_dir / "task.md").write_text(
        repair_task or _task_text(args.project, args.class_name, source_rel, test_rel),
        encoding="utf-8",
    )
    metadata: Dict[str, Any] = {
        "project": args.project,
        "class": args.class_name,
        "model_profile": args.model_profile,
        "model_id": profile["model"] if profile else None,
        "source": source_rel.as_posix(),
        "test_file": test_rel.as_posix(),
        "created_utc": stamp,
        "workspace": str(workspace),
        "phase": "repair" if args.repair_run_dir else "initial",
        "base_run_dir": str(base_run_dir) if base_run_dir else None,
        "openhands_timeout_seconds": args.timeout_seconds,
        "maven_timeout_seconds": args.maven_timeout_seconds,
    }
    if args.prepare_only:
        metadata["status"] = "prepared_only"
        (run_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metadata, indent=2))
        return 0

    model_alias = profile["model"]
    if not model_alias:
        raise SystemExit("Model profile {!r} has no LiteLLM model id".format(args.model_profile))
    python_exe = Path(args.openhands_python or _python_from_openhands_cli()).absolute()
    if not python_exe.is_file():
        raise SystemExit("OpenHands Python executable not found: {}".format(python_exe))
    python_venv = python_exe.parents[1]
    python_runtime = python_exe.resolve().parents[1]
    for path in (python_venv, python_runtime):
        if not path.is_dir():
            raise SystemExit("OpenHands Python runtime path does not exist: {}".format(path))
    profile_path = run_dir / "model-profile.json"
    profile_path.write_text(
        json.dumps({key: value for key, value in profile.items() if key != "api_key"}, indent=2)
        + "\n", encoding="utf-8"
    )
    worker_path = run_dir / "openhands_sdk_worker.py"
    shutil.copyfile(Path(__file__).with_name("openhands_sdk_worker.py"), worker_path)
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else uid
    container_python = str(python_exe.resolve())
    python_site_packages = python_venv / "lib" / "python3.12" / "site-packages"
    if not python_site_packages.is_dir():
        raise SystemExit("OpenHands Python packages not found: {}".format(python_site_packages))
    container_name = "cogpath-openhands-{}".format(uuid.uuid4().hex[:12])
    command = [
        "docker", "run", "--rm", "--init", "--name", container_name,
        "--user", "{}:{}".format(uid, gid),
        "--network", "bridge",
        "--mount", "type=bind,src={},dst=/workspace".format(workspace),
        "--mount", "type=bind,src={},dst=/run-data".format(run_dir),
        "--mount", "type=bind,src={},dst={},readonly".format(python_venv, python_venv),
        "--mount", "type=bind,src={},dst={},readonly".format(python_runtime, python_runtime),
        "--workdir", "/workspace",
        "--env", "HOME=/workspace/.openhands-home",
        "--env", "MAVEN_CONFIG=/workspace/.m2",
        "--env", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--env", "PYTHONPATH={}".format(python_site_packages),
        "--env", "PYTHONUNBUFFERED=1",
        "--env", "LLM_API_KEY",
        "--env", "LLM_MODEL={}".format(model_alias),
        "--env", "LLM_BASE_URL={}".format(profile["base_url"]),
        args.runtime_image,
        container_python, "/run-data/openhands_sdk_worker.py",
        "--workspace", "/workspace",
        "--task", "/run-data/task.md",
        "--profile", "/run-data/model-profile.json",
        "--event-log", "/run-data/openhands.jsonl",
        "--persistence", "/run-data/state",
        "--max-iterations", str(args.max_iterations),
    ]
    docker_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LLM_API_KEY": profile["api_key"],
    }
    if os.environ.get("DOCKER_HOST"):
        docker_env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
    started = time.monotonic()
    agent_exit: Optional[int] = None
    agent_error: Optional[str] = None
    try:
        with (run_dir / "agent-worker.log").open("w", encoding="utf-8") as stdout, \
                (run_dir / "agent-worker.stderr.log").open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(
                command, env=docker_env, stdout=stdout, stderr=stderr,
                timeout=args.timeout_seconds, check=False,
            )
            agent_exit = completed.returncode
    except subprocess.TimeoutExpired:
        agent_error = "OpenHands exceeded the configured timeout"
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except OSError as exc:
        agent_error = str(exc)
    agent_elapsed = round(time.monotonic() - started, 2)

    maven_command = ["mvn", "clean", "package", "-Dtest={}".format(test_class)]
    maven_exit: Optional[int] = None
    maven_error: Optional[str] = None
    try:
        with (run_dir / "final-maven.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                maven_command, cwd=str(workspace), stdout=log, stderr=subprocess.STDOUT,
                timeout=args.maven_timeout_seconds, check=False,
            )
            maven_exit = completed.returncode
    except subprocess.TimeoutExpired:
        maven_error = "Final Maven verification exceeded the configured timeout"
    except OSError as exc:
        maven_error = str(exc)

    jacoco_csv = workspace / "target" / "jacoco" / "jacoco.csv"
    metrics = _jacoco_metrics(jacoco_csv, args.class_name)
    metrics["tests"] = _surefire_metrics(workspace, test_class)
    metadata.update({
        "status": "completed",
        "agent_command": ["docker", "run", "<isolated runtime>", args.runtime_image,
                          "OpenHands SDK worker", "max_iterations={}".format(args.max_iterations)],
        "runtime_image": args.runtime_image,
        "openhands_python": str(python_exe),
        "openhands_max_iterations": args.max_iterations,
        "agent_usage": _agent_usage(run_dir),
        "agent_exit_code": agent_exit,
        "agent_error": agent_error,
        "agent_elapsed_seconds": agent_elapsed,
        "final_maven_command": maven_command,
        "final_maven_exit_code": maven_exit,
        "final_maven_error": maven_error,
        "metrics": metrics,
    })
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if base_run_dir:
        base_metadata.setdefault("initial_metrics", base_metadata.get("metrics"))
        base_metadata.setdefault("initial_agent_usage", base_metadata.get("agent_usage"))
        repair_history = base_metadata.setdefault("repairs", [])
        repair_history.append({
            "run_dir": str(run_dir),
            "agent_exit_code": agent_exit,
            "agent_error": agent_error,
            "agent_usage": metadata["agent_usage"],
            "final_maven_exit_code": maven_exit,
            "final_maven_error": maven_error,
            "metrics": metrics,
        })
        base_metadata["latest_repair_run"] = str(run_dir)
        base_metadata["metrics"] = metrics
        base_metadata["latest_metrics"] = metrics
        base_metadata["latest_repair_agent_exit_code"] = agent_exit
        base_metadata["latest_repair_maven_exit_code"] = maven_exit
        tests = metrics.get("tests", {})
        passed = (
            maven_exit == 0
            and tests.get("report_found")
            and tests.get("failures", 0) == 0
            and tests.get("errors", 0) == 0
        )
        base_metadata["status"] = "repaired" if passed else "repair_failed"
        base_metadata_path.write_text(
            json.dumps(base_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0 if agent_exit == 0 and maven_exit == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
