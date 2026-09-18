# cc-radio

Music that plays while Claude Code is working, so you know by ear when it's done.

The music isn't background ambiance you switch on. It's the progress indicator.

```
you send a deep problem   ──►  ...6 seconds of real work...  ──►  ♪ music starts
Claude needs your input   ──►  music ducks
Claude finishes           ──►  silence
Claude starts again       ──►  ♪ a different station
```

A quick two-second answer stays silent. Only real work earns a soundtrack.

## Install cc-radio

cc-radio needs [mpv](https://mpv.io). That's the only dependency.

```sh
brew install mpv          # macOS
sudo apt install mpv      # Debian, Ubuntu
```

Then add the marketplace and install the plugin:

```sh
claude plugin marketplace add surendranb/cc-radio
claude plugin install ccradio@cc-radio
```

Restart Claude Code. There's nothing to turn on.

## How it works

Five hooks and one script. No configuration.

| Hook | What it means | What cc-radio does |
|---|---|---|
| `UserPromptSubmit` | Claude starts working | Arms a timer, then starts music on a random station after 6 seconds. Also lifts any duck |
| `Stop` | Claude finishes | Stops the music |
| `Notification` | Claude needs your attention | Ducks the volume to 25% |
| `PermissionRequest` | Claude asks permission | Ducks the volume |
| `SessionEnd` | You close the window | Stops the music |

The six-second delay does the real work. Without it, every "yes" and "thanks"
triggers a burst of noise. With it, silence means done and music means working.

Each run picks a different station, so a long session doesn't loop the same
track bed.

## Multiple tabs

One machine, one pair of speakers, one radio. cc-radio tracks which tabs are
working, keyed by Claude Code's `session_id`:

| When | What happens |
|---|---|
| The first tab starts working | Music starts |
| A second tab joins | Music continues on the same station |
| One tab finishes | Music continues, because another tab is still working |
| The last tab finishes | Silence |

Silence always means nothing is working anywhere. That's the only way the signal
stays honest. To see which tabs are busy, run `ccradio working`.

cc-radio forgets a tab that dies without reporting in after two hours, so a crash
can't leave the music running forever. Tabs coordinate through a file lock, so
two tabs that start at the same instant can't lose each other or start two
players.

## Subagents

Subagents run under their own `session_id` and never submit a prompt, so they
never start or stop the music. cc-radio tracks the tab that spawned them.

Subagents do emit their own idle notifications. cc-radio ignores those, because
it only ducks for a session it knows is working. A subagent finishing can't dip
your music at random.

Background task completions arrive in the parent tab as a normal prompt, so a
long chain of agent work keeps the music going instead of cutting out between
steps.

## Music you start yourself

`ccradio play` marks the radio as yours. The hooks don't stop music you started
by hand — only `ccradio stop` does. Music the hooks started, the hooks still
stop.

## Controls

You never need these. The hooks do everything. They're here for when you want
them:

```
ccradio play [station]     pick a station by hand
ccradio next / prev        move one station along
ccradio shuffle            reshuffle the order
ccradio pause              pause or resume
ccradio vol up|down|<n>    volume 0-130, mpv only, never your system volume
ccradio now                current track
ccradio status             what's playing
ccradio stations           list the stations in play
ccradio genre lofi         play a genre, and keep the automatic music in it
ccradio language tamil     the same, by language
ccradio genre off          go back to the built-ins
ccradio working            which tabs are working right now
ccradio debug [n|clear]    trace log: why the radio did or didn't act
ccradio search <term>      find more through Radio Browser
ccradio stop               stop everything
```

Run them instantly with `!ccradio next` in the Claude Code prompt. That costs no
tokens. Use `/ccradio:radio` instead if you want plain English, such as "put on
something ambient".

## Diagnose a silent radio

Hooks run detached with their output discarded, which is right for not
disrupting a session. It also means a radio that stays quiet gives you nothing
to go on. Turn on tracing to see every decision cc-radio makes:

```jsonc
// ~/.claude/settings.json
"env": { "CCRADIO_DEBUG": "1" }
```

Restart Claude Code, then read the trace:

```
$ ccradio debug
11:55:18  arm aaaaaaaa (was_idle=True, working=1)
11:55:24  daemon up, pid 42425, volume 70
11:55:24  play soma-thistle -> https://ice2.somafm.com/thistle-128-mp3
11:55:26  arm bbbbbbbb (was_idle=False, working=2)
11:55:27  ducked 70 -> 17
11:55:27  duck from subagent ignored: not a working tab (subagent?)
11:55:27  disarm aaaaaaaa (1 still working)
11:55:27  disarm bbbbbbbb (0 still working)
```

The trace records why the radio did nothing as well as why it did something:
a turn that ended inside the six-second delay, a station already loaded, a duck
skipped because no daemon was running. Run `ccradio debug clear` to start over.

Tracing writes nothing and costs nothing when `CCRADIO_DEBUG` is unset. The log
caps at 512 KB and rotates once.

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
ccradio genre               # what's playing, and tags worth trying
ccradio genre off           # back to the 17 built-ins
```

A pick sticks. It becomes the pool the automatic music draws from, so every
station Claude puts on stays inside it until you clear it. Each pick fetches
about 30 stations, ordered by how much the directory's listeners play them.

Any tag [Radio Browser](https://www.radio-browser.info/) knows works, not just
the suggested ones. There's no API key.

### A note on "free and open source"

These stations are free to listen to and ad-free, but the music on them is
commercially licensed. It isn't open source or Creative Commons. For strictly
Creative Commons or public-domain audio, look at
[Free Music Archive](https://freemusicarchive.org),
[ccMixter](http://ccmixter.org), and [Musopen](https://musopen.org).

## Why cc-radio runs a daemon

Claude Code keeps no process alive between turns, so the player has to live
outside it. mpv runs detached with a JSON IPC socket. It's the only common player
that supports live pause, volume, and now-playing metadata without killing the
stream.

Volume is mpv's own software volume. It never touches your system volume, so
turning the radio down doesn't quiet your calls or notifications.

## Status line

Optional. Shows the current track, and nothing when the radio is off:

```
⚙ Opus 5  |  ♪ Groove Salad · Jens Buchert - Lakelectric
```

Point `statusLine.command` in `~/.claude/settings.json` at
`bin/ccradio-statusline`. To keep a status line you already have, put its command
in `~/.config/ccradio/base-statusline`.

## Tune cc-radio

| To change | Edit |
|---|---|
| When the music starts | `START_DELAY` in `bin/ccradio`, default 6.0 seconds |
| How far it ducks | `DUCK_RATIO`, default 0.25 |
| The built-in stations | `stations/curated.json` |

## Develop

```sh
python3 tests/test_ccradio.py    # 64 tests, no mpv, network, or speakers needed
claude plugin validate .
```

## Contributors

- [@pavithramohan-netizen](https://github.com/pavithramohan-netizen) — genre and
  language pools, the duplicate-definition catch, and the case for a trace log

## License

MIT. Please support the stations you listen to.
[SomaFM](https://somafm.com/support/) and
[Radio Paradise](https://radioparadise.com/support) both run on listener
donations.
