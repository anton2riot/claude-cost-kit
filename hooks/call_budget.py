#!/usr/bin/env python3
"""PreToolUse backstop: a reminder about how many tool calls this session has made.

Blocks nothing. The real brake is search_gate.py; this one covers loops that grow for
reasons other than search — screenshot cycles, repeated builds, heavy diagnostic runs.
Silent below the threshold.
"""

import json
import os
import sys
from pathlib import Path

FIRST_WARNING_AT = int(os.environ.get("CLAUDE_CALLS_FIRST_WARNING", "40"))
REPEAT_EVERY = int(os.environ.get("CLAUDE_CALLS_REPEAT_EVERY", "25"))

MESSAGE = (
    "Call budget: this session has already made {n} tool calls. "
    "Every call is a separate billed request carrying the whole conversation. "
    "Either stop and report the result, or batch the remaining mechanical lookups "
    "into a single subagent task (quick-lookup) instead of firing them one by one."
)


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return
    payload = json.loads(raw)

    session_id = payload.get("session_id")
    if not session_id:
        return
    # Subagent calls are accounted for by their own session, not this one.
    if payload.get("agent_id"):
        return

    directory = Path.home() / ".claude" / "hooks" / "state"
    directory.mkdir(parents=True, exist_ok=True)
    counter = directory / f"calls-{session_id}.txt"

    try:
        count = int(counter.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        count = 0
    count += 1
    try:
        counter.write_text(str(count), encoding="utf-8")
    except OSError:
        pass

    if count < FIRST_WARNING_AT:
        return
    if (count - FIRST_WARNING_AT) % REPEAT_EVERY != 0:
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": MESSAGE.format(n=count),
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
