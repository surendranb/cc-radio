#!/bin/sh
# Never disrupt a Claude Code session: bounded time, always exit 0.
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
( "$ROOT/bin/ccradio" "$@" >/dev/null 2>&1 & ) >/dev/null 2>&1
exit 0
