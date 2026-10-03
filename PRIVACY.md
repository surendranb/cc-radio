# Privacy

cc-radio collects no data about you, and it sends none to its author.

## What it reads

The mod reads three facts about each Claude Code tab: whether a turn is in
flight, whether Claude is waiting on you, and how many subagents are running.
It never reads your prompts, Claude's replies, your files, or tool arguments.
It passes each tab's session ID to the player so that tabs can be told apart.

## What it stores

The player keeps its state in `~/.local/state/ccradio` on your machine:

- `tabs.json`: each open tab's session ID and the three facts above
- `state.json`: the current station, volume, and mode
- `pool.json` and `found.json`: stations you picked or searched for
- `debug.log`: a trace of the player's decisions, written only when you set
  `CCRADIO_DEBUG=1`

Nothing in these files leaves your machine. Delete the directory to remove
all of it.

## What it sends over the network

- **mpv** fetches the audio stream of the station you're listening to. The
  station's server sees your IP address and a User-Agent of
  `cc-radio/<version>`, as any streaming client would.
- **Radio Browser** (`api.radio-browser.info`) receives the search term, genre,
  or language you type, and only when you run `search`, `genre`, or
  `language`. The built-in stations never contact it.

That's the complete list. There's no telemetry, no analytics, and no account.

## Support

Open an issue at https://github.com/surendranb/cc-radio/issues.
