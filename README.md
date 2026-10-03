# cc-radio

Music that plays while Claude Code is working, so you know by ear when it's done.

The music isn't background ambiance you switch on. It's the progress indicator.

```
you send a deep problem      ──►  ...6 seconds of real work...  ──►  ♪ music starts
Claude asks you something    ──►  silence
you answer                   ──►  ♪ music is back at once
Claude finishes              ──►  silence
Claude starts again          ──►  ♪ a different station
```

A quick two-second answer stays silent. Only real work earns a soundtrack.

## Install cc-radio

cc-radio needs two things: [mpv](https://mpv.io) to play the audio, and Python 3,
which macOS and most Linux distributions already ship.

```sh
brew install mpv          # macOS
sudo apt install mpv      # Debian, Ubuntu
```

It also needs Claude Code 2.1.287 or later, because it is a
[mod](https://code.claude.com/docs/en/plugins/mods/overview). Check with
`claude --version` and update if yours is older.

Then add the marketplace and install the plugin:

```sh
claude plugin marketplace add surendranb/cc-radio
claude plugin install ccradio@cc-radio
```

Restart Claude Code. There's nothing to turn on.

cc-radio runs on macOS and Linux. It doesn't run on Windows, and mods don't
load in a WSL session of the Desktop app. Tested on Claude Code 2.1.288.

### What you're trusting

A mod runs inside Claude Code with your own permissions. This one hooks nine
events, runs one process (`bin/ccradio`, in this repo, which drives mpv), and
makes no network calls of its own; mpv fetches the streams. To see exactly
that before you install, clone the repo and run:

```sh
claude plugin validate --strict .
```

The `hooks:` and `calls:` lines it prints are everything the mod can do.

## The one rule

Music plays while Claude Code is working anywhere, and only then. Three
things make a tab count as working or not:

| Tab state | Music |
|---|---|
| A turn is in flight | plays |
| A subagent is still running, even after the turn that started it ended | plays |
| Claude is waiting on you: a permission prompt or a question | silence |
| You pressed Escape, or the turn ended on an API error | silence |
| The tab is idle | silence |

You win over the machine. If any tab is waiting on you, the music pauses, even
while another tab is deep in work. You're about to think and type, and that's
when you want quiet. The moment you answer, it comes straight back, on the
same station.

## How it works

The plugin has two parts.

**The sensor** is a mod, `hooks/register.js`. It runs inside each Claude Code
tab and watches three things: whether a turn is in flight, whether Claude is
waiting on you, and how many subagents are running. Every time one of them
changes, and every five seconds as a heartbeat, it reports the tab's record to
the player.

It listens to the engine's own events only: `turn.start` and `turn.complete`
for the turn, `agent.spawn` and a subagent's `turn.complete` for the agents,
`tool.check` and `tool.call` for anything that waits on you. The `classic.*`
mirrors of the settings hooks are bypassed for a user-installed mod on a
machine with Claude Code's built-in guard, so nothing here depends on them.
The one gap that leaves is an MCP elicitation dialog, which doesn't pause the
music.

A permission ask gets two seconds of grace before it counts as waiting, so a
prompt you answer at once never dents the music. In auto mode the classifier
settles asks without you, and the engine gives a mod no event for the rare one
it hands back to you, so there a permission prompt doesn't pause the music.
A question Claude asks you with AskUserQuestion pauses it in every mode.

**The player** is `bin/ccradio`. It keeps every tab's record, decides from all
of them whether music should play, and makes mpv match. The decision is one
pure function of the records, and every player command is safe to repeat, so
it doesn't matter which tab reports first, or twice, or late. They all reach the
same answer from the same facts.

The heartbeat is what keeps the signal honest. A tab that crashes, or closes
without saying so, stops refreshing its record, and twenty seconds later the
other tabs stop counting it. A missed event can't leave the music on for hours.

The six-second delay does the real work for short turns. Without it, every
"yes" and "thanks" triggers a burst of noise. With it, silence means done and
music means working. A pause for a question keeps its place in the delay, so
the music comes straight back when you answer.

Pause is a real silence, not mpv's pause. A live stream can't pause: the
player would keep buffering and then play stale audio on resume. cc-radio
unloads the stream and reloads it, which is always live and costs a second.

## Multiple tabs

One machine, one pair of speakers, one radio.

| When | What happens |
|---|---|
| The first tab starts working | Music starts |
| A second tab joins | Music continues on the same station |
| The first tab finishes, the second is still working | Music continues |
| The last tab finishes | Silence |
| Any tab asks you something | Silence, until you answer |
| The last tab closes | The player process exits |

To see what each tab reports and what the radio decided, run `ccradio working`.

## Subagents

Subagents run inside the turn that spawned them, so they don't change the
answer while that turn runs. A background subagent that outlives its turn
keeps the tab counted as working until it stops. A subagent that asks for
permission counts as Claude waiting on you, because you're the one who has to
answer.

## Controls

You never need these. The hooks do everything. They're here for when you want
them. `/ccradio <verb>` runs at once, even while Claude is working, and costs
no tokens.

```
/ccradio                    what's playing
/ccradio play [station]     play now, or switch station
/ccradio next / prev        move one station along
/ccradio shuffle            reshuffle the station order
/ccradio pause              silence, and the tabs stay quiet
/ccradio auto               hand the radio back to the tabs
/ccradio stop               silence, and the player process down
/ccradio vol up|down|<n>    volume 0-130, mpv only, never your system volume
/ccradio now                current track
/ccradio stations           list the stations in play
/ccradio genre lofi         pick a genre, and keep the automatic music in it
/ccradio language tamil     the same, by language
/ccradio genre off          go back to the built-ins
/ccradio search <term>      find more through Radio Browser
/ccradio working            which tabs are reporting, and what the radio decided
/ccradio debug [n|clear]    trace log: why the radio did or didn't act
```

The same verbs work from any shell as `ccradio <verb>` once the plugin's `bin`
directory is on your path, and from Claude's Bash tool as a bare command.

### Who owns the music

Three modes, and `/ccradio` tells you which one you're in.

**auto** is the default. The tabs drive: music while they work, silence
otherwise. Changing the station with `next`, `prev`, `shuffle`, or `genre`
keeps it in auto. Changing the station never takes the radio away from the
tabs.

**manual** is yours. `/ccradio play` while nothing is working marks the music
as yours, and the tabs leave it alone until you say `/ccradio auto`. The
same `play` while a tab is already working just switches the station.

**off** is silence. `/ccradio pause` or `/ccradio stop` keeps the tabs from
starting anything until `/ccradio auto`. This is the switch for a call or a
meeting.

For plain words rather than a verb, `/ccradio:radio put on something ambient`
asks Claude to map it to the right call. That costs a turn.

## Diagnose a silent radio

Turn on tracing to see every decision cc-radio makes:

```jsonc
// ~/.claude/settings.json
"env": { "CCRADIO_DEBUG": "1" }
```

Restart Claude Code, then read the trace:

```
$ ccradio debug
11:55:18  report aaaaaaaa {"turn": true}
11:55:18  reconcile: wanted (1 tab(s) working), 6.0s of delay left
11:55:24  daemon up, pid 42425, volume 70
11:55:24  reconcile: play soma-thistle (1 tab(s) working)
11:55:40  report aaaaaaaa {"waiting": true}
11:55:40  reconcile: pause (a tab is waiting on you)
11:55:52  report aaaaaaaa {"waiting": false}
11:55:52  reconcile: play soma-fluid (1 tab(s) working)
11:57:03  report aaaaaaaa {"turn": false}
11:57:03  reconcile: pause (every tab is idle)
```

Tracing writes nothing and costs nothing when `CCRADIO_DEBUG` is unset. The log
caps at 512 KB and rotates once.

A `claude -p` run earns no soundtrack: the mod sees that nothing is drawn and
stays quiet. A session you drive from another device through Remote Control
draws nothing on this machine either, and that one does get music, because
it's you at work. Set `CCRADIO_HEADLESS=1` to give a scripted run music too.

The mod writes one line per report to Claude Code's debug log. Start a session
with `claude --debug-file ./radio.log` and `grep ccradio ./radio.log` to see
every event the sensor saw and what the player answered.

## Stations

cc-radio ships 17 stations, all commercial-free and listener-supported:

- **[SomaFM](https://somafm.com)** (12) — Groove Salad, Drone Zone, DEF CON
  Radio, Lush, Space Station, Beat Blender, Fluid, Deep Space One, Secret Agent,
  Boot Liquor, Sonic Universe, ThistleRadio
- **[Radio Paradise](https://radioparadise.com)** (4) — Main, Mellow, Rock,
  Global
- **[Nightwave Plaza](https://plaza.one)** (1) — vaporwave

### Pick a genre or a language

The built-in stations are all ambient and electronic. That suits focus, but it's
one mood, and not everyone writes code to Drone Zone.

```sh
ccradio genre lofi          # or jazz, classical, metal, carnatic, ghazal
ccradio language tamil      # or hindi, malayalam, japanese, french
ccradio genre               # what's in play, and tags worth trying
ccradio genre off           # back to the 17 built-ins
```

A pick is a preference, not a play button. It becomes the pool the automatic
music draws from, so every station the tabs put on stays inside it until you
clear it. If music is already playing, it switches over. Each pick fetches
about 30 stations, ordered by how much the directory's listeners play them.

Any tag [Radio Browser](https://www.radio-browser.info/) knows works, not just
the suggested ones. There's no API key. Only plain http and https streams are
ever handed to mpv.

### A note on "free and open source"

These stations are free to listen to and ad-free, but the music on them is
commercially licensed. It isn't open source or Creative Commons. For strictly
Creative Commons or public-domain audio, look at
[Free Music Archive](https://freemusicarchive.org),
[ccMixter](http://ccmixter.org), and [Musopen](https://musopen.org).

## Why cc-radio runs a daemon

A mod can't stream audio itself, and Claude Code keeps no process alive between
turns, so the player has to live outside it. mpv runs detached with a JSON IPC
socket. It's the only common player that supports live load, unload, volume,
and now-playing metadata without dying.

Volume is mpv's own software volume. It never touches your system volume, so
turning the radio down doesn't quiet your calls or notifications.

## Where the station shows

The mod draws the station and track in the band above the prompt while music
plays, and nothing when it's silent.

If you'd rather have it in the status line, point `statusLine.command` in
`~/.claude/settings.json` at `bin/ccradio-statusline`. To keep a status line
you already have, put its command in `~/.config/ccradio/base-statusline`.

## Tune cc-radio

| To change | Where |
|---|---|
| When the music starts | `start_delay` in `/plugin` → ccradio → configure, default 6 seconds |
| The built-in stations | `stations/curated.json` |

## Develop

```sh
python3 tests/test_ccradio.py    # the player: 81 tests, no mpv, network, or speakers
node --test tests/               # the mod's pure part
claude plugin validate .         # the manifest, and what the mod hooks and calls
claude plugin test               # the mod against a fake host, 2.1.287 or later
```

To try a change without installing it, start a session with
`claude --plugin-dir /path/to/cc-radio`. Claude Code reloads the mod when a
file in it changes.

## Contributors

- [@pavithramohan-netizen](https://github.com/pavithramohan-netizen) — genre and
  language pools, the duplicate-definition catch, and the case for a trace log

## License

MIT. Please support the stations you listen to.
[SomaFM](https://somafm.com/support/) and
[Radio Paradise](https://radioparadise.com/support) both run on listener
donations.
