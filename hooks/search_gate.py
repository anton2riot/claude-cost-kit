#!/usr/bin/env python3
"""PreToolUse gate: mechanical search must not run in the main dialogue context.

Cost physics: every tool call is a separate request to the model, and the whole
accumulated conversation is re-sent with it. A chain of twenty greps against a
100k-token conversation costs twenty full requests, no matter how small each grep
output is. A subagent has its own small isolated context, so the same chain inside
a subagent is an order of magnitude cheaper, and only the summary comes back.

This gate lets a couple of search calls through per user message (a one-off check
inline is cheaper than spawning a subagent), then denies and asks the agent to batch
the rest into a single subagent task.

Calls made *by* a subagent are never counted and never denied: their payload carries
`agent_id`. File edits, builds, tests and git are untouched.
"""

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

# How many search calls are allowed inline per user message.
FREE_SEARCH_CALLS = int(os.environ.get("CLAUDE_FREE_SEARCH_CALLS", "2"))

# Read-only exploration commands. Builds, tests, git and package managers are not here.
SEARCH_COMMAND = re.compile(
    r"(^|[\s;|&(])"
    r"(grep|rg|egrep|fgrep|find|fd|ls|dir|cat|head|tail|wc|tree|jq|sed|awk"
    r"|Select-String|Get-ChildItem|Get-Content)"
    r"(\s|$)"
)

SEARCH_TOOLS = {"Grep", "Glob"}
SHELL_TOOLS = {"Bash", "PowerShell"}

REASON = (
    "Mechanical search in the main context is closed: this is search call #{n} for the "
    "current user message, and each one drags the whole conversation into the request. "
    "Batch the remaining lookups into ONE task and hand it to a subagent: "
    "Agent with subagent_type quick-lookup, stating what to find and what to return. "
    "Its context is isolated and far smaller. "
    "File edits (Read/Edit/Write), builds, tests and git remain available directly."
)


def state_dir() -> Path:
    path = Path.home() / ".claude" / "hooks" / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def purge_old(directory: Path) -> None:
    cutoff = time.time() - 86400
    for stale in directory.glob("search-*.txt"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass


def is_search_call(payload: dict) -> bool:
    tool = payload.get("tool_name") or ""
    if tool in SEARCH_TOOLS:
        return True
    if tool in SHELL_TOOLS:
        command = (payload.get("tool_input") or {}).get("command") or ""
        return bool(SEARCH_COMMAND.search(command))
    return False


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return
    payload = json.loads(raw)

    # Subagent: small isolated context, nothing to save here.
    if payload.get("agent_id"):
        return

    if not is_search_call(payload):
        return

    prompt_id = payload.get("prompt_id") or "no-prompt"
    directory = state_dir()
    purge_old(directory)

    counter = directory / f"search-{prompt_id}.txt"
    try:
        count = int(counter.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        count = 0
    count += 1
    try:
        counter.write_text(str(count), encoding="utf-8")
    except OSError:
        pass

    if count <= FREE_SEARCH_CALLS:
        return

    # Denials are logged here so tools/report.py can count them exactly instead of
    # guessing from transcript text.
    try:
        with (directory / "denials.jsonl").open("a", encoding="utf-8") as log:
            log.write(
                json.dumps(
                    {
                        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                        "n": count,
                        "tool": payload.get("tool_name"),
                        "session": payload.get("session_id"),
                    }
                )
                + "\n"
            )
    except OSError:
        pass

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON.format(n=count),
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A broken gate must never break the session.
        pass
    sys.exit(0)
