# src/cogpath/__init__.py
"""CogPath: constraint-guided context reduction for LLM-based test generation.

``Cogpath`` is resolved lazily (PEP 562) so that importing a light submodule such
as :mod:`cogpath.config_validation`, :mod:`cogpath.run_label` or
:mod:`cogpath.provenance` does not drag in ``jinja2``, ``litellm`` and the
vendored CFG parser.  ``from cogpath import Cogpath`` keeps working unchanged.
"""

from typing import Any

__all__ = ["Cogpath"]


def __getattr__(name: str) -> Any:
    if name == "Cogpath":
        from .cogpath import Cogpath

        return Cogpath
    raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))


def __dir__():
    return sorted(list(globals().keys()) + __all__)
