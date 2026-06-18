// GMAT Copilot — draft GMAT mission scripts from natural language, review the diff, and apply to the
// active file, with lint (and the optional gmat-run dry-run) diagnostics surfaced inline.
//
// The extension is a thin client over the gmat-copilot engine worker (see ./worker and decision
// D15). It contributes generation commands only; the `.script` language itself (highlighting,
// lint-on-type, hover, formatting) is the gmat-script extension's job — install it alongside this
// one for the full editing experience.

import * as path from "path";
import * as vscode from "vscode";
import {
  CopilotWorker,
  DraftParams,
  DraftResult,
  ProgressNote,
  RawDiagnostic,
  WorkerCommand,
} from "./worker";

let worker: CopilotWorker | undefined;
let diagnostics: vscode.DiagnosticCollection;
let output: vscode.OutputChannel;

/** The progress reporter of an in-flight draft, so worker progress notifications can update it. */
let activeProgress: vscode.Progress<{ message?: string }> | undefined;

/** A read-only scheme backing the apply-to-file diff preview. */
const DRAFT_SCHEME = "gmat-copilot-draft";
const draftContents = new Map<string, string>();
let draftCounter = 0;

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("GMAT Copilot");
  diagnostics = vscode.languages.createDiagnosticCollection("gmat-copilot");
  worker = new CopilotWorker(resolveWorkerCommand, (m) => output.appendLine(m), forwardProgress);

  const draftProvider: vscode.TextDocumentContentProvider = {
    provideTextDocumentContent: (uri) => draftContents.get(uri.toString()) ?? "",
  };

  context.subscriptions.push(
    output,
    diagnostics,
    { dispose: () => worker?.dispose() },
    vscode.workspace.registerTextDocumentContentProvider(DRAFT_SCHEME, draftProvider),
    vscode.commands.registerCommand("gmatCopilot.draft", () => draftCommand("input")),
    vscode.commands.registerCommand("gmatCopilot.draftFromSelection", () =>
      draftCommand("selection"),
    ),
    vscode.commands.registerCommand("gmatCopilot.revalidate", revalidateCommand),
    vscode.commands.registerCommand("gmatCopilot.selectModel", () => pickModel()),
  );
}

export function deactivate(): void {
  worker?.dispose();
  worker = undefined;
}

/** Resolve the worker launch command: `server.pythonPath` wins over `server.path` (decision D15). */
function resolveWorkerCommand(): WorkerCommand {
  const config = vscode.workspace.getConfiguration("gmatCopilot");
  const extraArgs = config.get<string[]>("server.args", []);
  const pythonPath = (config.get<string>("server.pythonPath", "") ?? "").trim();
  if (pythonPath) {
    return { command: pythonPath, args: ["-m", "gmat_copilot.worker", ...extraArgs] };
  }
  const command = config.get<string>("server.path", "gmat-copilot-worker") || "gmat-copilot-worker";
  return { command, args: extraArgs };
}

function forwardProgress(note: ProgressNote): void {
  activeProgress?.report({ message: phaseLabel(note.phase) });
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case "generating":
      return "Generating the mission script…";
    case "linting":
      return "Validating…";
    default:
      return phase;
  }
}

// ---------------------------------------------------------------------------- the draft command
async function draftCommand(source: "input" | "selection"): Promise<void> {
  const activeWorker = worker;
  if (!activeWorker) {
    return;
  }
  const editor = vscode.window.activeTextEditor;
  const intent = await resolveIntent(source, editor);
  if (!intent) {
    return;
  }
  const model = await resolveModel();
  if (!model) {
    return;
  }
  const config = vscode.workspace.getConfiguration("gmatCopilot");
  const params: DraftParams = {
    intent,
    model,
    strict: config.get<boolean>("strict", true),
    repair: config.get<number>("repair", 0),
    dryRun: config.get<boolean>("dryRun", false),
  };

  let result: DraftResult;
  try {
    result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, cancellable: true, title: "GMAT Copilot" },
      async (progress, token) => {
        activeProgress = progress;
        progress.report({ message: "Generating the mission script…" });
        try {
          return await activeWorker.draft(params, token);
        } finally {
          activeProgress = undefined;
        }
      },
    );
  } catch (err) {
    if (!isCancellation(err)) {
      showWorkerError(err);
    }
    return;
  }

  applyDiagnostics(editor?.document, result.diagnostics);
  if (result.rejected) {
    vscode.window.showWarningMessage(
      "GMAT Copilot: the draft did not validate clean and was not applied. See the Problems panel — " +
        "switch to permissive mode or refine the prompt.",
    );
    return;
  }
  await reviewAndApply(editor, result);
}

async function resolveIntent(
  source: "input" | "selection",
  editor: vscode.TextEditor | undefined,
): Promise<string | undefined> {
  if (source === "selection") {
    if (!editor || editor.selection.isEmpty) {
      vscode.window.showWarningMessage(
        "GMAT Copilot: select the text to use as the prompt, then run this command.",
      );
      return undefined;
    }
    return editor.document.getText(editor.selection).trim() || undefined;
  }
  const input = await vscode.window.showInputBox({
    title: "GMAT Copilot: draft a mission",
    prompt: "Describe the mission in plain language",
    placeHolder: "e.g. circular LEO at 500 km, propagate one day, report altitude",
  });
  return input?.trim() || undefined;
}

// -------------------------------------------------------------------- apply-to-current-file UX
async function reviewAndApply(
  editor: vscode.TextEditor | undefined,
  result: DraftResult,
): Promise<void> {
  const script = result.script;
  if (!editor) {
    const doc = await vscode.workspace.openTextDocument({ language: "gmat", content: script });
    await vscode.window.showTextDocument(doc);
    vscode.window.showInformationMessage(
      "GMAT Copilot: no active editor to apply to — opened the draft in a new document for review.",
    );
    return;
  }

  const target = editor.document;
  const label = target.isUntitled ? "untitled" : path.basename(target.fileName);
  const draftUri = vscode.Uri.parse(`${DRAFT_SCHEME}:/${draftCounter++}/${label}`);
  draftContents.set(draftUri.toString(), script);
  try {
    await vscode.commands.executeCommand(
      "vscode.diff",
      target.uri,
      draftUri,
      `GMAT Copilot draft ↔ ${label}`,
      { preview: true },
    );
    const choice = await vscode.window.showInformationMessage(
      `Apply the gmat-copilot draft to ${label}?  (${result.provider}:${result.model})`,
      "Apply",
      "Discard",
    );
    if (choice !== "Apply") {
      return;
    }
    const edit = new vscode.WorkspaceEdit();
    const fullRange = new vscode.Range(
      target.positionAt(0),
      target.positionAt(target.getText().length),
    );
    edit.replace(target.uri, fullRange, script);
    const applied = await vscode.workspace.applyEdit(edit);
    vscode.window.showInformationMessage(
      applied
        ? "GMAT Copilot: draft applied to the active file."
        : "GMAT Copilot: could not apply the draft to the active file.",
    );
  } finally {
    draftContents.delete(draftUri.toString());
  }
}

// ------------------------------------------------------------------------- the other commands
async function revalidateCommand(): Promise<void> {
  const activeWorker = worker;
  const editor = vscode.window.activeTextEditor;
  if (!activeWorker) {
    return;
  }
  if (!editor) {
    vscode.window.showWarningMessage("GMAT Copilot: open a .script file to validate it.");
    return;
  }
  try {
    const result = await activeWorker.validate(editor.document.getText());
    applyDiagnostics(editor.document, result.diagnostics);
    if (result.diagnostics.length === 0) {
      vscode.window.showInformationMessage("GMAT Copilot: the script lints clean.");
    }
  } catch (err) {
    showWorkerError(err);
  }
}

/** The no-default-model picker (decision D4): a quick-pick over the providers the worker can reach. */
async function pickModel(): Promise<string | undefined> {
  const activeWorker = worker;
  if (!activeWorker) {
    return undefined;
  }
  let reachable: string[];
  try {
    reachable = (await activeWorker.providers()).reachable;
  } catch (err) {
    showWorkerError(err);
    return undefined;
  }
  if (reachable.length === 0) {
    vscode.window.showWarningMessage(
      "GMAT Copilot: no providers are reachable. Configure a credential (ANTHROPIC_API_KEY, " +
        "OPENAI_API_KEY, GH_TOKEN, or a running Ollama) in the worker's environment, then retry.",
    );
    return undefined;
  }
  const provider = await vscode.window.showQuickPick(reachable, {
    title: "GMAT Copilot: select a provider",
    placeHolder: "Only providers with a configured credential are listed",
  });
  if (!provider) {
    return undefined;
  }
  const model = await vscode.window.showInputBox({
    title: `GMAT Copilot: model for ${provider}`,
    prompt: `Enter the ${provider} model name (the part after the colon)`,
    value: `${provider}:`,
    valueSelection: [provider.length + 1, provider.length + 1],
  });
  if (!model || !model.includes(":") || model.endsWith(":")) {
    return undefined;
  }
  await vscode.workspace
    .getConfiguration("gmatCopilot")
    .update("model", model, vscode.ConfigurationTarget.Global);
  return model;
}

/** The configured `provider:model`, or — honouring the no-default rule (D4) — the picker. */
async function resolveModel(): Promise<string | undefined> {
  const configured = (
    vscode.workspace.getConfiguration("gmatCopilot").get<string>("model", "") ?? ""
  ).trim();
  return configured || (await pickModel());
}

// ----------------------------------------------------------------------------------- helpers
function applyDiagnostics(
  doc: vscode.TextDocument | undefined,
  raw: RawDiagnostic[],
): void {
  if (!doc) {
    return;
  }
  diagnostics.set(
    doc.uri,
    raw.map((d) => toVscodeDiagnostic(d)),
  );
}

function toVscodeDiagnostic(raw: RawDiagnostic): vscode.Diagnostic {
  const range = new vscode.Range(
    raw.range.start.line,
    raw.range.start.character,
    raw.range.end.line,
    raw.range.end.character,
  );
  const diagnostic = new vscode.Diagnostic(range, raw.message, raw.severity as vscode.DiagnosticSeverity);
  diagnostic.source = raw.source;
  diagnostic.code = raw.code;
  return diagnostic;
}

/** vscode-jsonrpc rejects a cancelled request with the LSP RequestCancelled code (-32800). */
function isCancellation(err: unknown): boolean {
  return typeof err === "object" && err !== null && (err as { code?: number }).code === -32800;
}

function showWorkerError(err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  output.appendLine(`error: ${message}`);
  if (/ENOENT|not found|failed to start|spawn/i.test(message)) {
    vscode.window.showErrorMessage(
      "GMAT Copilot: could not start the engine worker. Install it with `pip install gmat-copilot`, " +
        "then set `gmatCopilot.server.pythonPath` to that environment (or put `gmat-copilot-worker` " +
        "on your PATH).",
    );
    return;
  }
  vscode.window.showErrorMessage(`GMAT Copilot: ${message}`);
}
