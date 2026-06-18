"""Subprocess worker for the gmat-run dry-run tier (decision D12) — run as a module, not imported.

``python -m gmat_copilot._dryrun_worker --script <path> [--gmat-root <root>]`` loads a script
through gmat-run (the config tier), runs it and checks ``Results.converged`` when it declares a
solver (the execution tier), and prints the verdict as one JSON line on stdout for
:func:`gmat_copilot.dryrun.dry_run` to read back. gmatpy holds one process-global Moderator and
cannot re-bootstrap in a single interpreter, so every dry-run gets its own fresh process; this
module is that process's entry point.

``gmat_run`` is imported lazily inside :func:`_dry_run` so importing this module never bootstraps
gmatpy — the parent process and the GMAT-free base install stay clean. The actual GMAT round-trip is
exercised end to end by the gated, setup-gmat CI job (it is excluded from the coverage gate, which
runs GMAT-free).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from gmat_copilot.dryrun import extract_feedback_line, strip_paths

# The mission-sequence commands that open a solver branch (decision D12): only these warrant the
# execution tier, because only a solver can load-and-run yet fail to converge.
_SOLVER_COMMANDS = frozenset({"Target", "Optimize"})


def _has_solver(commands: Any) -> bool:
    """True when any command (or nested branch child) is a ``Target`` / ``Optimize``."""
    for cmd in commands:
        if cmd.type_name in _SOLVER_COMMANDS:
            return True
        if cmd.children and _has_solver(cmd.children):
            return True
    return False


def _err_text(exc: BaseException) -> str:
    """The richest text from a run-tier error: the raw GMAT ``.log`` if present, else ``str``."""
    log = getattr(exc, "log", None)
    if isinstance(log, str) and log.strip():
        return log
    return f"{type(exc).__name__}: {exc}"


def _load_text(exc: BaseException, load_log: Path) -> str:
    """Load-tier text: the redirected GMAT log (the real parse cause) if it captured an error.

    gmat-run's ``GmatLoadError`` is thin ("could not parse '<path>'") and carries no ``.log``, so
    the cause lives only in the redirected log. Falls back to ``str`` when that is uninformative.
    """
    if load_log.exists():
        text = load_log.read_text(encoding="utf-8", errors="replace")
        if "ERROR" in text or "Exception" in text:
            return text
    return f"{type(exc).__name__}: {exc}"


def _fail(tier: str, raw: str) -> dict[str, object]:
    """A failure verdict for *tier*, distilling *raw* into the one-line feedback."""
    return {
        "tier": tier,
        "ok": False,
        "converged": None,
        "one_line": extract_feedback_line(raw),
        "raw_log": strip_paths(raw),
    }


def _dry_run(script_path: Path, gmat_root: str | None) -> dict[str, object]:
    """Load (config tier) then, if a solver is present, run (execution tier); return the verdict."""
    from gmat_run import GmatError, Mission
    from gmat_run.install import locate_gmat
    from gmat_run.runtime import bootstrap

    root = gmat_root or None
    with tempfile.TemporaryDirectory() as wd:
        load_log = Path(wd) / "gmat_load.log"
        gmat = bootstrap(locate_gmat(root))
        # Redirect the GMAT log so a thin GmatLoadError's real cause is recoverable.
        with contextlib.suppress(Exception):  # pragma: no cover - older gmatpy may lack it
            gmat.UseLogFile(str(load_log))

        try:  # config tier
            mission = Mission.load(script_path, gmat_root=root)
        except Exception as exc:  # surface as a verdict, not a crash
            return _fail("load", _load_text(exc, load_log))

        if not _has_solver(mission.summary().commands):
            return {"tier": "load", "ok": True, "converged": None, "one_line": "", "raw_log": ""}

        try:  # execution tier (solver present)
            result = mission.run(working_dir=wd, overwrite=True)
        except GmatError as exc:
            return _fail("run", _err_text(exc))

        conv = {str(name): bool(ok) for name, ok in dict(result.converged).items()}
        if conv and all(conv.values()):
            return {"tier": "run", "ok": True, "converged": conv, "one_line": "", "raw_log": ""}
        failed = sorted(name for name, ok in conv.items() if not ok)
        one_line = (
            f"solver(s) {', '.join(failed)} did not converge"
            if failed
            else "solver convergence could not be determined"
        )
        return {
            "tier": "run",
            "ok": False,
            "converged": conv or None,
            "one_line": one_line,
            "raw_log": strip_paths(result.log),
        }


def main(argv: list[str] | None = None) -> int:
    """Parse args, dry-run the script, print the verdict as one JSON line; return the exit code."""
    parser = argparse.ArgumentParser(prog="python -m gmat_copilot._dryrun_worker")
    parser.add_argument("--script", required=True, help="Path to the .script to dry-run")
    parser.add_argument("--gmat-root", default=None, help="GMAT install root (else GMAT_ROOT)")
    args = parser.parse_args(argv)
    verdict = _dry_run(Path(args.script), args.gmat_root)
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry point
    sys.exit(main())
