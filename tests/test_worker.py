"""The stdio JSON-RPC command worker (decision D15): framing, dispatch, mapping, progress, cancel.

The worker is exercised in-process: ``serve`` runs on a thread over two ``BytesIO`` streams, so the
read loop, the single-worker executor, cancellation, and the framed responses are all covered
without spawning a subprocess (and without a real provider or GMAT install — ``draft`` /
``reachable_providers`` are stubbed at the worker module boundary). The pure framing and diagnostic
mappers are tested directly.
"""

from __future__ import annotations

import io
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from gmat_script import Severity

from gmat_copilot import CopilotResult, DraftCancelled, DraftRejected, draft
from gmat_copilot import worker as worker_mod
from gmat_copilot.providers import ProviderError
from gmat_copilot.result import DryRunReport, LintDiagnostic, LintReport, RetrievalTrace
from gmat_copilot.validate import validate
from gmat_copilot.worker import (
    apply_to_file_edit,
    read_message,
    serve,
    to_vscode_diagnostics,
    write_message,
)


# --------------------------------------------------------------------------------------- framing
def _frame(message: dict[str, Any]) -> bytes:
    out = io.BytesIO()
    write_message(out, message)
    return out.getvalue()


def test_write_then_read_round_trips() -> None:
    message = {"jsonrpc": "2.0", "id": 1, "method": "copilot/draft", "params": {"intent": "x"}}
    stream = io.BytesIO(_frame(message))
    assert read_message(stream) == message
    assert read_message(stream) is None  # EOF


def test_read_message_handles_multiple_and_crlf_headers() -> None:
    stream = io.BytesIO(_frame({"id": 1}) + _frame({"id": 2}))
    assert read_message(stream) == {"id": 1}
    assert read_message(stream) == {"id": 2}
    assert read_message(stream) is None


def test_read_message_none_on_missing_length() -> None:
    assert read_message(io.BytesIO(b"\r\n")) is None  # blank header block, no Content-Length


def test_read_message_none_on_non_object_body() -> None:
    assert read_message(io.BytesIO(_frame([1, 2, 3]))) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------- engine -> VS Code mapping
def test_diagnostics_are_zero_indexed_and_attributed(hallucinated_field_script: str) -> None:
    report = validate(hallucinated_field_script)
    assert not report.clean
    diags = to_vscode_diagnostics(report, hallucinated_field_script)
    assert len(diags) == len(report.diagnostics)
    src = report.diagnostics[0]
    mapped = diags[0]
    assert mapped["range"]["start"]["line"] == src.line - 1
    assert mapped["range"]["start"]["character"] == src.column - 1
    # The squiggle widens to end of line (LintDiagnostic keeps only the start position).
    assert mapped["range"]["end"]["character"] >= mapped["range"]["start"]["character"]
    assert mapped["source"] == "gmat-copilot"
    assert mapped["code"] == src.rule
    assert mapped["severity"] == 1  # a WARNING


@pytest.mark.parametrize(
    ("line", "column", "expected"),
    [
        ("Create Spacecraft Sat;", 1, 0),  # ASCII: byte column 1 -> UTF-16 unit 0
        ("Create Spacecraft Sat;", 8, 7),  # ASCII: byte column n -> unit n - 1
        ("% é tag", 6, 4),  # 'é' is 2 UTF-8 bytes / 1 UTF-16 unit, so byte 6 -> unit 4
        ("% \U0001f6f0 sat", 8, 5),  # 🛰 is 4 bytes / 2 units (a surrogate pair)
        ("", 1, 0),  # an empty line clamps to the start
    ],
)
def test_byte_column_maps_to_utf16_unit(line: str, column: int, expected: int) -> None:
    assert worker_mod._byte_col_to_utf16(line, column) == expected


def test_diagnostics_use_utf16_units_not_byte_offsets() -> None:
    # gmat-script reports a 1-indexed UTF-8 *byte* column; VS Code ranges are 0-indexed UTF-16.
    # A multi-byte character before the column means a bare `column - 1` would land the squiggle too
    # far right, and a code-point line length would overstate the end. Both must convert.
    source = "% é tag\n"  # the line "% é tag": 7 code points, 8 UTF-8 bytes, 7 UTF-16 units
    report = LintReport(
        diagnostics=(
            LintDiagnostic(
                rule="unknown-field", severity=Severity.WARNING, message="m", line=1, column=6
            ),
        )
    )
    mapped = to_vscode_diagnostics(report, source)[0]
    assert mapped["range"]["start"]["character"] == 4  # 't' at UTF-16 unit 4, not byte offset 5
    assert mapped["range"]["end"]["character"] == 7  # end of "% é tag" in units (7), not bytes (8)


def test_diagnostic_column_past_line_end_clamps_to_a_valid_range() -> None:
    # A column beyond the line (or a line beyond the source) must still yield start <= end, so VS
    # Code never gets an inverted range.
    report = LintReport(
        diagnostics=(
            LintDiagnostic(rule="x", severity=Severity.ERROR, message="m", line=1, column=999),
            LintDiagnostic(rule="y", severity=Severity.ERROR, message="m", line=9, column=1),
        )
    )
    mapped = to_vscode_diagnostics(report, "short\n")
    assert mapped[0]["range"]["start"]["character"] == mapped[0]["range"]["end"]["character"] == 5
    assert mapped[1]["range"] == {
        "start": {"line": 8, "character": 0},
        "end": {"line": 8, "character": 0},
    }


def test_apply_to_file_edit_is_a_full_document_replace() -> None:
    edit = apply_to_file_edit("Create Spacecraft Sat;\n")
    assert edit == {"kind": "replaceFullDocument", "newText": "Create Spacecraft Sat;\n"}


# ------------------------------------------------------------------------- the serve() harness
def _drive(requests: list[dict[str, Any]], timeout: float = 10.0) -> list[dict[str, Any]]:
    """Feed *requests* through ``serve`` over in-process streams; return the framed messages out."""
    reader = io.BytesIO(b"".join(_frame(r) for r in requests))
    writer = io.BytesIO()
    thread = threading.Thread(target=serve, args=(reader, writer))
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "serve did not terminate"
    writer.seek(0)
    out: list[dict[str, Any]] = []
    while (message := read_message(writer)) is not None:
        out.append(message)
    return out


def _clean_result(script: str) -> CopilotResult:
    return CopilotResult(
        script=script,
        lint=validate(script),
        retrieval=RetrievalTrace(),
        provider="stub",
        model="stub:model",
    )


def test_draft_happy_path_returns_script_edit_and_progress(
    monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    def fake_draft(request: str, **kwargs: Any) -> CopilotResult:
        return _clean_result(valid_script)

    monkeypatch.setattr(worker_mod, "draft", fake_draft)
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 7, "method": "copilot/draft", "params": {"intent": "a LEO"}},
            {"jsonrpc": "2.0", "method": "exit"},
        ]
    )
    progress = [m for m in out if m.get("method") == "copilot/progress"]
    responses = [m for m in out if m.get("id") == 7]
    assert progress and progress[0]["params"] == {"id": 7, "phase": "generating"}
    assert len(responses) == 1
    result = responses[0]["result"]
    assert result["rejected"] is False
    assert result["script"] == valid_script
    assert result["edit"] == {"kind": "replaceFullDocument", "newText": valid_script}
    assert result["diagnostics"] == []
    assert result["dryRun"] is None


def test_draft_strict_rejection_surfaces_diagnostics(
    monkeypatch: pytest.MonkeyPatch, hallucinated_field_script: str
) -> None:
    rejected = _clean_result(hallucinated_field_script)  # its lint carries a blocking WARNING

    def fake_draft(request: str, **kwargs: Any) -> CopilotResult:
        raise DraftRejected(rejected)

    monkeypatch.setattr(worker_mod, "draft", fake_draft)
    out = _drive(
        [{"jsonrpc": "2.0", "id": 1, "method": "copilot/draft", "params": {"intent": "x"}}]
    )
    result = next(m["result"] for m in out if m.get("id") == 1)
    assert result["rejected"] is True
    assert result["diagnostics"], "the rejecting diagnostics must reach the editor"


def test_draft_includes_failed_dryrun_as_a_diagnostic(
    monkeypatch: pytest.MonkeyPatch, valid_script: str
) -> None:
    result = CopilotResult(
        script=valid_script,
        lint=validate(valid_script),
        retrieval=RetrievalTrace(),
        provider="stub",
        model="stub:model",
        dry_run=DryRunReport(
            tier="load", ok=False, converged=None, one_line="bad epoch", raw_log=""
        ),
    )

    def fake_draft(request: str, **kwargs: Any) -> CopilotResult:
        return result

    monkeypatch.setattr(worker_mod, "draft", fake_draft)
    out = _drive(
        [{"jsonrpc": "2.0", "id": 2, "method": "copilot/draft", "params": {"intent": "x"}}]
    )
    payload = next(m["result"] for m in out if m.get("id") == 2)
    assert payload["dryRun"] == {"tier": "load", "ok": False, "oneLine": "bad epoch"}
    dry_diags = [d for d in payload["diagnostics"] if d["code"] == "dry-run:load"]
    assert dry_diags and dry_diags[0]["message"] == "bad epoch"


def test_validate_command_lints_a_buffer(hallucinated_field_script: str) -> None:
    out = _drive(
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "copilot/validate",
                "params": {"documentText": hallucinated_field_script},
            }
        ]
    )
    diags = next(m["result"]["diagnostics"] for m in out if m.get("id") == 3)
    assert diags and diags[0]["source"] == "gmat-copilot"


def test_providers_command_lists_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_mod, "reachable_providers", lambda: ["github", "ollama"])
    out = _drive([{"jsonrpc": "2.0", "id": 4, "method": "copilot/providers", "params": {}}])
    assert next(m["result"] for m in out if m.get("id") == 4) == {"reachable": ["github", "ollama"]}


def test_provider_error_is_an_engine_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_draft(request: str, **kwargs: Any) -> CopilotResult:
        raise ProviderError("no model selected")

    monkeypatch.setattr(worker_mod, "draft", fake_draft)
    out = _drive(
        [{"jsonrpc": "2.0", "id": 5, "method": "copilot/draft", "params": {"intent": "x"}}]
    )
    error = next(m["error"] for m in out if m.get("id") == 5)
    assert error["code"] == worker_mod._ENGINE_ERROR
    assert "no model selected" in error["message"]


def test_unknown_method_is_method_not_found() -> None:
    out = _drive([{"jsonrpc": "2.0", "id": 6, "method": "copilot/nope", "params": {}}])
    error = next(m["error"] for m in out if m.get("id") == 6)
    assert error["code"] == worker_mod._METHOD_NOT_FOUND


def test_unknown_notification_is_ignored() -> None:
    # A notification (no id) the worker does not recognise must be silently dropped, then the next
    # request still answers — the read loop never wedges on chatter.
    out = _drive(
        [
            {"jsonrpc": "2.0", "method": "$/setTrace", "params": {"value": "off"}},
            {"jsonrpc": "2.0", "id": 11, "method": "shutdown"},
        ]
    )
    assert next(m["result"] for m in out if m.get("id") == 11) == {"ok": True}


def test_missing_param_is_a_clean_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A malformed request (no "intent") must surface as an error, never take the worker down.
    monkeypatch.setattr(worker_mod, "draft", lambda *a, **k: None)
    out = _drive([{"jsonrpc": "2.0", "id": 12, "method": "copilot/draft", "params": {}}])
    error = next(m["error"] for m in out if m.get("id") == 12)
    assert error["code"] == worker_mod._INTERNAL_ERROR


def test_shutdown_is_acknowledged() -> None:
    out = _drive([{"jsonrpc": "2.0", "id": 9, "method": "shutdown"}])
    assert next(m["result"] for m in out if m.get("id") == 9) == {"ok": True}


def test_shutdown_stops_the_serve_loop() -> None:
    # shutdown both acknowledges *and* stops the read loop, so the worker exits on its own (the
    # client need not also send `exit`). A request queued after shutdown is therefore never run.
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 20, "method": "shutdown"},
            {"jsonrpc": "2.0", "id": 21, "method": "copilot/providers", "params": {}},
        ]
    )
    ids = [m.get("id") for m in out]
    assert 20 in ids  # shutdown acknowledged
    assert 21 not in ids  # the loop stopped before the trailing request was read


def test_cancel_request_aborts_an_in_flight_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()

    def blocking_draft(request: str, *, cancel: Callable[[], bool] | None = None, **kw: Any) -> Any:
        started.set()
        assert cancel is not None
        deadline = time.monotonic() + 5.0
        while not cancel():
            if time.monotonic() > deadline:  # pragma: no cover - safety valve, cancel always wins
                raise AssertionError("cancel never arrived")
            time.sleep(0.005)
        raise DraftCancelled("cancelled")

    monkeypatch.setattr(worker_mod, "draft", blocking_draft)
    out = _drive(
        [
            {"jsonrpc": "2.0", "id": 8, "method": "copilot/draft", "params": {"intent": "x"}},
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 8}},
        ]
    )
    error = next(m["error"] for m in out if m.get("id") == 8)
    assert error["code"] == worker_mod._REQUEST_CANCELLED


def test_stray_cancels_are_harmless() -> None:
    # A cancel for an unknown id, and one with no id at all, must be no-ops — the worker keeps
    # serving and the following request still answers.
    out = _drive(
        [
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 999}},
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {}},
            {"jsonrpc": "2.0", "id": 13, "method": "shutdown"},
        ]
    )
    assert next(m["result"] for m in out if m.get("id") == 13) == {"ok": True}


def test_main_returns_on_empty_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Std:
        def __init__(self, data: bytes = b"") -> None:
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _Std())
    monkeypatch.setattr(sys, "stdout", _Std())
    assert worker_mod.main() == 0


# ---------------------------------------------------------------------- the draft() cancel hook
def test_draft_cancel_before_first_attempt(
    stub_retriever: Any, sequence_provider: Any, valid_script: str
) -> None:
    provider = sequence_provider([valid_script])
    with pytest.raises(DraftCancelled):
        draft(
            "x",
            model="m",
            provider=provider,
            retriever=stub_retriever,
            repair=2,
            cancel=lambda: True,
        )
    assert provider.prompts == []  # cancelled before the model was ever called


def test_draft_cancel_after_provider_in_single_pass(
    stub_retriever: Any, sequence_provider: Any, valid_script: str
) -> None:
    # Even a single pass (repair=0) is cancellable between generate and validate: a cancel observed
    # after the provider returns stops the draft before the potentially expensive dry-run runs.
    provider = sequence_provider([valid_script])
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # False before the attempt, True once the provider has returned

    with pytest.raises(DraftCancelled):
        draft("x", model="m", provider=provider, retriever=stub_retriever, repair=0, cancel=cancel)
    assert len(provider.prompts) == 1  # the model ran once, then the post-call cancel fired


def test_draft_cancel_between_repair_attempts(
    stub_retriever: Any, sequence_provider: Any, invalid_script: str
) -> None:
    provider = sequence_provider([invalid_script])  # never passes -> the loop would retry
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # allow attempt 0, cancel before attempt 1

    with pytest.raises(DraftCancelled):
        draft(
            "x",
            model="m",
            provider=provider,
            retriever=stub_retriever,
            repair=3,
            strict=True,
            cancel=cancel,
        )
    assert len(provider.prompts) == 1  # exactly one attempt ran before the cancel
