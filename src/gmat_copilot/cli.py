"""The ``gmat-copilot`` command-line interface.

The headline command generates a script straight from an intent —
``gmat-copilot "<intent>" [-o PATH] [-m provider:model] [--strict|--permissive]`` — calling
:func:`gmat_copilot.draft` and writing the ``.script`` it returns, then printing a concise lint
summary. ``draft`` is a named alias of that same generate path. ``validate`` lints an existing
script and ``eval`` runs the evaluation suite. Generation needs a provider credential (there is no
default model, decision D4); ``validate`` and the recorded ``eval`` path are GMAT-free and
model-free.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .eval.judge import JUDGE_MODEL
from .eval.runner import run_recorded
from .generate import DraftRejected, draft
from .providers import ProviderError
from .result import LintReport
from .validate import validate

__all__ = ["main"]

# The named subcommands. A leading token that is neither one of these nor a flag is taken as an
# intent for the headline generate form, ``gmat-copilot "<intent>" ...``.
_SUBCOMMANDS = ("draft", "validate", "eval")

# Documents model selection and the per-provider credentials for the generate help text (decision
# D4). Kept ASCII so the help renders on a Windows cp1252 console.
_AUTH_EPILOG = (
    "model selection (no default; choose one explicitly as provider:model):\n"
    "  anthropic:<model>     a Claude model         env ANTHROPIC_API_KEY    extra [anthropic]\n"
    "  openai:<model>        an OpenAI model         env OPENAI_API_KEY       extra [openai]\n"
    "  ollama:<model>        a local Ollama server   env OLLAMA_HOST          extra [ollama]\n"
    "  github:<owner/model>  GitHub Models           env GH_TOKEN / MODELS_PAT\n"
    "\n"
    "Omit --model to list the providers reachable from your configured credentials.\n"
    "Credentials are read from the environment, never committed.\n"
    "\n"
    "modes:\n"
    "  --strict (default)  reject a draft that does not lint clean (any error or warning)\n"
    "  --permissive        write the best-effort draft with its diagnostics attached\n"
)


def _lint_summary(report: LintReport) -> str:
    """A one-line description of a lint report: ``clean`` or the error/warning/info counts."""
    if report.clean:
        return "clean"
    parts: list[str] = []
    if report.errors:
        parts.append(f"{len(report.errors)} error(s)")
    if report.warnings:
        parts.append(f"{len(report.warnings)} warning(s)")
    if report.infos:
        parts.append(f"{len(report.infos)} info(s)")
    return ", ".join(parts)


def _print_diagnostics(report: LintReport) -> None:
    """Print each lint diagnostic, one ``line:col: severity: rule: message`` per line, to stderr."""
    for d in report.diagnostics:
        print(
            f"{d.line}:{d.column}: {d.severity.value}: {d.rule}: {d.message}",
            file=sys.stderr,
        )


def _cmd_draft(args: argparse.Namespace) -> int:
    """Generate a ``.script`` from a request, write it, and print a lint summary (D4/D5/D10).

    Shared by the headline ``gmat-copilot "<intent>"`` form and the ``draft`` alias. The script is
    written to ``--output`` (default ``mission.script``; ``-`` for stdout); the lint summary and any
    diagnostics go to stderr. Strict rejection writes nothing and exits non-zero.
    """
    try:
        result = draft(args.request, model=args.model, strict=args.strict)
    except DraftRejected as exc:
        _print_diagnostics(exc.result.lint)
        print(f"gmat-copilot: lint: rejected: {_lint_summary(exc.result.lint)}", file=sys.stderr)
        return 1
    except (NotImplementedError, ProviderError) as exc:
        print(f"gmat-copilot: {exc}", file=sys.stderr)
        return 2
    if not result.lint.clean:
        _print_diagnostics(result.lint)
    if args.output == "-":
        sys.stdout.write(result.script)
        print(f"lint: {_lint_summary(result.lint)}", file=sys.stderr)
    else:
        target = result.save(args.output or "mission.script")
        print(f"lint: {_lint_summary(result.lint)} -> wrote {target}", file=sys.stderr)
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


def _add_generate_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the generate arguments shared by the bare ``<intent>`` form and the ``draft`` alias."""
    parser.add_argument("request", help="what the script should do, in natural language")
    parser.add_argument(
        "-m",
        "--model",
        metavar="PROVIDER:MODEL",
        help="provider:model selector (no default; e.g. anthropic:claude-..., "
        "github:openai/gpt-4.1-mini, ollama:llama3). Omit to list reachable providers.",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="write the .script to PATH (default: mission.script); use - for stdout",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        help="reject a draft that does not lint clean (any error or warning; the default)",
    )
    mode.add_argument(
        "--permissive",
        dest="strict",
        action="store_false",
        help="write the best-effort draft with all diagnostics attached",
    )
    parser.set_defaults(strict=True)
    return parser


def _generate_parser() -> argparse.ArgumentParser:
    """The standalone parser for the bare ``gmat-copilot "<intent>" ...`` generate form."""
    parser = argparse.ArgumentParser(
        prog="gmat-copilot",
        description="Generate a GMAT mission .script from a natural-language request.",
        epilog=_AUTH_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    return _add_generate_args(parser)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmat-copilot",
        description="Generate, validate, and evaluate GMAT mission scripts from natural language. "
        'Run `gmat-copilot "<intent>" ...` to generate a script directly.',
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    draft_parser = sub.add_parser(
        "draft",
        help='generate a GMAT .script from a request (alias of `gmat-copilot "<intent>"`)',
        description="Generate a GMAT mission .script from a natural-language request.",
        epilog=_AUTH_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_generate_args(draft_parser)

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
    argv = list(sys.argv[1:] if argv is None else argv)
    # Headline form: a leading non-flag token that is not a subcommand is an intent to generate.
    if argv and not argv[0].startswith("-") and argv[0] not in _SUBCOMMANDS:
        return _cmd_draft(_generate_parser().parse_args(argv))
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
