#!/usr/bin/env python3
"""Sync skills from /home/fuck/.claude/skills into ./skills/ as symlinks."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_SKILLS = BASE_DIR / "skills"
CLAUDE_SKILLS = Path(os.path.expanduser("~/.claude/skills"))


def sync():
    if not CLAUDE_SKILLS.is_dir():
        print(f"Claude skills directory not found: {CLAUDE_SKILLS}")
        return

    PROJECT_SKILLS.mkdir(parents=True, exist_ok=True)
    added = 0
    existing = 0

    for item in sorted(CLAUDE_SKILLS.iterdir()):
        if item.name.startswith("."):
            continue
        target = PROJECT_SKILLS / item.name
        if target.exists() or target.is_symlink():
            existing += 1
            continue
        try:
            target.symlink_to(item)
            added += 1
            print(f"  + Linked: {item.name}")
        except Exception as e:
            print(f"  ! Error linking {item.name}: {e}")

    print(f"\nSync complete: {added} new skill(s) linked, {existing} already present.")
    print(f"Total skills available in {PROJECT_SKILLS}: {len(list(PROJECT_SKILLS.iterdir()))}")


if __name__ == "__main__":
    sync()
