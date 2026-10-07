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

# AGENTS.md — CogPath research workspace

Working agreement for **any agent or human** editing this workspace. Read this file
first; then read the more specific one for the subtree you are touching.

| Scope | File |
| --- | --- |
| Whole workspace (this file) | `AGENTS.md` |
| `CogPath/` implementation + evaluation | `CogPath/AGENTS.md` |

DST convention: agents typically load the **nearest** `AGENTS.md` walking up from the
working directory, so `CogPath/AGENTS.md` **adds to** — and does not replace — this file.
There is no `paper/AGENTS.md`; paper rules live in the "Paper subtree" section below.

---

## 1. Topology — the facts that cause most mistakes

```
/Users/ljh/research/CogPath/          ← NOT a git repo (no .git)
├── paper/                            ← git repo #1, remote = Overleaf
└── CogPath/                          ← git repo #2, remote = github.com/SoftWiser-group/CogPath
```

1. **There is no repository at the workspace root.** `git status` at the root fails. Always
   `cd` into `paper/` or `CogPath/`, or use `git -C paper ...`.
2. **The two repos are unrelated and unlinked.** Never stage files from one while
   committing in the other. Never try to make one a submodule of the other.
3. **`paper/` is an Overleaf clone.** Other people may push to it through the Overleaf web
   editor. Consequences:
   - **Never** `git push --force`, `git rebase`, `git commit --amend`, or history-rewrite
     on any branch in `paper/`.
   - **Pull before you commit**: `git -C paper fetch && git -C paper status`.
   - The Overleaf history contains `Merge branch 'master' of https://git.overleaf.com/...`
     merge commits. This is normal; do not "clean it up".
4. **`CogPath/` is a normal 2-commit repo.** Rewriting its history is *allowed* but still
   unnecessary; prefer additive commits.

---

## 2. Golden rules

### R1 — Never bulk-stage
`paper/.gitignore` is **empty**, and `paper/` contains a lot of generated/scratch content
that is intentionally untracked:

- `.codex-build/`, `.codex-finalizer/`, `.codex-finalizer-5min/`
- `.chart-data-*/` (seven directories)
- `output/` (conference slides + arXiv zip)

`git add -A` or `git add .` in `paper/` **will** sweep these in. Stage explicit paths only:

```bash
git -C paper add main.tex sections/methodology.tex tables/rq1_main.tex
```

`CogPath/.gitignore` is a reasonable but partial allow-list. Do not add `defects4j-subjects-notests/`
contents, `result-files/`, or `evaluation/*.csv` outputs to Git; they are either huge or
regenerable.

### R2 — The evaluation harness mutates the working tree
`CogPath/evaluation/execute_cogpath.py` (and siblings) are **not** read-only:

- It writes `CogPath/src/cogpath/config.ini` in place — both sequentially
  (`fill_config`, line ~88) and via per-thread temp configs (`config_{thread}_{uuid}.ini`).
- It **renames** `<subject>/src/test/java` to `src/test/java_backup` to stop Maven
  compiling unrelated tests, then creates its own test directory (~lines 160–176).
- It shells out to `python -m cogpath.main` with `cwd="../"` and to `mvn` per class.

So: **do not run the evaluation harness unless explicitly asked**, and after any run check
`git -C CogPath status` for a dirty `config.ini` and check the subject directories for
leftover `*_backup` folders before committing.

### R3 — LLM calls cost real money and real time
Every `Cogpath.run` iteration performs multiple paid, network-bound LLM calls. A full
replication is 130 classes × up to 20 iterations × (generate + repair + CS + BS) with
3 repetitions. **Never** launch a full or parallel evaluation to "check that something
works". Use a single subject, or stub the invoker, and say what you ran.

### R4 — Report honestly, never fabricate results
This is a paper-backed artifact. Do not invent coverage numbers, do not "estimate" a table
entry, and do not silently change a table. If you cannot reproduce a number, say so and
cite the file where the number actually lives.

### R5 — Keep prompts and code in sync
All prompts live in `CogPath/src/cogpath/prompt_templates/**/*.toml` and are loaded by an
explicit allow-list in `CogPath/src/cogpath/config_loader.py` (`SETTINGS_FILES`).
**Adding a `.toml` file without adding it to `SETTINGS_FILES` means it is silently never
loaded.** Conversely, a listed file that does not exist raises `FileNotFoundError` at
startup.

---

## 3. Task routing

| If the request is… | Go to | Primary files |
| --- | --- | --- |
| Fix prose, restructure a section, address a reviewer | `paper/` | `sections/*.tex`, `tables/*.tex` |
| Update a table/figure number | `paper/` **and** `CogPath/evaluation/` | `tables/*.tex` + `evaluation/cogpath_results/**/*.csv` (curated). There is **no** `coverage_statistics.xlsx` — the evaluation README is wrong about that. |
| Critique the manuscript | `paper/` | Use the `paper-critique` skill (`.claude/skills/`, `.codex/skills/`) |
| Build slides / arXiv source | `paper/output/` | `.codex-build/build_cogpath_slides.mjs` |
| Change tool behaviour | `CogPath/src/cogpath/` | see `CogPath/README.md` module map |
| Change an LLM prompt | `CogPath/src/cogpath/prompt_templates/` | plus `config_loader.py` |
| Add/adjust a baseline | `CogPath/src/cogpath/` | `symprompt.py`, `hits.py` |
| Re-run / extend the benchmark | `CogPath/evaluation/` | `execute_*.py`, `result-*.py` |
| Understand the method | either | `paper/sections/methodology.tex`, `CogPath/docs/*.md` |

**Reading order for a cold start:** `paper/sections/abstract.tex` →
`paper/sections/methodology.tex` → `CogPath/src/cogpath/cogpath.py` (`run`) →
`CogPath/src/cogpath/prompt_builder.py` (`build_prompt_cfa_guided`).

---

## 4. Paper subtree — `paper/`

### Build
```bash
cd paper
pdflatex -interaction=nonstopmode main.tex
bibtex main                                    # only if references.bib changed
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex
```

- Toolchain present: `pdflatex`, `bibtex`, `latexmk` (TeX Live 2026/Homebrew).
  `latexdiff` is **not** installed.
- `main.bbl` is checked in. A single `pdflatex` pass is enough for prose-only edits;
  `bibtex` is only for bibliography changes.
- **`main.pdf` is stale**: `main.tex`, `sections/discussion.tex`, and
  `sections/related_work.tex` were last modified *after* the PDF was built. Rebuild after
  editing, and do not present the existing `main.pdf` as current.

### Known paper-side issues to be aware of
- `paper/README.txt`, `paper/sample-franklin.png`, `paper/sampleteaser.pdf`, and
  `paper/sample-base.bib` are **leftovers from the ACM template**, not from `IEEEtran.cls`.
  `README.txt` describes the ACM class — it is not documentation for this paper. Do not
  treat it as authoritative, and do not "fix" it by deleting files the author may still want.
- `main.tex` contains an unresolved placeholder in `\IEEEpubid`:
  `979-8-XXXX-XXXX-X` (conference ISBN) with a `TODO` comment. This is known and expected
  until the SCAM 2026 proceedings ISBN is available — do **not** guess a value.
- `paper/.gitignore` exists but is **empty (0 bytes)**. See R1.
- **Table 3 (`tables/rq2_ablation.tex`) has a verified wrong cell.** Jsoup/CogPath is
  `69.11 / 53.76` there, but `tables/rq1_main.tex`, `tables/rq3_different_llms.tex`, and the
  raw CSV (`evaluation/cogpath_results/cogpath/cogpath_qwen3-coder_30b-a3b_q8_0_constraints_bs_8iter.csv`)
  all give `66.43 / 52.55`. The table's own average (`53.14 / 44.41`) is reproduced exactly
  by `66.43 / 52.55` and not by the printed value. The adjacent **w/o BS** Jsoup cell holds
  the same suspect number. **Do not silently edit it** — confirm with the author first.
- `references.bib` entry `wang2024c` (HITS) has `date = {2024-10-27}` but **no `year`
  field**, so it renders yearless. Re-running `bibtex` will not fix it; the field must be
  added.
- **"pp" vs "%" is used inconsistently.** `abstract.tex` says "12.8% higher LC and 10.2%
  higher BC" where these are *percentage points* (53.14 − 40.31 = 12.83 pp); `intro.tex`
  and `conclusion.tex` correctly say "percentage points"/"pp"; `discussion.tex` switches to
  relative (+110%/+30%/+37%); `experiments.tex` says "pp" in one place and "%" in another
  for the same 5.94/4.62 figures. When editing, keep "pp" for differences and "%" for
  relative change.
- `experiments.tex` claims each experiment was "repeat[ed] … three times with averaged
  results", but the checked-in data has **one run per configuration**, no seed/repetition
  column, and no std-dev or CI. Treat that claim as **unverified**; do not cite it as
  evidence of variance control.
- Headline numbers live in the `.tex` tables, not in any generated artifact. Never
  recompute them from `result-files/` HTML without flagging the discrepancy.

### Paper writing conventions
- `\ourmethod` is the macro for **CogPath** — use it instead of typing `\textsc{CogPath}`
  inline; `\eg`, `\ulbf`, `\xtz` are also defined in `main.tex`.
- The term is **Constraint-Hints (CS)** and **Backward Slicing (BS)**. Avoid the variants
  "constraint-hint", "constraints-hint", "CH" — reviewer-facing inconsistency was flagged.
- Tables use `booktabs` + `siunitx` (`S` columns); keep alignment consistent when editing.
- The manuscript is authored in **English**; internal notes and the `paper-critique` skill
  may be in Chinese. Match the surrounding file's language.

---

## 5. Environment facts

| Thing | Value |
| --- | --- |
| Workspace root | `/Users/ljh/research/CogPath` |
| Python for the tool | conda env `cogpath` — Python 3.9.19 (`pyproject.toml` allows `>=3.9,<3.13`) |
| Dependency managers | Poetry (`pyproject.toml`) and conda (`CogPath/cogpath-env.yml`) — both exist, they disagree in places (see `CogPath/AGENTS.md`) |
| Java build | JDK 8+, Maven 3.6.3+ required by the Defects4J subjects |
| LaTeX | TeX Live 2026 / Homebrew |
| `poetry.lock` | **Not tracked** (listed in `CogPath/.gitignore`) — installs are not reproducible by hash |

---

## 6. Definition of done for agent work here

Before reporting a task complete:

1. **State exactly what you ran** (command, directory, subject) and what you did *not* run.
2. **For paper edits**: rebuild `main.pdf` and confirm the log has no new errors; report
   `main.log` warnings if you introduced any.
3. **For code edits**: do a smoke check — the stdlib-only core can be checked without any
   dependencies installed:
   `cd CogPath && python -m compileall -q -x 'version\.py' src/cogpath && PYTHONPATH=src python -c "import cogpath.config_validation, cogpath.run_label, cogpath.provenance"`.
   Note `src/cogpath/version.py` is a bare version string, not Python, so it must be
   excluded from `compileall`. Prefer a single-subject run if behaviour changed. There is
   **no test suite** in `CogPath` (no `pytest` tests are tracked despite pytest being
   declared), so do not claim "tests pass".
4. **Check `git status` in both repos** and confirm you did not sweep in scratch files or
   leave `config.ini` / `*_backup` modified.
5. **Flag uncertainty** rather than filling gaps with plausible-sounding content. This
   project has a documented history of reviewer criticism — an unverified claim in a doc
   is worse than an explicit "not verified".
