// cc-radio: music that plays while Claude Code works, so you know by ear
// when it's done.
//
// This mod is the sensor. It watches one tab: is a turn in flight, is Claude
// waiting on you, how many subagents are running. Every change, and every
// few seconds as a heartbeat, it reports that record to bin/ccradio, which
// keeps every tab's record, decides from all of them whether music should
// play, and drives mpv. The decision lives there, in one place, as a pure
// function of the records; this file only has to be an honest witness.
//
// Only the engine's own events are used. The `classic.*` mirrors of the
// settings hooks are bypassed for a user-installed mod on a machine with the
// built-in guard, so a sensor built on them would see nothing there.
//
// The host reads on(...) and $.noun.method(...) from source, so they are
// spelled literally, and helpers that take $ are top-level functions.

import { TabTracker, reportArgs } from "./radio-tab.mjs";

const HEARTBEAT_MS = 5000;
// A permission "ask" is often settled by the mode's own decider within a
// second, without you. Only an ask that outlives this grace is a real wait.
const ASK_GRACE_MS = 2000;

const tab = new TabTracker();
let sessionId = null;
let headless = false;
let startDelay = 6;
let heartbeat = null;
let askTimer = null;
let starting = false;
// Permission modes whose own decider settles an "ask" without you: a tool.check
// "ask" there says nothing about you being needed, so it is not a wait.
let autoDecider = false;
let asksLogged = 0;
let line = ""; // the statusline segment, as the last report printed it

export function register(on, options) {
  if (options && typeof options.start_delay === "number") {
    startDelay = options.start_delay;
  }

  on("session.start", async ($, e, next) => {
    await ready($);
    return next(e);
  });

  on("session.end", async ($, e, next) => {
    if (heartbeat && typeof heartbeat.cancel === "function") heartbeat.cancel();
    heartbeat = null;
    await gone($);
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
  // it: you, or in auto mode a classifier that usually answers in a second.
  // Start the clock; the tool call resolving stops it.
  on("tool.check", async ($, e, next) => {
    const verdict = await next(e);
    if (verdict && verdict.decision === "ask") {
      if (asksLogged < 5) {
        asksLogged += 1;
        $.ui.log(`tool.check ask for ${e.tool} (autoDecider=${autoDecider}): ${verdict.reason || ""}`, { to: "debug" });
      }
      if (!autoDecider) askStarted($, e.tool_use_id, ASK_GRACE_MS);
    }
    return verdict;
  });

  // Every tool call passes through here. A question to you is waiting from
  // before the dialog opens until it closes, no grace needed; any call
  // resolving means whatever it waited on was answered.
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
    const out = await run($, String(e.args || "status").trim().split(/\s+/));
    await refresh($);
    return { text: out || "(no output)" };
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
  let mode = "";
  try {
    const settings = await $.settings.read({});
    mode = String((settings && settings.permissions && settings.permissions.defaultMode) || "");
  } catch {
    mode = "";
  }
  autoDecider = ["auto", "bypassPermissions", "dontAsk"].includes(mode);
  $.ui.log(
    `begin: session ${sessionId ? sessionId.slice(0, 8) : "unknown"}, surfaces=${JSON.stringify(surfaces)}, headless=${headless}, mode=${mode || "default"}`,
    { to: "debug" },
  );
  if (!heartbeat) {
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
  }
  if (headless) return;
  tab.turnEnd();
  await report($, true);
  if (!heartbeat) {
    try {
      heartbeat = $.clock.every(HEARTBEAT_MS, () => report($, true));
    } catch {
      heartbeat = null; // no timer on this host: events alone keep the record fresh
    }
  }
}

async function askStarted($, id, graceMs) {
  const changed = tab.askStart(id);
  if (!changed) return;
  if (askTimer) {
    askTimer.cancel();
    askTimer = null;
  }
  if (graceMs <= 0) {
    await report($, true);
    return;
  }
  askTimer = $.clock.after(graceMs, () => {
    askTimer = null;
    if (tab.waiting) report($, true);
  });
}

async function askEnded($, id) {
  const changed = tab.askEnd(id);
  if (!changed) return;
  if (askTimer && !tab.waiting) {
    // The ask settled inside the grace: nothing was ever reported, nothing to undo.
    askTimer.cancel();
    askTimer = null;
    return;
  }
  await report($, true);
}

async function report($, changed) {
  await ready($);
  if (!changed || headless || !sessionId) return;
  const out = await run($, reportArgs(sessionId, tab.record()));
  setLine($, out);
}

async function gone($) {
  if (headless || !sessionId) return;
  await run($, ["report", sessionId, "gone"]);
  setLine($, "");
}

async function refresh($) {
  if (headless || !sessionId) return;
  setLine($, await run($, ["statusline"]));
}

function setLine($, text) {
  const next = (text || "").trim();
  if (next === line) return;
  line = next;
  $.ui.invalidate("ui.render");
}

async function run($, args) {
  try {
    const r = await $.process.run([`${$.plugin.root}/bin/ccradio`, ...args], {
      env: { CCRADIO_START_DELAY: String(startDelay) },
      timeoutMs: 20000,
    });
    const out = (r.stdout || r.stderr || "").trim();
    $.ui.log(`ccradio ${args.join(" ")} -> exit ${r.exitCode}${out ? ": " + out : ""}`, { to: "debug" });
    return out;
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    $.ui.log(`ccradio ${args.join(" ")} failed: ${msg}`, { to: "debug" });
    return `ccradio: ${msg}`;
  }
}
