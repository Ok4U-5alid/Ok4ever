#!/usr/bin/env python3
"""save_conversations.py - Continuous Agent Conversation Saver & Memory Sync

Syncs and persists conversations between you and the AI assistant into
the project SQLite database (`history.db`) continuously.

Features:
- Reads conversation transcripts from Antigravity session logs
- Extracts user prompts (cleaned of XML metadata) and assistant responses
- Deduplicates using (conversation_id, step_index, role)
- Modes:
    --sync     : Sync all past and present conversation steps into the DB
    --watch    : Continuously monitor and insert new messages in real-time
    --list     : View recent saved conversations
    --search Q : Search saved conversation memory for keywords
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

def get_db_path() -> Path:
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            db_name = cfg.get("history", {}).get("db_file", "history.db")
            return BASE_DIR / db_name
        except Exception:
            pass
    return BASE_DIR / "history.db"

DB_PATH = get_db_path()
LOGS_BASE = Path(os.path.expanduser("~/.gemini/antigravity-cli/brain"))

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            ts TEXT NOT NULL,
            role TEXT NOT NULL,             -- 'user' | 'assistant'
            content TEXT NOT NULL,
            tools_used TEXT,                -- JSON list of tools called, if any
            UNIQUE(conversation_id, step_index, role)
        )
    """)
    conn.commit()
    return conn

def clean_user_content(raw: str) -> str:
    """Strip XML wrappers like <USER_REQUEST>, <ADDITIONAL_METADATA>, etc."""
    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", raw, re.DOTALL)
    if m:
        text = m.group(1).strip()
    else:
        # Fallback: remove XML tags
        text = re.sub(r"<[^>]+>.*?</[^>]+>", "", raw, flags=re.DOTALL).strip()
        if not text:
            text = raw.strip()
    return text

def parse_transcript_line(line: str) -> list:
    """Parse one JSONL entry and return list of (step_index, ts, role, content, tools_json)."""
    if not line.strip():
        return []
    try:
        obj = json.loads(line)
    except Exception:
        return []

    step = obj.get("step_index", 0)
    ts = obj.get("created_at") or datetime.now(timezone.utc).isoformat()
    t_type = obj.get("type")
    results = []

    if t_type == "USER_INPUT":
        raw = obj.get("content", "")
        cleaned = clean_user_content(raw)
        if cleaned:
            results.append((step, ts, "user", cleaned, None))

    elif t_type == "PLANNER_RESPONSE":
        content = obj.get("content", "")
        tools = obj.get("tool_calls") or []
        tools_json = json.dumps(tools) if tools else None

        if content and content.strip():
            results.append((step, ts, "assistant", content.strip(), tools_json))
        elif tools:
            # If no text response yet, record tool calls summary
            summary = f"[Executing {len(tools)} tool(s): " + ", ".join(t.get("name", "tool") for t in tools) + "]"
            results.append((step, ts, "assistant", summary, tools_json))

    return results

def sync_file(file_path: Path, conn: sqlite3.Connection) -> int:
    """Sync a single transcript file into the database."""
    conv_id = file_path.parents[2].name  # .../brain/<conv_id>/.system_generated/logs/...
    inserted = 0

    if not file_path.is_file():
        return 0

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                entries = parse_transcript_line(line)
                for step, ts, role, content, tools_json in entries:
                    cur = conn.cursor()
                    try:
                        cur.execute("""
                            INSERT OR IGNORE INTO agent_conversations
                            (conversation_id, step_index, role, content, tools_used, ts)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (conv_id, step, role, content, tools_json, ts))
                        if cur.rowcount > 0:
                            inserted += 1
                    except Exception:
                        pass
        conn.commit()
    except Exception as e:
        print(f"[sync_file error] {file_path}: {e}", file=sys.stderr)

    return inserted

def find_transcript_files() -> list:
    pattern = str(LOGS_BASE / "*" / ".system_generated" / "logs" / "transcript_full.jsonl")
    files = [Path(p) for p in glob.glob(pattern)]
    # Also sort by last modified time (most recent last)
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0)
    return files

def sync_all(conn: sqlite3.Connection):
    files = find_transcript_files()
    total_new = 0
    for f in files:
        new_cnt = sync_file(f, conn)
        total_new += new_cnt
    return total_new

def watch_continuous(interval_sec: float = 2.0):
    """Continuously poll transcript files and insert any new entries into history.db."""
    conn = get_db()
    print("=" * 60)
    print("  Continuous Memory Sync Daemon Active")
    print(f"  Target DB    : {DB_PATH}")
    print(f"  Watch Base   : {LOGS_BASE}")
    print(f"  Poll Interval: {interval_sec}s")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    # Initial sync
    initial_cnt = sync_all(conn)
    print(f"[save_conversations] Initial sync complete: {initial_cnt} message(s) saved.")

    last_sizes = {}
    try:
        while True:
            files = find_transcript_files()
            for f in files:
                try:
                    cur_size = f.stat().st_size
                except OSError:
                    continue
                old_size = last_sizes.get(f)
                if old_size is None or cur_size > old_size:
                    new_cnt = sync_file(f, conn)
                    if new_cnt > 0:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        print(f"[{now_str}] +{new_cnt} new message(s) recorded from {f.parents[2].name[:8]}...")
                    last_sizes[f] = cur_size
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[save_conversations] Stopped continuous sync.")

def list_recent(limit: int = 20):
    conn = get_db()
    rows = conn.execute("""
        SELECT ts, conversation_id, role, content
        FROM agent_conversations
        ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        print("(No agent conversation history found in database)")
        return

    print(f"=== Last {len(rows)} Saved Messages from Memory ===\n")
    for ts, cid, role, content in reversed(rows):
        role_label = "👤 YOU" if role == "user" else "🤖 ASSISTANT"
        ts_clean = ts[:19].replace("T", " ")
        short_id = cid[:8]
        preview = content if len(content) <= 300 else content[:297] + "..."
        print(f"[{ts_clean}] [{short_id}] {role_label}:\n{preview}\n" + "-" * 50)

def search_memory(query: str):
    conn = get_db()
    q = f"%{query}%"
    rows = conn.execute("""
        SELECT ts, conversation_id, role, content
        FROM agent_conversations
        WHERE content LIKE ?
        ORDER BY id DESC LIMIT 50
    """, (q,)).fetchall()

    if not rows:
        print(f"No conversation records matching '{query}'")
        return

    print(f"=== Found {len(rows)} Match(es) for '{query}' ===\n")
    for ts, cid, role, content in reversed(rows):
        role_label = "👤 YOU" if role == "user" else "🤖 ASSISTANT"
        ts_clean = ts[:19].replace("T", " ")
        print(f"[{ts_clean}] {role_label}:")
        print(content)
        print("-" * 50)

def main():
    parser = argparse.ArgumentParser(description="Continuous Agent Conversation Memory Saver")
    parser.add_argument("--sync", action="store_true", help="Sync all existing conversations right now")
    parser.add_argument("--watch", action="store_true", help="Run continuously in background/foreground")
    parser.add_argument("--list", action="store_true", help="Display recent saved conversations")
    parser.add_argument("--search", type=str, help="Search stored memories for a keyword")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval for --watch (seconds)")
    args = parser.parse_args()

    conn = get_db()

    if args.watch:
        watch_continuous(args.interval)
        return

    if args.list:
        list_recent()
        return

    if args.search:
        search_memory(args.search)
        return

    # Default action: sync
    print(f"[save_conversations] Connecting to database: {DB_PATH}")
    cnt = sync_all(conn)
    total = conn.execute("SELECT count(*) FROM agent_conversations").fetchone()[0]
    print(f"[save_conversations] Synced {cnt} new message(s). Total in database: {total}")

if __name__ == "__main__":
    main()
