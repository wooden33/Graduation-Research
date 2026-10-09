# Experiments: manifest-driven runs

This directory holds the declarative definition of every CogPath experiment and
the runner that executes them.

It replaces the old workflow, in which an ablation was produced by **hand-editing
`src/cogpath/config.ini` between sweeps**. The driver scripts wrote only *some*
keys and `fill_config` *merged* into the existing file, so every unset key
silently inherited whatever the previous run had left behind. The only record of
what actually ran was the result directory name — and that name encodes which
factors were **enabled**, not what the paper column means.

That produced four verified defects in the published artifacts:

| Where | What was published | What actually ran |
| --- | --- | --- |
| Table 3, `w/o CS+BS` | clean ablation base | also had the **MCTS repair prompt** enabled; the clean base was never aggregated |
| Table 4, QW3.5-397B | same config as RQ1 | Constraint-Hints **disabled** (the full run has 2 of 130 classes) |
| Table 4, DS-V3.1 | same config as RQ1 | Backward Slicing **disabled** (0 slice-test rows in the reports) |
| Table 3, Jsoup | 69.11 / 53.76 | 66.43 / 52.55 (the table's own average implies this) |

Each of these is now structurally prevented rather than merely fixed.

---

## Quick start

```bash
cd evaluation

# 1. What does this study contain?
python experiment.py list --study experiments/studies/rq2_ablation.yaml

# 2. What config would a variant produce? (no side effects)
python experiment.py resolve --study experiments/studies/rq2_ablation.yaml \
    --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0

# 3. What would a run do? (validates every class config, changes nothing)
python experiment.py run --study experiments/studies/rq2_ablation.yaml \
    --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0 --dry-run --limit 5

# 4. Run it (one run directory contains all class tasks)
python experiment.py run --study experiments/studies/rq2_ablation.yaml \
    --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0

# If interrupted, resume the same run directory printed by the command:
RUN_DIR=/absolute/path/printed/by/the/runner
python experiment.py run --study experiments/studies/rq2_ablation.yaml \
    --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0 \
    --resume "$RUN_DIR"

# Verify one complete run:
python experiment.py verify --run-dir "$RUN_DIR"
# exit 0 = complete, exit 1 = incomplete (do not publish)
```

`--dry-run` performs no writes at all: it does not create result directories, does
not write configs, and (unlike a real run) does not delete a pre-existing subject
test file.

---

## Studies

| Manifest | Purpose |
| --- | --- |
| `base.yaml` | shared defaults, the factor vocabulary, `repetitions` |
| `studies/rq2_ablation.yaml` | the 2 x 2 CS/BS ablation with repair held constant |
| `studies/rq1_main.yaml` | full CogPath |
| `studies/rq3_models.yaml` | full CogPath across backbones |
| `studies/baselines.yaml` | SymPrompt and HITS execution modes |
| `legacy_map.yaml` | provenance backfill for pre-manifest result trees |

---

## Manifest schema

```yaml
study: rq2_ablation          # identifier recorded in run provenance
extends: ../base.yaml        # optional; merged, child wins
description: >-              # free text, shown by `list`
  ...

dataset: data/class_list.csv # relative to evaluation/
repetitions: 1               # independent repetitions per variant/model

# Settings shared by every variant in this study.
fixed:
  prompt_type: control
  maximum_iterations: 20

# A factor is a named experimental variable.  Each level is a set of config
# overrides.  Level names must be quoted if they are YAML booleans ("on"/"off") —
# this repository uses `enabled`/`disabled` to avoid that trap entirely.
factors:
  constraint_hints:
    enabled: {use_constraints: true}
    disabled: {use_constraints: false}

# A variant is a full assignment of levels, and its name should match the paper's
# column name so the mapping is mechanical.
variants:
  cogpath:
    constraint_hints: enabled
    backward_slicing: enabled
    repair: traditional

# Optional per-model overrides.  Keys are litellm model ids.  Left empty by
# default so that `run` requires an explicit --model and can never sweep every
# model in a manifest by accident.
models:
  openrouter/qwen/qwen3.5-397b-a17b:
    solver_model: openrouter/openai/gpt-5.4-mini
```

### Resolution order

```
base.yaml fixed  →  study fixed  →  factor levels (in variant order)  →  model overrides  →  model
```

`resolve` prints the result, so the effective configuration is always inspectable
before anything runs.

### The factor model

The three factors that matter for the ablations are:

| Factor | Levels | Config key |
| --- | --- | --- |
| `constraint_hints` | `enabled` / `disabled` | `use_constraints` |
| `backward_slicing` | `enabled` / `disabled` | `use_backward_slice` |
| `repair` | `traditional` / `mcts_prompt` | `fix_type` |

`repair` exists because `fix_type` was previously an implicit variable: the
published `w/o CS+BS` run had it enabled, so that "ablation" varied two things at
once. There is no Monte-Carlo tree search in the code — `MCTS` only selects a
different repair prompt template — so the level is named `mcts_prompt` to say what
it really does.

---

## Running with a new model

Nothing in the manifests needs editing: any litellm model id is accepted.

```bash
python experiment.py run --study experiments/studies/rq3_models.yaml \
    --variant cogpath --model openrouter/anthropic/claude-sonnet-4
```

`run` refuses to start without an explicit `--model` (or a non-empty `models:`
mapping), because a sweep is 4 x 130 classes x up to 20 iterations of paid
inference and should never begin by accident.

Add an entry under `models:` only when a model needs overrides, for example a
different solver model for Constraint-Hints. `solver_model` is deliberately *not*
defaulted to `model` in the resolved config: it is part of the result directory
name, and resolving it early would silently rename every run.

Model names and provider settings are resolved through LiteLLM and optional model
profiles. Keep credentials in environment variables or the local profile file; do
not put API keys in experiment manifests or committed config files.

---

## What a run writes

Each variant/model/repetition gets a unique directory. All class tasks and their
outputs stay inside it:

```
result-files/runs/<study>/<model>/<variant>/rep-001/<run-id>/
├── run.json                         # identity, overall status and progress
├── resolved-config.json             # effective variant/model config
├── class_list.csv                   # dataset snapshot
├── <study>.yaml                     # manifest snapshot
├── tasks/<project>/<class>/
│   ├── state.json                    # resumable task state
│   ├── input-test.json               # whether the initial test existed
│   ├── input-test.snapshot            # original test contents, if any
│   └── attempts/001/
│       ├── config.ini                # exact config passed via --config
│       ├── stdout.log
│       ├── stderr.log
│       ├── token-usage.jsonl          # one redacted event per LiteLLM request
│       ├── provenance.json
│       └── artifacts/                # HTML, JSON summaries and path history
└── workspaces/<project>/             # run-local copy of each subject project
```

Resume skips a class only when its state is `completed`, the process exited with
code 0, and the recorded report still exists. Failed, interrupted, or unfinished
tasks get a new numbered attempt; prior logs and artifacts remain available.
Each task's original test file is snapshotted and restored before retrying. The
source Defects4J subjects are not modified. Resume checks hashes for the manifest,
dataset, resolved config, and task plan before using an existing run.

`token-usage.jsonl` is appended during inference, so it survives interruption. Each
event records alias, resolved model ID, component, prompt/completion/total tokens,
request duration, status, and provider request ID when available. It never stores
prompt text, generated content, or API credentials. The runner places the file inside
each attempt, which makes per-task and per-run aggregation straightforward.

Use `--run-dir <path>` to choose a new directory explicitly. Repetitions get
separate directories. Existing `result-files/<old-label>/` outputs remain in
place and continue to be readable; no automatic migration is performed. A later
migration can first build a dry-run index, verify report counts and hashes, then
move only legacy trees whose destination is unambiguous.

Nothing writes to `src/cogpath/config.ini`; that file is now only for ad-hoc
single-subject debugging.

---

## `verify` — the completeness gate

```bash
python experiment.py verify --run-dir "$RUN_DIR"
```

```
  tasks   : 2/130 complete
  incomplete: Cli-40f::HelpFormatter (not started)
VERIFY FAILED: 1 incomplete run(s). Do not publish these numbers.
```

Exit code 1 on any incomplete run. This is the check that would have prevented the
QW3.5-397B column from being built out of a 2-of-130 run.

---

## `backfill` — provenance for existing results

```bash
python experiment.py backfill --dry-run
```

Reads `legacy_map.yaml` and emits one index line per existing report with
`"provenance": "inferred"`. Each entry records the evidence it rests on:

* `label` — the directory name decodes deterministically to a set of flags
  (`cogpath.run_label.report_label` is verified against all 12 existing
  directories), so this is strong evidence;
* `slices` — the report contains `s_N` rows, which can only exist if Backward
  Slicing ran. This is independent evidence from the report *content*, and it is
  what established that the DS-V3.1 run had BS disabled even though its directory
  name carries no configuration at all.

---

## Relationship to the legacy drivers

`execute_cogpath.py` is now a compatibility wrapper around the resumable runner.
The other legacy scripts remain available, with two changes:

1. `fill_config` now writes a **fresh** file instead of merging into the existing
   one, so a run can no longer inherit a stale factor.
2. `execute_classes_with_high_complexity.py` now states
   `use_constraints`, `use_backward_slice` and `fix_type` explicitly. They are
   therefore pinned to full CogPath and **cannot produce ablations** — use
   `experiment.py` for that.

New work should use `experiment.py`. The legacy drivers remain only so that the
recorded result trees stay reproducible.

---

## Still manual

* **`paper/tables/*.tex` is still transcribed by hand.** No script writes it. The
  authoritative inputs are the class-level and project-level CSVs produced by
  [`collect_results.py`](../README.md) (which supersedes
  `parse_coverage_results.py` + `calculate_project_stats.py`), and the run index now
  ties each one to a configuration.
* **The Panta and Vanilla-Prompt baselines are not reproducible here** — only their
  derived CSVs are checked in, with no raw HTML.
* **Averages are unweighted means of the 14 per-project averages**, not pooled
  per-class means. The two differ (e.g. CogPath pooled 53.18 / 45.71 vs published
  53.14 / 44.41); keep the convention consistent when regenerating tables.
