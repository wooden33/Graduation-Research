# Evaluation: runs → CSVs

This directory turns CogPath result trees into the two CSVs that everything
downstream (tables, figures) is built from.

OpenHands and Aider have separate, one-case smoke adapters. They run in
isolated copies and store raw logs plus final Maven/JaCoCo metrics:
[agent_baselines/README.md](agent_baselines/README.md). They are not included in
the 130-class experiment runner; validate and budget the single-case protocols
before adding batch execution.

> **For running experiments, see [`experiments/README.md`](experiments/README.md).**
> This file is about *turning finished runs into numbers*.

---

## The two outputs

**Class level** — one row per class:

```csv
project,class,complexity,iter_0_line,iter_0_branch,...,iter_7_line,iter_7_branch,final_line,final_branch,final_iter
JacksonDatabind,AnnotatedMethodCollector,15,0.0,0.0,...,39.29,27.94,39.29,27.94,7
```

**Project level** — one row per project:

```csv
project,num_classes,avg_complexity,avg_final_line,avg_final_branch,max_line,min_line,max_branch,min_branch,std_line,std_branch,classes_with_coverage
Cli,2,11.0,84.315,70.73,89.86,78.77,86.54,54.92,7.8418142033588145,22.358716421118636,2
```

Both schemas are **frozen** to match the CSVs already in `cogpath_results/`.
`--extended` *adds* columns (`project_id`, `median_line`, `median_branch`) and never
changes the existing ones.

---

## Usage

```bash
cd evaluation

# both levels at once
python collect_results.py all \
    --label control_ollama/qwen3-coder:30b-a3b-q8_0_constraints_bs \
    --prompt-type control --max-iterations 8 \
    --out-dir cogpath_results/cogpath --name <slug>

# or step by step
python collect_results.py class-level   --label <run> --output class.csv
python collect_results.py project-level --input class.csv --output project.csv

# which runs exist, and what configuration each recorded
python collect_results.py runs
```

`python -m cogpath_eval <command>` is equivalent to `collect_results.py`.
`project-level` reads a **CSV**, not a run directory, so a stored class-level table
can be re-aggregated without re-parsing 130 reports.

### Options that change the numbers

| Option | Default | Effect |
| --- | --- | --- |
| `--max-iterations N` | `8` | How many `iter_N_*` columns to export. **The checked-in CSVs are inconsistent here** — most used `3`, the three newer files used `8`. |
| `--fill {carry-forward,raw}` | `carry-forward` | What to write for an iteration the run never reached: repeat the final value (constant sample size) or leave the cell empty. **The 3-iteration CSVs were made with `raw`.** |
| `--source {html,auto,json}` | `html` | Where coverage is read from. See the warning below. |
| `--project-names {short,full}` | `short` | `short` reproduces the published label (`JacksonDatabind`); `full` keeps the subject id (`JacksonDatabind-112f`). |
| `--extended` | off | Adds `project_id` and medians. |

### ⚠️ `--source json` is not comparable to published numbers

The report HTML and the `_path_history.json` sidecar measure **different points in
the loop**:

* HTML `g_N` INFO rows are written after the generation phase, **before** repair;
* the sidecar is written at the **end** of each iteration, after repair.

Measured over one real run, **76 of 319** comparable `(class, iteration)` pairs
differ, with the sidecar consistently ahead. So `--source html` (the default) is what
reproduces published results; `json` is a convenience only.

### Row order and project labels are observable

The class-level CSV is emitted in **report-filename order**, and the project column
uses the **short label** (`project.split("-")[0]`). Both are load-bearing for byte
equality with the existing files: sorting by project, or using the full subject id,
changes the file. Use `--project-names full` when the version suffix matters — the
short label is lossy, so `JacksonDatabind-112f` and a hypothetical
`JacksonDatabind-113f` would collide.

### Two aggregation conventions

`all` also writes `summary_<name>.csv` containing **both**:

| Column | Meaning | CogPath (running example) |
| --- | --- | --- |
| `mean_of_project_means_*` | unweighted mean of the 14 project averages — every project counts once. **This is what the paper reports.** | 53.14 / 44.41 |
| `class_weighted_*` | every class counts once | 53.18 / 45.71 |

They differ because large projects dominate the second. `project-level` prints both,
so the convention in use is never implicit.

---

## Implementation

```
cogpath_eval/
├── paths.py       # where result-files/, data/, cogpath_results/ live
├── dataset.py     # class_list.csv index (BOM-safe, exact lookups, ambiguity report)
├── extract.py     # per-class results: HTML series + JSON sidecar
├── aggregate.py   # class-level and project-level CSV writers
├── cli.py         # argparse entry point
└── selftest.py    # python -m cogpath_eval.selftest
```

Standard library only — no pandas, no BeautifulSoup — so it runs wherever the result
trees exist.

`parse_coverage_results.py` and `calculate_project_stats.py` are retained but are now
**thin delegators** to this package, so there is one implementation instead of
several copies that drift. They print a deprecation note on stderr.

### Why the HTML is parsed with regex

The report HTML is **not well formed**: `report_generator.py` renders LLM-generated
Java without HTML escaping, so `List<String>` emits a raw `<String>` tag (verified: 0
escaped `&lt;` against 286,208 raw `<`). The extractor therefore reproduces the
original regex/positional scan rather than a real HTML parse, to keep the numbers
identical. Fixing the escaping in `report_generator.py` would allow a proper parser
here.

---

## Verification

```bash
cd evaluation && python -m cogpath_eval.selftest
```

11 tests, including golden tests that re-derive checked-in CSVs and assert **byte
equality**. They skip (not fail) when the raw result trees are absent.

Status of the checked-in class-level CSVs:

| CSV | Reproducible | Notes |
| --- | --- | --- |
| `cogpath_qwen3-coder_30b-a3b_q8_0_constraints_bs_8iter.csv` | ✅ byte-identical | `--max-iterations 8` |
| `cogpath_gpt-5.4-mini.csv` | ✅ byte-identical | `--max-iterations 8` |
| `cogpath_qwen3.5-397b-a17b_bs.csv` | ✅ byte-identical | `--max-iterations 8` |
| `cogpath_qwen3-coder_30b-a3b_q8_0_wo_cs.csv` | ✅ byte-identical | `--max-iterations 3 --fill raw` |
| `cogpath_qwen3-coder_30b-a3b_q8_0_deepseek-v3.csv` | ✅ byte-identical | `--max-iterations 3 --fill raw` |
| `cogpath_qwen3-coder_30b-a3b_q8_0_wo_bs.csv` | ⚠️ **stale** | final coverage matches on all 130 classes, but the **iteration curve** does not: the reports on disk have a different series (e.g. `iter_0` is `0.0` in the CSV vs `46.43` in the reports). The reports were regenerated after this CSV was made. |
| `cogpath_deepseek-v3.1.csv` | ⚠️ **stale** | 123/130 rows match on every column; 7 classes differ in final coverage and 15 rows differ. Same cause: a partial re-run overwrote the reports. |
| `symprompt_...csv` (class level) | ❌ different schema | `project,class,complexity,max_line,max_branch` — **not** produced by this pipeline (no `final_*`, no `iter_*`). Its origin is unknown, and the matching `project_symprompt_*.csv` cannot be regenerated from it. |
| `panta/...csv` | n/a | Panta ran outside this repository; only derived CSVs exist. |

For the two stale class-level files the disagreement is confined to the coverage-curve
columns. `final_line`/`final_branch` — the columns the paper's tables use — are
unaffected for `wo_bs` (130/130) and affected for 7 classes in `deepseek-v3.1`.

### Project-level CSVs

| CSV | Reproducible | Notes |
| --- | --- | --- |
| `project_..._wo_bs.csv` | ✅ byte-identical | |
| `project_..._wo_cs.csv` | ✅ byte-identical | |
| `project_panta_...csv` | ✅ byte-identical | aggregated from the checked-in `panta_...csv` |
| `project_..._deepseek-v3.csv` | ❌ **inconsistent with its own source** | Claims `Gson` `min_line=41.42`, but the checked-in class CSV contains `JsonReader=32.53`; `avg_final_line` is 57.85 vs 55.63 computed from that class CSV, and `Math` is 50.97 vs 53.19. The two files came from different generations of the same run. |
| `project_symprompt_...csv` | ❌ | its class-level source has an undocumented schema with no `final_line` column, so it cannot be derived from the checked-in input |

Several `std_line`/`std_branch` values also differ in the last one or two digits
(e.g. `23.877417504132783` vs `…787`) where the project CSV was produced by a
different summation order. That is floating-point noise, not a semantic difference.

---

## Relationship to the other scripts

| Script | Status |
| --- | --- |
| `collect_results.py`, `cogpath_eval/` | **current** — use this |
| `parse_coverage_results.py` | deprecated delegator |
| `calculate_project_stats.py` | deprecated delegator |
| `result-html-parser.py`, `result-parser-different-models.py`, `extract_pass_rate.py`, `context_limit.py` | legacy; they point at result directories that do not exist (`*_llama3-3`, `control_gpt-4o-mini`, …) and have inconsistent working-directory assumptions |
| `compute_statistics.py`, `count_classes_with_high_complexity.py` | dataset construction; still the source of `defects4j-codefiles/*.json` |
| `experiment.py`, `subject_config.py` | the experiment **runner** — see `experiments/` |
| `cogpath_results/plot_branch_coverage.py` | the coverage-curve figure; hardcodes Linux paths and its input CSV is absent |

Notes on the remaining dataset scripts:

* `compute_statistics.py` writes `subject_statistics.csv` into the working directory
  even though the checked-in copy lives in `data/`; run it from `evaluation/` and move
  the result (or point it at `data/`).
* `count_classes_with_high_complexity.py` only **counts and prints** — it does not
  generate `class_list.csv`, which is a curated input.
