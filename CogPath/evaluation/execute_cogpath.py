#!/usr/bin/env python3
"""Compatibility entry point for a resumable full-CogPath experiment.

New runs use the manifest runner's isolated run directory and task state files.
The previous implementation wrote all configurations into shared subjects and
used a class-named HTML file as its only resume marker; it is intentionally no
longer used by this entry point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from experiment import main as experiment_main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Prompt mode, e.g. control")
    parser.add_argument("model", help="LiteLLM model id or configured profile")
    parser.add_argument("--solver-model", default=None)
    parser.add_argument("--run-dir", default=None, help="Choose a new run directory")
    parser.add_argument("--resume", default=None, help="Resume a previous run directory")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N classes")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    evaluation_dir = Path(__file__).resolve().parent
    study = evaluation_dir / "experiments" / "studies" / "rq1_main.yaml"
    command = [
        "run", "--study", str(study), "--variant", "cogpath",
        "--model", args.model, "--prompt-type", args.prompt,
    ]
    for flag, value in (
        ("--solver-model", args.solver_model),
        ("--run-dir", args.run_dir),
        ("--resume", args.resume),
        ("--limit", str(args.limit) if args.limit is not None else None),
    ):
        if value is not None:
            command.extend([flag, value])
    if args.quiet:
        command.append("--quiet")
    if args.dry_run:
        command.append("--dry-run")
    return experiment_main(command)


if __name__ == "__main__":
    sys.exit(main())
