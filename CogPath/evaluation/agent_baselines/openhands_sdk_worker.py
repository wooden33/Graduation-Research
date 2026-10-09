"""Small worker process executed inside the disposable Maven container."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from openhands.sdk import Conversation, LLM
from openhands_cli.utils import get_default_cli_agent


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--persistence", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, default=12)
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY missing inside the isolated worker")
    extra_body = profile.get("litellm_params", {}).get("extra_body", {})
    llm = LLM(
        model=profile["model"],
        api_key=api_key,
        base_url=profile.get("base_url") or None,
        litellm_extra_body=extra_body,
        usage_id="openhands-agent",
    )
    # TerminalTool inherits the worker environment. Remove credentials before
    # the agent can execute shell commands; the LLM client retains its own copy.
    os.environ.pop("LLM_API_KEY", None)
    os.environ.pop("DEEPSEEK_API_KEY", None)
    Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)

    args.event_log.parent.mkdir(parents=True, exist_ok=True)
    args.persistence.mkdir(parents=True, exist_ok=True)
    with args.event_log.open("w", encoding="utf-8") as event_file:
        def on_event(event):
            event_file.write(json.dumps(_jsonable(event), sort_keys=True) + "\n")
            event_file.flush()

        conversation = Conversation(
            agent=get_default_cli_agent(llm),
            workspace=str(args.workspace),
            persistence_dir=str(args.persistence),
            callbacks=[on_event],
            max_iteration_per_run=args.max_iterations,
            visualizer=None,
        )
        conversation.send_message(args.task.read_text(encoding="utf-8"))
        conversation.run()
        status = str(conversation.state.execution_status)
        stats = _jsonable(conversation.conversation_stats)
        summary = {
            "conversation_id": str(conversation.id),
            "execution_status": status,
            "max_iterations": args.max_iterations,
            "stats": stats,
        }
        (args.persistence.parent / "openhands-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, sort_keys=True))
        conversation.close()
    return 0 if "FINISHED" in status.upper() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("OpenHands worker failed: {}".format(exc), file=sys.stderr)
        raise
