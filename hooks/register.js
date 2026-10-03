// cc-radio: music that plays while Claude Code works, so you know by ear
// when it's done.
//
// This mod is the sensor. It watches one tab: is a turn in flight, is Claude
// waiting on you, how many subagents are running. Every change, and every
// few seconds as a heartbeat while the tab is busy, it reports that record to
// scripts/ccradio, which keeps every tab's record, decides from all of them
// whether music should play, and drives mpv. The decision lives there, in one
// place, as a pure function of the records; this file only has to be an
// honest witness.
//
// Only the engine's own events are used. The `classic.*` mirrors of the
// settings hooks are bypassed for a user-installed mod on a machine with the
// built-in guard, so a sensor built on them would see nothing there.
//
// The host reads on(...) and $.noun.method(...) from source, so they are
// spelled literally, and helpers that take $ are top-level functions.

import { TabTracker, reportArgs } from "./radio-tab.mjs";

const HEARTBEAT_MS = 5000;
// A permission "ask" is often settled within a second, without you. Only an
// ask that outlives this grace is a real wait.
const ASK_GRACE_MS = 2000;
// Permission modes whose own decider settles an "ask" without you. There a
// tool.check "ask" says nothing about you being needed, so it is not a wait.
const AUTO_MODES = ["auto", "bypassPermissions", "dontAsk"];

let tab = new TabTracker();
let sessionId = null;
let headless = false;
let startDelay = 6;
let heartbeat = null;
let askTimer = null;
let starting = false;
let inFlight = false;
let asksLogged = 0;
let line = ""; // the band line, as the last report printed it

export function register(on, options) {
  if (options && typeof options.start_delay === "number") {
    startDelay = options.start_delay;
  }

  on("session.start", async ($, e, next) => {
    await ready($);
    return next(e);
  });

  // The session ends, or /clear, /resume, or /branch moves this process to a
  // new session id. Report the old tab gone and start over: the next event
  // of any kind begins again under the new id.
  on("session.end", async ($, e, next) => {
    if (heartbeat && typeof heartbeat.cancel === "function") heartbeat.cancel();
    heartbeat = null;
    if (askTimer && typeof askTimer.cancel === "function") askTimer.cancel();
    askTimer = null;
    await gone($);
    sessionId = null;
    tab = new TabTracker();
    return next(e);
  });

  // --- a turn in flight -------------------------------------------------

  // Fires for the main loop only; a subagent's run raises no turn.start.
  on("turn.start", async ($, e, next) => {
    await report($, tab.turnStart());
    return next(e);
  });

  on("turn.complete", async ($, e, next) => {
    // A main turn ending for any reason: answered, interrupted with Escape,
    // refused, or an API error. A subagent's turn ending is that agent done.
    if (e.agentId) await report($, tab.agentEnd(e.agentId));
    else await report($, tab.turnEnd());
    return next(e);
  });

  // --- subagents ----------------------------------------------------------

  on("agent.spawn", async ($, e, next) => {
    const started = await next(e);
    if (started && started.agentId) await report($, tab.agentStart(started.agentId));
    return started;
  });

  // --- waiting on you -----------------------------------------------------

  // The engine's verdict on a tool call. `ask` means a decider has to settle
  // it: you, or in auto mode a classifier. Start the clock; the tool call
  // resolving stops it.
  on("tool.check", async ($, e, next) => {
    const verdict = await next(e);
    if (verdict && verdict.decision === "ask") {
      const auto = await autoDecider($);
      if (asksLogged < 5) {
        asksLogged += 1;
        $.ui.log(`tool.check ask for ${e.tool} (auto=${auto}): ${verdict.reason || ""}`, { to: "debug" });
      }
      if (!auto) await askStarted($, e.tool_use_id, ASK_GRACE_MS);
    }
    return verdict;
  });

  // Every tool call passes through here. A question to you is waiting from
  // before the dialog opens until it closes, no grace needed; any call
  // resolving, allowed or refused, means whatever it waited on was answered.
  on("tool.call", async ($, e, next) => {
    if (e.tool === "AskUserQuestion") await askStarted($, e.tool_use_id, 0);
    try {
      return await next(e);
    } finally {
      await askEnded($, e.tool_use_id);
    }
  });

  // --- the user ------------------------------------------------------------

  on("command.run", { command: "ccradio" }, async ($, e) => {
    await ready($);
    const r = await run($, String(e.args || "status").trim().split(/\s+/));
    await refresh($);
    return { text: r.out || r.err || "(no output)" };
  });

  on("ui.render", { component: "AbovePrompt" }, async ($, e, next) => {
    if (e.hasSurvey || !line) return next(e);
    const { Box, Text } = $.ui.resolve(e);
    // Keep what the mods after this one draw in the band, and add our line.
    const theirs = await next(e);
    const children = [Text({ dimColor: true, children: line })];
    if (theirs) children.unshift(theirs);
    return Box({ flexDirection: "column", paddingX: 1, children });
  });
}

// --- helpers that take $ (top level, so the host can read what they call) ---

// A resumed session may fire no session.start, so the first event of any
// kind has to be able to start us up.
async function ready($) {
  if (sessionId || starting) return;
  starting = true;
  try {
    await begin($);
  } finally {
    starting = false;
  }
}

async function begin($) {
  try {
    sessionId = String(await $.session.id());
  } catch {
    // A host with no session id still gets a key of its own to report under.
    sessionId = "tab-" + Math.random().toString(36).slice(2, 10);
  }
  let surfaces = null;
  try {
    surfaces = await $.session.surfaces();
  } catch {
    surfaces = null; // a host that cannot say is not a scripted run
  }
  // An empty list means a scripted `claude -p` run, which earns no soundtrack.
  // A session driven from another device draws nothing here either, and that
  // one is you at work, so a bridge counts as a surface.
  headless = Array.isArray(surfaces) && surfaces.length === 0;
  try {
    if (headless && (await $.env.get("CLAUDE_CODE_BRIDGE_SESSION_ID"))) headless = false;
    if (headless && (await $.env.get("CCRADIO_HEADLESS")) === "1") headless = false;
  } catch {
    // leave it
  }
  $.ui.log(
    `begin: session ${sessionId.slice(0, 8)}, surfaces=${JSON.stringify(surfaces)}, headless=${headless}, auto=${await autoDecider($)}`,
    { to: "debug" },
  );
  try {
    await $.command.register({
      name: "ccradio",
      description: "Radio: status, play, next, pause, auto, vol up, genre <tag>",
      argumentHint: "[status|play|next|pause|auto|vol up|down|genre <tag>]",
      immediate: true,
    });
  } catch {
    // Already registered, or the name is taken: the shell command still works.
  }
  if (headless) return;
  await report($, true);
  if (!heartbeat) {
    try {
      heartbeat = $.clock.every(HEARTBEAT_MS, () => tick($));
    } catch {
      heartbeat = null; // no timer on this host: events alone keep the record fresh
    }
  }
}

// The heartbeat. An idle tab has nothing to keep fresh: the player reads a
// missing record as idle, and its watchdog retires the music on its own.
async function tick($) {
  if (inFlight) return; // a slow report is still out; do not pile up
  await pruneAgents($);
  const r = tab.record();
  if (!r.turn && !r.waiting && r.agents === 0) return;
  await report($, true);
}

// Drop any subagent the engine no longer lists as running, so one whose end
// we never saw cannot keep this tab working forever.
async function pruneAgents($) {
  if (tab.agents.size === 0) return;
  let listed;
  try {
    listed = await $.agent.list();
  } catch {
    return;
  }
  if (!Array.isArray(listed)) return;
  const running = new Set(listed.filter((a) => a && a.status === "running").map((a) => a.id));
  for (const id of [...tab.agents]) {
    if (!running.has(id)) tab.agentEnd(id);
  }
}

// The permission mode that settles an "ask", read each time it matters, so a
// change in settings is seen. A mode switched inside the session is not in
// the settings, and the engine gives a mod no other way to read it.
async function autoDecider($) {
  try {
    const settings = await $.settings.read({});
    const mode = settings && settings.permissions && settings.permissions.defaultMode;
    return AUTO_MODES.includes(String(mode || ""));
  } catch {
    return false;
  }
}

async function askStarted($, id, graceMs) {
  const changed = tab.askStart(id);
  if (!changed) return;
  if (askTimer && typeof askTimer.cancel === "function") askTimer.cancel();
  askTimer = null;
  if (graceMs <= 0) {
    await report($, true);
    return;
  }
  try {
    askTimer = $.clock.after(graceMs, () => {
      askTimer = null;
      if (tab.waiting) report($, true);
    });
  } catch {
    askTimer = null;
    await report($, true); // no timer on this host: report at once
  }
}

async function askEnded($, id) {
  const changed = tab.askEnd(id);
  if (!changed) return;
  if (askTimer && !tab.waiting) {
    // The ask settled inside the grace: nothing was ever reported, nothing to undo.
    if (typeof askTimer.cancel === "function") askTimer.cancel();
    askTimer = null;
    return;
  }
  await report($, true);
}

async function report($, changed) {
  await ready($);
  if (!changed || headless || !sessionId) return;
  inFlight = true;
  try {
    const r = await run($, reportArgs(sessionId, tab.record()));
    setLine($, r.exitCode === 0 ? r.out : `cc-radio: ${r.err || "report failed"}`);
  } finally {
    inFlight = false;
  }
}

async function gone($) {
  if (headless || !sessionId) return;
  await run($, ["report", sessionId, "gone"]);
  setLine($, "");
}

async function refresh($) {
  if (headless || !sessionId) return;
  const r = await run($, ["statusline"]);
  setLine($, r.out);
}

function setLine($, text) {
  const next = (text || "").trim().split("\n")[0].slice(0, 120);
  if (next === line) return;
  line = next;
  $.ui.invalidate("ui.render");
}

// Run the player's command line. `out` is its stdout, `err` the first line of
// its stderr; the whole stderr goes to the debug log, never to the band.
async function run($, args) {
  try {
    const r = await $.process.run([`${$.plugin.root}/scripts/ccradio`, ...args], {
      env: { CCRADIO_START_DELAY: String(startDelay) },
      timeoutMs: 20000,
    });
    const out = (r.stdout || "").trim();
    const errAll = (r.stderr || "").trim();
    $.ui.log(`ccradio ${args.join(" ")} -> exit ${r.exitCode}${out ? ": " + out : ""}${errAll ? " | " + errAll : ""}`, { to: "debug" });
    return { exitCode: r.exitCode, out, err: errAll.split("\n")[0] };
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    $.ui.log(`ccradio ${args.join(" ")} failed: ${msg}`, { to: "debug" });
    return { exitCode: -1, out: "", err: msg };
  }
}
