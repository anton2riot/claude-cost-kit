#!/usr/bin/env python3
"""Measure the effect of the context-saving hooks from local Claude Code transcripts.

Claude Code stores every session as JSONL under `~/.claude/projects/`, including the
per-turn `usage` block. That is enough to see whether the loop actually got shorter and
whether less context is being re-sent — without waiting for a billing dashboard.

    python3 tools/report.py                          # last 14 days, per day
    python3 tools/report.py --days 30
    python3 tools/report.py --split 2026-07-29       # before/after comparison
    python3 tools/report.py --project stacking       # only matching project dirs

Metrics, and why each one matters:

  calls          tool calls made in the main loop — the factor the gate attacks
  calls/msg      tool calls per user message; less sensitive to how busy the day was
  search         search calls in the main loop (Grep/Glob and read-only shell commands)
  search/msg     search calls per user message — the gate's direct target
  ctx/call       average context carried by one main-loop request
                 (input + cache read + cache write) / main-loop turns
  ctx total      all context sent in main-loop requests that day — the money line
  sub calls      tool calls made inside subagents, where context is cheap
  sub ctx        context sent in subagent requests
  denied         times the gate refused a search call in the main loop; read from the
                 gate's own log, so it only counts days after the hooks were installed

Money itself is not here on purpose: token prices depend on your plan and proxy, so read
the absolute spend from your billing dashboard and use this report to explain its shape.
"""

import argparse
import datetime as dt
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEARCH_TOOLS = {"Grep", "Glob"}
SHELL_TOOLS = {"Bash", "PowerShell"}
SEARCH_COMMAND = re.compile(
    r"(^|[\s;|&(])"
    r"(grep|rg|egrep|fgrep|find|fd|ls|dir|cat|head|tail|wc|tree|jq|sed|awk"
    r"|Select-String|Get-ChildItem|Get-Content)"
    r"(\s|$)"
)
DENIAL_LOG = Path.home() / ".claude" / "hooks" / "state" / "denials.jsonl"


def blank() -> dict:
    return {
        "turns": 0,
        "calls": 0,
        "search": 0,
        "ctx": 0,
        "out": 0,
        "sub_turns": 0,
        "sub_calls": 0,
        "sub_ctx": 0,
        "sub_out": 0,
        "denied": 0,
        "prompts": set(),
        "sessions": set(),
    }


def is_search(name: str, tool_input: dict) -> bool:
    if name in SEARCH_TOOLS:
        return True
    if name in SHELL_TOOLS:
        return bool(SEARCH_COMMAND.search((tool_input or {}).get("command") or ""))
    return False


def project_of(path: Path) -> str:
    """Project directory name, however deep the transcript sits inside it."""
    base = Path.home() / ".claude" / "projects"
    try:
        return path.relative_to(base).parts[0]
    except ValueError:
        return path.parent.name


def count_denials(days: dict, since: dt.date) -> None:
    """Exact denial count, written by the gate itself."""
    if not DENIAL_LOG.exists():
        return
    with DENIAL_LOG.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                stamp = (json.loads(line).get("ts") or "")[:10]
            except Exception:
                continue
            if stamp and stamp >= since.isoformat():
                days[stamp]["denied"] += 1


def collect(project_filter: str | None, since: dt.date) -> dict:
    base = Path.home() / ".claude" / "projects"
    days: dict[str, dict] = defaultdict(blank)

    # Main-loop transcripts sit directly in the project directory; subagent transcripts
    # are nested as <project>/<sessionId>/subagents/agent-*.jsonl.
    for name in glob.iglob(str(base / "**" / "*.jsonl"), recursive=True):
        path = Path(name)
        if project_filter and project_filter.lower() not in project_of(path).lower():
            continue
        sidechain_path = "subagents" in path.parts
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue

                stamp = (record.get("timestamp") or "")[:10]
                if not stamp or stamp < since.isoformat():
                    continue

                # A user message is one prompt; `promptId` lives only on these records.
                if record.get("type") == "user":
                    if not sidechain_path and record.get("promptId"):
                        days[stamp]["prompts"].add(record["promptId"])
                    continue

                if record.get("type") != "assistant":
                    continue

                message = record.get("message") or {}
                usage = message.get("usage") or {}
                context = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
                output = usage.get("output_tokens", 0)

                calls = 0
                search = 0
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            calls += 1
                            if is_search(block.get("name") or "", block.get("input")):
                                search += 1

                bucket = days[stamp]
                bucket["sessions"].add(record.get("sessionId"))
                if sidechain_path or record.get("isSidechain") or record.get("agentId"):
                    bucket["sub_turns"] += 1
                    bucket["sub_calls"] += calls
                    bucket["sub_ctx"] += context
                    bucket["sub_out"] += output
                else:
                    bucket["turns"] += 1
                    bucket["calls"] += calls
                    bucket["search"] += search
                    bucket["ctx"] += context
                    bucket["out"] += output

    count_denials(days, since)
    return days


def fmt(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    if value >= 100:
        return f"{value:.0f}"
    return f"{value:.1f}"


def per(a: float, b: float) -> float:
    return a / b if b else 0.0


HEADER = (
    f"{'day':<12}{'msgs':>6}{'calls':>7}{'calls/msg':>11}{'search':>8}"
    f"{'search/msg':>12}{'ctx/call':>10}{'ctx total':>11}{'sub calls':>10}"
    f"{'sub ctx':>9}{'denied':>8}"
)


def row(label: str, data: dict) -> str:
    msgs = len(data["prompts"]) if isinstance(data["prompts"], set) else data["prompts"]
    return (
        f"{label:<12}{msgs:>6}{data['calls']:>7}{per(data['calls'], msgs):>11.1f}"
        f"{data['search']:>8}{per(data['search'], msgs):>12.1f}"
        f"{fmt(per(data['ctx'], data['turns'])):>10}{fmt(data['ctx']):>11}"
        f"{data['sub_calls']:>10}{fmt(data['sub_ctx']):>9}{data['denied']:>8}"
    )


def merge(days: dict, selected: list[str]) -> dict:
    total = blank()
    total["prompts"] = set()
    for day in selected:
        source = days[day]
        for key in ("turns", "calls", "search", "ctx", "out", "sub_turns", "sub_calls",
                    "sub_ctx", "sub_out", "denied"):
            total[key] += source[key]
        total["prompts"] |= source["prompts"]
        total["sessions"] |= source["sessions"]
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=14, help="how many days back")
    parser.add_argument("--project", help="substring of the project directory name")
    parser.add_argument("--split", help="date the hooks were installed, YYYY-MM-DD")
    args = parser.parse_args()

    since = dt.date.today() - dt.timedelta(days=args.days - 1)
    days = collect(args.project, since)
    if not days:
        print("No sessions found for this period.")
        return

    print(HEADER)
    print("-" * len(HEADER))
    for day in sorted(days):
        print(row(day, days[day]))

    if args.split:
        before = [d for d in sorted(days) if d < args.split]
        after = [d for d in sorted(days) if d >= args.split]
        print()
        print(HEADER)
        print("-" * len(HEADER))
        if before:
            print(row(f"before ({len(before)}d)", merge(days, before)))
        if after:
            print(row(f"after ({len(after)}d)", merge(days, after)))
        if before and after:
            b, a = merge(days, before), merge(days, after)
            print()
            for name, bv, av in (
                ("calls per message", per(b["calls"], len(b["prompts"])),
                 per(a["calls"], len(a["prompts"]))),
                ("search per message", per(b["search"], len(b["prompts"])),
                 per(a["search"], len(a["prompts"]))),
                ("context per message", per(b["ctx"], len(b["prompts"])),
                 per(a["ctx"], len(a["prompts"]))),
            ):
                if bv:
                    change = (av - bv) / bv * 100
                    print(f"{name:<22}{fmt(bv):>10} -> {fmt(av):>8}   {change:+.0f}%")
        print()
        print("Days are not equally busy: read the per-message rows, not the totals.")


if __name__ == "__main__":
    main()
