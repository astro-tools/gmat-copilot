"""The ``gmat-copilot`` CLI plumbing."""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_copilot.cli import main
from gmat_copilot.result import RetrievalTrace


class _OfflineRetriever:
    """A retriever stand-in that returns an empty trace without loading the embedding model.

    ``draft()`` retrieves before it calls the provider, so a CLI test that wants to reach the
    provider error path would otherwise download the real embedder. This keeps the test hermetic.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def retrieve(self, query: str, *, top_k: int | None = None) -> RetrievalTrace:
        return RetrievalTrace()


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


def test_draft_errors_cleanly_without_credentials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stub the retriever so the test needs no network (no embedder download); with no credential the
    # missing key must surface as a clean exit-2 error, not a traceback.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("gmat_copilot.generate.Retriever", _OfflineRetriever)
    assert main(["draft", "a 500 km LEO", "-m", "anthropic:claude-x"]) == 2
    assert "gmat-copilot:" in capsys.readouterr().err


def test_eval_live_is_a_noop_stub(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval", "--live"]) == 0


def test_eval_recorded_replays_bundle(
    eval_bundle: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["eval", "--recorded", str(eval_bundle), "-m", "openai/gpt-4.1-mini"]) == 0
    assert "pass-rate: 100%" in capsys.readouterr().out
