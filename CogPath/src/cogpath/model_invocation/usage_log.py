"""Append privacy-safe LiteLLM usage events to the active task attempt."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


def record_usage(
    *,
    alias: str,
    model_id: str,
    component: str,
    started_at: float,
    usage: Optional[Any] = None,
    request_id: Optional[str] = None,
    status: str = "success",
    error_type: Optional[str] = None,
    attempt: Optional[int] = None,
) -> None:
    """Write one event when COGPATH_LLM_USAGE_LOG points to a JSONL file.

    Prompts, completions, credentials, and raw provider errors are deliberately
    excluded. Each append is a single write so interruption leaves valid lines.
    """
    destination = os.environ.get("COGPATH_LLM_USAGE_LOG")
    if not destination:
        return

    def value(source: Any, key: str) -> Any:
        if isinstance(source, Mapping):
            return source.get(key)
        return getattr(source, key, None)

    prompt_tokens = value(usage, "prompt_tokens")
    completion_tokens = value(usage, "completion_tokens")
    total_tokens = value(usage, "total_tokens")
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alias": alias,
        "model_id": model_id,
        "component": component,
        "status": status,
        "attempt": attempt,
        "request_id": request_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "error_type": error_type,
    }
    line = (json.dumps(event, sort_keys=True, default=str) + "\n").encode("utf-8")
    path = Path(destination)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)
    except OSError:
        # A logging failure must never trigger another paid model retry.
        return
