"""Configuration schema, coercion and cross-field validation for CogPath.

Why this module exists
----------------------
CogPath's ablation experiments are defined entirely by configuration flags
(``use_constraints``, ``use_backward_slice``, ``fix_type``, ``pick_two_paths``).
Historically those flags were read with ``configparser``'s ``SectionProxy.get*``
helpers, whose behaviour when a key is **absent** is to return ``None`` rather
than raise.  Combined with a harness that *merged* into a single shared
``config.ini``, that meant a run could silently inherit whatever the previous
run left behind, or silently run with a factor unset.

The result was a real data-integrity problem: ablation runs whose stored
directory names did not describe the configuration that actually executed.

This module therefore makes the configuration:

* **typed** -- every value is coerced exactly once, here;
* **complete** -- in CogPath mode the ablation factors must be stated
  explicitly and are never defaulted;
* **checked** -- cross-field invariants (e.g. Constraint-Hints requires
  ``pick_two_paths``) are enforced *before* any LLM call or Maven build.

``normalise_and_validate`` is the single entry point used by ``main.py``.

The module imports nothing outside the standard library so that it can be
unit-tested without the project's heavy dependency set.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

REQUIRED = "<required>"

#: name -> default.  ``REQUIRED`` means the key must be present and non-empty.
STR_KEYS: Dict[str, str] = {
    "project_directory": REQUIRED,
    "source_code_file": REQUIRED,
    "test_code_file": REQUIRED,
    "code_coverage_report_path": REQUIRED,
    "test_execution_command": REQUIRED,
    "model": REQUIRED,
    # Optional, with defaults.
    "test_file_output_path": "",
    "test_dependency_command": "",
    "test_code_command_dir": ".",
    "included_files": "",
    "report_filepath": "",
    "prompt_type": "control",
    "solver_model": "",
    "coverage_type": "jacoco",
    "additional_instructions": "",
    # Set by the experiment runner: path to a JSON blob of run metadata that is
    # merged into run_meta.json.  Empty for ad-hoc runs.
    "provenance_file": "",
    # Class list the run is part of; hashed into run_meta.json when present.
    "dataset_file": "",
    # Not a factor for the SymPrompt / HITS baselines, so handled separately.
    "fix_type": "",
}

INT_KEYS: Dict[str, Any] = {
    "junit_version": 4,
    "target_coverage": 100,
    "maximum_iterations": 20,
    "no_coverage_increase_iterations": 3,
    "enable_fixing": 3,
    "max_slices_per_method": 5,
}

#: Booleans that always have a harmless default.
PLAIN_BOOL_KEYS: Dict[str, Any] = {
    "run_symprompt": False,
    "run_hits": False,
    "pick_two_paths": True,
}

#: Booleans that select *which experiment variant* is running.  In CogPath mode
#: these must be stated explicitly; defaulting them is exactly what allowed an
#: ablation run to inherit a stale value from the previous run.
FACTOR_BOOL_KEYS: Tuple[str, ...] = ("use_constraints", "use_backward_slice")

#: Factor keys that are not booleans.
FACTOR_OTHER_KEYS: Tuple[str, ...] = ("fix_type",)

#: All keys whose explicitness is required in CogPath mode.
FACTOR_KEYS: Tuple[str, ...] = FACTOR_BOOL_KEYS + FACTOR_OTHER_KEYS

ENUMS: Dict[str, Iterable[str]] = {
    # "symprompt"/"hits" are used by the baseline drivers: in those modes
    # `prompt_type` no longer selects a prompt (run_symprompt/run_hits dispatch
    # first) but it still names the per-class report file.
    "prompt_type": ("control", "coverage", "baseline", "symprompt", "hits"),
    "coverage_type": ("jacoco",),  # "pycov" exists but is a stub; see below
    "fix_type": ("", "MCTS"),
}

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f", ""}

ALL_KEYS: Tuple[str, ...] = tuple(STR_KEYS) + tuple(INT_KEYS) + tuple(PLAIN_BOOL_KEYS) + FACTOR_BOOL_KEYS


class ConfigError(ValueError):
    """Raised when a configuration is missing, malformed or contradictory.

    Carries every problem found, not just the first, so that a bad run is
    rejected in one shot instead of being discovered one crash at a time.
    """

    def __init__(self, errors: Iterable[str]):
        self.errors: List[str] = [e for e in errors]
        super().__init__(
            "Invalid CogPath configuration ({} problem{}):\n".format(
                len(self.errors), "" if len(self.errors) == 1 else "s"
            )
            + "\n".join("  - {}".format(e) for e in self.errors)
        )


# --------------------------------------------------------------------------- #
# Coercion
# --------------------------------------------------------------------------- #


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_int(name: str, value: Any) -> int:
    if isinstance(value, bool):  # bool is an int subclass; reject loudly
        raise ConfigError(["`{}` must be an integer, got the boolean {!r}".format(name, value)])
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError(["`{}` must be an integer, got {!r}".format(name, value)])


def _as_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ConfigError(
        ["`{}` must be a boolean (true/false/yes/no/on/off/1/0), got {!r}".format(name, value)]
    )


def normalize_fix_type(value: Any) -> str:
    """Canonicalise ``fix_type`` (``"mcts"``/``"MCTS"`` -> ``"MCTS"``)."""
    text = _as_str(value)
    return "MCTS" if text.lower() == "mcts" else text


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


def normalise(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a raw (usually all-strings) config mapping into a typed dict.

    Applies defaults, enforces types, and refuses unknown keys so that a typo
    such as ``use_constraint`` cannot silently do nothing.

    Whether the ablation factors are *required* depends on the execution mode,
    which is read from ``run_symprompt`` / ``run_hits`` first.

    Raises:
        ConfigError: on a bad type, an unknown key, or a missing factor.
    """
    errors: List[str] = []
    known = set(ALL_KEYS)

    for key in sorted(k for k in raw if k not in known):
        errors.append("unknown option `{}`".format(key))

    # The mode must be resolved first: it decides whether the ablation factors
    # are meaningful for this run.
    mode: Dict[str, bool] = {}
    for key in ("run_symprompt", "run_hits"):
        if key in raw:
            try:
                mode[key] = _as_bool(key, raw[key])
            except ConfigError as exc:
                errors.extend(exc.errors)
                mode[key] = False
        else:
            mode[key] = False
    baseline_mode = mode["run_symprompt"] or mode["run_hits"]

    cfg: Dict[str, Any] = {}

    # -- strings ----------------------------------------------------------- #
    for key, default in STR_KEYS.items():
        present = key in raw
        value = _as_str(raw[key]) if present else ("" if default == REQUIRED else default)

        if default == REQUIRED:
            # Paths, commands and the model must be present *and* non-empty.
            if not present:
                errors.append("missing required option `{}`".format(key))
            elif not value:
                errors.append("`{}` is required and must not be empty".format(key))
        elif key in FACTOR_OTHER_KEYS and not baseline_mode and not present:
            # A factor must be *stated*, but its value may legitimately be empty
            # (`fix_type = ""` selects the traditional repair prompt).
            errors.append(
                "missing required option `{}` (every ablation factor must be stated "
                "explicitly in CogPath mode, so that a run cannot inherit a stale "
                "value from a previous run)".format(key)
            )
        cfg[key] = value

    # -- ints -------------------------------------------------------------- #
    for key, default in INT_KEYS.items():
        if key in raw:
            try:
                cfg[key] = _as_int(key, raw[key])
            except ConfigError as exc:
                errors.extend(exc.errors)
                cfg[key] = default
        else:
            cfg[key] = default

    # -- booleans ---------------------------------------------------------- #
    for key, default in PLAIN_BOOL_KEYS.items():
        if key in raw:
            try:
                cfg[key] = _as_bool(key, raw[key])
            except ConfigError as exc:
                errors.extend(exc.errors)
                cfg[key] = default
        else:
            cfg[key] = default
    cfg.update(mode)

    for key in FACTOR_BOOL_KEYS:
        if key in raw:
            try:
                cfg[key] = _as_bool(key, raw[key])
            except ConfigError as exc:
                errors.extend(exc.errors)
                cfg[key] = False
        elif baseline_mode:
            # Factors do not apply to the baselines; record the neutral value.
            cfg[key] = False
        else:
            errors.append(
                "missing required option `{}` (every ablation factor must be stated "
                "explicitly in CogPath mode, so that a run cannot inherit a stale "
                "value from a previous run)".format(key)
            )
            cfg[key] = False

    cfg["fix_type"] = normalize_fix_type(cfg.get("fix_type", ""))

    if errors:
        raise ConfigError(errors)

    return cfg


# --------------------------------------------------------------------------- #
# Cross-field validation
# --------------------------------------------------------------------------- #


def check(cfg: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    """Validate an already-normalised config.

    Returns:
        ``(errors, warnings)``.  Errors mean "do not run"; warnings mean
        "this will run, but the result may not mean what you think".
    """
    errors: List[str] = []
    warnings: List[str] = []

    # -- enums ------------------------------------------------------------- #
    for key, allowed in ENUMS.items():
        value = cfg.get(key, "")
        if value not in allowed:
            errors.append(
                "`{}` = {!r} is not supported (allowed: {})".format(
                    key, cfg.get(key), ", ".join(repr(a) for a in allowed)
                )
            )

    # -- mutually exclusive modes ------------------------------------------ #
    if cfg.get("run_symprompt") and cfg.get("run_hits"):
        errors.append("`run_symprompt` and `run_hits` are mutually exclusive")

    # -- models that cannot work ------------------------------------------- #
    for key in ("model", "solver_model"):
        value = _as_str(cfg.get(key))
        if "deepseek-r1" in value:
            errors.append(
                "`{}` = {!r} is not usable: LLMInvocation.call_model() replaces the "
                "request for that model with a hard-coded SageMaker probe and "
                "discards the caller's prompt, so no test generation happens.".format(key, value)
            )

    # -- Constraint-Hints needs two candidate paths ------------------------ #
    if cfg.get("use_constraints"):
        if not cfg.get("pick_two_paths", True):
            errors.append(
                "`use_constraints=true` requires `pick_two_paths=true`: "
                "build_prompt_cfa_guided() calls the constraint solver only for the "
                "second (least-visited) candidate path, so with a single path no "
                "constraints are ever generated and the run silently degrades to "
                "`w/o CS`."
            )
        if not _as_str(cfg.get("solver_model")):
            warnings.append(
                "`solver_model` is empty; the Constraint-Hints solver will use "
                "`model` ({}). State it explicitly when a run has to be "
                "reproducible against a specific solver model.".format(cfg.get("model"))
            )

    # -- coverage backend -------------------------------------------------- #
    # `coverage_type` is already restricted to "jacoco" by ENUMS above, which is
    # what rejects "pycov": PycovCoverage.parse_coverage_report() is a no-op
    # returning None, and the CFG backend has no Python language map.  The
    # restriction is deliberate rather than incidental, hence this note.

    # -- accepted but currently broken ------------------------------------- #
    if _as_str(cfg.get("included_files")):
        warnings.append(
            "`included_files` is read as a string but iterated as a list of paths "
            "(UnitTestGenerator.get_included_files), so a non-empty value is walked "
            "character by character and every file fails to open. The prompt will "
            "silently contain no additional includes."
        )

    if not _as_str(cfg.get("report_filepath")) and not (
        cfg.get("run_symprompt") or cfg.get("run_hits")
    ):
        warnings.append(
            "`report_filepath` is empty; a name will be derived from the project and "
            "prompt type. Set it explicitly if you rely on the report file name."
        )

    return errors, warnings


def normalise_and_validate(raw: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Coerce, validate and canonicalise a raw config mapping.

    Returns:
        ``(cfg, warnings)``.

    Raises:
        ConfigError: if anything would make the run meaningless, unsupported or
            ambiguous.  All problems are reported together.
    """
    cfg = normalise(raw)
    errors, warnings = check(cfg)
    if errors:
        raise ConfigError(errors)
    # NOTE: `solver_model` is deliberately left empty when unspecified rather than
    # resolved to `model` here. The result directory name appends it only when it
    # is explicitly set, so resolving it early would silently rename every result
    # directory. Consumers fall back with `solver_model or model`.
    return cfg, warnings


def to_namespace_fields(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a validated config onto the ``argparse.Namespace`` field names."""
    return {key: cfg[key] for key in ALL_KEYS if key in cfg}
