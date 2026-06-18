"""V6 spike proof: the VS Code surface -- engine integration, apply-to-file, inline diagnostics.

Demonstrates the recommended integration path end to end, headless and credential-free:

    VS Code extension  <--stdio JSON-RPC-->  gmat-copilot worker  -->  gmat_copilot.draft()/validate()

The worker speaks line-delimited JSON-RPC over stdin/stdout and exposes *generation commands only*
(`copilot/draft`, `copilot/validate`). The `.script` language features -- syntax highlighting,
lint-on-type, hover, go-to-definition, formatting -- stay with gmat-script's existing
extension / language server; gmat-copilot does not reimplement them. That division of labour is the
core finding the prototype exists to make concrete.

What this proof exercises:
  1. a real stdio boundary -- the client spawns the worker as a subprocess and talks JSON-RPC to it,
     exactly as the VS Code `LanguageClient`/child-process would;
  2. deterministic generation against a *recorded provider* (committed .script fixtures, replayed by
     intent) -- no credential, no network, no GMAT install;
  3. the engine's lint diagnostics mapped into the VS Code `Diagnostic` shape (1-indexed gmat-script
     positions -> 0-indexed VS Code ranges) for the Problems panel / inline squiggles;
  4. the explicit, reviewable apply-to-current-file edit -- a diff the user accepts -- never a silent
     auto-apply (a charter non-goal);
  5. the long-running-op channel (`$/progress` notifications + a `$/cancel` request) the v0.2 repair
     loop and dry-run will use.

Run:
    python v6_vscode_surface_proof.py            # the client drives the worker (the demo)
    python v6_vscode_surface_proof.py --worker   # internal: the stdio worker, spawned by the client

stdlib + gmat_copilot only. Excluded from ruff/mypy/pytest per the spike convention (it lives under
docs/ and is a reference artefact, not project source).
"""

from __future__ import annotations

import difflib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from gmat_copilot import (
    DraftRejected,
    LintReport,
    RetrievalTrace,
    Severity,
    draft,
)
from gmat_copilot.providers import Completion
from gmat_copilot.validate import validate

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "v6_vscode_fixtures.json"

# The recorded-fixture "model" name. Selection stays explicit (no default model, D4); the shipping
# extension surfaces a real provider:model quick-pick -- here the recorded provider stands in for it.
RECORDED_MODEL = "recorded:fixture"

# VS Code DiagnosticSeverity: Error=0, Warning=1, Information=2, Hint=3. gmat-script emits the first
# three; anything unmapped degrades to a Hint rather than crashing the surface.
_VSCODE_SEVERITY: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


# --------------------------------------------------------------------------------------------------
# recorded provider + empty retriever -- the deterministic, GMAT-free generation seam
# --------------------------------------------------------------------------------------------------
class RecordedProvider:
    """Replays one committed completion regardless of prompt -- deterministic, no credential.

    Production keys a recorded bundle by ``(provider, model, prompt)`` (decision D7); the spike keys
    by intent (one fixture per intent) so the proof is robust against system-prompt edits. Either
    way the property the surface relies on is the same: identical input -> identical draft.
    """

    name = "recorded"

    def __init__(self, completion_text: str, usage: dict[str, int]):
        self._text = completion_text
        self._usage = usage

    def reachable(self) -> bool:
        return True

    def complete(
        self, prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 1024
    ) -> Completion:
        return Completion(text=self._text, provider="recorded", model=model, usage=self._usage)


class _EmptyRetriever:
    """A no-grounding retriever so the proof never loads the FAISS index (the recorded draft is
    fixed regardless of grounding). The real extension uses the shipped corpus retriever."""

    def retrieve(self, request: str) -> RetrievalTrace:
        return RetrievalTrace(chunks=())


def _load_fixture(intent: str) -> tuple[str, dict[str, int]]:
    """Resolve an intent to its recorded completion text (the .script wrapped in a ```script fence,
    matching the generation output contract) and the recorded usage."""
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    entry = fixtures.get(intent)
    if entry is None:
        raise KeyError(f"no recorded fixture for intent {intent!r}")
    script = (HERE / entry["script_file"]).read_text(encoding="utf-8")
    return f"```script\n{script}```", entry.get("usage", {})


# --------------------------------------------------------------------------------------------------
# diagnostic + edit mapping -- engine result -> VS Code shapes
# --------------------------------------------------------------------------------------------------
def _line_end_char(text: str, line_1indexed: int) -> int:
    """The 0-indexed character at the end of a source line, so a start-only diagnostic still gets a
    visible squiggle. gmat_copilot's LintDiagnostic keeps only the start position; the shipping
    worker can widen this using gmat-script's full start/end span (a small #46 enrichment)."""
    lines = text.splitlines()
    idx = line_1indexed - 1
    return len(lines[idx]) if 0 <= idx < len(lines) else 0


def to_vscode_diagnostics(report: LintReport, source_text: str) -> list[dict[str, Any]]:
    """Map a LintReport into the VS Code Diagnostic JSON the Problems panel consumes.

    gmat-script positions are 1-indexed; VS Code ranges are 0-indexed. `source` and `code` let the
    user filter gmat-copilot findings and click through to the rule.
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


def apply_to_file_edit(new_script: str) -> dict[str, Any]:
    """The apply-to-current-file edit descriptor: a full-document replace the editor applies only
    after the user accepts the preview. Explicit and reviewable -- never auto-applied (charter)."""
    return {"kind": "replaceFullDocument", "newText": new_script}


def preview_diff(current_text: str, new_script: str) -> str:
    """The unified diff the extension shows for review before applying anything."""
    return "".join(
        difflib.unified_diff(
            current_text.splitlines(keepends=True),
            new_script.splitlines(keepends=True),
            fromfile="active editor (before)",
            tofile="gmat-copilot draft (after)",
        )
    )


# --------------------------------------------------------------------------------------------------
# the worker -- stdio JSON-RPC, generation commands only
# --------------------------------------------------------------------------------------------------
def _write(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _progress(req_id: int, phase: str) -> None:
    """A `$/progress` notification (no id-as-response) for a long-running step -- the channel the
    v0.2 repair loop and gmat-run dry-run report through (per-attempt / per-tier)."""
    _write({"method": "$/progress", "params": {"id": req_id, "phase": phase}})


def _handle_draft(req_id: int, params: dict[str, Any]) -> dict[str, Any]:
    intent = params["intent"]
    strict = params.get("strict", True)
    completion_text, usage = _load_fixture(intent)
    provider = RecordedProvider(completion_text, usage)
    _progress(req_id, "generating")
    # The repair loop (repair>0) would emit a `$/progress` per attempt here and check a cancel flag
    # between attempts; the static path is single-pass.
    try:
        result = draft(
            intent,
            model=RECORDED_MODEL,
            provider=provider,
            retriever=_EmptyRetriever(),
            strict=strict,
        )
        script, lint, rejected = result.script, result.lint, False
    except DraftRejected as exc:
        # Strict rejected the draft (a blocking lint diagnostic). The extension still needs the
        # best-effort text and the diagnostics to show why -- they live on the raised result.
        script, lint, rejected = exc.result.script, exc.result.lint, True
    _progress(req_id, "linting")
    return {
        "script": script,
        "diagnostics": to_vscode_diagnostics(lint, script),
        "rejected": rejected,
        "provider": "recorded",
        "model": RECORDED_MODEL,
        # dry_run is the v0.2 dynamic tier (the [gmat] extra); the static spike leaves it null.
        "dryRun": None,
    }


def _handle_validate(params: dict[str, Any]) -> dict[str, Any]:
    text = params["documentText"]
    report = validate(text)
    return {"diagnostics": to_vscode_diagnostics(report, text)}


def run_worker() -> int:
    """Read line-delimited JSON-RPC requests from stdin; write one JSON response per request.

    Line-delimited JSON keeps the proof minimal; the shipping worker would use LSP Content-Length
    framing (reusing vscode-languageclient's transport) but the request/response contract is this.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})
        try:
            if method == "copilot/draft":
                _write({"id": req_id, "result": _handle_draft(req_id, params)})
            elif method == "copilot/validate":
                _write({"id": req_id, "result": _handle_validate(params)})
            elif method == "$/cancel":
                # The repair loop / dry-run check this between attempts; nothing to cancel here.
                _write({"id": req_id, "result": {"cancelled": True}})
            elif method == "shutdown":
                _write({"id": req_id, "result": {"ok": True}})
                return 0
            else:
                _write({"id": req_id, "error": {"message": f"unknown method {method!r}"}})
        except Exception as exc:  # a worker never dies on one bad request -- it reports and continues
            _write({"id": req_id, "error": {"message": f"{type(exc).__name__}: {exc}"}})
    return 0


# --------------------------------------------------------------------------------------------------
# the client -- a simulated VS Code extension driving the worker
# --------------------------------------------------------------------------------------------------
class WorkerClient:
    """Spawns the worker subprocess and exchanges JSON-RPC over its stdio, routing `$/progress`
    notifications away from the matching response -- exactly the extension's client loop."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        req_id = self._id
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(json.dumps({"id": req_id, "method": method, "params": params}) + "\n")
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("worker exited before responding")
            msg = json.loads(line)
            if msg.get("method") == "$/progress":
                p = msg["params"]
                print(f"    .. progress: {p['phase']}")
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"]["message"])
                return msg["result"]

    def close(self) -> None:
        try:
            self.request("shutdown", {})
        finally:
            self._proc.wait(timeout=10)


def _print_diagnostics(diags: list[dict[str, Any]]) -> None:
    if not diags:
        print("    (clean -- no diagnostics)")
        return
    names = {0: "error", 1: "warning", 2: "info", 3: "hint"}
    for d in diags:
        r = d["range"]["start"]
        print(
            f"    [{names[d['severity']]}] {r['line']}:{r['character']} "
            f"{d['code']}: {d['message']}  (source={d['source']})"
        )


def run_client() -> int:
    client = WorkerClient()
    ok = True
    try:
        # ---- 1. apply-to-current-file happy path: NL intent -> clean draft -> reviewable diff -----
        print("=== copilot/draft: clean draft -> apply-to-current-file ===")
        intent = "circular LEO at 500 km, propagate one day, report altitude"
        # The active editor holds a stale stub the user is replacing.
        current = "% TODO: a circular LEO mission\nCreate Spacecraft Sat;\n"
        print(f'  intent: "{intent}"')
        res = client.request("copilot/draft", {"intent": intent, "strict": True})
        print(f"  provider:model = {res['provider']}:{res['model']}   rejected={res['rejected']}")
        print("  diagnostics:")
        _print_diagnostics(res["diagnostics"])
        edit = apply_to_file_edit(res["script"])
        print(f"  apply edit kind: {edit['kind']} ({len(edit['newText'])} chars)")
        print("  --- preview diff the user accepts before anything is written ---")
        for dl in preview_diff(current, res["script"]).splitlines():
            print(f"    {dl}")
        ok &= res["rejected"] is False and res["diagnostics"] == []

        # ---- 2. strict rejection: a hallucinated field -> diagnostics, no apply -------------------
        print("\n=== copilot/draft: strict rejects a hallucinated field ===")
        bad_intent = "LEO at 7000 km SMA with an 850 kg dry mass, propagate 10 minutes"
        print(f'  intent: "{bad_intent}"')
        res_bad = client.request("copilot/draft", {"intent": bad_intent, "strict": True})
        print(f"  rejected={res_bad['rejected']}  (strict gate; nothing applied to the editor)")
        print("  diagnostics surfaced in the Problems panel:")
        _print_diagnostics(res_bad["diagnostics"])
        ok &= res_bad["rejected"] is True and len(res_bad["diagnostics"]) == 1
        ok &= res_bad["diagnostics"][0]["code"] == "unknown-field"

        # ---- 3. copilot/validate: lint an existing buffer on demand (a command, not lint-on-type) -
        print("\n=== copilot/validate: lint the active .script on demand ===")
        print("  (lint-on-type stays with gmat-script's LSP; this is the explicit re-lint command)")
        res_val = client.request("copilot/validate", {"documentText": res_bad["script"]})
        _print_diagnostics(res_val["diagnostics"])
        ok &= len(res_val["diagnostics"]) == 1

        # ---- 4. determinism: the recorded surface is byte-stable across calls ---------------------
        print("\n=== determinism: identical intent -> identical draft + diagnostics ===")
        again = client.request("copilot/draft", {"intent": intent, "strict": True})
        same = again["script"] == res["script"] and again["diagnostics"] == res["diagnostics"]
        print(f"  byte-identical re-draft: {same}")
        ok &= same
    finally:
        client.close()

    print(f"\nRESULT: V6 surface prototype end-to-end = {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker":
        return run_worker()
    return run_client()


if __name__ == "__main__":
    raise SystemExit(main())
