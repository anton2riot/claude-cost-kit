#!/usr/bin/env python3
"""Install the context-saving hooks into Claude Code user settings.

Writes to `~/.claude/settings.json`, so the hooks apply to every project. Unrelated hooks
are left alone; only entries belonging to this kit are removed, so re-installing never
doubles the counters.

    python3 install.py            # install or update
    python3 install.py --remove   # uninstall
    python3 install.py --dry-run  # show what would change
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# Windows consoles are not UTF-8 by default.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KIT_SCRIPTS = ("search_gate.py", "call_budget.py")
# Substrings identifying this kit's entries in settings.json.
KIT_MARKERS = ("search_gate.py", "call_budget.py")


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def install(dry_run: bool) -> None:
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
    print("Hooks are read at startup — restart Claude Code.")


def remove(dry_run: bool) -> None:
    path = settings_path()
    settings = load_settings(path)
    removed = strip_kit_entries(settings)
    if dry_run:
        print(json.dumps(settings.get("hooks"), ensure_ascii=False, indent=2))
        return
    if removed and path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Kit entries removed: {removed}")
    print("The scripts in ~/.claude/hooks were left in place — delete them manually.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="uninstall the hooks")
    parser.add_argument("--dry-run", action="store_true", help="show only")
    args = parser.parse_args()
    if args.remove:
        remove(args.dry_run)
    else:
        install(args.dry_run)


if __name__ == "__main__":
    main()
