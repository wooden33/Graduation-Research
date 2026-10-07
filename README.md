> **Archive layout note.** The text below describes the original working layout, in
> which `paper/` and `CogPath/` were **two independent Git repositories** and the
> workspace root was not under version control. This repository is the combined
> graduation-research archive: both directories live under a **single history**,
> each imported with `git subtree`, so the original commit histories are preserved
> as ancestry. To browse them directly:
>
> ```bash
> git log --oneline 34715961ac889886a4eb8be1d5432a30ef5463fc   # paper history (56 commits)
> git log --oneline 0dd087cc337eeda4072619570af8ffdf7414252a     # CogPath history
> ```
>
> Statements about "two repositories" or "no repository at the root" apply to the
> original layout, not to this archive. A path-limited log inside a subtree
> (`git log -- paper/`) shows only the import commit, by design.

# CogPath — Research Workspace

This directory holds the two deliverables of the **CogPath** project:

> **CogPath: A Constraint-Guided Context-Reduction Framework for LLM-Based Test Generation**
> Jianhan Liu, Tangzhi Xu, Yuan Yao, Feng Xu, Xiaoxing Ma — Nanjing University
> Target venue: **IEEE SCAM 2026** (camera-ready; previously submitted to ASE 2026).

It is **not** a single repository. It is a workspace containing **two independent Git
repositories** plus this navigation layer:

| Directory | What it is | Git remote |
| --- | --- | --- |
| [`paper/`](paper/) | The LaTeX manuscript, figures, tables, and talk slides | Overleaf (`git.overleaf.com/69ae38e0316dbc5ac0d58ef1`) |
| [`CogPath/`](CogPath/) | The tool implementation + evaluation harness | GitHub (`github.com/SoftWiser-group/CogPath`) |

There is **no Git repository at this root level** — `git` commands only work inside
`paper/` or `CogPath/`. See [AGENTS.md](AGENTS.md) for the rules that follow from this.

---

## The idea in one paragraph

Branch coverage on logic-heavy methods stays low not (only) because LLMs are weak, but
because the prompt is *cognitively misaligned* with branch reachability: implicit
cross-method preconditions are **hidden**, while branch-irrelevant code is
**over-provided**. CogPath attacks both halves inside an iterative
generate → execute → repair loop:

- **Constraint-Hints (CS)** — asks an LLM to externalize the sufficient conditions for
  reaching the first uncovered branch on a selected CFG path, then injects them into the
  generation prompt as explicit hints.
- **Backward Slicing (BS)** — when coverage plateaus, rebuilds the prompt around only the
  statements / object states / setup actions that can influence a specific uncovered
  predicate, discarding the rest of the method body.

Measured on **130 classes / 2,971 methods with cyclomatic complexity > 10** from **14
Defects4J projects**, CogPath reaches **44.41 % average branch coverage** and **53.14 %
average line coverage**, i.e. **+10.2 pp BC** over the strongest baseline (HITS) and
+12.1 pp over Panta. Ablations: removing CS costs 4.62 pp BC, removing BS costs 5.94 pp BC.
RQ3 shows large backbones reach 79.76–83.47 % BC.

---

## Repository layout

```
CogPath/                            # workspace root (this file)
├── README.md                       # ← you are here
├── AGENTS.md                       # working agreement for humans + AI agents
│
├── paper/                          # ── LaTeX manuscript repo (Overleaf clone) ──
│   ├── main.tex                    # entry point: \input's every section
│   ├── sections/                   # abstract, intro, motivation, methodology,
│   │                               # experiments, discussion, related_work,
│   │                               # conclusion, data_availability_statement
│   ├── tables/                     # dataset, rq1_main, rq2_ablation, rq3_different_llms
│   ├── figures/                    # overview.pdf, branch_coverage_comparison.pdf
│   ├── references.bib              # bibliography source
│   ├── main.bbl / main.aux / main.pdf / main.log   # build products (partly stale)
│   ├── IEEEtran.cls                # document class
│   ├── output/                     # SCAM talk slides (.pptx) + arXiv source zip
│   ├── .claude/, .codex/           # paper-critique agent skill (tracked)
│   └── .codex-build/, .codex-finalizer*/, .chart-data-*/   # agent scratch (untracked)
│
└── CogPath/                        # ── implementation + evaluation repo ──
    ├── src/cogpath/                # the tool (see CogPath/README.md for the map)
    │   ├── main.py                 # CLI entry: `python -m cogpath.main`
    │   ├── cogpath.py              # orchestration / the iterative loop
    │   ├── unit_test_generator.py  # generation, validation, repair
    │   ├── prompt_builder.py       # prompt construction + path selection
    │   ├── llm_constraint_solver.py# Constraint-Hints (CS)
    │   ├── llm_backward_slicer.py  # Backward Slicing (BS)
    │   ├── symprompt.py, hits.py   # baseline re-implementations
    │   ├── prompt_templates/       # ALL prompts, as .toml (edit prompts here)
    │   ├── coverage/               # JaCoCo + coverage.py adapters
    │   └── cfg/src/comex/          # vendored CoMEX CFG/DFG parser
    ├── evaluation/                 # replication harness, data, result CSVs, figures
    ├── result-files/               # raw per-class HTML reports + path-history JSON
    ├── defects4j-subjects-notests/ # 14 checked-out Defects4J subjects (no test suites)
    ├── docs/                       # design notes for CS and BS
    └── config.ini                  # single-subject config, MUTATED by the eval harness
```

---

## Paper → code traceability

The manuscript maps onto the code as follows. This is the fastest way to answer
"where is X implemented?" or "which run produced Table Y?".

| Paper element | Implemented in | Produced by |
| --- | --- | --- |
| Alg. 1 iterative loop, termination (maxIter=20, Λ=3, β=0.6) | `src/cogpath/cogpath.py` (`Cogpath.run`) | — |
| §3.2 Constraint-Hints | `src/cogpath/llm_constraint_solver.py` + `prompt_templates/java_templates/constraint_solving_prompt.toml` | `evaluation/execute_cogpath.py <prompt> <model>` |
| §3.3 Backward Slicing | `src/cogpath/llm_backward_slicer.py` + `prompt_templates/slicer_templates/backward_slice.toml` | same |
| CFG construction, path enumeration, path selection | `src/cogpath/prompt_builder.py` + vendored `cfg/src/comex` | — |
| Repair phase / compiler diagnostics | `src/cogpath/unit_test_generator.py` (`fix_failed_tests`) + `error_message_parser.py` | — |
| Coverage measurement (JaCoCo) | `src/cogpath/coverage/jacoco_coverage.py`, `jacoco_parser.py` | — |
| SymPrompt baseline | `src/cogpath/symprompt.py` | `evaluation/execute_symprompt.py` |
| HITS baseline (re-implemented) | `src/cogpath/hits.py` | `evaluation/execute_hits.py` |
| Panta baseline | external (separate repo) | `evaluation/cogpath_results/panta/` |
| Table 1 (dataset) | `paper/tables/dataset.tex` | `evaluation/compute_statistics.py` → `evaluation/defects4j-codefiles/*.json` |
| Table 2 / RQ1 (coverage) | `paper/tables/rq1_main.tex` | `evaluation/parse_coverage_results.py` → `evaluation/cogpath_results/cogpath/*.csv` |
| Table 3 / RQ2 (ablation) | `paper/tables/rq2_ablation.tex` | same script, `*_wo_bs` / `*_wo_cs` / `*_mcts` runs (see the mapping note below) |
| Table 4 / RQ3 (models) | `paper/tables/rq3_different_llms.tex` | same script, per-backbone result dirs |
| Fig. 2 (branch growth) | `paper/figures/branch_coverage_comparison.pdf` | `evaluation/cogpath_results/plot_branch_coverage.py` (**currently unrunnable**) |

> **Traceability caveats — read before touching any number.**
> 1. **No script writes `paper/tables/*.tex`.** The numbers were transcribed by hand. If
>    you change an evaluation result you must update the `.tex` yourself.
> 2. **`coverage_statistics.xlsx` does not exist** anywhere in either repo, even though
>    [`CogPath/evaluation/README.md`](CogPath/evaluation/README.md) refers to it. Treat
>    that README as stale.
> 3. `evaluation/result-html-parser.py`, `result-parser-different-models.py`, and
>    `extract_pass_rate.py` point at result directories that **do not exist**
>    (`*_llama3-3`, `control_gpt-4o-mini`, …). The scripts that match the checked-in data
>    are `parse_coverage_results.py` + `calculate_project_stats.py`.
> 4. The **ablation config suffixes are inverted** relative to what they contain: a raw
>    directory named `..._mcts` backs the paper's **w/o CS+BS (Base)** column, and
>    `..._bs` backs **w/o CS** while `..._constraints` backs **w/o BS** (the suffix names
>    what was *kept*; the derived CSV names what was *removed*).
> 5. **Verified arithmetic defect in Table 3.** `paper/tables/rq2_ablation.tex` lists Jsoup
>    (CogPath) as `69.11 / 53.76`, but Table 2, Table 4, and the raw result CSV
>    `cogpath_qwen3-coder_30b-a3b_q8_0_constraints_bs_8iter.csv` all give `66.43 / 52.55`.
>    The table's own average row implies `66.43 / 52.55`: the CogPath column averages
>    `53.33 / 44.50` as printed, versus the stated `53.14 / 44.41`, and substituting
>    `66.43 / 52.55` restores the stated average exactly. The adjacent **w/o BS** Jsoup cell
>    duplicates the same suspect value.

---

## Quick start

### Rebuild the paper

```bash
cd paper
pdflatex -interaction=nonstopmode main.tex
bibtex main            # only needed if references.bib changed
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex
# → main.pdf
```

`pdflatex`, `bibtex`, and `latexmk` are available on this machine (TeX Live 2026 /
Homebrew). `main.bbl` is checked in, so a plain `pdflatex` run works if the bibliography
is unchanged. **`main.pdf` is older than `main.tex`, `discussion.tex`, and
`related_work.tex` — it is currently stale.** Rebuild before trusting or sharing the PDF.

### Run the tool on one subject

```bash
cd CogPath
conda env create -f cogpath-env.yml && conda activate cogpath   # or: poetry install
export OPENROUTER_API_KEY=...                                   # litellm reads provider keys
python -m cogpath.main                                          # uses src/cogpath/config.ini
```

Requires a JDK 8+, Maven 3.6.3+, and — at runtime — `git`, a C compiler, and network
access (the vendored CFG parser fetches and compiles tree-sitter grammars). Results land in
`result-files/`, logs in `logs/`.

> ⚠️ **None of that toolchain is currently installed on this workstation**: no `conda`, no
> `poetry`, no `mvn`, no working `java` runtime, and the system `python3` is 3.14 (outside
> the supported `>=3.9,<3.13`). The tool cannot run end-to-end until those are installed.
> See [`CogPath/README.md`](CogPath/README.md#-status-on-the-current-workstation).

### Re-run the full evaluation

```bash
cd CogPath/evaluation
python3 compute_statistics.py java                 # dataset stats → defects4j-codefiles/*.json
python3 execute_cogpath.py control <model> --parallel --workers 4
python3 parse_coverage_results.py \                # the parser behind the published CSVs
    --result-dir ../result-files/<run> --class-list data/class_list.csv \
    --output cogpath_results/<run>.csv --prompt-type control
```

`evaluation/README.md` describes an older pipeline and names files that do not exist; use
[`CogPath/README.md`](CogPath/README.md#evaluation-harness) as the authoritative guide.

### Run an ablation or model sweep

Experiments are defined by declarative manifests, **not** by hand-editing `config.ini`:

```bash
cd CogPath/evaluation
python experiment.py list    --study experiments/studies/rq2_ablation.yaml
python experiment.py resolve --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0
python experiment.py run     --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0
python experiment.py verify  --study experiments/studies/rq2_ablation.yaml \
                             --variant w_o_cs_bs --model ollama/qwen3-coder:30b-a3b-q8_0
```

Any litellm model id works, so a new backbone needs no manifest edit. `verify` exits
non-zero unless every planned class has a result — the check that would have caught the
RQ3 Qwen column being built from a 2-of-130 run. See
[`evaluation/experiments/README.md`](CogPath/evaluation/experiments/README.md).

---

## Working in this workspace

Read [AGENTS.md](AGENTS.md) before making changes. The four rules that bite most often:

1. **Two repos, two histories.** Never `git add` across the workspace boundary, and never
   rewrite the Overleaf history in `paper/`.
2. **Do not commit generated artifacts.** `paper/` has an *empty* `.gitignore` and a long
   list of untracked agent scratch directories; `git add -A` there is unsafe.
3. **The legacy evaluation harness is destructive to the subject projects.** It rewrites
   `src/cogpath/config.ini` in place and renames `defects4j-subjects-notests/*/src/test/java`.
   Do not run it casually, and re-check that directory before/after. `experiment.py` does
   neither — it writes per-class configs into the run directory.
4. **Ablations go through manifests.** Editing `src/cogpath/config.ini` to select an
   ablation is what produced three of the four verified defects in the published artifacts.

Also see [`CogPath/AGENTS.md`](CogPath/AGENTS.md) for the code-specific landmine list.

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
