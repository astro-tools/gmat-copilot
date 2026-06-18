import * as assert from "assert";
import * as vscode from "vscode";

const EXTENSION_ID = "astro-tools.gmat-copilot";

const COMMANDS = [
  "gmatCopilot.draft",
  "gmatCopilot.draftFromSelection",
  "gmatCopilot.revalidate",
  "gmatCopilot.selectModel",
];

suite("GMAT Copilot activation", () => {
  test("the extension is installed", () => {
    assert.ok(vscode.extensions.getExtension(EXTENSION_ID), "extension not found");
  });

  test("it activates without a worker or the gmat-script extension present", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(ext, "extension not found");
    await ext.activate();
    assert.ok(ext.isActive, "extension did not activate");
  });

  test("it registers its generation commands", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(ext, "extension not found");
    await ext.activate();
    const registered = await vscode.commands.getCommands(true);
    for (const id of COMMANDS) {
      assert.ok(registered.includes(id), `command not registered: ${id}`);
    }
  });
});
