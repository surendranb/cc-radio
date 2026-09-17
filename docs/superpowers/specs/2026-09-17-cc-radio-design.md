# cc-radio — Design Spec

**Date:** 2026-09-17
**Status:** Approved, ready for implementation plan

## 1. Purpose

A Claude Code plugin that plays ad-free internet radio in the background while Claude works.
Developers switch stations and control playback without leaving the terminal.

Success means: install, type one command, music plays, and the plugin stays installed
because controlling it never costs a model round-trip.

## 2. Scope

**In scope (v1):**

- Background audio daemon that survives between Claude Code turns and sessions
- Station switching across a curated list and a searchable open directory
- Controls: next, previous, shuffle, pause, volume up, volume down, now-playing
- Automatic volume ducking when Claude asks the user a question
- Public distribution as a GitHub-hosted plugin marketplace

**Out of scope (v1):**

- Track skipping. Live radio has no track list to skip within. `next` moves to the next
  *station*.
- Local file playback, playlists of downloaded music, podcast support
- Per-project default stations, saved favourites, statusline integration
- Windows support. macOS and Linux only.

## 3. Constraints

- Claude Code runs no persistent process. Audio state must live outside the session.
- Slash commands are prompts to the model. Each one costs 2-4 seconds and tokens.
- Users may run several Claude Code windows at once against one set of speakers.
- External dependencies must stay near zero. Developers abandon plugins that need a
  toolchain.

## 4. Architecture

```
  mpv --idle --no-video --no-terminal --input-ipc-server=$SOCK
        ^                                  detached daemon
        | JSON commands over unix socket
        |
   bin/ccradio  (single python3 file)  <-->  state.json
        ^                    ^
        |                    |
  commands/radio.md     hooks/duck.py
  (/radio, via model)   (Stop, UserPromptSubmit, SessionEnd)
```

### 4.1 Player daemon

`mpv` runs detached with an IPC socket. Chosen over `ffplay` and `afplay` because it is the
only option that supports live pause, live volume change, and now-playing metadata without
killing and restarting the stream.

mpv volume is software volume scoped to the mpv process. It never touches system volume.
This is a hard requirement — a radio plugin that turns down the user's whole machine is
broken.

Socket path: `$XDG_RUNTIME_DIR/ccradio.sock`, falling back to `~/.local/state/ccradio/ipc.sock`.

### 4.2 Control CLI

`bin/ccradio` is one Python 3 file. Python over shell because the job needs JSON parsing
and unix-socket writes; shell would add `jq` and `socat` as dependencies. Python 3 ships
with macOS and every mainstream Linux.

**Total external dependency: mpv.** The CLI detects it missing and prints the one-line
install command rather than failing silently.

### 4.3 State

`~/.local/state/ccradio/state.json` holds: current station id, station list and order,
volume, shuffle flag, duck flag and pre-duck volume, daemon pid, and the active session
refcount. Writes are atomic (write temp, rename) because several sessions may write at once.

### 4.4 Two control surfaces

| Surface | Latency | Purpose |
|---|---|---|
| `!ccradio vol up` | instant, zero tokens | routine control, especially volume |
| `/radio vol up` | 2-4s, one model turn | discovery, search, natural language |

Both call the same CLI. Shipping only the slash command would make every volume nudge cost
a model turn, which is the difference between a plugin people keep and one they uninstall.

`bin/ccradio` is added to PATH by the installer, or invoked as
`${CLAUDE_PLUGIN_ROOT}/bin/ccradio` when it is not.

## 5. Commands

| Command | mpv IPC action |
|---|---|
| `start` / `stop` | spawn or terminate the detached daemon |
| `play [station]` | `loadfile <resolved url> replace` |
| `next` / `prev` | move one station along the current order, then `loadfile` |
| `shuffle` | reshuffle station order, jump to a random station |
| `pause` | `cycle pause`. Stream resumes live, not from the pause point |
| `vol up` / `vol down` | `add volume ±10`, clamped 0-130 |
| `vol <n>` | `set_property volume <n>` |
| `now` | read `media-title` (ICY metadata) — current track and artist |
| `stations` | print the curated list with ids and genres |
| `search <term>` | query Radio Browser, print matches, allow play by index |
| `status` | station, track, volume, paused state, duck state |

## 6. Stations

### 6.1 Curated list

Shipped as `stations/curated.json`, a verified snapshot so the first run works offline.
Refreshed at runtime from SomaFM's `channels.json` when the network is available.

All sources are free to listen, commercial-free, and properly licensed. They are **not**
open-source or Creative Commons licensed music — that distinction was raised and the
free-to-listen pool was chosen deliberately for quality and for having true 24/7 streams.

Verified live on 2026-09-17:

| Source | Channels | Notes |
|---|---|---|
| SomaFM | 46 | Listener-supported, no ads, no tracking. `channels.json` directory |
| Radio Paradise | 4 | `stream.radioparadise.com/mp3-192` |
| Nightwave Plaza | 1 | `radio.plaza.one/mp3` |

Default station on first run: SomaFM Groove Salad.

Seed picks: `groovesalad`, `dronezone`, `defcon`, `lush`, `spacestation`, `beatblender`,
`fluid`, `deepspaceone`, `secretagent`, `bootliquor`, `sonicuniverse`, `thistle`.

SomaFM publishes `.pls` playlist URLs. The CLI resolves a `.pls` to its first `File1=`
entry before handing the URL to mpv, rather than relying on mpv's playlist handling.

### 6.2 Search

Radio Browser API (`de1.api.radio-browser.info`), verified live and keyless on 2026-09-17.

- Send a descriptive `User-Agent` per the project's stated etiquette
- Always pass `hidebroken=true`; the directory carries many dead streams
- Resolve the server name from `all.api.radio-browser.info/json/servers` and cache it, so a
  single down mirror does not break search
- Cap results at 20 and print name, country, bitrate, and tags

Search results are untrusted third-party data. Stream URLs are handed to mpv only; they are
never evaluated as shell.

## 7. Hooks

Declared in `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}`.

| Event | Behaviour |
|---|---|
| `Stop` | Claude finished and is awaiting the user. Duck volume: store current, set to `max(10, current * 0.25)` |
| `UserPromptSubmit` | User replied. Restore pre-duck volume |
| `SessionEnd` | Decrement session refcount. Stop the daemon at zero |

**Multi-session model.** One daemon is shared across all Claude Code windows, because the
user has one set of speakers. Duck is last-writer-wins in v1; refcounted ducking is
deliberately deferred as unnecessary complexity.

**Hook safety.** Every hook exits 0 within 200ms regardless of daemon state. A hook that
blocks or fails must never disrupt a Claude Code session. If the socket is absent or the
daemon is dead, the hook exits silently.

## 8. Repository layout

```
cc-radio/
├── .claude-plugin/
│   ├── plugin.json           # name, version, description, author, license
│   └── marketplace.json      # makes the repo installable directly
├── bin/
│   └── ccradio               # the entire backend
├── commands/
│   └── radio.md              # /radio, subcommand-routed
├── hooks/
│   ├── hooks.json
│   └── duck.py
├── stations/
│   └── curated.json          # verified offline fallback snapshot
├── tests/
├── LICENSE                   # MIT
└── README.md
```

Install path for others:

```
claude plugin marketplace add <user>/cc-radio
claude plugin install radio@cc-radio
```

## 9. Error handling

| Failure | Behaviour |
|---|---|
| mpv not installed | Print `brew install mpv` or `apt install mpv`, exit 1. Never fail silently |
| Daemon not running | Any control command auto-starts it, then retries once |
| Socket stale after a crash | Detect dead pid, remove socket, respawn |
| Stream dead or 404 | Print the failure, advance to the next station automatically |
| Radio Browser unreachable | Fall back to the curated list, print a one-line notice |
| `curated.json` missing or corrupt | Fall back to a hardcoded three-station list in the CLI |

## 10. Testing

- **Unit:** `.pls` resolution, station-order rotation, shuffle, volume clamping, state
  read/write round-trip, atomic-write behaviour under concurrent writers
- **IPC:** a fake unix-socket server asserts the exact JSON payload each command emits, with
  no mpv running
- **Network:** recorded fixtures for SomaFM `channels.json` and Radio Browser responses.
  One opt-in live test, skipped by default, confirms the seed stream URLs still resolve
- **Hooks:** assert exit code 0 and sub-200ms runtime with the daemon absent, dead, and live
- **Manual:** the single check no test covers — audio actually comes out of the speakers,
  ducking is audible, and killing one of three sessions does not stop the music

## 11. Open questions

None. Deferred to v2: saved favourites, per-project default stations, statusline
now-playing, refcounted ducking, Windows support.
