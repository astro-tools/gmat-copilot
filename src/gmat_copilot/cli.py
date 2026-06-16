"""The ``gmat-copilot`` command-line interface.

Three subcommands map onto the library surface: ``draft`` (generate a script), ``validate`` (lint a
script), and ``eval`` (run the evaluation suite). ``validate`` and the recorded ``eval`` path are
GMAT-free and model-free; ``draft`` and live ``eval`` need a provider credential.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .eval.judge import JUDGE_MODEL
from .eval.runner import run_recorded
from .generate import draft
from .providers import ProviderError
from .validate import validate

__all__ = ["main"]


def _cmd_draft(args: argparse.Namespace) -> int:
    try:
        result = draft(args.request, model=args.model, strict=not args.permissive)
    except (NotImplementedError, ProviderError) as exc:
        print(f"gmat-copilot: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(result.script)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.script == "-" else Path(args.script).read_text("utf-8")
    report = validate(text)
    for d in report.diagnostics:
        print(f"{d.line}:{d.column}: {d.severity.value}: {d.rule}: {d.message}")
    blocking = report.blocking(strict=not args.permissive)
    if blocking:
        print(f"{len(blocking)} blocking diagnostic(s); script rejected", file=sys.stderr)
        return 1
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    if args.recorded:
        report = run_recorded(args.recorded, model=args.model)
        for outcome in report.outcomes:
            structural = "PASS" if outcome.structural.passed else "FAIL"
            verdict = "PASS" if outcome.passed else "FAIL"
            print(f"{outcome.id:28} structural={structural} judge={outcome.judge} -> {verdict}")
        print(f"pass-rate: {report.pass_rate:.0%}")
        return 0
    if args.live:
        print(
            "gmat-copilot eval --live: no eval prompt-set is committed yet; the live evaluation "
            "lands with the eval-suite work. Nothing to run.",
            file=sys.stderr,
        )
        return 0
    print(
        "gmat-copilot eval: pass --recorded <bundle> to replay a recorded bundle, or --live once "
        "the prompt-set lands.",
        file=sys.stderr,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmat-copilot",
        description="Generate, validate, and evaluate GMAT mission scripts from natural language.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    draft_parser = sub.add_parser("draft", help="generate a GMAT .script from a request")
    draft_parser.add_argument("request", help="what the script should do, in natural language")
    draft_parser.add_argument(
        "-m",
        "--model",
        required=True,
        help="provider:model selector (no default; e.g. anthropic:...)",
    )
    draft_parser.add_argument(
        "--permissive",
        action="store_true",
        help="return the best-effort draft with diagnostics attached",
    )

    validate_parser = sub.add_parser("validate", help="lint a GMAT .script")
    validate_parser.add_argument("script", help="path to a .script file, or - for stdin")
    validate_parser.add_argument(
        "--permissive", action="store_true", help="report diagnostics without rejecting"
    )

    eval_parser = sub.add_parser("eval", help="run the evaluation suite")
    eval_parser.add_argument(
        "--live", action="store_true", help="run live inference (needs a credential)"
    )
    eval_parser.add_argument(
        "--recorded", metavar="BUNDLE", help="replay a recorded eval bundle directory"
    )
    eval_parser.add_argument(
        "-m", "--model", default=JUDGE_MODEL, help="model selector for the run"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "draft":
        return _cmd_draft(args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "eval":
        return _cmd_eval(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
