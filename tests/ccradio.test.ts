// Mod tests for `claude plugin test` (Claude Code 2.1.287 or later).
//
// These fire the events the mod handles and check what it asked the host
// to do. They need no session, sign-in, mpv, or network. The host answers
// every $.process.run with a canned reply, so scripts/ccradio never runs here;
// its own behaviour is covered by tests/test_ccradio.py.
//
// A stub for a mods API call answers with `{ value }`; one for an event such
// as tool.call answers with that event's own result shape.

import { expect, test } from "claude-code/testing";

// A test host draws nothing, which the mod reads as a scripted run and goes
// quiet. Give it a terminal and a session id, as a real tab has. The module
// keeps its state across the tests in this file, so every test does this.
function likeATab(on) {
  on("session.surfaces", () => ({ value: ["terminal"] }));
  on("session.id", () => ({ value: "test-session" }));
  on("ui.log", () => ({ value: undefined }));
  on("env.get", () => ({ value: undefined }));
  on("command.register", () => ({ value: { command: "ccradio" } }));
  // A stub's value must be plain data, so no cancel(); the mod copes.
  on("clock.every", () => ({ value: {} }));
  on("clock.after", () => ({ value: {} }));
}

test("/ccradio runs the shell command and prints its output", async ($, on) => {
  likeATab(on);
  on("process.run", () => ({ value: { exitCode: 0, stdout: "playing  |  Groove Salad", stderr: "" } }));
  const answer = await $.command.run({ command: "ccradio", args: "status" });
  expect(answer.text).toBe("playing  |  Groove Salad");
});

// The "waiting on you" path (an AskUserQuestion, a permission prompt) is
// covered live and by tests/test_ccradio.py on the player side; the test host
// does not route a tool.call raised from a test through this mod's hook the
// way a session does, so it is not asserted here.
