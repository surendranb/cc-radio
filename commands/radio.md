---
description: Control the background radio - play, next, prev, shuffle, pause, volume, search
argument-hint: "[play|next|prev|shuffle|pause|vol up|vol down|now|stations|search <term>|stop]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/ccradio:*)
---

Run the radio control below and report its output to the user in one short line.
Do not add commentary, do not explain what radio is, do not offer follow-ups.

!`"${CLAUDE_PLUGIN_ROOT}/bin/ccradio" ${ARGUMENTS:-status}`

If the user asked for something in words rather than a subcommand (for example
"put on something ambient", "find me a jazz station", "turn it down"), map it to
the right `ccradio` call and run that instead:

- a mood or genre -> `ccradio stations` first, then `ccradio play <id>`
- an unlisted genre or place -> `ccradio search <term>`, then `ccradio play <number>`
- "louder" / "quieter" -> `ccradio vol up` / `ccradio vol down`

For routine control the user should prefer `!ccradio next` directly in the
prompt - it is instant and costs no tokens, where this command costs a full turn.
