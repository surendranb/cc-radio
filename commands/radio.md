---
description: Control the radio in plain words - "put on something ambient", "find a jazz station", "quieter"
argument-hint: "[what you want, in words]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/ccradio:*)
---

The radio's current state:

!`"${CLAUDE_PLUGIN_ROOT}/bin/ccradio" status`

The user asked: $ARGUMENTS

Map what they asked for to one `ccradio` call, run it, and report its output
in one short line. Do not add commentary, do not explain what the radio is,
do not offer follow-ups. If they asked for nothing, report the state above.

- a mood or genre -> `ccradio stations` first, then `ccradio play <id>`;
  if nothing fits, `ccradio genre <tag>` (lofi, jazz, classical, ...)
- a language -> `ccradio language <name>`
- a place or an unlisted name -> `ccradio search <term>`, then `ccradio play <number>`
- "louder" / "quieter" -> `ccradio vol up` / `ccradio vol down`
- "pause", "quiet", "stop" -> `ccradio pause`; "resume", "back on" -> `ccradio auto`

Run `"${CLAUDE_PLUGIN_ROOT}/bin/ccradio" <args>` for each call.

For a plain verb the user should prefer `/ccradio <verb>`, which runs at once
and costs no tokens, even while Claude is working.
