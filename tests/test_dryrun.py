"""The dry-run tier's GMAT-free surface (decision D12): log extraction, verdict parsing, the

``[gmat]``-extra guard, and the subprocess orchestration with ``subprocess.run`` mocked. The real
GMAT round-trip is covered by ``test_dryrun_gmat.py`` under the gated setup-gmat CI job.
"""

from __future__ import annotations

import importlib.util
import subprocess

import pytest

from gmat_copilot import DryRunReport, GmatExtraNotInstalled
from gmat_copilot import dryrun as dryrun_mod
from gmat_copilot.dryrun import (
    _report_from_verdict,
    _verdict_from_stdout,
    dry_run,
    extract_feedback_line,
    require_gmat_extra,
    strip_paths,
)

# --------------------------------------------------------------------------- extraction

# Realistic raw GMAT log fragments and the one actionable line each distils to. Mirrors the defect
# classes characterised in spike V5: an ERROR with an Interpreter Exception, a bare field ERROR, and
# an ODEModel reference error, each with the ``in line:`` / path noise GMAT appends.
_ERROR_CASES = [
    (
        '**** ERROR **** Interpreter Exception: Gregorian date "01 Foo 2025 12:00:00.000" '
        "is not valid. in line:\n",
        'Gregorian date "01 Foo 2025 12:00:00.000" is not valid.',
    ),
    (
        '**** ERROR **** The field name "DryMas" on object "Sat" is not permitted\n',
        'The field name "DryMas" on object "Sat" is not permitted',
    ),
    (
        'Interpreter Exception: The ODEModel named "FM", referenced by the Propagator '
        '"Prop" cannot be found\n',
        'The ODEModel named "FM", referenced by the Propagator "Prop" cannot be found',
    ),
]


@pytest.mark.parametrize(("raw", "expected"), _ERROR_CASES)
def test_extract_keeps_the_substantive_error_line(raw: str, expected: str) -> None:
    assert extract_feedback_line(raw) == expected


def test_extract_strips_seqno_and_path_prefix() -> None:
    raw = "12: /home/u/work/draft.script: **** ERROR **** Utility Exception: bad value\n"
    assert extract_feedback_line(raw) == "Utility Exception: bad value"


def test_extract_falls_back_to_warning_then_first_line() -> None:
    assert extract_feedback_line("**** WARNING **** something mild happened") == (
        "something mild happened"
    )
    # No ERROR/Interpreter/WARNING marker: the first non-blank line, path-sanitised.
    raw = 'GMAT could not parse "/tmp/abc/draft.script"; check the GMAT log\n'
    assert extract_feedback_line(raw) == 'GMAT could not parse "draft.script"; check the GMAT log'


def test_extract_empty_and_blank_return_empty() -> None:
    assert extract_feedback_line("") == ""
    assert extract_feedback_line("   \n  \n\t\n") == ""


def test_strip_paths_collapses_any_absolute_path_to_basename() -> None:
    assert strip_paths("see /a/b/c/foo.log for details") == "see foo.log for details"
    assert strip_paths("no path here") == "no path here"
    # Extension-agnostic (decision D12 / spike V5): run-tier artefacts the old .script/.txt/.log
    # allow-list missed are collapsed too, so a random temp path can't leak through them.
    assert strip_paths("dump /tmp/gmat-run-q9/DifferentialCorrectorDC.data unreadable") == (
        "dump DifferentialCorrectorDC.data unreadable"
    )
    assert strip_paths("/run/ephem/EphemerisFile1.oem") == "EphemerisFile1.oem"
    # Per-segment (no spaces): two paths on one line collapse independently, without the greedy
    # match eating the message text between them.
    assert strip_paths("both /opt/g/a.script and /var/log/run.log here") == (
        "both a.script and run.log here"
    )


# --------------------------------------------------------------------------- verdict parsing

_GOOD = '{"tier":"load","ok":true,"converged":null,"one_line":"","raw_log":""}'


def test_verdict_parses_a_clean_json_line() -> None:
    assert _verdict_from_stdout(_GOOD) == {
        "tier": "load",
        "ok": True,
        "converged": None,
        "one_line": "",
        "raw_log": "",
    }


def test_verdict_scans_from_the_tail_past_chatter() -> None:
    noisy = f"UserWarning: solver log parse fell back\nbanner line\n{_GOOD}\n"
    assert _verdict_from_stdout(noisy) is not None


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json at all",
        '{"tier":"load"}',
        '{"a":1}\ntrailing garbage',
        "[1, 2, 3]",
        "{not valid json",  # starts with { but fails to parse -> the JSONDecodeError skip
    ],
)
def test_verdict_rejects_unparseable_or_incomplete(stdout: str) -> None:
    assert _verdict_from_stdout(stdout) is None


def test_report_from_verdict_coerces_types() -> None:
    report = _report_from_verdict(
        {
            "tier": "run",
            "ok": False,
            "converged": {"DC": False},
            "one_line": "solver(s) DC did not converge",
            "raw_log": "log",
        }
    )
    assert report == DryRunReport(
        tier="run",
        ok=False,
        converged={"DC": False},
        one_line="solver(s) DC did not converge",
        raw_log="log",
    )


# --------------------------------------------------------------------------- the [gmat] guard


def test_require_gmat_extra_raises_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(GmatExtraNotInstalled, match=r"\[gmat\] extra"):
        require_gmat_extra()


def test_require_gmat_extra_passes_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    require_gmat_extra()  # does not raise


def test_dry_run_raises_a_clear_error_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(GmatExtraNotInstalled):
        dry_run("Create Spacecraft Sat;")


# --------------------------------------------------------------------------- orchestration (mocked)


def _completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def _bypass_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the [gmat]-extra check so the orchestration runs GMAT-free."""
    monkeypatch.setattr(dryrun_mod, "require_gmat_extra", lambda: None)


@pytest.mark.usefixtures("_bypass_guard")
def test_dry_run_builds_the_report_from_the_worker_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"tier":"run","ok":false,"converged":{"DC":false},'
        '"one_line":"solver(s) DC did not converge","raw_log":"raw"}'
    )
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured["timeout"] = kwargs.get("timeout")
        return _completed(stdout=payload)

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = dry_run("Create Spacecraft Sat;", timeout=42)

    assert report == DryRunReport(
        tier="run",
        ok=False,
        converged={"DC": False},
        one_line="solver(s) DC did not converge",
        raw_log="raw",
    )
    assert captured["timeout"] == 42
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[1:3] == ["-m", "gmat_copilot._dryrun_worker"]
    assert "--script" in argv


@pytest.mark.usefixtures("_bypass_guard")
def test_dry_run_forwards_explicit_gmat_root(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        return _completed(stdout=_GOOD)

    monkeypatch.setattr(subprocess, "run", fake_run)
    dry_run("x", gmat_root="/opt/gmat")
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "--gmat-root" in argv
    assert "/opt/gmat" in argv


@pytest.mark.usefixtures("_bypass_guard")
def test_dry_run_falls_back_to_gmat_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAT_ROOT", "/env/gmat")
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        return _completed(stdout=_GOOD)

    monkeypatch.setattr(subprocess, "run", fake_run)
    dry_run("x")
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "/env/gmat" in argv


@pytest.mark.usefixtures("_bypass_guard")
def test_dry_run_degrades_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=argv, timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = dry_run("x", timeout=5)
    assert report.tier == "timeout"
    assert report.ok is False
    assert report.converged is None
    assert "5s" in report.one_line


@pytest.mark.usefixtures("_bypass_guard")
def test_dry_run_degrades_on_crash_and_sanitises_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(
            stdout="not json", stderr="Traceback: boom at /tmp/x/draft.script", returncode=1
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = dry_run("x")
    assert report.tier == "crash"
    assert report.ok is False
    assert "no verdict" in report.one_line
    assert "draft.script" in report.raw_log
    assert "/tmp" not in report.raw_log  # the local path was sanitised away


@pytest.mark.usefixtures("_bypass_guard")
def test_dry_run_crash_falls_back_to_stdout_when_stderr_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No JSON verdict and an empty stderr: the raw_log is distilled from stdout instead.
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(stdout="garbage at /tmp/y/draft.script with no verdict", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = dry_run("x")
    assert report.tier == "crash"
    assert "draft.script" in report.raw_log
    assert "/tmp" not in report.raw_log
