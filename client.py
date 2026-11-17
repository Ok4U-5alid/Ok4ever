#!/usr/bin/env python3
"""Client for the local LLM server (ai_server.py) with Agent tool support.

Usage:
    python client.py "Check python version on terminal"
    python client.py "Write a test script hello.py that prints hello"
    python client.py -i                 # interactive chat mode!
    python client.py --no-tools "What is 13 * 27?"
    python client.py --module math_utils "What is 13 * 27?"
    python client.py --list             # show status, backend, and tools
    python client.py --history          # show saved chat history
    python client.py --sessions         # list chat sessions

Auto-detects plain (8000) or SSL (8444) API; override with AI_API_URL env var.
Reads ports from config.json if present.
"""

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

# ------------------------------------------------------------------
# Load config.json for port defaults
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

def _load_config() -> dict:
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

CFG = _load_config()
_srv = CFG.get("server", {})
_ssl_cfg = _srv.get("ssl", {})
API_PORT = _srv.get("api_port", 8000)
API_SSL_PORT = _srv.get("api_ssl_port", 8444)

# ------------------------------------------------------------------
# Auto-detect API URL (plain or SSL)
# ------------------------------------------------------------------
_URL_OVERRIDE = os.environ.get("AI_API_URL")

# Build an SSL context that skips verification for self-signed certs
_insecure_ctx = ssl.create_default_context()
_insecure_ctx.check_hostname = False
_insecure_ctx.verify_mode = ssl.CERT_NONE


def _probe(url: str) -> bool:
    """Check if a URL answers (any HTTP status = alive)."""
    try:
        kwargs = {}
        if url.startswith("https://"):
            kwargs["context"] = _insecure_ctx
        urllib.request.urlopen(f"{url}/health", timeout=3, **kwargs)
        return True
    except urllib.error.HTTPError:
        return True      # answered with an error status, but alive
    except Exception:
        return False


def detect_api_url() -> str:
    """Auto-detect which API URL works: explicit override, plain, then SSL."""
    if _URL_OVERRIDE:
        return _URL_OVERRIDE
    candidates = [
        f"http://localhost:{API_PORT}",
        f"https://localhost:{API_SSL_PORT}",
    ]
    for url in candidates:
        if _probe(url):
            return url
    return candidates[0]   # fall back to plain for error messages


URL = detect_api_url()


def _urlopen(req_or_url, timeout=300):
    """urlopen wrapper that handles self-signed SSL certs."""
    kwargs = {}
    url_str = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
    if url_str.startswith("https://"):
        kwargs["context"] = _insecure_ctx
    return urllib.request.urlopen(req_or_url, timeout=timeout, **kwargs)


def post_chat(message: str, module: str | None = None, max_new_tokens: int = 512, enable_tools: bool = True):
    payload = json.dumps({
        "message": message,
        "module": module,
        "max_new_tokens": max_new_tokens,
        "enable_tools": enable_tools,
    }).encode()
    req = urllib.request.Request(
        f"{URL}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with _urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def get_json(path: str):
    with _urlopen(f"{URL}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode())


def print_response(result: dict, original_message: str | None = None, module: str | None = None):
    if module and result.get("processed_message") != original_message:
        print(f"[module '{module}' transformed message to: {result['processed_message']!r}]")

    tools_used = result.get("tools_used") or []
    if tools_used:
        print(f"\n[Tools Executed: {len(tools_used)}]")
        for i, t in enumerate(tools_used, 1):
            args_str = ", ".join(f"{k}={v!r}" for k, v in t.get("args", {}).items())
            print(f"  ({i}) {t['name']}({args_str})")
        print("----------------------------------------\n")

    print(result.get("response", ""))


def print_history(limit: int = 50):
    """Fetch and display chat history from history.db via the API."""
    try:
        data = get_json(f"/history?limit={limit}")
        msgs = data.get("messages", [])
        if not msgs:
            print("(no chat history)")
            return
        print(f"=== Chat History ({len(msgs)} messages) ===\n")
        for m in msgs:
            ts = m.get("ts", "?")[:19]
            role = m["role"].upper()
            sid = m.get("session_id", "?")
            prefix = f"[{ts}] [S{sid}] {role}"
            mod_tag = f" (module: {m['module']})" if m.get("module") else ""
            content = m["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"{prefix}{mod_tag}: {content}\n")
    except Exception as e:
        print(f"Error fetching history: {e}", file=sys.stderr)


def print_sessions():
    """Fetch and display chat sessions."""
    try:
        data = get_json("/sessions")
        sessions = data.get("sessions", [])
        if not sessions:
            print("(no sessions)")
            return
        print(f"=== Chat Sessions ({len(sessions)}) ===\n")
        for s in sessions:
            ended = s.get("ended_at") or "active"
            title = s.get("title") or "(untitled)"
            summary = s.get("summary") or ""
            print(f"  Session #{s['id']}: {title}")
            print(f"    Started: {s['started_at']}")
            print(f"    Ended:   {ended}")
            if summary:
                print(f"    Summary: {summary}")
            print()
    except Exception as e:
        print(f"Error fetching sessions: {e}", file=sys.stderr)


def print_agent_memory(limit: int = 20):
    """Fetch and display conversations with Antigravity from agent_conversations in history.db."""
    import sqlite3
    db_file = BASE_DIR / CFG.get("history", {}).get("db_file", "history.db")
    if not db_file.is_file():
        print(f"(database not found: {db_file})")
        return
    try:
        conn = sqlite3.connect(str(db_file))
        rows = conn.execute("""
            SELECT ts, conversation_id, role, content
            FROM agent_conversations
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        if not rows:
            print("(No agent conversations recorded yet. Run: python save_conversations.py --sync)")
            return
        print(f"=== Saved Agent Memory ({len(rows)} messages) ===\n")
        for ts, cid, role, content in reversed(rows):
            role_label = "👤 YOU" if role == "user" else "🤖 ASSISTANT"
            ts_clean = ts[:19].replace("T", " ")
            short_id = cid[:8]
            preview = content if len(content) <= 250 else content[:247] + "..."
            print(f"[{ts_clean}] [{short_id}] {role_label}:\n  {preview}\n")
    except Exception as e:
        print(f"Error reading agent memory: {e}", file=sys.stderr)


def interactive_chat(module: str | None = None, tokens: int = 512, enable_tools: bool = True):
    is_ssl = URL.startswith("https://")
    print("==================================================")
    print("  Local Ollama Agent Terminal (ai_server)")
    print(f"  Target: {URL} {'🔒 SSL' if is_ssl else '🔓 Plain'} | Tools: {'ON' if enable_tools else 'OFF'}")
    print("  Type your prompt, or type 'exit' or 'quit' to stop.")
    print("  Special commands: /history, /sessions, /memory, /clear, /config")
    print("==================================================\n")
    while True:
        try:
            prompt = input("you> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        if not prompt:
            continue
        if prompt.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break
        # Built-in commands
        if prompt.lower() == "/history":
            print_history()
            continue
        if prompt.lower() == "/sessions":
            print_sessions()
            continue
        if prompt.lower() in ("/memory", "/agent"):
            print_agent_memory()
            continue
        if prompt.lower() == "/clear":
            try:
                get_json_del = urllib.request.Request(f"{URL}/history", method="DELETE")
                with _urlopen(get_json_del) as resp:
                    print("✓ History cleared.\n")
            except Exception as e:
                print(f"Error clearing history: {e}\n")
            continue
        if prompt.lower() == "/config":
            try:
                print(json.dumps(get_json("/health"), indent=2))
            except Exception as e:
                print(f"Error: {e}")
            print()
            continue
        try:
            print("\n[agent thinking / running tools...]")
            res = post_chat(prompt, module=module, max_new_tokens=tokens, enable_tools=enable_tools)
            print()
            print_response(res, prompt, module)
            print()
        except Exception as e:
            print(f"Error: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="Client for local LLM agent server.")
    parser.add_argument("message", nargs="?", help="prompt to send to the server")
    parser.add_argument("-i", "--interactive", action="store_true", help="start interactive terminal chat session")
    parser.add_argument("--module", help="pre-processing module to apply (see --list)")
    parser.add_argument("--tokens", type=int, default=512, help="max_new_tokens (default 512)")
    parser.add_argument("--no-tools", action="store_true", help="disable terminal/file tools")
    parser.add_argument("--list", action="store_true", help="list server status, backend, and tools")
    parser.add_argument("--history", action="store_true", help="show saved chat history from history.db")
    parser.add_argument("--sessions", action="store_true", help="list chat sessions")
    parser.add_argument("--agent-memory", action="store_true", help="show saved conversations with Antigravity from history.db")
    args = parser.parse_args()

    if args.list:
        try:
            print(f"API: {URL}")
            print(json.dumps(get_json("/health"), indent=2))
        except Exception:
            try:
                print(json.dumps(get_json("/modules"), indent=2))
            except Exception as e:
                print(f"Error: {e}\nIs the server running? Start it with: python ai_server.py")
        return

    if args.history:
        print_history()
        return

    if args.sessions:
        print_sessions()
        return

    if args.agent_memory:
        print_agent_memory()
        return

    if args.interactive or not args.message:
        interactive_chat(args.module, args.tokens, enable_tools=not args.no_tools)
        return

    try:
        result = post_chat(args.message, args.module, args.tokens, enable_tools=not args.no_tools)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print(f"Is the server running? Tried: {URL}", file=sys.stderr)
        print("Start it with: python ai_server.py [--ssl]", file=sys.stderr)
        sys.exit(1)

    print_response(result, args.message, args.module)


if __name__ == "__main__":
    main()
