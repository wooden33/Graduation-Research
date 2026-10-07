"""Result-directory naming for a CogPath run.

The label is derived from the runtime flags and becomes the directory under
``result-files/``::

    <prompt_type|symprompt|hits>_<model>[_constraints][_mcts][_bs][_<solver_model>]

Model ids keep their ``/``, so a model such as ``openrouter/openai/gpt-5.4-mini``
produces nested directories.  That is intentional and existing result trees
depend on it, so this function reproduces the historical behaviour exactly and is
the single place that defines it.

Keeping it here (rather than inline in ``cogpath.py``) means the experiment
runner can predict a run's output directory without importing the whole tool,
and that the two can never drift apart.
"""

from __future__ import annotations

from typing import Any, Mapping


def report_label(config: Mapping[str, Any]) -> str:
    """Compose the result-directory label for a config mapping.

    Mirrors ``Cogpath.__init__``: the model is used *raw* (before any short-name
    mapping), and ``solver_model`` is appended only when it is explicitly set --
    never when it merely defaults to ``model``.
    """
    model = str(config.get("model", "") or "")

    if config.get("run_symprompt"):
        parts = ["symprompt", model]
    elif config.get("run_hits"):
        parts = ["hits", model]
    else:
        parts = [str(config.get("prompt_type", "control") or "control"), model]

    if config.get("use_constraints"):
        parts.append("constraints")
    if str(config.get("fix_type", "") or "") == "MCTS":
        parts.append("mcts")
    if config.get("use_backward_slice"):
        parts.append("bs")

    solver_model = str(config.get("solver_model", "") or "")
    if solver_model:
        parts.append(solver_model)

    return "_".join(parts)
