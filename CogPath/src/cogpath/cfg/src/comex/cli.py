"""CLI for depend."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from .codeviews.combined_graph.combined_driver import CombinedDriver
from . import get_language_map

get_language_map()
app = typer.Typer()


@app.callback(invoke_without_command=True)
def main(
        lang: str = typer.Option(..., help="java, cs"),
        code: Optional[str] = typer.Option(None, help="""
    public class Max2 {
        public static void main(String[] args) {
            int x= 3;
            x = x + 3;
            int y = 4;
            y += 1;
        }
    }
    """),
        code_file: Optional[Path] = typer.Option(None, help="./test_file,java"),
        debug: bool = typer.Option(False, help="Enables debug logs"),
):
    """
    Comex

    Generates, customizes and combines multiple source code representations (AST, CFG, DFG)


    """
    if debug:
        level = "DEBUG"
    else:
        level = "WARNING"

    config = {
        "handlers": [{"sink": sys.stderr, "level": level}],
    }
    logger.configure(**config)

    try:
        if code_file:
            file_handle = open(code_file, "r", encoding="utf-8", errors="ignore")
            src_code = file_handle.read()
            file_handle.close()
            CombinedDriver(src_language=lang, src_code=src_code)
        else:
            if not code:
                raise Exception("No code provided")
            CombinedDriver(src_language=lang, src_code=code)
    except (
            Exception
    ) as e:
        try:
            logger.error(e.msg)
        except AttributeError:
            logger.error(e)
        sys.exit(-1)
