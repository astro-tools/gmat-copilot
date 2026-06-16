"""The ``gmat-copilot`` CLI plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_copilot.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "gmat-copilot" in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_validate_accepts_clean_script(tmp_path: Path, valid_script: str) -> None:
    script = tmp_path / "ok.script"
    script.write_text(valid_script, encoding="utf-8")
    assert main(["validate", str(script)]) == 0


def test_validate_rejects_broken_script(tmp_path: Path, invalid_script: str) -> None:
    script = tmp_path / "bad.script"
    script.write_text(invalid_script, encoding="utf-8")
    assert main(["validate", str(script)]) == 1


def test_draft_is_not_wired_yet(capsys: pytest.CaptureFixture[str]) -> None:
    # The generation pipeline is a stub; the CLI surfaces it as a clean error, not a traceback.
    assert main(["draft", "a 500 km LEO", "-m", "anthropic:claude-x"]) == 2
    assert "gmat-copilot:" in capsys.readouterr().err


def test_eval_live_is_a_noop_stub(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval", "--live"]) == 0


def test_eval_recorded_replays_bundle(
    eval_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["eval", "--recorded", str(eval_bundle), "-m", "openai/gpt-4.1-mini"]) == 0
    assert "pass-rate: 100%" in capsys.readouterr().out
