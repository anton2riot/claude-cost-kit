#!/usr/bin/env python3
"""Install the context-saving hooks and rules into Claude Code user settings.

Two halves are installed, both at user level so they apply to every project:

* the hooks, into `~/.claude/hooks` + `~/.claude/settings.json`;
* the rules block from `rules-snippet.md`, into `~/.claude/CLAUDE.md`, wrapped in
  marker comments so it can be updated and removed without touching anything else
  in that file.

Unrelated hooks and unrelated CLAUDE.md content are left alone, and only entries
belonging to this kit are removed, so re-installing never doubles anything.

    python3 install.py            # install or update
    python3 install.py --remove   # uninstall
    python3 install.py --dry-run  # show what would change
    python3 install.py --no-rules # hooks only, leave CLAUDE.md untouched
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Windows consoles are not UTF-8 by default.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KIT_SCRIPTS = ("search_gate.py", "call_budget.py")
# Substrings identifying this kit's entries in settings.json.
KIT_MARKERS = ("search_gate.py", "call_budget.py")

# The rules live in one place only — this file — and are extracted from it at install
# time, so the installed copy can never drift from the documented one.
RULES_SOURCE = "rules-snippet.md"
RULES_BEGIN = "<!-- claude-cost-kit:begin -->"
RULES_END = "<!-- claude-cost-kit:end -->"
RULES_NOTE = (
    "<!-- Managed by claude-cost-kit. Edits inside this block are overwritten on "
    "re-install; change rules-snippet.md in the kit instead. -->"
)


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def claude_md_path() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


# Files edited on Windows often carry a UTF-8 BOM; `utf-8-sig` reads them and plain
# UTF-8 alike. Writing stays BOM-less.
READ_ENCODING = "utf-8-sig"


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding=READ_ENCODING).strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        sys.exit(
            f"{path} is not valid JSON ({error}). Fix or move the file, then re-run — "
            "refusing to overwrite settings that cannot be parsed."
        )


def strip_kit_entries(settings: dict) -> int:
    """Remove this kit's entries from PreToolUse, keeping every other hook."""
    hooks = (settings.get("hooks") or {}).get("PreToolUse")
    if not hooks:
        return 0
    removed = 0
    for entry in hooks:
        kept = []
        for hook in entry.get("hooks", []):
            command = hook.get("command", "")
            if any(marker in command for marker in KIT_MARKERS):
                removed += 1
            else:
                kept.append(hook)
        entry["hooks"] = kept
    settings["hooks"]["PreToolUse"] = [e for e in hooks if e.get("hooks")]
    return removed


def extract_rules(path: Path) -> str:
    """Pull the installable rules out of rules-snippet.md.

    Contract with that file: the block handed to the agent is everything between the
    first two lines consisting of `---`. Prose outside those fences is documentation
    for the human and is not installed.
    """
    if not path.exists():
        sys.exit(f"Missing kit file: {path}")
    lines = path.read_text(encoding=READ_ENCODING).splitlines()
    fences = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if len(fences) < 2:
        sys.exit(
            f"Cannot locate the rules block in {path}: expected it between two '---' "
            "lines. Fix the file or run with --no-rules."
        )
    block = "\n".join(lines[fences[0] + 1 : fences[1]]).strip()
    if not block:
        sys.exit(f"The rules block in {path} is empty.")
    return block


def strip_rules_block(text: str) -> tuple:
    """Remove a previously installed block. Returns (remaining text, was it there)."""
    pattern = re.compile(
        re.escape(RULES_BEGIN) + r".*?" + re.escape(RULES_END) + r"[ \t]*\n?",
        re.DOTALL,
    )
    remaining, count = pattern.subn("", text)
    return remaining, count > 0


def install_rules(dry_run: bool) -> None:
    block = extract_rules(Path(__file__).resolve().parent / RULES_SOURCE)
    path = claude_md_path()
    existing = path.read_text(encoding=READ_ENCODING) if path.exists() else ""
    body, replaced = strip_rules_block(existing)
    body = body.rstrip()

    section = f"{RULES_BEGIN}\n{RULES_NOTE}\n\n{block}\n{RULES_END}\n"
    result = f"{body}\n\n{section}" if body else section

    if dry_run:
        print(f"--- {path} ---")
        print(result)
        return

    if path.exists():
        shutil.copy2(path, path.with_suffix(".md.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result, encoding="utf-8")

    lines = block.count("\n") + 1
    verb = "updated" if replaced else "added"
    print(f"Rules {verb} in {path} ({lines} lines, inside the kit's marker block)")
    if path.with_suffix(".md.bak").exists():
        print(f"  backup: {path.name}.bak")


def remove_rules(dry_run: bool) -> None:
    path = claude_md_path()
    if not path.exists():
        print(f"No {path} — nothing to remove.")
        return
    existing = path.read_text(encoding=READ_ENCODING)
    remaining, found = strip_rules_block(existing)
    if not found:
        print(f"No kit rules block in {path}.")
        return
    remaining = remaining.rstrip()
    remaining = f"{remaining}\n" if remaining else ""
    if dry_run:
        print(f"--- {path} ---")
        print(remaining or "(file would be left empty)")
        return
    shutil.copy2(path, path.with_suffix(".md.bak"))
    path.write_text(remaining, encoding="utf-8")
    print(f"Rules block removed from {path} (backup: {path.name}.bak)")


def install(dry_run: bool, with_rules: bool) -> None:
    source = Path(__file__).resolve().parent / "hooks"
    target_dir = Path.home() / ".claude" / "hooks"
    path = settings_path()

    commands = []
    for name in KIT_SCRIPTS:
        src = source / name
        if not src.exists():
            sys.exit(f"Missing kit file: {src}")
        dst = target_dir / name
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        commands.append(f'"{sys.executable}" "{dst}"')

    settings = load_settings(path)
    settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    replaced = strip_kit_entries(settings)
    settings["hooks"]["PreToolUse"].append(
        {"matcher": "*", "hooks": [{"type": "command", "command": c} for c in commands]}
    )

    if dry_run:
        print(json.dumps(settings["hooks"], ensure_ascii=False, indent=2))
        if with_rules:
            install_rules(dry_run=True)
        return

    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Scripts copied to {target_dir}")
    if replaced:
        print(f"Previous kit entries removed: {replaced}")
    print(f"Settings updated: {path} (backup: {path.name}.bak)")

    if with_rules:
        install_rules(dry_run=False)
    else:
        print(f"Rules skipped (--no-rules): {claude_md_path()} left untouched.")
        print("The hooks then deny search without explaining why — expect more retries.")

    print("Hooks are read at startup — restart Claude Code.")


def remove(dry_run: bool, with_rules: bool) -> None:
    path = settings_path()
    settings = load_settings(path)
    removed = strip_kit_entries(settings)
    if dry_run:
        print(json.dumps(settings.get("hooks"), ensure_ascii=False, indent=2))
        if with_rules:
            remove_rules(dry_run=True)
        return
    if removed and path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Kit entries removed: {removed}")
    if with_rules:
        remove_rules(dry_run=False)
    print("The scripts in ~/.claude/hooks were left in place — delete them manually.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="uninstall the kit")
    parser.add_argument("--dry-run", action="store_true", help="show only")
    parser.add_argument(
        "--no-rules",
        action="store_true",
        help="hooks only; do not touch ~/.claude/CLAUDE.md",
    )
    args = parser.parse_args()
    if args.remove:
        remove(args.dry_run, with_rules=not args.no_rules)
    else:
        install(args.dry_run, with_rules=not args.no_rules)


if __name__ == "__main__":
    main()
