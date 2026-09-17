#!/bin/sh
# Never disrupt a Claude Code session: bounded time, always exit 0.
# stdin carries the hook payload (session_id) - ccradio needs it to tell tabs apart.
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
payload="$(cat)"
( printf '%s' "$payload" | "$ROOT/bin/ccradio" "$@" >/dev/null 2>&1 & ) >/dev/null 2>&1
exit 0
