# cc-radio

**Music that plays while Claude Code is working, so you know by ear when it's done.**

Not background ambiance you switch on. The music *is* the progress indicator.

```
you send a deep problem   ──►  ...6 seconds of real work...  ──►  ♪ music starts
Claude needs your input   ──►  music ducks
Claude finishes           ──►  silence
Claude goes on another tear ──►  ♪ different station
```

A quick two-second answer stays silent. Only real work earns a soundtrack.

## Install

Needs `mpv`. That is the only dependency.

```sh
brew install mpv          # macOS
sudo apt install mpv      # Debian/Ubuntu

claude plugin marketplace add surendranb/cc-radio
claude plugin install ccradio@cc-radio
```

Restart Claude Code. That's it — there is nothing to turn on.

## How it works

Five hooks, one script. No configuration.

| Hook | What it means | What happens |
|---|---|---|
| `UserPromptSubmit` | Claude starts working | Arms a timer. After 6s of real work, music starts on a random station |
| `Stop` | Claude finished | Music stops |
| `Notification` | Claude needs your attention | Volume ducks to 25% |
| `PermissionRequest` | Claude is asking permission | Volume ducks |
| `SessionEnd` | You closed the window | Music stops |

The 6-second delay is the whole trick. Without it every "yes" and "thanks"
triggers a burst of noise. With it, silence means done and music means working.

A different station each time, so a long session doesn't loop the same track bed.

## Many tabs open?

One machine, one pair of speakers, one radio. cc-radio tracks which tabs are
working, keyed by Claude Code's `session_id`:

| | |
|---|---|
| **Music starts** | when the *first* tab starts working |
| **A second tab joins** | keeps playing — it does not change the station mid-song |
| **One tab finishes** | music keeps playing, because another tab is still working |
| **The last tab finishes** | silence |

So silence always means *nothing is working anywhere*, which is the only way the
signal stays honest. `ccradio working` shows which tabs are busy right now.

A tab that dies without reporting in is forgotten after 2 hours, so a crash can
never wedge the music on forever. Tabs coordinate through a file lock, so two
tabs starting at the same instant can't lose each other or start two players.

## Music you start yourself

`ccradio play` marks the radio as yours. The hooks won't stop it when I finish a
task — only `ccradio stop` will. Music the hooks started, the hooks still stop.

## Subagents

Subagents run under their own `session_id` and never submit a prompt of their
own, so they never start or stop the music. The tab that spawned them is still
the thing being tracked.

They do emit their own idle notifications. Those are ignored — cc-radio only
ducks for a session it knows is working, so a subagent finishing can't dip your
music at random.

Background task completions arrive in the parent tab as a normal prompt, so a
long chain of agent work keeps the music going rather than cutting out between
steps.

## Controls (optional)

You never need these — the hooks do everything. They exist for when you want them:

```
ccradio play [station]     pick a station by hand
ccradio next / prev        move one station along
ccradio shuffle            reshuffle the order
ccradio pause              pause or resume
ccradio vol up|down|<n>    volume 0-130 (mpv only, never system volume)
ccradio now                current track
ccradio status             what's playing
ccradio stations           list the stations in play
ccradio genre lofi         play a genre, and keep the automatic music in it
ccradio language tamil     same, by language
ccradio genre off          back to the built-ins
ccradio search <term>      find more via Radio Browser
ccradio stop               stop everything
```

Run them instantly with `!ccradio next` in the Claude Code prompt, or via
`/ccradio:radio` if you want plain English ("put on something ambient").

## Statusline (optional)

```
⚙ Opus 5  |  ♪ Groove Salad · Jens Buchert - Lakelectric
```

Point Claude Code at the wrapper:

```jsonc
// ~/.claude/settings.json
"statusLine": { "type": "command",
                "command": "/path/to/cc-radio/bin/ccradio-statusline" }
```

Already have a statusline? Put its command in
`~/.config/ccradio/base-statusline` and the wrapper runs yours first, then
appends the radio. Claude Code launches the statusline without a shell, so an
env var in `settings.json` never reaches it — the file is the way.

`ccradio statusline` alone prints just the radio segment, or nothing when it's
off.

## Stations

17 built in, all commercial-free and listener-supported:

- **SomaFM** (12) — Groove Salad, Drone Zone, DEF CON Radio, Lush, Space Station,
  Beat Blender, Fluid, Deep Space One, Secret Agent, Boot Liquor, Sonic Universe, ThistleRadio
- **Radio Paradise** (4) — Main, Mellow, Rock, Global
- **Nightwave Plaza** (1) — vaporwave

`ccradio search <term>` reaches the [Radio Browser](https://www.radio-browser.info/)
directory for anything else. No API key.

### Pick a genre, or a language

The built-ins are all ambient and electronic. Good for focus, but it is one mood,
and not everyone writes code to Drone Zone.

```sh
ccradio genre lofi          # or jazz, classical, metal, carnatic, ghazal ...
ccradio language tamil      # or hindi, malayalam, japanese, french ...
ccradio genre               # what is playing, and some tags worth trying
ccradio genre off           # back to the 17 built-ins
```

This sticks. The pick becomes the pool the *automatic* music draws from, so every
station Claude puts on while it works stays inside it until you clear it. Around
30 stations per pick, ordered by how much the directory's listeners play them.

Anything Radio Browser tags works, not just the suggested list.

**On "free and open source":** these stations are free to listen to and ad-free.
The *music* on them is commercially licensed — not open-source or Creative
Commons. For strictly CC or public-domain audio, look at Free Music Archive,
ccMixter, and Musopen.

## Why a daemon

Claude Code keeps no process alive between turns, so the player has to live
outside it. mpv runs detached with a JSON IPC socket — the only common player
that supports live pause, volume, and now-playing metadata without killing the
stream. Volume is mpv's own software volume; it never touches your system volume.

## Tune it

| Want | Change |
|---|---|
| Music sooner or later | `START_DELAY` in `bin/ccradio` (default 6.0s) |
| Quieter ducking | `DUCK_RATIO` (default 0.25) |
| Your own stations | `stations/curated.json` |
| A whole genre or language | `ccradio genre <tag>` / `ccradio language <name>` |

## Develop

```sh
python3 tests/test_ccradio.py    # 55 tests, no mpv/network/speakers needed
claude plugin validate .
```

## License

MIT. Please support the stations you listen to —
[SomaFM](https://somafm.com/support/) and
[Radio Paradise](https://radioparadise.com/support) both run on listener donations.
