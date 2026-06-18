// The client side of the gmat-copilot command worker (decision D15).
//
// The engine runs as a child process — `python -m gmat_copilot.worker` (or the
// `gmat-copilot-worker` console script) — and speaks JSON-RPC 2.0 over stdio, framed with the LSP
// `Content-Length` base protocol. We use `vscode-jsonrpc`'s stream transport for that framing; we do
// NOT use `vscode-languageclient`, because this is deliberately *not* a language server — all
// `.script` language features stay with the gmat-script extension. The worker exposes generation
// commands only: `copilot/draft`, `copilot/validate`, `copilot/providers`.

import { ChildProcess, spawn } from "child_process";
import {
  CancellationToken,
  createMessageConnection,
  MessageConnection,
  StreamMessageReader,
  StreamMessageWriter,
} from "vscode-jsonrpc/node";

/** A worker launch command resolved from the extension's settings. */
export interface WorkerCommand {
  command: string;
  args: string[];
}

/** The parameters of a `copilot/draft` request — mirrors the CLI generate surface. */
export interface DraftParams {
  intent: string;
  model: string;
  strict: boolean;
  repair: number;
  dryRun: boolean;
}

/** A diagnostic already mapped to the VS Code shape by the worker (0-indexed positions). */
export interface RawDiagnostic {
  range: {
    start: { line: number; character: number };
    end: { line: number; character: number };
  };
  severity: number;
  source: string;
  code: string;
  message: string;
}

export interface DraftResult {
  script: string;
  diagnostics: RawDiagnostic[];
  rejected: boolean;
  provider: string;
  model: string;
  dryRun: { tier: string; ok: boolean; oneLine: string } | null;
  edit: { kind: string; newText: string };
}

export interface ValidateResult {
  diagnostics: RawDiagnostic[];
}

export interface ProvidersResult {
  reachable: string[];
}

/** A `copilot/progress` notification from the worker during a long-running request. */
export interface ProgressNote {
  id: number | string;
  phase: string;
}

/**
 * Lazily spawns and talks to the engine worker. The child is started on first use and restarted if
 * it exits, so a worker crash (or a settings change followed by a reload) self-heals on the next
 * request rather than wedging the surface.
 */
export class CopilotWorker {
  private proc?: ChildProcess;
  private connection?: MessageConnection;

  constructor(
    private readonly resolveCommand: () => WorkerCommand,
    private readonly log: (message: string) => void,
    private readonly onProgress: (note: ProgressNote) => void,
  ) {}

  private start(): MessageConnection {
    if (this.connection) {
      return this.connection;
    }
    const { command, args } = this.resolveCommand();
    this.log(`starting worker: ${command} ${args.join(" ")}`);
    const proc = spawn(command, args, { stdio: ["pipe", "pipe", "pipe"] });
    proc.on("error", (err) => this.log(`worker failed to start: ${err.message}`));
    proc.on("exit", (code, signal) => {
      this.log(`worker exited (code=${code ?? "null"}, signal=${signal ?? "null"})`);
      this.connection = undefined;
      this.proc = undefined;
    });
    proc.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8").trimEnd();
      if (text) {
        this.log(text);
      }
    });
    const connection = createMessageConnection(
      new StreamMessageReader(proc.stdout!),
      new StreamMessageWriter(proc.stdin!),
    );
    connection.onNotification("copilot/progress", (note: ProgressNote) => this.onProgress(note));
    connection.onError((data) => this.log(`worker connection error: ${data[0].message}`));
    connection.listen();
    this.proc = proc;
    this.connection = connection;
    return connection;
  }

  draft(params: DraftParams, token?: CancellationToken): Promise<DraftResult> {
    return this.start().sendRequest<DraftResult>("copilot/draft", params, token);
  }

  validate(documentText: string): Promise<ValidateResult> {
    return this.start().sendRequest<ValidateResult>("copilot/validate", { documentText });
  }

  providers(): Promise<ProvidersResult> {
    return this.start().sendRequest<ProvidersResult>("copilot/providers", {});
  }

  dispose(): void {
    const connection = this.connection;
    const proc = this.proc;
    this.connection = undefined;
    this.proc = undefined;
    if (connection) {
      // Best-effort graceful shutdown, then tear down the transport and the child.
      connection
        .sendRequest("shutdown", {})
        .catch(() => undefined)
        .finally(() => connection.dispose());
    }
    proc?.kill();
  }
}
