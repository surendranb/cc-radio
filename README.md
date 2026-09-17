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

claude plugin marketplace add OWNER/cc-radio
claude plugin install radio@cc-radio
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
ccradio stations           list built-in stations
ccradio search <term>      find more via Radio Browser
ccradio stop               stop everything
```

Run them instantly with `!ccradio next` in the Claude Code prompt, or via
`/radio next` if you want plain English ("put on something ambient").

## Statusline (optional)

```
⚙ Opus 5  |  ♪ Groove Salad · Jens Buchert - Lakelectric
```

`ccradio statusline` prints one segment, or nothing when the radio is off.
Already have a statusline? `bin/ccradio-statusline` runs yours first and appends
the radio — point it at your existing command with `CCRADIO_BASE_STATUSLINE`.

## Stations

17 built in, all commercial-free and listener-supported:

- **SomaFM** (12) — Groove Salad, Drone Zone, DEF CON Radio, Lush, Space Station,
  Beat Blender, Fluid, Deep Space One, Secret Agent, Boot Liquor, Sonic Universe, ThistleRadio
- **Radio Paradise** (4) — Main, Mellow, Rock, Global
- **Nightwave Plaza** (1) — vaporwave

`ccradio search <term>` reaches the [Radio Browser](https://www.radio-browser.info/)
directory for anything else. No API key.

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

## Develop

```sh
python3 tests/test_ccradio.py    # 33 tests, no mpv/network/speakers needed
claude plugin validate .
```

## License

MIT. Please support the stations you listen to —
[SomaFM](https://somafm.com/support/) and
[Radio Paradise](https://radioparadise.com/support) both run on listener donations.
