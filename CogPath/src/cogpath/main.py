"""Command line entry point for CogPath.

Responsibilities kept deliberately small:

1. load ``config.ini``;
2. coerce and validate it (:mod:`cogpath.config_validation`) -- failing fast,
   with every problem reported at once, before any paid LLM call or Maven build;
3. hand a fully-resolved ``argparse.Namespace`` to :class:`cogpath.cogpath.Cogpath`.

``--print-config`` prints the resolved configuration as JSON and exits without
running anything, which is what the experiment runner uses for ``--dry-run``.
"""

import argparse
import configparser
import json
import os
import sys

from .cogpath import Cogpath
from .config_validation import ConfigError, normalise_and_validate, to_namespace_fields


def load_config(config_file=None):
    """Read the ``[default]`` section of a config file as a raw string mapping.

    A relative ``config_file`` resolves against this package's directory, which
    is where the shipped ``config.ini`` lives.
    """
    base_dir = os.path.dirname(__file__)
    config_path = (
        config_file if config_file and os.path.isabs(config_file)
        else os.path.join(base_dir, config_file or "config.ini")
    )

    if not os.path.exists(config_path):
        raise FileNotFoundError("Configuration file not found: {}".format(config_path))

    parser = configparser.ConfigParser()
    parser.read(config_path)
    if not parser.has_section("default"):
        raise ConfigError(["configuration has no [default] section: {}".format(config_path)])
    return dict(parser["default"])


def config_to_namespace(config):
    """Build the ``argparse.Namespace`` expected by :class:`Cogpath`.

    ``config`` is an already-validated mapping, so no key can be ``None`` and no
    defaulting happens here.
    """
    return argparse.Namespace(**to_namespace_fields(config))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="CogPath - Automated Unit Test Generation")
    parser.add_argument(
        "--config", "-c", type=str, default=None,
        help="Path to the configuration file (default: config.ini next to this module)",
    )
    parser.add_argument(
        "--print-config", action="store_true",
        help="Print the resolved configuration as JSON and exit without running",
    )
    parser.add_argument(
        "--no-warn", action="store_true",
        help="Suppress configuration warnings",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    try:
        raw = load_config(args.config)
        config, warnings = normalise_and_validate(raw)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except (FileNotFoundError, OSError) as exc:
        print("Configuration error: {}".format(exc), file=sys.stderr)
        raise SystemExit(2)

    if args.print_config:
        print(json.dumps(config, indent=2, sort_keys=True, default=str))
        return 0

    if warnings and not args.no_warn:
        for warning in warnings:
            print("WARNING: {}".format(warning), file=sys.stderr)

    config_args = config_to_namespace(config)

    cogpath = Cogpath(config_args)
    if config_args.run_symprompt:
        cogpath.run_symprompt()
    elif config_args.run_hits:
        cogpath.run_hits()
    else:
        cogpath.run()
    return 0


if __name__ == "__main__":
    main()
