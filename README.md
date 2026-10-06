# CogPath

**CogPath: A Constraint-Guided Context-Reduction Framework for LLM-Based Test Generation.**

CogPath generates JUnit tests for complex Java methods using an LLM inside an iterative
*generate → execute → repair* loop. Its distinguishing features are two analyses that
realign the prompt with the branch being targeted:

- **Constraint-Hints (CS)** — an LLM externalizes the sufficient conditions for reaching
  the first uncovered branch on a selected CFG path; those conditions are injected into the
  generation prompt as explicit hints.
- **Backward Slicing (BS)** — when coverage plateaus, an LLM rebuilds the prompt around
  only the statements, object states, and setup calls that can influence one specific
  uncovered predicate, discarding the rest of the method body.

This repository also contains the **evaluation harness** used for the paper's tables and
figures, plus re-implementations of two baselines (SymPrompt, HITS).

> This directory is one of two sibling repositories. For the manuscript and the workspace
> overview, see [`../README.md`](../README.md). For working rules, see
> [`AGENTS.md`](AGENTS.md) (and [`../AGENTS.md`](../AGENTS.md) for workspace-wide rules).

---

## Table of contents

- [Repository layout](#repository-layout)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration reference](#configuration-reference)
- [Configuration validation](#configuration-validation)
- [Running CogPath](#running-cogpath)
- [Experiments](#experiments)
- [Prompts](#prompts)
- [Outputs](#outputs)
- [Architecture](#architecture)
- [Evaluation harness](#evaluation-harness)
- [Replicating the paper's tables and figures](#replicating-the-papers-tables-and-figures)
- [Known issues and caveats](#known-issues-and-caveats)
- [Citation](#citation)

---

## Repository layout

```
CogPath/
├── src/cogpath/                  # the tool
├── evaluation/                   # benchmark harness, data, parsed results, figures
├── result-files/                 # raw per-class HTML reports + path-history JSON
├── defects4j-subjects-notests/   # 14 checked-out Defects4J v2.0.1 subjects
├── docs/                         # design notes for CS and BS
├── cogpath-env.yml               # conda environment snapshot
├── pyproject.toml                # Poetry project + `cogpath` console script
└── config.ini → src/cogpath/config.ini   # single-subject configuration
```

`src/cogpath/` in detail:

```
main.py                  CLI entry point (`python -m cogpath.main`)
cogpath.py               orchestration: the iterative loop, report writing
unit_test_generator.py   prompt dispatch, LLM call, test validation, repair
prompt_builder.py        CFG path enumeration, path selection, prompt assembly
llm_constraint_solver.py Constraint-Hints (CS)
llm_backward_slicer.py   Backward Slicing (BS)
symprompt.py, hits.py    baseline re-implementations
templates.py             JUnit 3/4/5 test-class skeletons
error_message_parser.py  compiler/runtime error extraction for the repair prompt
yaml_parser_utils.py     tolerant YAML parsing of LLM responses
report_generator.py      HTML report writer
logger.py, utils.py, command_executor.py, file_access_interface.py
config_loader.py         Dynaconf loader for the prompt templates
config_validation.py     config schema, coercion and cross-field validation (stdlib-only)
provenance.py            run_meta / resolved-config / summary records (stdlib-only)
run_label.py             result-directory naming for a config (stdlib-only, shared)
coverage/                JaCoCo (Java) and coverage.py (Python) adapters
model_invocation/        litellm-based LLM clients
cfg/src/comex/           VENDORED third-party CFG/DFG parser (see below)
prompt_templates/        ALL prompts as .toml files
```

---

## Requirements

| Requirement | Version | Why |
| --- | --- | --- |
| Python | **3.9 – 3.12** (`pyproject.toml`: `>=3.9,<3.13`) | pinned deps (`numpy ^1.26`, `litellm 1.63.2`) do not support newer interpreters |
| JDK | 8+ | subjects are Java; Java ≤ 8-era sources with modern Maven plugins |
| Maven | 3.6.3+ | `mvn clean package -Dtest=…` is the test/coverage driver |
| **`git` + a C compiler + network access** | any | **at runtime**: the vendored CFG parser git-clones two tree-sitter grammars and recompiles `languages.so` on *every* prompt construction (see [Known issues](#known-issues-and-caveats) #11) |
| LLM API key | e.g. `OPENROUTER_API_KEY`, `OPENAI_API_KEY` | read by `litellm`, not by this code |
| `defects4j` | v2.0.1 checkout | only needed to *regenerate* `defects4j-subjects-notests/` |

### ⚠️ Status on the current workstation

Verified at the time of writing, and **none of the documented environment is installed**:

| Tool | Status |
| --- | --- |
| `conda` | **not installed** |
| `poetry` | **not installed** |
| `mvn` | **not installed** |
| `java` | binary present, but **no JRE/JDK found** (`java -version` → "Unable to locate a Java Runtime") |
| `python3` | `/opt/homebrew/bin/python3` is **3.14.5** — outside the supported range |

Consequence: **the tool cannot currently be run end-to-end on this machine.** You must
first install a Python 3.9–3.12 environment (conda or `pyenv` + `venv`), a JDK, and Maven.
This is a prerequisite gap, not a code defect. Do not "fix" it by loosening the version
constraint in `pyproject.toml` — the pinned dependency set will not install on 3.13+.

---

## Installation

The repo ships **two, partly divergent** dependency specifications. Prefer the conda
snapshot if you want the environment that produced the results; prefer Poetry for
development.

### Option A — conda (closest to the recorded environment)

```bash
cd CogPath
conda env create -f cogpath-env.yml      # env name: cogpath, Python 3.9.19
conda activate cogpath
pip install -e .                         # optional: installs the `cogpath` entry point
```

### Option B — Poetry

```bash
cd CogPath
python3.11 -m venv .venv && source .venv/bin/activate
pip install poetry && poetry install
```

Notes:
- `poetry.lock` is **not tracked** (it is in `.gitignore`), so `poetry install` resolves
  versions afresh and is *not* hash-reproducible. `cogpath-env.yml` is the pinned record.
- `pyproject.toml` declares `numpy` twice (runtime and dev group) with different
  constraints — harmless, but expect Poetry to mention it.
- See [Known issues](#known-issues-and-caveats) for imported-but-undeclared modules that
  can make a clean install fail at import time.

### API keys

The code never reads environment variables itself; `litellm` does. Export whichever the
provider prefix in your `model` setting requires:

```bash
export OPENROUTER_API_KEY=...     # for model = openrouter/<vendor>/<model>
export OPENAI_API_KEY=...         # for model = gpt-4o-mini, ...
```

`AWS_*` credentials are needed for Bedrock models, GCP credentials for Vertex models.

---

## Configuration reference

Everything is driven by `[default]` in **`src/cogpath/config.ini`** — one subject per run.
`main.py` (`config_to_namespace`) maps each key to an `argparse.Namespace` field.

| Key | Type | Meaning |
| --- | --- | --- |
| `project_directory` | path | Root of the Maven subject, e.g. `defects4j-subjects-notests/JacksonXml-5f` |
| `source_code_file` | path | **The only** file the LLM is shown as the focal class |
| `test_code_file` | path | Test file the tool reads/writes (skeleton created if missing/empty) |
| `test_file_output_path` | path | If non-empty, the test file is copied here before the run |
| `code_coverage_report_path` | path | JaCoCo CSV to parse, e.g. `<project>/target/jacoco/jacoco.csv` |
| `test_execution_command` | shell | Run after each generation round; must produce the coverage report |
| `test_dependency_command` | shell | e.g. `mvn dependency:list …`; output is pasted into the prompt as available test deps |
| `test_code_command_dir` | path | cwd for both commands above |
| `included_files` | text | Extra file contents appended to the prompt |
| `junit_version` | 3 / 4 / 5 | Selects the test-class skeleton in `templates.py` |
| `model` | str | `litellm` model id. Short aliases (`gpt-4o`, `deepseek-v3`, …) are mapped by `model_invocation/models.py`; anything else is passed through, so `openrouter/openai/gpt-5.4-mini` works |
| `solver_model` | str | Optional separate model for Constraint-Hints; falls back to `model` |
| `coverage_type` | `jacoco` \| `pycov` | Which coverage adapter to instantiate |
| `report_filepath` | filename | HTML report name inside the run's result directory |
| `target_coverage` | int % | Line-coverage target τ (paper: 100) |
| `maximum_iterations` | int | `maxIter` (paper: 20) |
| `no_coverage_increase_iterations` | int | Λ: consecutive non-improving iterations before stopping (paper: 3) |
| `enable_fixing` | int | Repair rounds per iteration; `0` disables the repair phase |
| `run_symprompt` | bool | Run the SymPrompt baseline instead of CogPath |
| `run_hits` | bool | Run the HITS baseline instead of CogPath (absent from the shipped `.ini`; treated as false) |
| `prompt_type` | str | `control` → CFG-guided (the CogPath path); `coverage` → coverage-report prompt; anything else → baseline prompt |
| `use_constraints` | bool | **Enable Constraint-Hints** |
| `use_backward_slice` | bool | **Enable Backward Slicing** |
| `fix_type` | str | `MCTS` switches the repair prompt template; empty = plain repair |
| `pick_two_paths` | bool | Select two paths per method (highest missed-line impact + least-visited) instead of one |
| `additional_instructions` | text | Appended to the prompt verbatim |
| `max_slices_per_method` | int | HITS only; caps slices per method (absent → 5) |
| `provenance_file` | path | Optional JSON of run metadata, merged into `run_meta.json` (set by the experiment runner) |
| `dataset_file` | path | Class list the run belongs to; hashed into `run_meta.json` |

### Configuration validation

Configuration is coerced and validated **before** any LLM call or Maven build, by
`src/cogpath/config_validation.py`. Every problem is reported at once and the run is
refused with exit code 2, rather than surfacing as a crash or — worse — a silently
different experiment.

```bash
python -m cogpath.main --print-config     # validate, print the resolved config as JSON, exit
python -m cogpath.main --no-warn          # suppress warnings
```

What is enforced:

| Check | Why |
| --- | --- |
| The ablation factors (`use_constraints`, `use_backward_slice`, `fix_type`) must be **stated explicitly** in CogPath mode | a missing factor used to be inherited silently from the previous run — the root cause of the ablation defects |
| `use_constraints=true` requires `pick_two_paths=true` | the constraint solver is only called for the *second* candidate path, so otherwise no constraints are ever generated and the run silently degrades to `w/o CS` |
| `coverage_type` must be `jacoco` | `PycovCoverage.parse_coverage_report()` is a no-op and the CFG backend has no Python map |
| `model`/`solver_model` must not contain `deepseek-r1` | that branch replaces the request with a hard-coded SageMaker probe and discards the prompt |
| `run_symprompt` / `run_hits` are mutually exclusive | dispatch is `if/elif` |
| Unknown option names are rejected | a typo such as `use_constraint` previously did nothing |

Warnings (not errors) cover things that run but may not mean what you expect, such as a
non-empty `included_files` (iterated character-by-character) or an empty `solver_model`
(which then follows `model`).

> `solver_model` is intentionally left empty when unspecified rather than resolved to
> `model` in the config: it is part of the result directory name, so resolving it early
> would silently rename every run. Consumers fall back with `solver_model or model`.

---

## Running CogPath

```bash
cd CogPath                                   # must be the repo root: relative paths in config.ini
export OPENROUTER_API_KEY=...

python -m cogpath.main                       # uses src/cogpath/config.ini
python -m cogpath.main -c /path/to/other.ini # explicit config
```

The console script installed by Poetry is equivalent: `cogpath`.

Dispatch (`main.py`):

```
run_symprompt → Cogpath.run_symprompt()
run_hits      → Cogpath.run_hits()
otherwise     → Cogpath.run()        # the CogPath loop
```

### What `Cogpath.run()` does

1. `initial_test_suite_analysis_AST()` — locate the insertion points and skeleton.
2. Loop while `line_coverage < target_coverage` **and** `iterations < maximum_iterations`
   **and** `no_coverage_increase < no_coverage_increase_iterations`:
   - iteration 0 → `generate_init_tests()` (baseline prompt);
   - later iterations → `generate_tests()` (CFG-guided prompt, with Constraint-Hints if
     `use_constraints`);
   - if `use_backward_slice` **and** `no_coverage_increase >= 0.6 × Λ` (β = 0.6 hard-coded
     at `cogpath.py:51`) → `generate_tests_by_slice()`;
   - validate every candidate individually (`validate_test`), then
     `fix_failed_tests()` for up to `enable_fixing` rounds;
   - `run_coverage()` — re-run the test command and re-parse JaCoCo.
3. Write the HTML report and `<report>_path_history.json` into `result-files/<label>/`,
   then delete the test file.

### Running a single subject quickly

Edit `src/cogpath/config.ini` to point at one subject and lower the budget, then run
`python -m cogpath.main`. To do this without permanently dirtying the tracked file, copy it
and pass `-c`, or `git checkout src/cogpath/config.ini` afterwards.

---

## Experiments

> **For any ablation or model sweep, use the manifest-driven runner — not hand-edited
> `config.ini`.** Full documentation:
> [`evaluation/experiments/README.md`](evaluation/experiments/README.md).

```bash
cd evaluation

python experiment.py list    --study experiments/studies/rq2_ablation.yaml
python experiment.py resolve --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0
python experiment.py run     --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0 --dry-run
python experiment.py run     --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0
python experiment.py verify  --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0   # exit 1 if incomplete
```

Why it exists: ablations used to be produced by editing `config.ini` by hand between
sweeps. The drivers wrote only some keys and merged into the existing file, so unset
keys inherited the previous run's values, and the only record of what ran was the result
directory name. Four verified defects in the published artifacts trace back to that.
The runner replaces it with:

* **declarative manifests** whose variant names match the paper's column names;
* a **factor model** in which `repair` (`fix_type`) is an explicit factor, so it can no
  longer co-vary with CS/BS by accident;
* **resolution + validation** that is printable (`resolve`) and side-effect-free
  (`--dry-run`);
* **provenance written by the tool** — `config.resolved.json`, `run_meta.json`
  (config hash, git commit/dirty, dependency versions, all 20 prompt-template hashes,
  dataset hash) and a per-class `<report>_run_summary.json`;
* a per-class **`evaluation/runs_index.jsonl`**, so provenance is never inferred from a
  directory name;
* a **completeness gate** (`verify`) that refuses incomplete runs — this is what would
  have caught the RQ3 Qwen column being built from a 2-of-130 run.

Any litellm model id works without editing a manifest, so new backbones need no code
change:

```bash
python experiment.py run --study experiments/studies/rq3_models.yaml \
    --variant cogpath --model openrouter/anthropic/claude-sonnet-4
```

Note that the manifest's `maximum_iterations` overrides the historical per-class budget.
The legacy drivers set the iteration budget to each class's own cyclomatic complexity;
`base.yaml` sets a uniform 20 to match the protocol the paper states. Pick one
deliberately — the two are not mixed silently.

---

## Prompts

**All prompts are data, not code.** They live in `src/cogpath/prompt_templates/` as TOML
and are loaded by Dynaconf through an explicit allow-list in `config_loader.py`
(`SETTINGS_FILES`).

```
prompt_templates/
├── java_templates/
│   ├── test_generation_prompt_baseline.toml
│   ├── test_generation_prompt_with_code_coverage_report.toml
│   ├── test_generation_prompt_with_existing_test_code_and_control_flow_analysis.toml
│   ├── ..._and_constraint_solver.toml          ← CogPath's main generation prompt
│   ├── constraint_solving_prompt.toml          ← Constraint-Hints
│   ├── backward_slice_test_generation.toml     ← generation from a validated slice
│   ├── failed_test_feedback_prompt.toml        ← repair
│   ├── failed_test_feedback_prompt_with_MCTS.toml
│   ├── analyze_suite_test_insert_line.toml
│   └── test_headers_indentation_prompt.toml
├── slicer_templates/backward_slice.toml        ← the slicing analysis prompt
├── hits_templates/{gen_slice,gen_code,test_repair}.toml
├── python_templates/                           ← Python-target variants
└── language_extensions.toml
```

**Two rules when editing prompts:**

1. Templates are rendered by Jinja2 with `StrictUndefined` — referencing an undefined
   variable does **not** raise, it silently produces an empty prompt (the render is wrapped
   in a `try/except` that returns `{"system": "", "user": ""}`). If output looks empty, that
   is why.
2. A new `.toml` file is invisible until it is added to `SETTINGS_FILES` in
   `config_loader.py`. A listed-but-missing file aborts startup with `FileNotFoundError`.

---

## Outputs

For a run with `prompt_type=control`, `model=openrouter/openai/gpt-5.4-mini`,
`use_constraints=true`, `use_backward_slice=true`, the report label becomes
`control_openrouter/openai/gpt-5.4-mini_constraints_bs` — the model id keeps its `/`, so
results nest:

```
result-files/
└── control_openrouter/openai/gpt-5.4-mini_constraints_bs/
    ├── ToXmlGenerator_control_test_results.html          # per-test status + coverage table
    └── ToXmlGenerator_control_test_results_path_history.json
```

The JSON holds per-iteration line/branch coverage, missed lines/branches, the path-visit
history, and the final plateau state — this is the best source for per-iteration plots.

Logs go to `logs/<prompt_type>_<model>[_constraints][_mcts]/<project>.log`
(`logger.py`), created relative to the repo root. `logs/` is not currently in
`.gitignore`.

### Report label composition

```
<prompt_type>_<model>[_constraints][_mcts][_bs][_<solver_model>]
```
with `mcts` only when `fix_type=MCTS`, and `bs` only when `use_backward_slice`.

---

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │ cogpath.py — Cogpath.run()  (the loop)       │
                    └───────┬──────────────────────────────┬───────┘
                            │                              │
              ┌─────────────▼─────────────┐   ┌────────────▼─────────────┐
              │ prompt_builder.py         │   │ unit_test_generator.py   │
              │  • CFG via cfg/src/comex  │   │  • build_prompt dispatch │
              │  • enumerate feasible     │   │  • LLM call              │
              │    paths                  │   │  • validate_test         │
              │  • pick_two_paths /       │   │  • fix_failed_tests      │
              │    pick_path (pathHistory)│   └────────────┬─────────────┘
              │  • render Jinja2 TOML     │                │
              └────────┬──────────────────┘                │
                       │                                   │
      ┌────────────────▼───────────┐         ┌─────────────▼─────────────┐
      │ llm_constraint_solver.py   │         │ coverage/                 │
      │   Constraint-Hints (CS)    │         │  jacoco_coverage.py       │
      ├────────────────────────────┤         │  jacoco_parser.py         │
      │ llm_backward_slicer.py     │         │  pycov_coverage.py        │
      │   Backward Slicing (BS)    │         └───────────────────────────┘
      └────────────────────────────┘                     │
                       │                                 │
                  model_invocation/llm_invocation.py (litellm, streaming)
                       │
                  command_executor.py → mvn clean package -Dtest=…
```

Key entry points, for orientation:

| Concern | Function |
| --- | --- |
| Iteration loop, termination, reporting | `cogpath.py` → `Cogpath.run` |
| Prompt type dispatch | `unit_test_generator.py:214` → `UnitTestGenerator.build_prompt` |
| CFG-guided prompt + path selection + CS injection | `prompt_builder.py:444` → `build_prompt_cfa_guided` |
| Path ranking | `prompt_builder.py:189` / `:214` → `pick_two_paths` / `pick_path` |
| Constraint-Hints | `llm_constraint_solver.py:116` → `generate_constraints` |
| Backward slice analysis | `llm_backward_slicer.py:108` → `slice` |
| Test validation + insertion | `unit_test_generator.py:602` → `validate_test` |
| Repair | `unit_test_generator.py:784` → `fix_failed_tests` |
| Coverage | `unit_test_generator.py:114` → `run_coverage` |
| Config validation | `config_validation.py` → `normalise_and_validate` |
| Result directory name | `run_label.py` → `report_label` (verified against all 12 existing directories) |
| Run provenance | `cogpath.py` → `write_provenance`; `provenance.py` |

### Vendored code

`src/cogpath/cfg/src/comex/` is **third-party vendored code** (the CoMEX code-views
package) providing Java/C# parsing, control-flow graphs, and combined CFG/DFG views. It is
not part of CogPath's contribution: treat it as read-only, and do not restructure it. It
carries its own `setup.py`, `setup.cfg`, and READMEs (`cfg/README.md`,
`cfg/README-comex.md`). Check those files for provenance/licence before redistributing.

---

## Evaluation harness

`evaluation/` contains the scripts, the curated dataset, the parsed result CSVs, and the
figure sources. See [`evaluation/README.md`](evaluation/README.md) for the short version.

### Dataset

- `defects4j-subjects-notests/` — 14 Defects4J *fixed versions* with their test suites
  removed (Chart, Mockito, Closure excluded as non-Maven/deprecated).
- `evaluation/data/class_list.csv` — the 130 selected classes and their max cyclomatic
  complexity. **Manually curated input**: no script in the repo writes it; the runners only
  read it.
- `evaluation/data/d4j-fixed-version.csv`, `evaluation/data/subject_statistics.csv`.
- `evaluation/defects4j-codefiles/<subject>-codefiles.json` — 14 per-subject indexes of
  methods-under-test and complexity; this is the source of the paper's 130 / 2,971 numbers.
- Paper totals: 130 classes, 2,971 methods with CC > 10.

To regenerate the subjects you need `defects4j`:

```bash
cd CogPath/evaluation/data          # NOTE: the script reads a bare `d4j-fixed-version.csv`
./../setup_d4j-subjects.sh           # clones defects4j at a pinned commit, checks out each subject
```

> The script's comment says "defects4j tag: v2.0.0" while the paper says v2.0.1. The pinned
> commit is the authority; this discrepancy is unresolved.

### Scripts

| Script | Purpose | Reads / writes |
| --- | --- | --- |
| `utils.py` | Shared helpers (glob source files, fuzzy src↔test pairing, token counting) | imported by `compute_statistics.py` |
| `compute_statistics.py` | Builds per-subject CFG/method/CC statistics | reads `data/d4j-fixed-version.csv`, `../defects4j-subjects-notests/**`; writes `defects4j-codefiles/*.json` and `subject_statistics.csv` in the CWD |
| `count_classes_with_high_complexity.py` | Counts classes passing the CC>10 / non-abstract / CC≤40 filter | reads `defects4j-codefiles/*.json`; **prints only — writes no file** |
| `execute_cogpath.py <prompt> <model> [--parallel -w N]` | Main CogPath runner, resume-aware | reads `data/class_list.csv`; writes `result-files/**` and a temp config |
| `execute_classes_with_high_complexity.py` | Same, sequential/older driver | writes `result-files/control_*` |
| `execute_symprompt.py <prompt> <model>` | SymPrompt baseline | writes `result-files/symprompt_*` |
| `execute_hits.py <prompt> <model>` | HITS baseline | writes `result-files/hits_*` (directory **hard-coded**, ignores the `prompt` argument) |
| `execute_classes_pick_one.py` | Legacy single-class driver | points at stale paths (`defects4j-subjects-reduced`, `../src`) — not usable as-is |
| **`collect_results.py`** / **`cogpath_eval/`** | **Current pipeline**: class-level and project-level CSVs from a run directory (stdlib only) | `class-level` / `project-level` / `all` / `runs` subcommands; see [`evaluation/README.md`](evaluation/README.md) |
| `parse_coverage_results.py`, `calculate_project_stats.py` | Deprecated thin delegators to `cogpath_eval` (legacy flags still work) | prints a deprecation note on stderr |
| `result-html-parser.py` | Older per-class parser | writes `coverage_statistics.csv` — but reads **non-existent** dirs (see below) |
| `result-parser-different-models.py` | Older per-model parser | writes `coverage_statistics_models.csv` — non-existent dirs |
| `extract_pass_rate.py` | Per-test PASS/FAIL rates | writes `pass_rate_statistics.csv`; **feeds no paper table** |
| `context_limit.py` | Counts rows whose prompt exceeded 64 k tokens | writes `pass_rate_statistics.csv` (**misnamed**, header-only) |
| `cogpath_results/plot_branch_coverage.py` | Branch-growth figure | **broken** — see [Known issues](#known-issues-and-caveats) #5 |
| `experiment.py` | **Manifest-driven runner**: `list` / `resolve` / `run` / `verify` / `backfill` | writes `runs_index.jsonl`; never edits `config.ini` |
| `subject_config.py` | Per-class subject paths (stdlib-only; legacy special cases preserved) | consumed by `experiment.py` |

The pipeline that actually produced the checked-in aggregates is:

```bash
cd CogPath/evaluation
python3 compute_statistics.py java                 # → defects4j-codefiles/*.json
python3 execute_cogpath.py control qwen3-coder:30b-a3b-q8_0 --parallel --workers 4
python3 parse_coverage_results.py \
    --result-dir ../result-files/<run> --class-list data/class_list.csv \
    --output cogpath_results/<run>.csv --prompt-type control
python3 calculate_project_stats.py \
    --input cogpath_results/<run>.csv --output cogpath_results/project_<run>.csv
```

> ⚠️ **The scripts do not agree on the working directory.** Most expect `evaluation/`
> (`data/class_list.csv`, `../../result-files/…`), but `count_classes_with_high_complexity.py`,
> `result-parser-different-models.py`, `extract_pass_rate.py`, `context_limit.py`, and
> `setup_d4j-subjects.sh` open **bare filenames** and must run from `evaluation/data/`.
> `result-html-parser.py` uses `../result-files` while `extract_pass_rate.py` uses
> `../../result-files` — only one can be right from a given directory. Expect
> `FileNotFoundError` if you follow the commands in `evaluation/README.md` verbatim.

### ⚠️ The harness mutates the tree

`execute_cogpath.py` and friends are **not read-only**:

- they rewrite `../src/cogpath/config.ini` (or create per-thread
  `config_<thread>_<uuid>.ini` files) and launch `python -m cogpath.main` with `cwd="../"`;
- they **rename** `<subject>/src/test/java` → `src/test/java_backup` and create their own
  test directory, so that Maven does not compile unrelated tests;
- they then remove the generated test file and restore state — but **an interrupted run can
  leave `*_backup` directories behind.**

Check `git status` and look for `src/test/java_backup` after any harness run. Do not run the
harness "just to see if it works": each class costs many paid LLM calls and minutes of
Maven.

### Checked-in vs. generated data

| Path | Nature |
| --- | --- |
| `evaluation/data/class_list.csv`, `d4j-fixed-version.csv`, `subject_statistics.csv`, `debug.txt` | curated inputs (checked in) |
| `evaluation/defects4j-codefiles/*.json` | 14 per-subject MUT/CC indexes (checked in) |
| `evaluation/cogpath_results/**/*.csv` | 22 curated per-class / per-project aggregates (checked in) |
| `evaluation/figures/branch_coverage_comparison.{png,pdf,svg}` | rendered figure (checked in) |
| `evaluation/cogpath_results/plot_branch_coverage.py` | script (checked in, **not portable and not runnable** — #5) |
| `evaluation/coverage_statistics*.csv`, `pass_rate_statistics.csv` | generated outputs (**not tracked**) |
| `result-files/**` | raw run outputs — ~1,729 HTML reports; coverage is broad but **not complete** (e.g. `symprompt_openrouter/qwen` has 37 of 130 classes) |

**`coverage_statistics.xlsx` does not exist** anywhere in either repository, despite
[`evaluation/README.md`](evaluation/README.md) naming it as the source of the tables.

### Raw result directory → paper configuration

The directory suffixes name what was **kept**, while the derived `project_*.csv` names say
what was **removed**. Under `result-files/control_ollama/`:

| Raw directory | Paper configuration |
| --- | --- |
| `…_constraints_bs` | CogPath (full) |
| `…_bs` | **w/o CS** |
| `…_constraints` | **w/o BS** |
| `…_mcts` | **w/o CS+BS** (the "Base" column) |
| `…_constraints_mcts_deepseek-v3` | the DS-V3.1 run |

---

## Replicating the paper's tables and figures

| Paper artifact | Source of truth |
| --- | --- |
| Table 1 — dataset | `evaluation/defects4j-codefiles/*.json` + `data/class_list.csv` → hand-copied to `../paper/tables/dataset.tex` |
| Table 2 — RQ1 coverage | `evaluation/cogpath_results/cogpath/*.csv` → `../paper/tables/rq1_main.tex` |
| Table 3 — RQ2 ablation | `cogpath_results` `wo_bs` / `wo_cs` / `mcts` runs → `../paper/tables/rq2_ablation.tex` |
| Table 4 — RQ3 models | `cogpath_results` per-model runs → `../paper/tables/rq3_different_llms.tex` |
| Figure 2 — branch growth | `evaluation/figures/branch_coverage_comparison.pdf` → `../paper/figures/` |

### The CSV pipeline

```bash
cd evaluation
python collect_results.py all \
    --label control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_bs \
    --prompt-type control --max-iterations 8 \
    --out-dir cogpath_results/cogpath --name <slug>
python -m cogpath_eval.selftest        # 11 tests, incl. byte-equality golden tests
```

Three semantics change the numbers, so choose them deliberately:

* `--max-iterations` — the checked-in CSVs are **inconsistent**: most used `3`, the
  three newer ones used `8`.
* `--fill {carry-forward,raw}` — `carry-forward` repeats the final value for an
  iteration the run never reached; `raw` leaves the cell empty. The 3-iteration CSVs
  used `raw`.
* `--source {html,json}` — HTML `g_N` rows are **pre-repair**, the `_path_history.json`
  sidecar is **post-repair**; they differ on 76 of 319 comparable points. `html` is
  the default and the only source comparable to published numbers.

`all` also writes `summary_<name>.csv` with both the paper's convention (unweighted
mean of the 14 project averages, 53.14 / 44.41) and the class-weighted mean
(53.18 / 45.71), which differ.

Two checked-in class-level CSVs are **stale** relative to the reports on disk
(`*_wo_bs.csv` differs in the iteration curve; `cogpath_deepseek-v3.1.csv` differs on
7 classes). Details and the full reproducibility table are in
[`evaluation/README.md`](evaluation/README.md).

**There is no automated path from result files to `paper/tables/*.tex`.** No script in the
repo writes a `.tex` file; the numbers were transcribed by hand. If you re-run the
benchmark you must update the LaTeX by hand, and say so explicitly in your commit message.
Averages in the tables are **unweighted means of the 14 per-project averages**, not pooled
per-class means (the two differ: e.g. CogPath pooled is 53.18 / 45.71 vs. the published
53.14 / 44.41).

> **Verified defect inherited from the data.** `../paper/tables/rq2_ablation.tex` gives
> Jsoup (CogPath) as `69.11 / 53.76`; `cogpath_results/cogpath/cogpath_qwen3-coder_30b-a3b_q8_0_constraints_bs_8iter.csv`
> gives `66.43 / 52.55`, matching Tables 2 and 4. The table's own average row
> (`53.14 / 44.41`) is reproduced exactly by `66.43 / 52.55`, not by the printed value.
> Confirm with the author before changing it.

---

## Known issues and caveats

These are verified observations from reading the repository, not speculation. Each is
worth checking before you rely on the behaviour.

1. **Hard-coded remote host.** `model_invocation/llm_invocation.py:52` forces the Ollama
   API base to `http://210.28.134.33:11434` — a specific lab machine. Any `ollama*` model
   will fail unless that host is reachable; there is no configuration knob for it.

2. **Imported but undeclared dependencies.** `llm_invocation.py:6` does `import ollama` and
   `file_access_interface.py:10` does `import javalang`, at module import time. **Neither is
   declared in `pyproject.toml`, and neither appears in `cogpath-env.yml`.** A clean install
   from the declared dependencies may therefore fail on import. Verify against the
   environment that actually produced the results before trusting a fresh install.

3. ~~**`self.backward_slicer` may not exist, and the failure is silent.**~~ **FIXED.**
   `UnitTestGenerator.__init__` now initialises both optional analysers to `None` before
   conditionally constructing them, so `use_backward_slice = false` no longer raises
   `AttributeError` (which the loop's `try/except` used to swallow, producing a silent run
   at baseline coverage). This was the blocker for the `w/o BS` ablation. The same fix
   applies to the slice phase's token accounting: `_generate_tests_from_slice` returned
   only the tests and dropped the token count, and `cogpath.py` then hard-zeroed
   `gen_token_count` — discarding the cost of *both* the slice phase and the generation
   phase for every iteration that triggered slicing. Slice tokens are now added.
   See [Configuration validation](#configuration-validation) and
   [`evaluation/experiments/README.md`](evaluation/experiments/README.md).

4. **The "w/o BS" ablation is not reachable through the shipped configuration.** The
   evaluation harness hard-codes `'use_backward_slice': 'true'` for every run, and the
   ablation variant is not selected by any CLI flag — the `wo_bs` result directories must
   have been produced another way. Do not assume re-running the documented commands
   regenerates the ablation.

5. **`plot_branch_coverage.py` is not portable.** It has absolute Linux paths baked in:
   `INPUT_CSV = '/mnt/data1/ljh/code/Panta/evaluation/cogpath_results/branch_coverage_4configs_8iter.csv'`
   and `OUTPUT_DIR = '/mnt/data1/ljh/code/Panta/evaluation/figures/'`. Furthermore that
   **input CSV is not in this repository**, so the paper's Figure 2 cannot be regenerated
   as-is from checked-in data. The rendered figure is checked in under `evaluation/figures/`.

6. **`prompt_builder.build_prompt_cfa_guided` swallows render errors.** The Jinja2 render is
   wrapped in `try/except` that returns empty prompts (line 567–569) and logs via the root
   logger. If generation quality suddenly collapses, check the prompt is non-empty.

7. **Irrelevant-response filter.** `generate_test_by_prompt_llm` discards any response
   containing "Congress", "government", "policy", or "politics" (line 568) — a safeguard
   against refusal/canned replies. It can silently drop legitimate tests whose text happens
   to contain one of those words.

8. **`_get_default_template` fallbacks.** Both `llm_constraint_solver.py` and
   `llm_backward_slicer.py` embed default prompt templates used if the TOML key is missing.
   Editing only the TOML, or only the fallback, will produce divergent behaviour depending
   on whether the settings loaded.

9. **`code_coverage_report_path` and paths in `config.ini` are relative to the repo root**,
   and `test_code_command_dir` is used as the `cwd` for both Maven commands. Run
   `python -m cogpath.main` from `CogPath/`, not from inside `src/`.

10. **No test suite.** Despite `pytest`, `pytest-cov`, `pytest-mock`, and `pytest-asyncio`
    being declared as dev dependencies, **no tests are tracked** in the repository. There is
    nothing to run; verification must be manual.

11. **The CFG parser clones from GitHub and compiles C at runtime — on every prompt build.**
    `cfg/src/comex/__init__.py` `get_language_map()` `git init`/`fetch`/`checkout`s the
    `tree-sitter-java` and `tree-sitter-python` grammars into `$TMPDIR/comex` and calls
    `Language.build_library(...)` to rebuild `languages.so`. A **new `PromptBuilder`** is
    constructed per generation round *and* per repair round
    (`unit_test_generator.py:232`, `:525`), so a network connection, `git`, and a C compiler
    are effectively hard runtime requirements. It also pins `tree-sitter` 0.20.x, because
    `Language.build_library` was removed in later releases.

12. **Some runtime dependencies are declared only in the dev group.** The vendored CFG needs
    `networkx`, `tree-sitter`, and `loguru`; in `pyproject.toml` all three sit under
    `[tool.poetry.group.dev.dependencies]`, so a production install
    (`poetry install --only main`) breaks at runtime. `PyYAML` is not declared in
    `pyproject.toml` at all — it exists only in `cogpath-env.yml`.

13. **`deepseek-r1` silently discards your prompt.** `llm_invocation.py:31–40` replaces the
    request with a hard-coded SageMaker endpoint
    (`sagemaker/endpoint-deepseek-r1-nashid`, `us-east-2`) and a hard-coded question
    ("Are you better than GPT-4o for test generation and why?"), ignoring the caller's
    `prompt`. Any run configured with `model = deepseek-r1` does not perform test generation.

14. **Python support is nominal.** `coverage_type = pycov` cannot work:
    `coverage/pycov_coverage.py` `parse_coverage_report()` is literally `pass`, so it returns
    `None` and the unpacking in `unit_test_generator.py:152` fails. `CFGDriver.CFG_map` and
    `ParserDriver.parser_map` contain only `java`/`cs`, so a `.py` source raises `KeyError` in
    `PromptBuilder.__init__`. The `python_templates/` prompts that *are* loaded are never
    selected, because prompt dispatch always requests the Java keys.

15. **The SymPrompt baseline has a result-shape bug.** `symprompt.py:162` wraps the parsed
    test in a list (`generated_tests[label].extend([generated_test['single_test']])`) while
    the template defines `single_test` as a list, so `validate_test` receives a `list` and
    calls `.get()` on it. The exception is caught and the affected tests are recorded as
    **FAIL without ever being compiled**. Treat the SymPrompt numbers with that in mind.

16. **`included_files` is iterated character by character.** `main.py:30` reads it as a raw
    string, but `UnitTestGenerator.get_included_files` (`:184–212`) loops over it expecting a
    list of paths, so every non-empty value produces one failed open per character (errors
    are only printed). Leave it empty unless you also fix the type handling.

17. **`cleanup_test_file()` deletes the generated test at the end of every mode**
    (`cogpath.py:173–183`, called from `run`, `run_symprompt`, and `run_hits`). Generated
    tests survive only inside the HTML report and the `_path_history.json` — do not expect to
    find the test sources afterwards.

18. **Coverage parsing is strict about freshness.** `Coverage.verify_report_update` requires
    the coverage report's mtime (ms) to be **strictly newer** than the test-command start
    time, otherwise it raises `AssertionError` — which `unit_test_generator.py:173–175`
    catches and re-raises. A cached/incremental Maven build that does not rewrite
    `jacoco.csv` aborts the run. Separately, the JaCoCo HTML path used by `jacoco_parser.py:75`
    is built from the *dotted* package name while JaCoCo lays packages out as directories; a
    missing HTML file raises `FileNotFoundError`, which is **not** in the caught exception
    list at `unit_test_generator.py:173–179`.

19. **`test_file_output_path` must differ from `test_code_file`.** `duplicate_test_file`
    (`cogpath.py:167–171`) calls `shutil.copy(a, a)` when the two are equal and non-empty,
    raising `shutil.SameFileError`. Only the empty-string case is handled.

20. **Constraint-Hints fire on a narrow path.** `prompt_builder.py:525–532` appends
    constraints only when `pick_two_paths=True`, a solver exists, and the two selected paths
    differ — and only for the *second* (least-visited) path. With `pick_two_paths=false` the
    constraint-solver prompt variant is still used but contains **no** constraints.

21. **Dead code that looks live.** `file_access_interface.py` (`FileAccessInterface`),
    `model_invocation/tool_calling_llm.py` (`ToolCalling*`), `AzureOpenAIInvocation`,
    `FilePreprocessor`, `PromptBuilder.build_prompt_backward` (whose `backward_analysis`
    variable is referenced by no template), `UnitTestGenerator.initial_test_suite_analysis`
    (the LLM variant), and the HITS `test_repair` template are **never invoked** in the
    current flow. Reading them as part of the pipeline will mislead you. Also note
    `java_templates/test_headers_indentation_prompt.toml` is *not* in `SETTINGS_FILES`,
    although a dead path requests it.

22. **Packaging: dynamic versioning points at a missing file.** `pyproject.toml` enables
    `poetry-dynamic-versioning` sourced from `src/cogpath/version.txt`, which does not exist
    (only `version.py`, containing `0.0.1`). Expect builds to fail or fall back to `0.0.0`.

---

## Citation

```bibtex
@inproceedings{cogpath2026,
  title     = {CogPath: A Constraint-Guided Context-Reduction Framework for LLM-Based Test Generation},
  author    = {Liu, Jianhan and Xu, Tangzhi and Yao, Yuan and Xu, Feng and Ma, Xiaoxing},
  booktitle = {IEEE International Conference on Software Analysis, Evolution and Reengineering (SCAM)},
  year      = {2026}
}
```

Replication package: <https://doi.org/10.5281/zenodo.19249603>
