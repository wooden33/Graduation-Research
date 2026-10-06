"""The evaluation work list: which classes belong to which project.

``data/class_list.csv`` is the authoritative list of the 130 classes, with each
class's maximum cyclomatic complexity.  It is the only place that knows the
project <-> class association, and getting that association wrong silently
attributes coverage to the wrong project, so lookups are exact rather than
pattern-based (see :meth:`ClassList.by_class`).

The file is UTF-8 **with a BOM**, so it must be opened with ``utf-8-sig``;
reading it with plain ``utf-8`` yields a first column named ``"\\ufeffproject"``
and every lookup fails.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .paths import DEFAULT_CLASS_LIST


@dataclass(frozen=True)
class ClassSpec:
    """One row of the work list."""

    project: str
    class_name: str
    complexity: Optional[int]

    @property
    def key(self) -> Tuple[str, str]:
        return (self.project, self.class_name)

    @property
    def label(self) -> str:
        """Short project label, e.g. ``JacksonDatabind-112f`` -> ``JacksonDatabind``.

        The published CSVs use this shortened form: the original pipeline derived
        it with ``key.split("-")[0]``.  It is lossy (``-112f`` is dropped), so the
        full id is preserved in :attr:`project` and can be exported with
        ``--project-names full``.
        """
        return self.project.split("-")[0]


class ClassList:
    """An indexed view of the class list."""

    def __init__(self, specs: Sequence[ClassSpec]):
        self.specs: Tuple[ClassSpec, ...] = tuple(specs)
        self._by_class: Dict[str, List[ClassSpec]] = {}
        self._by_key: Dict[Tuple[str, str], ClassSpec] = {}
        for spec in self.specs:
            self._by_class.setdefault(spec.class_name, []).append(spec)
            self._by_key[spec.key] = spec

    # -- construction ------------------------------------------------------ #

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ClassList":
        """Read the class list.  ``path`` defaults to ``data/class_list.csv``."""
        path = Path(path) if path else DEFAULT_CLASS_LIST
        specs: List[ClassSpec] = []
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                project = (row.get("project") or row.get("\ufeffproject") or "").strip()
                class_name = (row.get("class") or "").strip()
                if not project or not class_name:
                    continue
                raw_complexity = (row.get("complexity") or "").strip()
                try:
                    complexity: Optional[int] = int(float(raw_complexity))
                except ValueError:
                    complexity = None
                specs.append(ClassSpec(project, class_name, complexity))
        return cls(specs)

    # -- lookups ----------------------------------------------------------- #

    def __len__(self) -> int:
        return len(self.specs)

    def __iter__(self) -> Iterable[ClassSpec]:
        return iter(self.specs)

    @property
    def projects(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for spec in self.specs:
            if spec.project not in seen:
                seen.append(spec.project)
        return tuple(seen)

    def by_class(self, class_name: str) -> Optional[ClassSpec]:
        """Look a class up by name.

        Returns the single matching spec, or ``None`` when the name is unknown
        **or ambiguous**.  Ambiguity is surfaced by :meth:`ambiguous_classes`
        rather than resolved by picking the first match, which is how a class in
        one project can end up attributed to another.
        """
        matches = self._by_class.get(class_name)
        if not matches or len(matches) > 1:
            return None
        return matches[0]

    def by_key(self, project: str, class_name: str) -> Optional[ClassSpec]:
        return self._by_key.get((project, class_name))

    def ambiguous_classes(self) -> Dict[str, List[str]]:
        """Class names that occur in more than one project."""
        return {
            name: sorted(spec.project for spec in specs)
            for name, specs in self._by_class.items()
            if len(specs) > 1
        }
