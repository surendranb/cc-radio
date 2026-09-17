# cc-radio

Ad-free internet radio that plays while Claude Code works.

Switch stations, skip, shuffle, and change volume without leaving your terminal —
and without spending a model turn on it.

```
$ ccradio play groovesalad
> Groove Salad  (ambient, electronic)

$ ccradio status
playing  |  Groove Salad  |  Kick Bong - Kind Of Imagination  |  vol 55
```

## Install

Needs `mpv`. That is the only dependency.

```sh
brew install mpv          # macOS
sudo apt install mpv      # Debian/Ubuntu
```

Then:

```sh
claude plugin marketplace add OWNER/cc-radio
claude plugin install radio@cc-radio
```

Put `ccradio` on your PATH so you can drive it without a model turn:

```sh
ln -s ~/.claude/plugins/cache/cc-radio/radio/*/bin/ccradio /usr/local/bin/ccradio
```

## Use

Two ways to control it. Prefer the first.

| | |
|---|---|
| `!ccradio next` | instant, costs nothing |
| `/radio next` | ~3s, costs a model turn — use it for search and plain-English requests |

```
ccradio play [station]     start, or switch station
ccradio next / prev        move one station along
ccradio shuffle            reshuffle the station order
ccradio pause              pause or resume
ccradio vol up|down|<n>    volume 0-130
ccradio now                current track
ccradio status             what's playing
ccradio stations           list built-in stations
ccradio search <term>      find more, then: ccradio play <number>
ccradio stop               stop everything
```

`/radio` also understands plain English: *"put on something ambient"*,
*"find me a jazz station"*, *"turn it down"*.

## What it does automatically

| When | What happens |
|---|---|
| Claude stops and asks you something | Volume ducks to 25% |
| You send your next prompt | Volume restores |
| You close your last Claude Code window | Music stops |

Closing *one* window when others are open leaves the music playing.

## Stations

17 built in, all commercial-free and listener-supported:

- **SomaFM** (12) — Groove Salad, Drone Zone, DEF CON Radio, Lush, Space Station,
  Beat Blender, Fluid, Deep Space One, Secret Agent, Boot Liquor, Sonic Universe, ThistleRadio
- **Radio Paradise** (4) — Main, Mellow, Rock, Global
- **Nightwave Plaza** (1) — vaporwave

`ccradio search <term>` reaches the [Radio Browser](https://www.radio-browser.info/)
directory for anything else. No API key.

**On "free and open source":** these stations are free to listen to, ad-free, and
listener-supported. The *music* on them is commercially licensed — it is not
open-source or Creative Commons. If you want strictly CC or public-domain audio,
look at Free Music Archive, ccMixter, and Musopen instead.

## How it works

```
  mpv --idle --input-ipc-server=$SOCK        detached daemon, survives your turns
        ^
        | JSON over a unix socket
        |
   bin/ccradio  <->  ~/.local/state/ccradio/state.json
        ^                    ^
   /radio, !ccradio     hooks (duck / unduck / session refcount)
```

Claude Code keeps no process alive between turns, so the player has to live
outside it. mpv is the only common player with a live control socket — it is what
makes real pause and real volume possible without killing the stream.

Volume is mpv's own software volume. It never touches your system volume.

## Notes

- `next` means **next station**, not next track. Live radio has no track list to
  skip within.
- Pause resumes *live*, not from where you paused. It is radio.
- One daemon is shared across all your Claude Code windows, because you have one
  set of speakers.

## Develop

```sh
python3 tests/test_ccradio.py    # 33 tests, no mpv/network/speakers needed
claude plugin validate .
```

## License

MIT. Please support the stations you listen to —
[SomaFM](https://somafm.com/support/) and
[Radio Paradise](https://radioparadise.com/support) both run on listener donations.
