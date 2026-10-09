# AGENTS.md — `CogPath/` implementation and evaluation

This file **adds to** the workspace-level [`../AGENTS.md`](../AGENTS.md). Read that first;
it covers repository topology, the never-bulk-stage rule, and the harness-is-destructive
rule. This file covers the code itself.

For a human-readable tour, see [`README.md`](README.md).

---

## 1. Orientation

| I want to… | Start here |
| --- | --- |
| Understand the method | [`../paper/sections/methodology.tex`](../paper/sections/methodology.tex), then [`docs/constraints_hints_subsection.md`](docs/constraints_hints_subsection.md) and [`docs/backward_slicing_subsection.md`](docs/backward_slicing_subsection.md) |
| Find the main loop | `src/cogpath/cogpath.py` → `Cogpath.run` |
| Find prompt construction | `src/cogpath/prompt_builder.py` → `build_prompt_cfa_guided` (:444) |
| Change a prompt | `src/cogpath/prompt_templates/**/*.toml` |
| Find the Constraint-Hints step | `src/cogpath/llm_constraint_solver.py` → `generate_constraints` (:116) |
| Find the Backward Slicing step | `src/cogpath/llm_backward_slicer.py` → `slice` (:108) |
| Find LLM plumbing | `src/cogpath/model_invocation/llm_invocation.py` |
| Find coverage parsing | `src/cogpath/coverage/jacoco_coverage.py`, `jacoco_parser.py` |
| Reproduce or run an experiment | `evaluation/experiments/README.md` + `evaluation/experiment.py` |
| Turn a finished run into CSVs | `evaluation/README.md` + `evaluation/collect_results.py` (`cogpath_eval/`) |
| Reproduce a table | `evaluation/` (see the traceability notes in `README.md`) |

Module-by-module map: [`README.md`](README.md#architecture).

---

## 2. Environment reality check — read before promising a run

The tool **cannot run end-to-end on this workstation as configured**. Verified:

- `conda` — not installed
- `poetry` — not installed
- `mvn` — not installed
- `java` — binary present but **no runtime** (`java -version` → "Unable to locate a Java Runtime")
- `python3` — **3.14.5**, outside the project's `>=3.9,<3.13` window

Minimum to make it runnable: a Python 3.9–3.12 environment (conda env from
`cogpath-env.yml`, or pyenv/venv + `pip install -e .`), a JDK 8+, and Maven 3.6.3+.

**Do not widen the Python constraint in `pyproject.toml` as a shortcut.** The pins
(`litellm==1.63.2`, `openai==1.64.0`, `numpy ^1.26`) will not install on 3.13+.

If a task requires running the tool and the prerequisites are missing, **report that and
stop** rather than half-installing a toolchain or inventing results.

---

## 3. Hard constraints

### C1 — No test suite exists
`pytest` is declared, but **zero tests are tracked**. Do not claim "tests pass". Your
verification options, in increasing cost:

```bash
# 1. syntax / import check (needs deps installed)
cd CogPath && python -c "import cogpath.prompt_builder"
# 2. compile-only check (works even without deps).
#    NOTE: src/cogpath/version.py is a bare version string, not Python, so a plain
#    `compileall src/cogpath` ALWAYS fails on it. Exclude it:
cd CogPath && python -m compileall -q -x 'version\.py' src/cogpath
# 3. config-only check (stdlib-only, no deps needed)
cd CogPath && PYTHONPATH=src python -c "import cogpath.config_validation, cogpath.run_label, cogpath.provenance"
# 4. single-subject run (slow, paid, needs JDK+Maven+API key)
```

Use 2 as the default, 3 only when behaviour actually changed and the user asked for it.

### C2 — Never launch the full/parallel evaluation unprompted
`evaluation/execute_*.py` iterate 130 classes × up to 20 iterations × multiple LLM calls,
with Maven builds in between. That is hours and real money. One subject, or a stub.

### C3 — Prefer isolated experiment runs
`evaluation/experiment.py run` stores configs, reports, logs, task states, and
workspace copies under one `result-files/runs/...` directory. Use `--resume` with
the printed run directory after interruption. `execute_cogpath.py` is a wrapper
around this runner. Older scripts can still edit shared subject/config files, so
inspect their implementation before using them.

### C4 — `src/cogpath/cfg/src/comex/` is vendored third-party code
Read-only. Do not refactor, reformat, or "fix" it, and do not fold it into CogPath's own
style. If you must change it, say so loudly in the commit and in your report.

### C5 — The prompt allow-list is load-bearing
`src/cogpath/config_loader.py` (:5–24) lists every settings file explicitly. A new
`.toml` prompt is **silently ignored** until it is added there; a listed file that is
missing aborts startup with `FileNotFoundError`.

### C6 — Experiments go through manifests, not `config.ini`
Never produce an ablation or model sweep by editing `src/cogpath/config.ini`. Use the
manifest-driven runner:

```bash
cd evaluation
python experiment.py run --study experiments/studies/rq2_ablation.yaml \
    --variant w_o_cs_bs --model <litellm-model-id> --dry-run   # inspect first
# After run/resume, use the concrete run directory printed by the runner.
python experiment.py verify --run-dir "$RUN_DIR"
```

The runner never writes `config.ini`; it generates a per-class config under the run
directory. See `evaluation/experiments/README.md`. The legacy `execute_*.py` drivers are
pinned to full CogPath and can no longer express ablations.

### C7 — Don't commit generated artifacts
Keep out of Git: `result-files/**` (except when intentionally publishing raw results),
`logs/**`, `evaluation/coverage_statistics*.csv`, `evaluation/pass_rate_statistics.csv`,
`config_<thread>_*.ini`, `src/cogpath/*.json`, `src/cogpath/*.html`, and anything under
`defects4j-subjects-notests/*/target/`.

---

## 4. Landmine index

Each entry: **symptom → cause → what to do.** Line numbers are as of this writing; verify
before relying on them.

| # | Symptom | Cause | Action |
| --- | --- | --- | --- |
| L1 | Ollama models hang/fail | `model_invocation/llm_invocation.py:52` hard-codes `api_base = "http://210.28.134.33:11434"` (a lab host). No config knob. | Make it read from config/env if you need portability; otherwise document the dependency. |
| L2 | `ModuleNotFoundError: ollama` / `javalang` on a clean install | `llm_invocation.py:6` imports `ollama`; `file_access_interface.py:10` imports `javalang`. **Neither is in `pyproject.toml` or `cogpath-env.yml`.** | Add them to `pyproject.toml` (and ideally the conda snapshot) before claiming a reproducible install. |
| L3 | ~~Run finishes instantly with 0 % coverage, "iteration stops due to error"~~ | **FIXED**: both optional analysers are now initialised to `None` before conditional construction, so `use_backward_slice=false` no longer raises `AttributeError` (which the loop's `try/except` used to swallow). Slice-phase token accounting was also fixed — `_generate_tests_from_slice` now returns `(tests, tokens)` and `cogpath.py` adds them instead of hard-zeroing. | No action. If you see a silent 0 % run again, look for another swallowed exception inside `cogpath.py`'s `try/except`. |
| L4 | Prompts come out empty and generation quality collapses | `prompt_builder.py:567–569` catches all Jinja2 render errors and returns `{"system": "", "user": ""}`. `StrictUndefined` is set, but the error is swallowed. | Raise/regenerate instead of returning empty; at minimum log at ERROR with the exception. |
| L5 | A valid-looking test is silently dropped | `unit_test_generator.py:568` discards any LLM response containing `Congress`, `government`, `policy`, or `politics`. | Broaden the check or make it configurable; be aware when debugging "missing" tests. |
| L6 | Editing a TOML prompt has no effect | The solver/slicer classes embed fallback templates (`llm_constraint_solver.py:58`, `llm_backward_slicer.py:56`) used when the settings key is absent. | Edit the TOML **and** confirm which path is taken; if unsure, make the fallback raise. |
| L7 | New results are nested under `result-files/runs/` | Each run path groups study/model/variant/repetition/run-id, and task artifacts are below `tasks/<project>/<class>/attempts/`. The extractor reads completed task states; legacy label paths remain supported. | Intended run layout; use the run directory printed by `experiment.py`. |
| L8 | Coverage never moves | `run_coverage` (`unit_test_generator.py:114`) treats a non-zero exit from `test_execution_command` as fatal, and depends on `code_coverage_report_path` being regenerated by that command. Relative paths resolve against the **repo root**, while the command runs in `test_code_command_dir`. | Verify by hand: run `test_execution_command` in `test_code_command_dir` and confirm the JaCoCo CSV appears and has a fresh mtime. |
| L9 | The ablation configs don't reproduce | Historically `execute_cogpath.py` hard-coded `use_backward_slice=true` and the other drivers omitted the factors entirely, so an ablation was produced only by hand-editing `config.ini`. | **Addressed** by `evaluation/experiment.py` + `experiments/studies/*.yaml`. The *published* columns still need re-running — see `experiments/legacy_map.yaml`, where the confounded runs are flagged. |
| L10 | `plot_branch_coverage.py` fails / writes nowhere | Absolute Linux paths at `evaluation/cogpath_results/plot_branch_coverage.py:35–37`, and the input CSV `branch_coverage_4configs_8iter.csv` **is not in the repo**. | Rewrite paths to be relative if asked, but note the missing input — the figure is not regenerable from checked-in data. |
| L11 | Tables in `paper/` drift from the results | No script emits `paper/tables/*.tex`; numbers were transcribed by hand from `evaluation/cogpath_results/**/*.csv`. There is **no** `coverage_statistics.xlsx`, contrary to `evaluation/README.md`. | Treat table edits as manual, cross-repo, and explicitly reported. Also: `paper/tables/rq2_ablation.tex` has a verified wrong Jsoup cell (69.11/53.76 vs 66.43/52.55) — flag, don't silently fix. |
| L12 | First run stalls, or fails with git/compiler errors, or re-downloads grammars every prompt | `cfg/src/comex/__init__.py` `get_language_map()` `git clone`s tree-sitter grammars into `$TMPDIR/comex` and rebuilds `languages.so` via `Language.build_library`. A new `PromptBuilder` is built per generation *and* per repair (`unit_test_generator.py:232`, `:525`). | Requires network + `git` + a C compiler at runtime; keep the `tree-sitter` 0.20.x pin (`build_library` was removed later). Cache or pre-build if you need offline runs. |
| L13 | Runtime import errors under a minimal install | `networkx`, `tree-sitter`, `loguru` (needed by the vendored CFG) are only in `[tool.poetry.group.dev.dependencies]`; `PyYAML` isn't declared in `pyproject.toml` at all. | Move them to main dependencies before claiming a reproducible install. |
| L14 | Model requests ignore provider/model settings | Model invocation now resolves the selected model through LiteLLM and optional model profiles. | Keep API credentials in environment variables or local untracked profiles; inspect the resolved config before a run. |
| L15 | `coverage_type = pycov` crashes; `.py` sources crash | `pycov_coverage.parse_coverage_report()` is `pass` (returns `None`); `CFGDriver.CFG_map`/`ParserDriver.parser_map` have no `"python"` key. | Python is unsupported in practice — don't try to "enable" it without implementing both halves. |
| L16 | SymPrompt baseline reports near-zero passing tests | The parsed-test container shape was corrected so `validate_test` receives the expected mapping. | Re-run the target case and inspect its report before trusting older outputs. |
| L17 | `included_files` silently does nothing | `main.py:30` reads a string; `get_included_files` (`unit_test_generator.py:184–212`) iterates it per character. | Leave empty, or fix the type handling. |
| L18 | Generated tests vanish after a run | Cleanup restores pre-existing tests and removes only files created by the run; experiment runs preserve outputs and logs in their attempt directory. | Inspect the run's `tasks/<project>/<class>/attempts/` folder. |

---

## 5. Common task recipes

### Add or change a prompt template
1. Add/edit the `.toml` under `src/cogpath/prompt_templates/`.
2. If new, register its path in `SETTINGS_FILES` (`config_loader.py:5–24`).
3. Reference it with `get_settings().<key>.system` / `.user`.
4. Check the fallback in `_load_prompt_template` / `_get_default_template` of the consuming
   class, and keep them consistent.
5. `python -c "import cogpath.config_loader as c; c.get_settings()"` to confirm it loads.

### Add a configuration option
1. Declare it in `src/cogpath/config_validation.py`: add it to `STR_KEYS`, `INT_KEYS`,
   `PLAIN_BOOL_KEYS` (or `FACTOR_BOOL_KEYS` / `FACTOR_OTHER_KEYS` if it is an experimental
   factor), with a default. Types, defaults and unknown-key rejection all live there.
2. Add it to `src/cogpath/config.ini` with the same default, so ad-hoc runs work.
3. Add a cross-field rule in `check()` if the option can contradict another one.
4. `main.py` picks it up automatically via `to_namespace_fields` — no change needed there.
5. Thread it through `Cogpath.__init__` → `UnitTestGenerator.__init__` if it reaches the tool.
6. Document it in the configuration table in
   [`README.md`](README.md#configuration-reference).
7. If a *staged* experiment needs it, add it to a study manifest — do **not** add it to
   `execute_*.py`, which are frozen.

### Add or adjust a baseline
`symprompt.py` and `hits.py` each own their prompt plumbing and are driven by
`Cogpath.run_symprompt` / `run_hits` (`cogpath.py:374`, `:421`). Dispatch is in `main.py`
via `run_symprompt` / `run_hits`. Note the paper's footnote: HITS was **re-implemented**
because the official repository was incomplete — preserve that provenance in comments.

### Debug a single class
1. Point `config.ini` at the one class (`project_directory`, `source_code_file`,
   `test_code_file`, `code_coverage_report_path`, `test_execution_command`).
2. Reduce `maximum_iterations` (e.g. 3) and keep `target_coverage` at 100.
3. Run `python -m cogpath.main` from `CogPath/`, and read
   `logs/<label>/<project>.log` (DEBUG level) — the rendered prompts are logged there.
4. Restore `config.ini`: `git checkout src/cogpath/config.ini`.

---

## 6. Code conventions

- **Style**: match the surrounding file. The codebase uses 4-space indent, `snake_case`
  functions/variables, `PascalCase` classes, type hints on new public methods, and a
  module-level `self.logger` obtained from `cogpathLogger.initialize_logger(__name__)`.
- **Logging**: use the injected logger, not `print`. `print` is used in places
  (`models.py`, `llm_invocation.py` streaming) — don't add more.
- **Comments**: keep existing comments; several encode non-obvious rationale (e.g. the
  `mvn` command is executed in the run-local project workspace by `experiment.py`).
- **Imports**: absolute intra-package imports (`from .prompt_builder import PromptBuilder`).
- **Language**: code comments and docstrings are English. Some evaluation scripts and
  `docs/` contain Chinese — match the file you are editing rather than translating it.
- **Prompt text**: prompts are user-facing research artifacts. Change wording deliberately
  and note it in your report; a prompt edit is a *result-affecting* change, not a refactor.

---

## 7. Definition of done

Before reporting a code task complete:

1. `python -m compileall -q -x 'version\.py' src/cogpath` passes (`version.py` is a bare
   version string, not Python, so it must be excluded). Also run the stdlib-only checks:
   `PYTHONPATH=src python -c "import cogpath.config_validation, cogpath.run_label, cogpath.provenance"`
   and, if you touched the analysis pipeline, `cd evaluation && python -m cogpath_eval.selftest`.
2. You state precisely what you executed and what you could not (missing JDK/Maven/conda
   counts as "could not").
3. `git status` is clean of accidental artifacts; `config.ini` is unmodified.
4. If you changed behaviour, you updated the relevant section of
   [`README.md`](README.md) — especially the configuration table and the landmine list.
5. If you changed anything that affects a reported number, you flagged that the paper's
   tables must be updated **by hand** and did not silently rewrite them.
