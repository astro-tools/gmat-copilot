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
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .dryrun import GmatExtraNotInstalled, dry_run, require_gmat_extra
from .eval.judge import JUDGE_MODEL
from .eval.leaderboard import (
    LeaderboardError,
    assert_aggregate_only,
    build_from_config,
    bundle_sha16,
    dumps,
    summarize,
)
from .eval.lift import DEFAULT_BUDGET, LiftReport, run_live_lift, run_recorded_lift
from .eval.prompts import load_prompts
from .eval.runner import EvalReport, record_bundle, run_live, run_recorded
from .generate import DraftRejected, draft
from .provenance import Provenance, sidecar_path
from .providers import ProviderError
from .result import CopilotResult, DryRunReport, LintReport
from .validate import validate

__all__ = ["main"]

# The named subcommands. A leading token that is neither one of these nor a flag is taken as an
# intent for the headline generate form, ``gmat-copilot "<intent>" ...``.
_SUBCOMMANDS = ("draft", "validate", "eval", "leaderboard")

# The committed defaults for the leaderboard subcommand: the seed config and the published board.
_LEADERBOARD_CONFIG = "leaderboard/seeds.json"
_LEADERBOARD_BOARD = "leaderboard/leaderboard.json"

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
    "\n"
    "close-the-loop (the [gmat] extra is needed only for --dry-run):\n"
    "  --dry-run           after linting, load/run the draft in GMAT to catch runtime errors\n"
    "                      (needs the [gmat] extra and a discoverable GMAT install)\n"
    "  --repair N          on a failing draft, feed the diagnostics back and regenerate up to N\n"
    "                      times (default 0: a single pass)\n"
    "  --provenance        also write a .copilot.json provenance sidecar next to the script\n"
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


def _dry_run_status(report: DryRunReport | None) -> str | None:
    """One-line dry-run outcome for the summary, or ``None`` when the dynamic tier did not run."""
    if report is None:
        return None
    if report.ok:
        return "dry-run: ok"
    detail = report.one_line or "the dry-run failed"
    return f"dry-run: failed at {report.tier}: {detail}"


def _retries_spent(result: CopilotResult) -> int:
    """How many repair retries the loop spent: one fewer than the recorded draft attempts (D13)."""
    prov = result.provenance
    if isinstance(prov, Provenance):
        return max(len(prov.repair.attempts) - 1, 0)
    return 0


def _generate_summary(result: CopilotResult, args: argparse.Namespace) -> str:
    """The stderr summary: lint, plus the dry-run outcome and retries when those ran (ASCII)."""
    parts = [f"lint: {_lint_summary(result.lint)}"]
    if args.dry_run:
        parts.append(_dry_run_status(result.dry_run) or "dry-run: skipped (lint not clean)")
    if args.repair > 0:
        parts.append(f"retries: {_retries_spent(result)}")
    return "; ".join(parts)


def _ensure_gmat_extra() -> int | None:
    """Check the ``[gmat]`` extra; return exit code 2 with a clear message when it is absent."""
    try:
        require_gmat_extra()
    except GmatExtraNotInstalled as exc:
        print(f"gmat-copilot: {exc}", file=sys.stderr)
        return 2
    return None


def _report_rejection(result: CopilotResult, args: argparse.Namespace) -> int:
    """Print why a strict draft was rejected (lint and/or dry-run) and return exit code 1 (D13)."""
    _print_diagnostics(result.lint)
    if result.lint.blocking(strict=True):
        reason = f"lint: {_lint_summary(result.lint)}"
    elif result.dry_run is not None and not result.dry_run.ok:
        detail = result.dry_run.one_line or "the dry-run failed"
        reason = f"dry-run failed at {result.dry_run.tier}: {detail}"
    else:  # defensive: DraftRejected implies at least one blocking tier
        reason = _lint_summary(result.lint)
    spent = ""
    if args.repair > 0:
        n = _retries_spent(result)
        spent = f" (after {n} repair {'retry' if n == 1 else 'retries'})"
    print(f"gmat-copilot: rejected: {reason}{spent}", file=sys.stderr)
    return 1


def _cmd_draft(args: argparse.Namespace) -> int:
    """Generate a ``.script`` from a request, write it, and print a summary (D4/D5/D12/D13/D14).

    Shared by the headline ``gmat-copilot "<intent>"`` form and the ``draft`` alias. ``--dry-run``
    enables the gmat-run tier (needs the ``[gmat]`` extra), ``--repair N`` the bounded repair loop,
    and ``--provenance`` writes a ``.copilot.json`` sidecar next to the script. The script goes to
    ``--output`` (default ``mission.script``; ``-`` for stdout); the summary and any diagnostics go
    to stderr. Strict rejection (after the repair budget) writes nothing and exits non-zero.
    """
    if args.repair < 0:
        print("gmat-copilot: --repair must be >= 0", file=sys.stderr)
        return 2
    if args.dry_run:
        code = _ensure_gmat_extra()
        if code is not None:
            return code
    if args.provenance and args.output == "-":
        print(
            "gmat-copilot: --provenance needs a file output for its sidecar, not stdout (-o -)",
            file=sys.stderr,
        )
        return 2
    try:
        result = draft(
            args.request,
            model=args.model,
            strict=args.strict,
            repair=args.repair,
            dry_run=args.dry_run,
        )
    except DraftRejected as exc:
        return _report_rejection(exc.result, args)
    except GmatExtraNotInstalled as exc:  # defensive — the eager check above usually catches it
        print(f"gmat-copilot: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"gmat-copilot: {exc}", file=sys.stderr)
        return 2
    if not result.lint.clean:
        _print_diagnostics(result.lint)
    summary = _generate_summary(result, args)
    if args.output == "-":
        sys.stdout.write(result.script)
        print(summary, file=sys.stderr)
    else:
        target = result.save(args.output or "mission.script", sidecar=args.provenance)
        suffix = f" -> wrote {target}"
        if args.provenance:
            suffix += f" (+ {sidecar_path(target).name})"
        print(summary + suffix, file=sys.stderr)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Lint a script and, with ``--dry-run``, dry-run a lint-clean one in the ``[gmat]`` tier."""
    if args.dry_run:
        code = _ensure_gmat_extra()
        if code is not None:
            return code
    text = sys.stdin.read() if args.script == "-" else Path(args.script).read_text("utf-8")
    report = validate(text)
    for d in report.diagnostics:
        print(f"{d.line}:{d.column}: {d.severity.value}: {d.rule}: {d.message}")
    blocking = report.blocking(strict=not args.permissive)
    rejected = bool(blocking)
    if blocking:
        print(f"{len(blocking)} blocking diagnostic(s); script rejected", file=sys.stderr)
    # The dynamic tier runs only on a lint-clean script (decision D12) and only when asked. When it
    # is asked for but the script is not lint-clean, say so rather than skipping it silently (the
    # generate path reports the same skip).
    if args.dry_run:
        if report.blocking(strict=True):
            print("dry-run: skipped (lint not clean)", file=sys.stderr)
        else:
            verdict = dry_run(text)
            print(_dry_run_status(verdict), file=sys.stderr)
            if not verdict.ok:
                rejected = True
    return 1 if rejected else 0


def _print_eval_report(report: EvalReport) -> None:
    """Print per-prompt outcomes, the per-tier pass-rates, and the aggregate."""
    for outcome in report.outcomes:
        structural = "PASS" if outcome.structural.passed else "FAIL"
        verdict = "PASS" if outcome.passed else "FAIL"
        print(
            f"{outcome.id:28} [{outcome.difficulty:6}] structural={structural} "
            f"judge={outcome.judge} -> {verdict}"
        )
    for tier, rate in sorted(report.pass_rate_by_tier.items()):
        print(f"  {tier:6}: {rate:.0%}")
    print(f"pass-rate: {report.pass_rate:.0%}")


def _print_lift_report(report: LiftReport) -> None:
    """Print per-prompt base/repaired outcomes, then the per-tier dry-run-agreement and lift."""
    for row in report.rows:
        base = "runnable" if row.base.runnable else "FAIL"
        repaired = "runnable" if row.repaired.runnable else "FAIL"
        print(
            f"{row.id:24} [{row.difficulty:6}] repair=0:{base:9} "
            f"repair={report.budget}:{repaired:9} (retries={row.retries}, {row.stop_reason})"
        )
    print("dry-run agreement (of statically-accepted drafts, the fraction that also run):")
    for tier, agree in sorted(report.dry_run_agreement_by_tier.items()):
        print(f"  {tier:6}: {'n/a' if agree is None else f'{agree:.0%}'}")
    print(f"repair-loop lift (repair={report.budget} - repair=0):")
    base_by, repaired_by = report.base_runnable_by_tier, report.repaired_runnable_by_tier
    for tier, lift in sorted(report.lift_by_tier.items()):
        print(f"  {tier:6}: {base_by[tier]:.0%} -> {repaired_by[tier]:.0%}  ({lift:+.0%})")
    print(
        f"overall: {report.base_runnable:.0%} -> {report.repaired_runnable:.0%}  "
        f"({report.lift:+.0%})"
    )


def _cmd_eval(args: argparse.Namespace) -> int:
    try:
        if args.recorded:
            # A recorded bundle keyed for a different model raises ProviderError ("no fixture …");
            # keep it inside the guard so it exits cleanly like the live paths, not as a traceback.
            _print_eval_report(run_recorded(args.recorded, model=args.model))
            return 0
        if args.lift_recorded:
            _print_lift_report(run_recorded_lift(args.lift_recorded, budget=args.budget))
            return 0
        if args.lift:
            if not args.prompts:
                print("gmat-copilot eval --lift: pass --prompts <path>", file=sys.stderr)
                return 2
            code = (
                _ensure_gmat_extra()
            )  # the live lift drives a real gmat-run dry-run (decision D12)
            if code is not None:
                return code
            _print_lift_report(
                run_live_lift(
                    load_prompts(args.prompts),
                    model=args.model,
                    judge_model=args.judge_model,
                    n=args.n,
                    budget=args.budget,
                    pace=args.pace,
                )
            )
            return 0
        if args.record:
            prompts_path = args.prompts or Path(args.record) / "prompts.json"
            report = record_bundle(
                load_prompts(prompts_path),
                args.record,
                model=args.model,
                judge_model=args.judge_model,
                n=args.n,
                pace=args.pace,
            )
            _print_eval_report(report)
            return 0
        if args.live:
            if not args.prompts:
                print("gmat-copilot eval --live: pass --prompts <path>", file=sys.stderr)
                return 2
            report = run_live(
                load_prompts(args.prompts),
                model=args.model,
                judge_model=args.judge_model,
                n=args.n,
                pace=args.pace,
            )
            _print_eval_report(report)
            return 0
    except ProviderError as exc:
        print(f"gmat-copilot: {exc}", file=sys.stderr)
        return 2
    print(
        "gmat-copilot eval: pass --recorded <bundle> to replay deterministically, --live "
        "--prompts <path> to run live, or --record <dir> to refresh a bundle's fixtures. For the "
        "close-the-loop eval (dry-run agreement + repair lift), pass --lift-recorded <bundle> or "
        "--lift --prompts <path>.",
        file=sys.stderr,
    )
    return 0


def _now_utc() -> str:
    """The current UTC time as a ``Z``-suffixed ISO-8601 stamp (the board's ``generated_at``)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cmd_leaderboard(args: argparse.Namespace) -> int:
    if args.leaderboard_command == "build":
        return _leaderboard_build(args)
    if args.leaderboard_command == "verify":
        return _leaderboard_verify(args)
    print(
        "gmat-copilot leaderboard: pass `build` to assemble the board from the seed config, or "
        "`verify` to re-derive each row's public score from its recorded bundle (decision D7).",
        file=sys.stderr,
    )
    return 0


def _leaderboard_build(args: argparse.Namespace) -> int:
    """Assemble ``leaderboard.json`` from the seed config via the recorded scorer (decision D16)."""
    try:
        config = json.loads(Path(args.config).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"gmat-copilot leaderboard build: cannot read {args.config}: {exc}", file=sys.stderr)
        return 2
    held_out_root = Path(args.held_out) if args.held_out else None
    board, notes = build_from_config(
        config,
        root=Path(args.root),
        generated_at=args.generated_at or _now_utc(),
        tool_version=__version__,
        held_out_root=held_out_root,
    )
    for note in notes:
        print(f"gmat-copilot leaderboard: {note}", file=sys.stderr)
    text = dumps(board)
    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {len(board['entries'])} row(s) to {args.out}", file=sys.stderr)
    return 0


def _leaderboard_verify(args: argparse.Namespace) -> int:
    """Re-derive each seeded row's public score + bundle hash and check the firewall (decision D16).

    The reproducibility audit a third party runs: the **public** number must reproduce byte-for-byte
    from the committed recorded bundle, and the board must carry no per-prompt gold (aggregate-only,
    decision D7). The held-out cells are not re-derived here — they reproduce only in gated CI,
    which is exactly the firewall.
    """
    try:
        board = json.loads(Path(args.board).read_text("utf-8"))
        config = json.loads(Path(args.config).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"gmat-copilot leaderboard verify: cannot read input: {exc}", file=sys.stderr)
        return 2
    try:
        assert_aggregate_only(board)
    except LeaderboardError as exc:
        print(f"gmat-copilot leaderboard verify: {exc}", file=sys.stderr)
        return 1

    seeds = {seed["model"]: seed for seed in config.get("seeds", [])}
    problems: list[str] = []
    checked = 0
    for row in board.get("entries", []):
        model = row["model"]
        seed = seeds.get(model)
        if seed is None:
            print(
                f"gmat-copilot leaderboard: skip {model}: no seed config to reproduce",
                file=sys.stderr,
            )
            continue
        public_dir = Path(args.root) / seed["public_bundle"]
        if not (public_dir / "completions.json").exists():
            problems.append(f"{model}: public bundle absent, cannot reproduce")
            continue
        try:
            got = summarize(run_recorded(public_dir, model=model)).to_dict()
        except ProviderError as exc:
            problems.append(f"{model}: {exc}")
            continue
        if got != row["public"]:
            problems.append(f"{model}: public score does not reproduce ({got} != {row['public']})")
        if bundle_sha16(public_dir) != row["run"]["recorded_bundle_sha16"]:
            problems.append(f"{model}: recorded bundle hash does not match the row")
        checked += 1

    if problems:
        for problem in problems:
            print(f"gmat-copilot leaderboard verify: {problem}", file=sys.stderr)
        return 1
    print(f"verified: {checked} public row(s) reproduce; board is aggregate-only", file=sys.stderr)
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="after linting, load/run the draft in GMAT (needs the [gmat] extra + a GMAT install)",
    )
    parser.add_argument(
        "--repair",
        metavar="N",
        type=int,
        default=0,
        help="on a failing draft, feed the diagnostics back and regenerate up to N times "
        "(default 0: a single pass)",
    )
    parser.add_argument(
        "--provenance",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also write a .copilot.json provenance sidecar next to the script",
    )
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
    validate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="also dry-run a lint-clean script in GMAT (needs the [gmat] extra + a GMAT install)",
    )

    eval_parser = sub.add_parser("eval", help="run the evaluation suite")
    mode = eval_parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--recorded", metavar="BUNDLE", help="replay a recorded eval bundle directory (no model)"
    )
    mode.add_argument("--live", action="store_true", help="run live inference (needs a credential)")
    mode.add_argument(
        "--record", metavar="DIR", help="run live and freeze the bundle's fixtures into DIR"
    )
    mode.add_argument(
        "--lift-recorded",
        metavar="BUNDLE",
        help="replay a recorded close-the-loop bundle: dry-run agreement + repair lift (no model)",
    )
    mode.add_argument(
        "--lift",
        action="store_true",
        help="run the close-the-loop eval live (needs a credential and the [gmat] extra)",
    )
    eval_parser.add_argument(
        "--prompts",
        metavar="PATH",
        help="prompt-set JSON for --live (defaults to DIR/prompts.json for --record)",
    )
    eval_parser.add_argument(
        "-m",
        "--model",
        default=JUDGE_MODEL,
        help="recorded-key model for --recorded, or a provider:model selector for --live/--record",
    )
    eval_parser.add_argument(
        "--judge-model", default=JUDGE_MODEL, help="judge model for --live/--record"
    )
    eval_parser.add_argument(
        "-n", type=int, default=3, help="judge votes per prompt for --live/--record (default 3)"
    )
    eval_parser.add_argument(
        "--pace", type=float, default=0.0, help="seconds between model calls (free-tier pacing)"
    )
    eval_parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help=f"repair retry budget for --lift / --lift-recorded (default {DEFAULT_BUDGET}: the D13 "
        "budget)",
    )

    _add_leaderboard_parser(sub)
    return parser


def _add_leaderboard_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``leaderboard build`` / ``leaderboard verify`` subcommands (decision D16)."""
    parser = sub.add_parser(
        "leaderboard",
        help="build or verify the per-model leaderboard over the eval suite",
        description="Assemble the per-model leaderboard from the recorded eval bundles, ranked on "
        "the never-committed held-out headline with the committed public set as the anchor, or "
        "verify that a published board reproduces.",
    )
    board_sub = parser.add_subparsers(dest="leaderboard_command")

    build = board_sub.add_parser("build", help="assemble leaderboard.json from the seed config")
    build.add_argument(
        "--config", default=_LEADERBOARD_CONFIG, metavar="PATH", help="seed config JSON"
    )
    build.add_argument(
        "--out",
        default=_LEADERBOARD_BOARD,
        metavar="PATH",
        help="where to write leaderboard.json (use - for stdout)",
    )
    build.add_argument(
        "--held-out",
        metavar="DIR",
        help="root of the never-committed held-out bundles (fetched in gated CI); omit to leave "
        "every held-out cell pending",
    )
    build.add_argument(
        "--generated-at",
        metavar="ISO",
        help="board timestamp (default: now, UTC); pass a fixed value for a reproducible build",
    )
    build.add_argument(
        "--root",
        default=".",
        metavar="DIR",
        help="repo root the config's bundle paths resolve under",
    )

    verify = board_sub.add_parser(
        "verify", help="re-derive each row's public score from its recorded bundle (decision D7)"
    )
    verify.add_argument(
        "board", nargs="?", default=_LEADERBOARD_BOARD, help="path to a published leaderboard.json"
    )
    verify.add_argument(
        "--config", default=_LEADERBOARD_CONFIG, metavar="PATH", help="seed config JSON"
    )
    verify.add_argument(
        "--root",
        default=".",
        metavar="DIR",
        help="repo root the config's bundle paths resolve under",
    )


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
    if args.command == "leaderboard":
        return _cmd_leaderboard(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
