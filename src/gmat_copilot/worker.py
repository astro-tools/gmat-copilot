"""The stdio JSON-RPC command worker that drives the editor surface (decision D15).

The VS Code extension launches ``python -m gmat_copilot.worker`` (or the ``gmat-copilot-worker``
console script) in the user's Python environment and talks JSON-RPC 2.0 to it over stdio, framed
with the LSP ``Content-Length`` base protocol so the extension can reuse ``vscode-jsonrpc``'s stream
transport. The worker exposes **generation commands only** — it is *not* a language server: all
``.script`` language features (highlighting, lint-on-type, hover, formatting) stay with the
gmat-script extension. The division of labour is the V6 finding D15 records.

Three requests wrap the public Python API:

- ``copilot/draft`` — :func:`gmat_copilot.draft`: generate a script, lint it, and (when ``dryRun``
  is set) dry-run it; returns the script, the diagnostics mapped to the VS Code shape, a
  ``rejected`` flag, the resolved ``provider``/``model``, the dry-run verdict, and the apply edit.
- ``copilot/validate`` — :func:`gmat_copilot.validate.validate`: re-lint a buffer on demand.
- ``copilot/providers`` — :func:`gmat_copilot.providers.reachable_providers`: the providers
  reachable from configured credentials, for the no-default model quick-pick (decision D4).

Long-running steps report through ``copilot/progress`` notifications, and a ``$/cancelRequest`` for
an in-flight ``copilot/draft`` is honoured at the next repair-attempt boundary (the request runs on
a single-worker executor so the read loop stays free to receive the cancel). Credentials resolve in
this process's environment, exactly where the provider abstraction already discovers them — the
extension never handles a raw key. A missing credential / extra surfaces as a JSON-RPC error the
editor shows as a clear message, never a crash.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, BinaryIO

from gmat_script import Severity

from .dryrun import GmatExtraNotInstalled
from .generate import DraftCancelled, DraftRejected, draft
from .providers import ProviderError, reachable_providers
from .result import CopilotResult, DryRunReport, LintReport
from .validate import validate

__all__ = ["main", "serve"]

# JSON-RPC 2.0 / LSP error codes. RequestCancelled is the LSP code (decision D15): the client maps
# it back to a silent cancellation, while every other code surfaces as an editor error message.
_METHOD_NOT_FOUND = -32601
_INTERNAL_ERROR = -32603
_REQUEST_CANCELLED = -32800
_ENGINE_ERROR = -32001  # a provider/extra problem — expected, actionable, shown to the user

# VS Code DiagnosticSeverity: Error=0, Warning=1, Information=2, Hint=3. gmat-script emits the first
# three; anything unmapped degrades to a Hint rather than crashing the surface.
_VSCODE_SEVERITY: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}

_RequestId = int | str


# -------------------------------------------------------------------------- Content-Length framing
def read_message(reader: BinaryIO) -> dict[str, Any] | None:
    """Read one ``Content-Length``-framed JSON-RPC message, or ``None`` at end of stream.

    Parses the LSP base-protocol header block (``Name: value`` lines terminated by a blank line),
    then reads exactly ``Content-Length`` bytes of UTF-8 JSON. Returns ``None`` on EOF or a
    malformed / absent length, which ends the serve loop cleanly.
    """
    headers: dict[bytes, bytes] = {}
    while True:
        line = reader.readline()
        if not line:
            return None  # EOF
        stripped = line.strip()
        if not stripped:
            break  # the blank line that ends the header block
        name, sep, value = stripped.partition(b":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    length = int(headers.get(b"content-length", b"0"))
    if length <= 0:
        return None
    body = reader.read(length)
    parsed = json.loads(body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else None


def write_message(writer: BinaryIO, message: Mapping[str, Any]) -> None:
    """Write one ``Content-Length``-framed JSON-RPC message to *writer* and flush it."""
    body = json.dumps(message).encode("utf-8")
    writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    writer.write(body)
    writer.flush()


# ------------------------------------------------------------------- engine result -> VS Code shape
def _line_end_char(text: str, line_1indexed: int) -> int:
    """The 0-indexed end-of-line character, so a start-only diagnostic gets a visible squiggle.

    ``LintDiagnostic`` keeps only the start position; widening to the line end gives the Problems
    panel a non-empty range to underline.
    """
    lines = text.splitlines()
    idx = line_1indexed - 1
    return len(lines[idx]) if 0 <= idx < len(lines) else 0


def to_vscode_diagnostics(report: LintReport, source_text: str) -> list[dict[str, Any]]:
    """Map a :class:`LintReport` into the VS Code ``Diagnostic`` JSON the Problems panel consumes.

    gmat-script positions are 1-indexed; VS Code ranges are 0-indexed. ``source`` and ``code`` let
    the user filter gmat-copilot findings and click through to the rule.
    """
    out: list[dict[str, Any]] = []
    for d in report.diagnostics:
        line0 = max(d.line - 1, 0)
        char0 = max(d.column - 1, 0)
        out.append(
            {
                "range": {
                    "start": {"line": line0, "character": char0},
                    "end": {"line": line0, "character": _line_end_char(source_text, d.line)},
                },
                "severity": _VSCODE_SEVERITY.get(d.severity, 3),
                "source": "gmat-copilot",
                "code": d.rule,
                "message": d.message,
            }
        )
    return out


def _dryrun_diagnostic(report: DryRunReport) -> dict[str, Any]:
    """A file-level VS Code ``Diagnostic`` for a failed dry-run (decision D12).

    A :class:`DryRunReport` carries no precise location, so the finding is attached at the top of
    the file as an error (a not-``ok`` dry-run blocks in strict mode, like a blocking lint finding).
    """
    return {
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
        "severity": _VSCODE_SEVERITY[Severity.ERROR],
        "source": "gmat-copilot",
        "code": f"dry-run:{report.tier}",
        "message": report.one_line or f"the dry-run failed at the {report.tier} tier",
    }


def _dryrun_payload(report: DryRunReport | None) -> dict[str, Any] | None:
    """The structured dry-run verdict, or ``None`` when the dynamic tier did not run."""
    if report is None:
        return None
    return {"tier": report.tier, "ok": report.ok, "oneLine": report.one_line}


def apply_to_file_edit(script: str) -> dict[str, Any]:
    """The apply-to-current-file edit descriptor: a full-document replace.

    The extension shows this as a reviewable diff and applies it only after the user accepts —
    explicit and reviewable, never auto-applied (a charter non-goal).
    """
    return {"kind": "replaceFullDocument", "newText": script}


def _draft_payload(result: CopilotResult, *, rejected: bool) -> dict[str, Any]:
    """Assemble the ``copilot/draft`` result: script, diagnostics, verdict, and the apply edit.

    Lint diagnostics and a failed dry-run both land in ``diagnostics`` (the Problems panel); the
    structured ``dryRun`` verdict rides alongside for a status line.
    """
    diagnostics = to_vscode_diagnostics(result.lint, result.script)
    if result.dry_run is not None and not result.dry_run.ok:
        diagnostics.append(_dryrun_diagnostic(result.dry_run))
    return {
        "script": result.script,
        "diagnostics": diagnostics,
        "rejected": rejected,
        "provider": result.provider,
        "model": result.model,
        "dryRun": _dryrun_payload(result.dry_run),
        "edit": apply_to_file_edit(result.script),
    }


# ----------------------------------------------------------------------------- the command handlers
# A handler takes the request params, a progress emitter, and a cancel predicate, and returns the
# JSON-RPC result. `draft` / `validate` / `reachable_providers` are module globals so tests can
# replace them without a real provider or GMAT install.
_Handler = Callable[[Mapping[str, Any], Callable[[str], None], Callable[[], bool]], dict[str, Any]]


def _handle_draft(
    params: Mapping[str, Any], progress: Callable[[str], None], is_cancelled: Callable[[], bool]
) -> dict[str, Any]:
    """Generate a draft for an intent; return the apply-ready result (decisions D4/D5/D12/D13)."""
    intent = params["intent"]
    progress("generating")
    try:
        result = draft(
            intent,
            model=params.get("model"),
            strict=bool(params.get("strict", True)),
            repair=int(params.get("repair", 0)),
            dry_run=bool(params.get("dryRun", False)),
            cancel=is_cancelled,
        )
        rejected = False
    except DraftRejected as exc:
        # Strict rejected the draft. The editor still needs the best-effort text and the diagnostics
        # to show why it was rejected — they live on the attached result.
        result, rejected = exc.result, True
    return _draft_payload(result, rejected=rejected)


def _handle_validate(
    params: Mapping[str, Any], progress: Callable[[str], None], is_cancelled: Callable[[], bool]
) -> dict[str, Any]:
    """Re-lint a buffer on demand (the explicit command; lint-on-type stays with gmat-script)."""
    text = params["documentText"]
    return {"diagnostics": to_vscode_diagnostics(validate(text), text)}


def _handle_providers(
    params: Mapping[str, Any], progress: Callable[[str], None], is_cancelled: Callable[[], bool]
) -> dict[str, Any]:
    """List the providers reachable from configured credentials, for the model quick-pick (D4)."""
    return {"reachable": reachable_providers()}


_HANDLERS: dict[str, _Handler] = {
    "copilot/draft": _handle_draft,
    "copilot/validate": _handle_validate,
    "copilot/providers": _handle_providers,
}


# --------------------------------------------------------------------------------------- the worker
class _Worker:
    """Runs the JSON-RPC read loop, dispatching requests to a single-worker executor.

    The read loop never blocks on a handler, so a ``$/cancelRequest`` that arrives while a draft is
    generating is processed immediately and sets that request's cancel event. Writes are serialised
    behind a lock because both the read loop (the ``shutdown`` reply) and the executor (results and
    progress notifications) emit framed messages.
    """

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self._reader = reader
        self._writer = writer
        self._write_lock = threading.Lock()
        self._cancels: dict[_RequestId, threading.Event] = {}
        self._cancels_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._running = True

    def run(self) -> int:
        try:
            while self._running:
                message = read_message(self._reader)
                if message is None:
                    break
                self._on_message(message)
        finally:
            self._executor.shutdown(wait=True)
        return 0

    def _on_message(self, message: Mapping[str, Any]) -> None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        if method == "$/cancelRequest":
            self._cancel(params.get("id"))
            return
        if method == "exit":
            self._running = False
            return
        if msg_id is None:
            return  # an unrecognised notification — nothing to answer
        if method == "shutdown":
            self._respond(msg_id, {"ok": True})
            return
        event = threading.Event()
        with self._cancels_lock:
            self._cancels[msg_id] = event
        self._executor.submit(self._dispatch, msg_id, str(method), params, event)

    def _cancel(self, req_id: _RequestId | None) -> None:
        if req_id is None:
            return
        with self._cancels_lock:
            event = self._cancels.get(req_id)
        if event is not None:
            event.set()

    def _dispatch(
        self, msg_id: _RequestId, method: str, params: Mapping[str, Any], event: threading.Event
    ) -> None:
        try:
            handler = _HANDLERS.get(method)
            if handler is None:
                self._error(msg_id, _METHOD_NOT_FOUND, f"unknown method {method!r}")
                return
            result = handler(params, lambda phase: self._progress(msg_id, phase), event.is_set)
            self._respond(msg_id, result)
        except DraftCancelled as exc:
            self._error(msg_id, _REQUEST_CANCELLED, str(exc))
        except (ProviderError, GmatExtraNotInstalled) as exc:
            self._error(msg_id, _ENGINE_ERROR, str(exc))
        except (
            Exception
        ) as exc:  # a worker never dies on one bad request — it reports and continues
            self._error(msg_id, _INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        finally:
            with self._cancels_lock:
                self._cancels.pop(msg_id, None)

    def _respond(self, msg_id: _RequestId, result: Mapping[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error(self, msg_id: _RequestId, code: int, message: str) -> None:
        self._send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

    def _progress(self, msg_id: _RequestId, phase: str) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "method": "copilot/progress",
                "params": {"id": msg_id, "phase": phase},
            }
        )

    def _send(self, message: Mapping[str, Any]) -> None:
        with self._write_lock:
            write_message(self._writer, message)


def serve(reader: BinaryIO, writer: BinaryIO) -> int:
    """Serve the JSON-RPC command protocol over *reader* / *writer* until end of stream."""
    return _Worker(reader, writer).run()


def main(argv: list[str] | None = None) -> int:
    """Entry point: serve the protocol over stdio (``python -m gmat_copilot.worker``)."""
    out = sys.stdout.buffer
    # Protect the protocol channel: a stray ``print`` or a provider-SDK banner on stdout would
    # corrupt the framed stream. Send text-stdout to stderr; the framed bytes go to the real buffer.
    sys.stdout = sys.stderr
    return serve(sys.stdin.buffer, out)


if __name__ == "__main__":
    raise SystemExit(main())
