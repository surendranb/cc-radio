// One tab's view of itself, kept by the mod and reported to bin/ccradio.
//
// Pure: no mods API in here, so it runs under plain node for tests. Every
// method returns true when the record changed, so the caller reports only
// on a change and not on every tool call.
//
// The record answers three questions about this tab:
//   turn     is a main-thread turn in flight?
//   waiting  is Claude waiting on you (permission, question, elicitation)?
//   agents   how many subagents are running, including background ones that
//            outlive the turn that started them?

export class TabTracker {
  constructor() {
    this.turn = false;
    this.agents = new Set();
    // Open asks, by tool_use_id when the event carries one. An ask with no
    // id is kept under a shared key, so it clears when any tool resolves.
    this.asks = new Set();
  }

  get waiting() {
    return this.asks.size > 0;
  }

  record() {
    return { turn: this.turn, waiting: this.waiting, agents: this.agents.size };
  }

  // A main-thread turn began. Any ask still open belongs to a turn that is gone.
  turnStart() {
    const before = this.key();
    this.turn = true;
    this.asks.clear();
    return before !== this.key();
  }

  // A main-thread turn ended: answered, interrupted, refused, or errored.
  turnEnd() {
    const before = this.key();
    this.turn = false;
    this.asks.clear();
    return before !== this.key();
  }

  agentStart(id) {
    const before = this.key();
    this.agents.add(id || "agent");
    return before !== this.key();
  }

  agentEnd(id) {
    const before = this.key();
    if (id && this.agents.has(id)) {
      this.agents.delete(id);
    } else if (!id) {
      this.agents.clear();
    }
    return before !== this.key();
  }

  // Claude put something in front of you and is waiting for the answer.
  askStart(id) {
    const before = this.key();
    this.asks.add(id || "*");
    return before !== this.key();
  }

  // The thing you were asked about resolved: the tool ran, was refused, or the
  // dialog closed. With no id, every open ask is taken as answered.
  askEnd(id) {
    const before = this.key();
    if (id) {
      // This call resolved: its own dialog, if any, is closed, and so is any
      // permission prompt, which arrives with no id. A dialog another call
      // opened is still up.
      this.asks.delete(id);
      this.asks.delete("*");
    } else {
      this.asks.clear();
    }
    return before !== this.key();
  }

  key() {
    const r = this.record();
    return `${r.turn ? 1 : 0}:${r.waiting ? 1 : 0}:${r.agents}`;
  }
}

// What `ccradio report` wants on its command line for a record.
export function reportArgs(sessionId, rec) {
  return [
    "report",
    sessionId,
    `turn=${rec.turn ? 1 : 0}`,
    `waiting=${rec.waiting ? 1 : 0}`,
    `agents=${rec.agents}`,
  ];
}
