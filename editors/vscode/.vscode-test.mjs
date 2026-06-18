import { defineConfig } from "@vscode/test-cli";

// Compiled test suites (tsc -> out/) run in a clean VS Code instance with no other
// extensions, so the activation smoke test sees only this extension. The extension under
// development is always loaded regardless of --disable-extensions.
export default defineConfig({
  files: "out/test/**/*.test.js",
  launchArgs: ["--disable-extensions"],
  mocha: {
    ui: "tdd",
    timeout: 60000,
  },
});
