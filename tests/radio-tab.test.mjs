// Tests for the mod's pure part. Run:  node --test tests/
//
// The TabTracker is what the mod reports from, so these pin down the
// "working" rule from one tab's point of view, event by event.

import { test } from "node:test";
import assert from "node:assert/strict";
import { TabTracker, reportArgs } from "../hooks/radio-tab.mjs";

test("a fresh tab is idle", () => {
  const t = new TabTracker();
  assert.deepEqual(t.record(), { turn: false, waiting: false, agents: 0 });
});

test("a turn starts and ends", () => {
  const t = new TabTracker();
  assert.equal(t.turnStart(), true, "starting changes the record");
  assert.equal(t.turnStart(), false, "the same fact twice is no change");
  assert.deepEqual(t.record(), { turn: true, waiting: false, agents: 0 });
  assert.equal(t.turnEnd(), true);
  assert.deepEqual(t.record(), { turn: false, waiting: false, agents: 0 });
});

test("a permission prompt is waiting until any tool call resolves", () => {
  const t = new TabTracker();
  t.turnStart();
  assert.equal(t.askStart(), true, "PermissionRequest carries no id");
  assert.equal(t.waiting, true);
  assert.equal(t.askEnd("tool-1"), true, "the granted tool resolving answers it");
  assert.equal(t.waiting, false);
});

test("a question to the user is waiting until that call resolves", () => {
  const t = new TabTracker();
  t.turnStart();
  t.askStart("ask-1");
  assert.equal(t.askEnd("other-tool"), false, "a different call resolving is not the answer");
  assert.equal(t.waiting, true, "the dialog is still open");
  assert.equal(t.askEnd("ask-1"), true);
  assert.equal(t.waiting, false);
});

test("an interrupted or finished turn clears anything it was waiting on", () => {
  const t = new TabTracker();
  t.turnStart();
  t.askStart("ask-1");
  t.askStart();
  t.turnEnd();
  assert.equal(t.waiting, false, "Escape during a dialog must not leave the tab 'waiting'");
});

test("subagents keep the tab working after the turn, until they stop", () => {
  const t = new TabTracker();
  t.turnStart();
  t.agentStart("a1");
  t.agentStart("a2");
  t.turnEnd();
  assert.deepEqual(t.record(), { turn: false, waiting: false, agents: 2 });
  assert.equal(t.agentEnd("a1"), true);
  assert.equal(t.agentEnd("a1"), false, "an agent can only end once");
  assert.equal(t.agentEnd("a2"), true);
  assert.deepEqual(t.record(), { turn: false, waiting: false, agents: 0 });
});

test("an agent ending with no id is taken as every agent ending", () => {
  const t = new TabTracker();
  t.agentStart("a1");
  t.agentStart("a2");
  t.agentEnd();
  assert.equal(t.record().agents, 0);
});

test("report args are what scripts/ccradio parses", () => {
  const t = new TabTracker();
  t.turnStart();
  t.askStart();
  t.agentStart("x");
  assert.deepEqual(reportArgs("sess-1", t.record()),
    ["report", "sess-1", "turn=1", "waiting=1", "agents=1"]);
});
