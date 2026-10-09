#!/usr/bin/env python3
"""Run Aider on one isolated Defects4J class and measure tests/JaCoCo."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

from openhands_runner import (
    EVAL_DIR,
    REPO_DIR,
    _copy_subject,
    _find_class,
    _failing_test_cases,
    _jacoco_metrics,
    _model_profile,
    _subject_paths,
    _surefire_metrics,
)


def _aider_paths(executable: Optional[str]) -> tuple[Path, Path, Path, Path]:
    command = executable or os.environ.get("AIDER_EXECUTABLE") or shutil.which("aider")
    if not command:
        raise SystemExit(
            "Aider not found. Install it outside panta-env or pass --aider-executable."
        )
    aider = Path(command).resolve()
    try:
        first_line = aider.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        raise SystemExit("Cannot read Aider launcher {}; pass --aider-executable.".format(aider))
    if not first_line.startswith("#!"):
        raise SystemExit("Aider launcher has no Python shebang: {}".format(aider))
    python = Path(first_line[2:].split()[0])
    venv = python.parent.parent
    try:
        link_target = Path(os.readlink(str(python)))
        if not link_target.is_absolute():
            link_target = python.parent / link_target
    except OSError:
        link_target = python
    runtime_mountpoint = link_target.parent.parent
    runtime_source = link_target.resolve().parent.parent
    if not venv.is_dir() or not runtime_source.is_dir():
        raise SystemExit(
            "Aider Python runtime or venv is missing: {} / {}".format(venv, runtime_source)
        )
    return aider, venv, runtime_source, runtime_mountpoint


def _write_skeleton(test_path: Path, package_name: str) -> None:
    if test_path.exists():
        return
    test_path.parent.mkdir(parents=True, exist_ok=True)
    package = "package {};\n\n".format(package_name) if package_name else ""
    test_path.write_text(
        package + "import org.junit.Test;\n\n"
        + "public class {} {{\n}}\n".format(test_path.stem),
        encoding="utf-8",
    )


def _task_text(project: str, source_rel: Path, test_rel: Path) -> str:
    return """Create JUnit 4 tests for the focal Java class.

Project: {project}
Production class (read only): {source}
Only editable file: {test}

Use the source and existing project dependencies to write a concise, executable
test suite for distinct public behaviors and feasible edge cases. Aim for useful
line and branch coverage; do not invent unsupported behavior. Add at most 15 test
methods. Do not modify production code, Maven files, or any other project file.
Run the configured Maven test command after editing and fix compilation or test
failures. Keep the final suite self-contained and avoid broad project searches.
""".format(project=project, source=source_rel.as_posix(), test=test_rel.as_posix())


def _usage(analytics_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reported_cost": 0.0,
        "cost_available": False,
    }
    if not analytics_path.is_file():
        result["analytics_found"] = False
        return result
    result["analytics_found"] = True
    for line in analytics_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "message_send":
            continue
        properties = event.get("properties", {})
        result["request_count"] += 1
        result["prompt_tokens"] += int(properties.get("prompt_tokens", 0) or 0)
        result["completion_tokens"] += int(properties.get("completion_tokens", 0) or 0)
        result["total_tokens"] += int(properties.get("total_tokens", 0) or 0)
        result["reported_cost"] += float(properties.get("cost", 0.0) or 0.0)
        result["cost_available"] = result["cost_available"] or bool(properties.get("cost"))
    if not result["cost_available"]:
        result["reported_cost"] = None
    return result


def _failure_details(workspace: Path, test_class: str) -> list[str]:
    details = []
    for report in (workspace / "target" / "surefire-reports").glob("TEST-*.xml"):
        try:
            root = ET.parse(str(report)).getroot()
        except ET.ParseError:
            continue
        if not (root.get("name", "").endswith("." + test_class) or root.get("name") == test_class):
            continue
        for case in root.findall("testcase"):
            for tag in ("failure", "error"):
                issue = case.find(tag)
                if issue is not None:
                    message = (issue.get("message") or (issue.text or "").strip()).splitlines()
                    details.append("{} [{}]: {}".format(
                        case.get("name", "unknown"), issue.get("type", tag),
                        message[0][:400] if message else "no message",
                    ))
    return details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--class", dest="class_name", required=True)
    parser.add_argument("--model-profile", default="deepseek-v4.1-flash")
    parser.add_argument("--aider-executable", default=os.environ.get("AIDER_EXECUTABLE"))
    parser.add_argument("--runtime-image", default="maven:3.9.9-eclipse-temurin-8")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--maven-timeout-seconds", type=int, default=900)
    parser.add_argument("--max-chat-history-tokens", type=int, default=32768)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--repair-run-dir", type=Path)
    args = parser.parse_args()

    item = _find_class(args.project, args.class_name)
    subject, source, test_path = _subject_paths(args.project, item)
    if not subject.is_dir() or not source.is_file():
        raise SystemExit("Subject or focal source is missing: {} / {}".format(subject, source))
    if not test_path.is_relative_to(subject):
        raise SystemExit("Resolved test path escaped subject root: {}".format(test_path))
    source_rel = source.relative_to(subject)
    test_rel = test_path.relative_to(subject)
    package_name = ".".join(source_rel.parts[3:-1])

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_run_dir: Optional[Path] = None
    base_metadata: Optional[Dict[str, Any]] = None
    if args.repair_run_dir:
        if args.run_dir or args.prepare_only:
            raise SystemExit("--repair-run-dir cannot be combined with --run-dir or --prepare-only")
        base_run_dir = args.repair_run_dir.resolve()
        base_metadata_path = base_run_dir / "run.json"
        if not base_metadata_path.is_file():
            raise SystemExit("Cannot repair run without run.json: {}".format(base_metadata_path))
        base_metadata = json.loads(base_metadata_path.read_text(encoding="utf-8"))
        if (base_metadata.get("project"), base_metadata.get("class")) != (args.project, args.class_name):
            raise SystemExit("Repair project/class do not match prior run metadata")
        if base_metadata.get("model_profile") != args.model_profile:
            raise SystemExit("Repair model profile must match the prior run")
        workspace = base_run_dir / "workspace"
        if not workspace.is_dir() or not (workspace / test_rel).is_file():
            raise SystemExit("Prior run workspace or generated test is missing")
        prior_tests = base_metadata.get("metrics", {}).get("tests", {})
        failing = _failing_test_cases(workspace, test_path.stem)
        details = _failure_details(workspace, test_path.stem)
        task_text = """Repair only the failing tests in {test} for {project}::{class_name}.

Previous Maven results: {tests} tests, {failures} failures, {errors} errors.
Failing methods: {failing}
Failure details: {details}

Use the test report and test methods to correct only these failures. Preserve
passing tests. Do not add tests or edit production code, pom.xml, or other files.
Run the configured Maven command after the edit. Stop when all tests pass.
""".format(
            test=test_rel.as_posix(), project=args.project, class_name=args.class_name,
            tests=prior_tests.get("tests", "unknown"),
            failures=prior_tests.get("failures", "unknown"),
            errors=prior_tests.get("errors", "unknown"),
            failing=", ".join(failing[:30]) or "not listed",
            details="; ".join(details[:20]) or "not listed",
        )
        run_dir = base_run_dir / "repairs" / stamp
    else:
        if args.run_dir and args.run_dir.exists():
            raise SystemExit("Run directory already exists: {}".format(args.run_dir))
        workspace = None
        run_dir = args.run_dir or EVAL_DIR / "result-files" / "aider" / args.project / args.class_name / stamp
        run_dir = run_dir.resolve()
        task_text = _task_text(args.project, source_rel, test_rel)
    if run_dir.exists():
        raise SystemExit("Run directory already exists: {}".format(run_dir))
    run_dir.mkdir(parents=True)
    if not args.repair_run_dir:
        workspace = run_dir / "workspace"
        _copy_subject(subject, workspace)
        _write_skeleton(workspace / test_rel, package_name)
    task_path = run_dir / "task.md"
    task_path.write_text(task_text, encoding="utf-8")

    metadata: Dict[str, Any] = {
        "agent": "aider",
        "agent_version": None,
        "project": args.project,
        "class": args.class_name,
        "model_profile": args.model_profile,
        "model_id": None,
        "source": source_rel.as_posix(),
        "test_file": test_rel.as_posix(),
        "created_utc": stamp,
        "workspace": str(workspace),
        "phase": "repair" if args.repair_run_dir else "initial",
        "base_run_dir": str(base_run_dir) if base_run_dir else None,
        "runtime_image": args.runtime_image,
        "timeout_seconds": args.timeout_seconds,
        "maven_timeout_seconds": args.maven_timeout_seconds,
        "max_chat_history_tokens": args.max_chat_history_tokens,
    }
    if args.prepare_only:
        metadata["status"] = "prepared_only"
        (run_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metadata, indent=2))
        return 0

    profile = _model_profile(args.model_profile)
    model = profile["model"]
    if not model:
        raise SystemExit("Model profile {!r} has no LiteLLM model id".format(args.model_profile))
    aider, aider_venv, python_runtime, python_runtime_mountpoint = _aider_paths(
        args.aider_executable
    )
    metadata["model_id"] = model
    try:
        version = subprocess.run(
            [str(aider), "--version"], check=False, capture_output=True, text=True, timeout=30
        )
        metadata["agent_version"] = version.stdout.strip() or version.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        metadata["agent_version"] = "unknown"

    extra_params = profile.get("litellm_params", {})
    model_settings = [{"name": model, "edit_format": "diff", "extra_params": extra_params}]
    model_settings_path = run_dir / "aider-model-settings.yml"
    try:
        import yaml  # type: ignore
    except ImportError:
        # YAML is emitted with JSON syntax, which is a valid YAML subset.
        model_settings_path.write_text(json.dumps(model_settings, indent=2) + "\n", encoding="utf-8")
    else:
        model_settings_path.write_text(yaml.safe_dump(model_settings, sort_keys=False), encoding="utf-8")
    profile_snapshot = {key: value for key, value in profile.items() if key != "api_key"}
    (run_dir / "model-profile.json").write_text(
        json.dumps(profile_snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    model_metadata_path = run_dir / "aider-model-metadata.json"
    model_metadata_path.write_text(json.dumps({model: {
        # DeepSeek documents a 1M context and a 393,216-token maximum output.
        # Bound each Aider response to 8k tokens for this one-case pilot.
        "max_tokens": 8192,
        "max_input_tokens": 1048576,
        "max_output_tokens": 8192,
        "litellm_provider": "openai",
        "mode": "chat",
    }}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    analytics_path = run_dir / "aider-analytics.jsonl"
    test_command = (
        "env -u OPENAI_API_KEY sh -c 'mvn -q -f /workspace/pom.xml clean package -Dtest={}; "
        "status=$?; if [ \"$status\" -ne 0 ]; then "
        "grep -hE \"Tests run:|<<< FAILURE!|<<< ERROR!\" "
        "/workspace/target/surefire-reports/*.txt; fi; exit \"$status\"'"
    ).format(test_path.stem)
    container_name = "cogpath-aider-{}".format(uuid.uuid4().hex[:12])
    command = [
        "docker", "run", "--rm", "--init", "--name", container_name,
        "--user", "{}:{}".format(os.getuid(), os.getgid()),
        "--network", "bridge",
        "--mount", "type=bind,src={},dst=/workspace".format(workspace),
        "--mount", "type=bind,src={},dst=/run-data".format(run_dir),
        "--mount", "type=bind,src={},dst={},readonly".format(aider_venv, aider_venv),
        "--mount", "type=bind,src={},dst={},readonly".format(python_runtime, python_runtime_mountpoint),
        "--workdir", "/workspace",
        "--env", "HOME=/workspace/.aider-home",
        "--env", "MAVEN_CONFIG=/workspace/.m2",
        "--env", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--env", "OPENAI_API_KEY",
        args.runtime_image,
        str(aider),
        "--model", model,
        "--openai-api-base", profile["base_url"],
        "--model-settings-file", "/run-data/aider-model-settings.yml",
        "--model-metadata-file", "/run-data/aider-model-metadata.json",
        "--message-file", "/run-data/task.md",
        "--file", test_rel.as_posix(),
        "--read", source_rel.as_posix(),
        "--test-cmd", test_command,
        "--auto-test",
        "--yes-always",
        "--no-auto-commits",
        "--no-git",
        "--no-gitignore",
        "--no-stream",
        "--no-show-model-warnings",
        "--timeout", "120",
        "--max-chat-history-tokens", str(args.max_chat_history_tokens),
        "--analytics-log", "/run-data/aider-analytics.jsonl",
        "--no-analytics",
    ]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "OPENAI_API_KEY": profile["api_key"],
    }
    if os.environ.get("DOCKER_HOST"):
        env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
    command_started = time.monotonic()
    agent_exit: Optional[int] = None
    agent_error: Optional[str] = None
    try:
        with (run_dir / "aider.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command, env=env, stdout=log, stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds, check=False,
            )
            agent_exit = completed.returncode
    except subprocess.TimeoutExpired:
        agent_error = "Aider exceeded the configured timeout"
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except OSError as exc:
        agent_error = str(exc)

    maven_command = ["mvn", "clean", "package", "-Dtest={}".format(test_path.stem)]
    maven_exit: Optional[int] = None
    maven_error: Optional[str] = None
    try:
        verification_env = os.environ.copy()
        if profile.get("api_key_env"):
            verification_env.pop(profile["api_key_env"], None)
        verification_env.pop("OPENAI_API_KEY", None)
        with (run_dir / "final-maven.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                maven_command, cwd=str(workspace), stdout=log, stderr=subprocess.STDOUT,
                timeout=args.maven_timeout_seconds, check=False, env=verification_env,
            )
            maven_exit = completed.returncode
    except subprocess.TimeoutExpired:
        maven_error = "Final Maven verification exceeded the configured timeout"
    except OSError as exc:
        maven_error = str(exc)

    metrics = _jacoco_metrics(workspace / "target" / "jacoco" / "jacoco.csv", args.class_name)
    metrics["tests"] = _surefire_metrics(workspace, test_path.stem)
    metadata.update({
        "status": "passed" if (
            agent_exit == 0 and maven_exit == 0
            and metrics.get("tests", {}).get("report_found")
            and metrics.get("tests", {}).get("failures", 0) == 0
            and metrics.get("tests", {}).get("errors", 0) == 0
        ) else "failed",
        "agent_command": ["docker", "run", "<isolated runtime>", args.runtime_image, "aider"],
        "agent_exit_code": agent_exit,
        "agent_error": agent_error,
        "agent_elapsed_seconds": round(time.monotonic() - command_started, 2),
        "agent_usage": _usage(analytics_path),
        "final_maven_command": maven_command,
        "final_maven_exit_code": maven_exit,
        "final_maven_error": maven_error,
        "metrics": metrics,
    })
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if base_run_dir and base_metadata is not None:
        history = base_metadata.setdefault("repairs", [])
        history.append({
            "run_dir": str(run_dir),
            "agent_exit_code": agent_exit,
            "agent_usage": metadata["agent_usage"],
            "final_maven_exit_code": maven_exit,
            "metrics": metrics,
        })
        base_metadata["latest_repair_run"] = str(run_dir)
        base_metadata["latest_metrics"] = metrics
        base_metadata["metrics"] = metrics
        passed = metadata["status"] == "passed"
        base_metadata["status"] = "repaired" if passed else "repair_failed"
        base_metadata["repair_agent_exit_code"] = agent_exit
        base_metadata["repair_final_maven_exit_code"] = maven_exit
        (base_run_dir / "run.json").write_text(
            json.dumps(base_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0 if agent_exit == 0 and maven_exit == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
