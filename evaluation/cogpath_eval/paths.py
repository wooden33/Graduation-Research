"""Filesystem locations used across the analysis package.

Kept separate so submodules never have to import the package ``__init__`` (which
would risk an import cycle) and so the layout is stated in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

#: ``<repo>/evaluation``
EVAL_DIR: Path = Path(__file__).resolve().parent.parent
#: ``<repo>`` -- the CogPath checkout
REPO_ROOT: Path = EVAL_DIR.parent
#: Default location of the tool's result trees
RESULT_FILES: Path = REPO_ROOT / "result-files"
#: The authoritative work list (130 classes, UTF-8 with BOM)
DEFAULT_CLASS_LIST: Path = EVAL_DIR / "data" / "class_list.csv"
#: Per-subject method/complexity indexes written by compute_statistics.py
SUBJECT_INDEX_DIR: Path = EVAL_DIR / "defects4j-codefiles"
#: Curated per-run aggregates
RESULTS_DIR: Path = EVAL_DIR / "cogpath_results"
