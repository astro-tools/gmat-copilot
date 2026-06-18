"""The dynamic gmat-run dry-run tier — the optional ``[gmat]`` half of validation (decision D12).

Where :mod:`gmat_copilot.validate` is the static, GMAT-free, instant lint gate (decision D5), this
is the dynamic backstop: it drives GMAT's own loader and engine over a lint-clean script to catch
the defects a tree-sitter parse cannot — bad numerics, malformed epochs, missing data files, the
undeclared-reference case the linter is too conservative to flag, and solver non-convergence.

The dry-run is **tiered** (decision D12): ``Mission.load`` is the config tier; ``mission.run`` +
``Results.converged`` is the execution tier, entered only when the script has a solver
(``Target`` / ``Optimize``), because a script can load and run yet leave a solver unconverged. Each
dry-run runs in a **fresh subprocess** — gmatpy holds one process-global Moderator and cannot
re-bootstrap in a single interpreter — so a crash or timeout degrades to a failure verdict rather
than taking down the caller, and a repair loop can dry-run several drafts back to back.

The runner imports gmat-run only inside the worker subprocess (:mod:`gmat_copilot._dryrun_worker`);
this module stays import-safe with the ``[gmat]`` extra absent, raising
:class:`GmatExtraNotInstalled` only when :func:`dry_run` is actually called without it. The static
lint gate and all of generation remain GMAT-free.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from .result import DryRunReport

__all__ = [
    "GmatExtraNotInstalled",
    "dry_run",
    "extract_feedback_line",
    "require_gmat_extra",
    "strip_paths",
]

#: Default wall-clock budget for one dry-run subprocess (decision D12) — bounds a runaway solver.
DRYRUN_TIMEOUT_S = 300.0


class GmatExtraNotInstalled(RuntimeError):
    """The dry-run was called without the optional ``[gmat]`` extra (or no GMAT install).

    Generation and the static lint gate are GMAT-free; only the dynamic dry-run needs gmat-run and a
    GMAT install. This is raised eagerly by :func:`dry_run` so a missing extra is a clear,
    actionable error rather than an obscure import failure inside a subprocess.
    """


# --------------------------------------------------------------------------- raw log -> one line

# Distil a raw GMAT log / gmat-run error into one actionable feedback line. GMAT emits its
# substantive cause as an ``Interpreter Exception:`` or a ``**** ERROR ****`` line, optionally
# prefixed with the script path and a sequence number and suffixed with ``in line:``; strip the
# noise and keep the first substantive error line, with warnings as a fallback. (Measured over the
# real defect corpus in spike V5.)
_PATH_PREFIX_RE = re.compile(r"^[^:\n]*\.script:\s*", re.IGNORECASE)
_SEQNO_PREFIX_RE = re.compile(r"^\d+:\s+\S+:\s+")
_ERROR_RE = re.compile(r"\*+\s*ERROR\s*\*+\s*(?:Interpreter\s+Exception:\s*)?(?P<msg>.+?)\s*$")
_INTERP_RE = re.compile(r"Interpreter\s+Exception:\s*(?P<msg>.+?)\s*$")
_WARNING_RE = re.compile(r"\*+\s*WARNING\s*\*+\s*(?P<msg>.+?)\s*$")
_IN_LINE_SUFFIX_RE = re.compile(r"\s+in\s+line:?\s*$")
# Final guard: collapse any absolute path ending in a known artefact to its basename, so a feedback
# line never leaks a local filesystem path.
_ABS_PATH_RE = re.compile(r"/[\w./ -]+/([\w.-]+\.(?:script|txt|log))")


def strip_paths(text: str) -> str:
    """Replace any absolute path to a ``.script`` / ``.txt`` / ``.log`` with its basename."""
    return _ABS_PATH_RE.sub(r"\1", text)


def extract_feedback_line(raw: str) -> str:
    """Return one actionable line from a raw GMAT log or gmat-run error string.

    Prefers the first substantive ERROR / Interpreter-Exception line; falls back to the first
    WARNING, then to the first non-blank line. Strips the script-path prefix, the sequence-number
    prefix, and the trailing ``in line:`` noise GMAT appends, and sanitises any absolute path to its
    basename.
    """
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return ""
    warning: str | None = None
    for ln in lines:
        bare = _SEQNO_PREFIX_RE.sub("", ln)
        bare = _PATH_PREFIX_RE.sub("", bare)
        for rx in (_ERROR_RE, _INTERP_RE):
            m = rx.search(bare)
            if m:
                return strip_paths(_IN_LINE_SUFFIX_RE.sub("", m.group("msg")).strip())
        if warning is None:
            mw = _WARNING_RE.search(bare)
            if mw:
                warning = strip_paths(_IN_LINE_SUFFIX_RE.sub("", mw.group("msg")).strip())
    if warning:
        return warning
    first = _PATH_PREFIX_RE.sub("", _SEQNO_PREFIX_RE.sub("", lines[0]))
    return strip_paths(first)[:200]


# --------------------------------------------------------------------------- the runner

_VERDICT_KEYS = frozenset({"tier", "ok", "converged", "one_line", "raw_log"})


def require_gmat_extra() -> None:
    """Raise :class:`GmatExtraNotInstalled` unless gmat-run is importable.

    The eager guard the dynamic tier and its CLI surfaces call before attempting a dry-run, so a
    missing ``[gmat]`` extra is a clear, actionable error rather than an obscure import failure.
    """
    if importlib.util.find_spec("gmat_run") is None:
        raise GmatExtraNotInstalled(
            "the gmat-run dry-run needs the optional [gmat] extra and a GMAT install. "
            "Install it with `pip install gmat-copilot[gmat]` and make GMAT discoverable "
            "(set GMAT_ROOT or install to a standard location). Generation and the lint gate "
            "do not need GMAT."
        )


def _verdict_from_stdout(stdout: str) -> dict[str, object] | None:
    """Parse the worker's one-line JSON verdict from *stdout*, scanning from the tail.

    The worker prints exactly one JSON object on stdout; scanning from the end skips any incidental
    chatter (warnings, banners). Returns the parsed verdict, or ``None`` when no line parses as a
    JSON object carrying the expected keys.
    """
    import json

    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.keys() >= _VERDICT_KEYS:
            return cast("dict[str, object]", data)
    return None


def _report_from_verdict(verdict: dict[str, object]) -> DryRunReport:
    """Build a :class:`DryRunReport` from the worker's validated JSON verdict."""
    converged = verdict.get("converged")
    return DryRunReport(
        tier=str(verdict.get("tier", "run")),
        ok=bool(verdict.get("ok", False)),
        converged=cast("dict[str, bool]", converged) if isinstance(converged, dict) else None,
        one_line=str(verdict.get("one_line", "")),
        raw_log=str(verdict.get("raw_log", "")),
    )


def dry_run(
    script: str,
    *,
    timeout: float = DRYRUN_TIMEOUT_S,
    gmat_root: str | None = None,
) -> DryRunReport:
    """Dry-run a lint-clean GMAT *script* against gmat-run in a fresh subprocess (decision D12).

    The script is loaded with ``Mission.load`` (the config tier); when it declares a solver
    (``Target`` / ``Optimize``) it is also run with ``mission.run`` and its ``Results.converged``
    checked (the execution tier). The verdict is a :class:`~gmat_copilot.result.DryRunReport`:
    ``ok`` is True when the script loads (and, if a solver is present, runs and converges), and a
    failure carries one actionable, path-free line distilled from GMAT's own diagnostics.

    This is the dynamic tier only — it does **not** lint. Per decision D12 the dry-run runs only on
    a lint-clean script, so callers gate it behind :func:`gmat_copilot.validate.validate`; the
    repair loop sequences the two.

    :param script: GMAT mission-script source text (lint-clean — see above).
    :param timeout: wall-clock budget in seconds for the subprocess; on expiry the verdict degrades
        to a ``"timeout"`` failure (decision D12 default: 300 s, to bound a runaway solver).
    :param gmat_root: GMAT install root; defaults to ``GMAT_ROOT`` / standard-location discovery
        (gmat-run's ``locate_gmat``), which runs inside the worker subprocess.
    :raises GmatExtraNotInstalled: when the ``[gmat]`` extra (gmat-run) is not importable.
    :returns: the dry-run verdict as a :class:`~gmat_copilot.result.DryRunReport`.
    """
    require_gmat_extra()
    root = gmat_root if gmat_root is not None else os.environ.get("GMAT_ROOT", "")
    with tempfile.TemporaryDirectory(prefix="gmat-copilot-dryrun-") as td:
        script_path = Path(td) / "draft.script"
        script_path.write_text(script, encoding="utf-8")
        argv = [sys.executable, "-m", "gmat_copilot._dryrun_worker", "--script", str(script_path)]
        if root:
            argv += ["--gmat-root", root]
        try:
            # Fixed argv (our own worker module + a temp path); never shell-interpreted.
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return DryRunReport(
                tier="timeout",
                ok=False,
                converged=None,
                one_line=f"dry-run exceeded the {timeout:g}s timeout",
                raw_log="",
            )
    verdict = _verdict_from_stdout(proc.stdout)
    if verdict is None:
        tail = (proc.stderr or proc.stdout).strip()[-200:]
        return DryRunReport(
            tier="crash",
            ok=False,
            converged=None,
            one_line="dry-run subprocess produced no verdict",
            raw_log=strip_paths(tail),
        )
    return _report_from_verdict(verdict)
