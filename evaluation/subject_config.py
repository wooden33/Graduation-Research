"""Per-class subject configuration for CogPath runs.

Split out of ``execute_cogpath.py`` so that the manifest-driven runner
(:mod:`evaluation.experiment`) does not have to import a legacy script that pulls
in BeautifulSoup at module scope.  This module is standard-library only.

The path handling below is copied faithfully from ``execute_cogpath.extract_config_data``
so that subject resolution cannot drift between the two drivers.  The two
project-specific special cases are preserved deliberately:

* ``Gson-16f`` keeps its sources in a nested ``gson/`` directory;
* ``JxPath-22f`` uses ``src/java`` rather than ``src/main/java``.

The ablation factors are *not* set here: they belong to the experiment manifest.
Keys written here are subject-scoped only.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

SUBJECTS_ROOT = "defects4j-subjects-notests"


def project_directory(project_name: str) -> str:
    """Repository-relative root of a subject project."""
    if project_name == "Gson-16f":
        return "{}/{}/gson".format(SUBJECTS_ROOT, project_name)
    return "{}/{}".format(SUBJECTS_ROOT, project_name)


def source_path(src_file_obj: Mapping[str, Any]) -> str:
    """Repository-relative path of the file under test."""
    path = str(src_file_obj["src_path"]).replace("defects4j-subjects", SUBJECTS_ROOT)
    return path.lstrip("../")


def test_path(project_name: str, src_file_obj: Mapping[str, Any]) -> str:
    """Repository-relative path of the generated test file."""
    src = source_path(src_file_obj)
    file_name = os.path.basename(src)
    dir_name = os.path.dirname(src)

    if project_name == "JxPath-22f":
        test_dir = dir_name.replace("src/java", "src/test")
    else:
        test_dir = dir_name.replace("src/main/java", "src/test/java")

    test_name = file_name.replace(
        "{}.java".format(src_file_obj["src_name"]),
        "{}Test.java".format(src_file_obj["src_name"]),
    )
    return os.path.join(test_dir, test_name)


def subject_config(
    src_file_obj: Mapping[str, Any],
    project_name: str,
    max_complexity: Any,
    prompt_type: str,
    remove_existing_test: bool = True,
) -> Dict[str, Any]:
    """Build the subject-scoped part of a per-class config.

    Args:
        src_file_obj: entry from ``defects4j-codefiles/<project>-codefiles.json``.
        project_name: Defects4J subject id, e.g. ``JacksonXml-5f``.
        max_complexity: the class's maximum cyclomatic complexity, used as the
            iteration budget.
        prompt_type: names the per-class report file.
        remove_existing_test: delete a pre-existing test file so the run starts
            clean.  Enabled by default, matching the legacy driver.
    """
    project_dir = project_directory(project_name)
    src_path = source_path(src_file_obj)
    t_path = test_path(project_name, src_file_obj)

    if remove_existing_test and os.path.exists(t_path):
        os.remove(t_path)

    test_file_name = os.path.splitext(os.path.basename(t_path))[0]

    return {
        "project_directory": project_dir,
        "source_code_file": src_path,
        "test_code_file": t_path,
        "test_file_output_path": "",
        "code_coverage_report_path": "{}/target/jacoco/jacoco.csv".format(project_dir),
        # `clean` is kept here to match the recorded runs; the parallel driver
        # deliberately avoids it, which is why this is a single-class call path.
        "test_execution_command": "mvn clean package -Dtest={}".format(test_file_name),
        "test_dependency_command": 'mvn dependency:list -DexcludeTransitive=true | grep ":test"',
        "test_code_command_dir": project_dir,
        "included_files": "",
        "junit_version": 4,
        "coverage_type": "jacoco",
        "report_filepath": "{}_{}_test_results.html".format(src_file_obj["src_name"], prompt_type),
        "maximum_iterations": int(max_complexity),
    }
