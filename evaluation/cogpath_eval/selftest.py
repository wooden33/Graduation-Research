"""Self-tests for the result-analysis pipeline.

Runnable without any third-party dependency::

    cd evaluation && python -m cogpath_eval.selftest

The golden tests at the end re-derive checked-in CSVs from the checked-in run
directories and assert **byte equality**.  They are skipped (not failed) when the
result trees are absent, so the suite still runs in a bare checkout.
"""

from __future__ import annotations

import csv
import io
import unittest
from pathlib import Path

from .aggregate import (
    class_level_columns,
    class_level_rows,
    overall_summary,
    project_level_rows,
)
from .dataset import ClassList, ClassSpec
from .extract import (
    ClassResult,
    class_name_from_report,
    final_iteration_index,
    parse_html_coverage,
    read_run,
)
from .paths import EVAL_DIR, RESULT_FILES

# A miniature report in the tool's exact (unescaped) output shape.
SAMPLE_HTML = """<html><body><table>
<tr><th>Status</th><th>Label</th></tr>
<tr><td class="status-PASS">PASS</td><td>g_0</td><td>r</td><td>0</td><td>10.0</td><td>5.0</td><td>x</td><td>x</td><td>x</td></tr>
<tr><td class="status-INFO">INFO</td><td>g_0</td><td>1.5</td><td>100</td><td>20.0</td><td>10.0</td><td></td><td></td><td></td></tr>
<tr><td class="status-INFO">INFO</td><td>g_1</td><td>2.5</td><td>200</td><td>30.0</td><td>15.0</td><td></td><td></td><td></td></tr>
<tr><td class="status-INFO">INFO</td><td></td><td></td><td>0</td><td>40.0</td><td>25.0</td><td></td><td></td><td></td></tr>
<tr><td>broken</td><td>row</td></tr>
<tr><td class="status-INFO">INFO</td><td>g_2</td><td></td><td></td><td>not-a-number</td><td>1.0</td><td></td><td></td><td></td></tr>
</table></body></html>"""


class TestHtmlParsing(unittest.TestCase):
    def test_info_rows_only_and_final(self):
        coverage = parse_html_coverage(SAMPLE_HTML)
        # The PASS row repeats label g_0 and must be ignored.
        self.assertEqual(coverage["g_0"], (20.0, 10.0))
        self.assertEqual(coverage["g_1"], (30.0, 15.0))
        # The empty-label INFO row is the run's final coverage.
        self.assertEqual(coverage["final"], (40.0, 25.0))
        # A row with too few cells is skipped, and an unparseable pair is skipped.
        self.assertNotIn("g_2", coverage)

    def test_final_iteration_index(self):
        smallest = {"g_0": (1.0, 1.0)}
        self.assertEqual(final_iteration_index(smallest), 0)
        self.assertEqual(final_iteration_index({}), -1)
        self.assertEqual(final_iteration_index({"g_3": (1.0, 1.0), "g_1": (1.0, 1.0)}), 3)

    def test_class_name_derivation(self):
        self.assertEqual(
            class_name_from_report("ToXmlGenerator_control_test_results.html", "control"),
            "ToXmlGenerator",
        )
        # Doubled prompt token, seen in some trees.
        self.assertEqual(
            class_name_from_report("Foo_control_control_test_results.html", "control"),
            "Foo",
        )
        # Wrong prompt token must not match.
        self.assertIsNone(
            class_name_from_report("Foo_control_test_results.html", "symprompt")
        )
        # Auto-detection prefers the longest class prefix.
        self.assertEqual(
            class_name_from_report("Foo_Bar_control_test_results.html"), "Foo_Bar"
        )


class TestClassList(unittest.TestCase):
    def test_label_is_first_hyphen_token(self):
        spec = ClassSpec("JacksonDatabind-112f", "Foo", 15)
        self.assertEqual(spec.label, "JacksonDatabind")

    def test_ambiguous_names_are_not_guessed(self):
        class_list = ClassList(
            [ClassSpec("A-1f", "Dup", 11), ClassSpec("B-2f", "Dup", 12)]
        )
        # Returning a match here would silently attribute coverage to one project.
        self.assertIsNone(class_list.by_class("Dup"))
        self.assertEqual(class_list.ambiguous_classes(), {"Dup": ["A-1f", "B-2f"]})
        self.assertIsNotNone(class_list.by_key("A-1f", "Dup"))

    def test_load_handles_bom(self):
        class_list = ClassList.load()
        self.assertGreater(len(class_list), 0)
        first = class_list.specs[0]
        self.assertTrue(first.project and first.class_name)
        self.assertFalse(first.project.startswith("\ufeff"))


class TestAggregation(unittest.TestCase):
    def test_presence_not_truthiness(self):
        """A coverage of 0.0 must count as present, matching the CSV-string source."""
        rows = [
            {"project": "P", "complexity": "11", "final_line": 0.0, "final_branch": 0.0},
            {"project": "P", "complexity": "12", "final_line": None, "final_branch": None},
        ]
        stats = project_level_rows(rows)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["num_classes"], 1)
        self.assertEqual(stats[0]["avg_final_line"], 0.0)
        self.assertEqual(stats[0]["classes_with_coverage"], 0)

    def test_both_mean_conventions_differ(self):
        """The two conventions must be reported, not conflated."""
        rows = [
            # small project, high coverage
            {"project": "Small", "num_classes": 1, "avg_final_line": 100.0, "avg_final_branch": 100.0},
            # large project, low coverage
            {"project": "Big", "num_classes": 99, "avg_final_line": 0.0, "avg_final_branch": 0.0},
        ]
        summary = overall_summary(rows)
        self.assertEqual(summary["n_classes"], 100)
        self.assertAlmostEqual(summary["mean_of_project_means_line"], 50.0)   # paper convention
        self.assertAlmostEqual(summary["class_weighted_line"], 1.0)           # different!
        self.assertNotAlmostEqual(
            summary["mean_of_project_means_line"], summary["class_weighted_line"]
        )

    def test_columns_and_missing_policy(self):
        record = ClassResult(
            project="P",
            project_id="P-1f",
            class_name="C",
            complexity=11,
            iterations=((1.0, 2.0), None),
            final_line=5.0,
            final_branch=6.0,
            final_iter=1,
        )
        rows = class_level_rows([record], max_iterations=2)
        self.assertEqual(rows[0]["iter_0_line"], 1.0)
        # None (iteration never reached) becomes an empty CSV cell.
        self.assertIsNone(rows[0]["iter_1_line"])
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=class_level_columns(2))
        writer.writeheader()
        writer.writerow(rows[0])
        self.assertIn(",1.0,2.0,,", buffer.getvalue())

    def test_project_id_only_when_extended(self):
        plain = class_level_columns(1)
        extended = class_level_columns(1, extended=True)
        self.assertNotIn("project_id", plain)
        self.assertIn("project_id", extended)
        self.assertEqual(plain[-3:], ["final_line", "final_branch", "final_iter"])


class TestGoldenRegeneration(unittest.TestCase):
    """Re-derive checked-in CSVs and require byte equality.

    These pin down the semantics that matter: the iteration-missing policy, the
    short project label, and report-filename row order.  Skipped when the raw
    result trees are not present.
    """

    CASES = (
        # (checked-in class CSV, run label, prompt type, iterations, --fill)
        (
            "cogpath_results/cogpath/cogpath_qwen3-coder_30b-a3b_q8_0_constraints_bs_8iter.csv",
            "control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_bs",
            "control",
            8,
            "carry-forward",
        ),
        (
            "cogpath_results/cogpath/cogpath_gpt-5.4-mini.csv",
            "control_openrouter/openai/gpt-5.4-mini_constraints_bs",
            "control",
            8,
            "carry-forward",
        ),
        (
            "cogpath_results/cogpath/cogpath_qwen3.5-397b-a17b_bs.csv",
            "control_openrouter/qwen/qwen3.5-397b-a17b_bs",
            "control",
            8,
            "carry-forward",
        ),
        (
            "cogpath_results/cogpath/cogpath_qwen3-coder_30b-a3b_q8_0_wo_cs.csv",
            "control_ollama/qwen3-coder:30b-a3b-q8_0_bs",
            "control",
            3,
            "raw",
        ),
        (
            "cogpath_results/cogpath/cogpath_qwen3-coder_30b-a3b_q8_0_deepseek-v3.csv",
            "control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_mcts_deepseek-v3",
            "control",
            3,
            "raw",
        ),
    )

    def _regenerate(self, run_label, prompt_type, iterations, fill):
        from .aggregate import write_class_level

        run_dir = RESULT_FILES / run_label
        class_list = ClassList.load()
        run = read_run(
            run_dir,
            class_list,
            prompt_type=prompt_type,
            max_iterations=iterations,
            missing=fill,
        )
        rows = class_level_rows(run.records, iterations)
        out = EVAL_DIR / "_selftest_regen.csv"
        write_class_level(out, rows, iterations)
        data = out.read_bytes()
        out.unlink(missing_ok=True)
        return data

    def test_checked_in_class_csvs_reproduce(self):
        checked = 0
        for rel, run_label, prompt_type, iterations, fill in self.CASES:
            target = EVAL_DIR / rel
            if not target.exists() or not (RESULT_FILES / run_label).is_dir():
                continue
            with self.subTest(csv=rel):
                self.assertEqual(
                    self._regenerate(run_label, prompt_type, iterations, fill),
                    target.read_bytes(),
                    "{} no longer reproduces byte-for-byte".format(rel),
                )
            checked += 1
        if checked == 0:
            self.skipTest("no checked-in CSV with raw result trees available")


if __name__ == "__main__":
    unittest.main(verbosity=2)
