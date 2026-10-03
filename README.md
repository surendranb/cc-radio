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

A quick two-second answer stays silent. Only real work gets a soundtrack.

## Before you begin

cc-radio needs the following:

- **Claude Code 2.1.287 or later.** cc-radio is a
  [mod](https://code.claude.com/docs/en/plugins/mods/overview), and mods need
  this version. Run `claude --version` to check, and update if yours is older.
- **[mpv](https://mpv.io)**, which plays the audio.
- **Python 3**. On macOS it comes with the Xcode Command Line Tools
  (`xcode-select --install`) or Homebrew; most Linux distributions include it.
- **macOS or Linux.** cc-radio doesn't run on Windows, and mods don't load in a
  WSL session of the Desktop app.

To install mpv:

```sh
brew install mpv          # macOS
sudo apt install mpv      # Debian, Ubuntu
```

cc-radio was last tested on Claude Code 2.1.288. If mpv isn't on the `PATH`
that Claude Code sees, which can happen when you start it from a GUI, set
`CCRADIO_MPV` to mpv's full path in the `env` block of
`~/.claude/settings.json`.

## Install cc-radio

1. Add the marketplace and install the plugin:

   ```sh
   claude plugin marketplace add surendranb/cc-radio
   claude plugin install ccradio@cc-radio
   ```

   Or, inside a Claude Code session, run both in one command:

   ```
   /plugin install ccradio --marketplace surendranb/cc-radio
   ```

2. Restart Claude Code.

There's nothing to turn on. Music starts the next time Claude works for more
than six seconds.

### What the mod can do

A mod runs inside Claude Code with your own permissions. This one hooks nine
events and runs one process, `scripts/ccradio` in this repository, which drives
mpv. mpv fetches the streams. The script calls one web service,
[Radio Browser](https://www.radio-browser.info/), and only when you run
`search`, `genre`, or `language`.

To check this yourself before you install, clone the repository and run the
following command:

```sh
claude plugin validate --strict .
```

The `hooks:` and `calls:` lines in the output list every event the mod handles
and every call it makes.

## The one rule

Music plays while Claude Code is working anywhere, and only then. A tab counts
as working or not depending on its state:

| Tab state | Music |
|---|---|
| A turn is in flight | plays |
| A subagent is still running, even after the turn that started it ended | plays |
| Claude is waiting on you: a permission prompt or a question | silence |
| You pressed Escape, or the turn ended on an API error | silence |
| The tab is idle | silence |

You take priority over the machine. If any tab is waiting on you, the music
pauses, even while another tab is working. You're about to think and type, and
that's when you want quiet. When you answer, the music comes back at once, on
the same station.

## How it works

The plugin has two parts: a sensor and a player.

### The sensor

The sensor is a mod, `hooks/register.js`. It runs inside each Claude Code tab
and watches three things: whether a turn is in flight, whether Claude is
waiting on you, and how many subagents are running. Every time one of them
changes, and every five seconds as a heartbeat, it reports the tab's record to
the player.

The sensor listens to the engine's own events only: `turn.start` and
`turn.complete` for the turn, `agent.spawn` and a subagent's `turn.complete`
for the agents, and `tool.check` and `tool.call` for anything that waits on
you. On a machine with Claude Code's built-in guard, the guard bypasses the
`classic.*` mirrors of the settings hooks for a user-installed mod, so nothing
here depends on them. This leaves one gap: an MCP elicitation dialog doesn't
pause the music.

A permission prompt gets two seconds of grace before it counts as waiting, so
a prompt that you answer at once doesn't interrupt the music. In auto mode,
the classifier settles most prompts without you, and the engine gives a mod no
event for the rare one it hands back to you. So in auto mode a permission
prompt doesn't pause the music. A question that Claude asks you with
AskUserQuestion pauses the music in every mode.

### The player

The player is `scripts/ccradio`. It keeps every tab's record, decides from all of
them whether music should play, and makes mpv match. The decision is one pure
function of the records, and every player command is safe to repeat, so it
doesn't matter which tab reports first, twice, or late. They all reach the same
answer from the same facts.

The heartbeat and a watchdog keep the signal honest. A busy tab refreshes its
record every five seconds. A tab that crashes, or closes without reporting,
stops refreshing it, and 20 seconds later the record no longer counts. The
player also runs a small watchdog process for as long as mpv is up. Every ten
seconds it reconciles the player with the records, so even when the only tab
dies without a word, the music stops within half a minute.

The six-second delay handles short turns. Without it, every "yes" and "thanks"
triggers a burst of noise. With it, silence means done and music means working.
A pause for a question keeps its place in the delay, so the music comes
straight back when you answer.

Pause is a real silence, not mpv's pause. A live stream can't pause: the player
would keep buffering and then play stale audio on resume. cc-radio unloads the
stream and reloads it, which is always live and takes about a second.

## Multiple tabs

One machine, one pair of speakers, one radio.

| When | What happens |
|---|---|
| The first tab starts working | Music starts |
| A second tab joins | Music continues on the same station |
| The first tab finishes, and the second is still working | Music continues |
| The last tab finishes | Silence |
| Any tab asks you something | Silence, until you answer |
| The last tab closes | The player process exits |

To see what each tab reports and what the radio decided, run `ccradio working`.

## Subagents

Subagents run inside the turn that spawned them, so they don't change the
answer while that turn runs. A background subagent that outlives its turn keeps
the tab counted as working until it stops. A question or permission prompt from
a subagent counts the same as one from the main thread, because you're the one
who has to answer it.

## Control the radio

You never need these commands. The mod does everything. They're here for when
you want them. `/ccradio <verb>` runs at once, even while Claude is working,
and costs no tokens.

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

The same verbs work from any shell as `ccradio <verb>` after you add the
plugin's `scripts` directory to your `PATH`.

### Who owns the music

The radio is in one of three modes, and `/ccradio` tells you which.

- `auto` is the default. The tabs drive: music while they work, silence
  otherwise. Changing the station with `next`, `prev`, `shuffle`, or `genre`
  keeps the radio in `auto`. Changing the station never takes the radio away
  from the tabs.
- `manual` means the music is yours. Running `/ccradio play` while nothing is
  working marks the music as yours, and the tabs leave it alone until you run
  `/ccradio auto`. Running `play` while a tab is already working only switches
  the station.
- `off` is silence. `/ccradio pause` or `/ccradio stop` keeps the tabs from
  starting anything until you run `/ccradio auto`. Use this for a call or a
  meeting.

To use plain words instead of a verb, run `/ccradio:radio put on something
ambient`. Claude maps the words to the right call. This costs a turn.

## Diagnose a silent radio

To see every decision cc-radio makes, turn on tracing:

1. Add the following to `~/.claude/settings.json`:

   ```jsonc
   "env": { "CCRADIO_DEBUG": "1" }
   ```

2. Restart Claude Code.

3. Read the trace:

   ```
   $ ccradio debug
   11:55:18  report aaaaaaaa {"turn": true}
   11:55:18  reconcile: wanted (1 tab(s) working), 6.0s of delay left
   11:55:24  daemon up, pid 42425, volume 70
   11:55:24  reconcile: play soma-thistle (1 tab(s) working)
   11:55:40  report aaaaaaaa {"waiting": true}
   11:55:40  reconcile: pause (a tab is waiting on you)
   11:55:52  report aaaaaaaa {"waiting": false}
   11:55:52  reconcile: play soma-thistle (1 tab(s) working)
   11:57:03  report aaaaaaaa {"turn": false}
   11:57:03  reconcile: pause (every tab is idle)
   ```

When `CCRADIO_DEBUG` is unset, tracing writes nothing and costs nothing. The
log caps at 512 KB and rotates once.

To see every event the sensor saw and what the player answered, start a
session with `claude --debug-file ./radio.log` and run
`grep ccradio ./radio.log`. The mod writes one line per report to that log.

A `claude -p` run gets no soundtrack: the mod sees that nothing is drawn and
stays quiet. A session that you drive from another device through Remote
Control also draws nothing on this machine, but it does get music, because
that's you at work. To give a scripted run music too, set
`CCRADIO_HEADLESS=1`.

## Stations

cc-radio ships 17 stations, all commercial-free and listener-supported:

- **[SomaFM](https://somafm.com)** (12): Groove Salad, Drone Zone, DEF CON
  Radio, Lush, Space Station, Beat Blender, Fluid, Deep Space One, Secret Agent,
  Boot Liquor, Sonic Universe, and ThistleRadio
- **[Radio Paradise](https://radioparadise.com)** (4): Main, Mellow, Rock, and
  Global
- **[Nightwave Plaza](https://plaza.one)** (1): vaporwave

### Pick a genre or a language

The built-in stations are all ambient and electronic. That suits focus, but
it's one mood, and not everyone writes code to Drone Zone.

```sh
ccradio genre lofi          # or jazz, classical, metal, carnatic, ghazal
ccradio language tamil      # or hindi, malayalam, japanese, french
ccradio genre               # what's in play, and tags worth trying
ccradio genre off           # back to the 17 built-ins
```

A pick is a preference, not a play button. It becomes the pool that the
automatic music draws from, so every station the tabs put on stays inside it
until you clear it. If music is already playing, it switches over. Each pick
fetches about 30 stations, ordered by how often the directory's listeners play
them.

Any tag that [Radio Browser](https://www.radio-browser.info/) knows works, not
only the suggested ones. There's no API key. cc-radio hands only plain `http`
and `https` streams to mpv, starts mpv with `--ytdl=no` so a directory entry
can never run yt-dlp, and strips terminal control characters from every
station name and track title before it shows them.

### A note on "free and open source"

These stations are free to listen to and ad-free, but the music on them is
commercially licensed. It isn't open source or Creative Commons. For strictly
Creative Commons or public-domain audio, see
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
`~/.claude/settings.json` at `scripts/ccradio-statusline`. To keep a status line
you already have, put its command in `~/.config/ccradio/base-statusline`.

## Tune cc-radio

| To change | Where |
|---|---|
| When the music starts | In Claude Code, run `/plugin configure ccradio@cc-radio` and set **Start delay**. The default is 6 seconds. |
| The built-in stations | `stations/curated.json` |

## Develop

Run the checks from the repository root:

```sh
python3 tests/test_ccradio.py    # the player: 90 tests, no mpv, network, or speakers
node --test tests/               # the mod's pure part
claude plugin validate .         # the manifest, and what the mod hooks and calls
claude plugin test               # the mod against a fake host, 2.1.287 or later
```

To try a change without installing it, start a session with
`claude --plugin-dir /path/to/cc-radio`. Claude Code reloads the mod when a
file in it changes.

## Contributors

- [Pavithra Mohan (@pavi-mo-han)](https://github.com/pavi-mo-han): genre and
  language pools, the duplicate-definition catch, and the case for a trace log

## License

MIT. Support the stations you listen to.
[SomaFM](https://somafm.com/support/) and
[Radio Paradise](https://radioparadise.com/support) both run on listener
donations.
