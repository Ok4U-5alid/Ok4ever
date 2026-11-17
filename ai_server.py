#!/usr/bin/env python3
"""Local LLM server with pluggable modules.

Backends (auto-detected, override with AI_BACKEND=ollama|transformers):
    ollama       - talks to a local Ollama daemon (recommended: small RAM footprint)
    transformers - classic HuggingFace transformers pipeline (needs lots of RAM)

Endpoints:
    POST /chat     {"message": str, "module": str|None, "max_new_tokens": int|None}
    GET  /modules  list of available modules
    GET  /health   backend + model info

Modules live in ./modules/ and must expose:
    def process(text: str) -> str
"""

import importlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ------------------------------------------------------------------
# Config — loads from config.json, env-vars override, sane defaults
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

def _load_config() -> dict:
    """Load config.json if it exists; return empty dict otherwise."""
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[ai_server] WARNING: could not parse config.json: {exc}")
    return {}

CFG = _load_config()
_ai = CFG.get("ai", {})
_ollama = _ai.get("ollama", {})
_hf = _ai.get("transformers", {})
_agent = CFG.get("agent", {})
_hist = CFG.get("history", {})
_paths = CFG.get("paths", {})

MODULES_DIR = BASE_DIR / _paths.get("modules_dir", "modules")
SKILLS_DIR = BASE_DIR / _paths.get("skills_dir", "skills")
OLLAMA_URL = os.environ.get("OLLAMA_URL", _ollama.get("url", "http://localhost:11434"))
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", _ollama.get("model", "llama3.2:3b"))
HF_MODEL_NAME = os.environ.get("HF_MODEL", _hf.get("model", "meta-llama/Meta-Llama-3-8B-Instruct"))
BACKEND = os.environ.get("AI_BACKEND", _ai.get("backend", "auto"))    # auto | ollama | transformers

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ------------------------------------------------------------------
# Chat history persistence (SQLite, stdlib only) → history.db
# ------------------------------------------------------------------
DB_PATH = str(BASE_DIR / _hist.get("db_file", "history.db"))
_db_lock = threading.Lock()

_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        title TEXT,
        summary TEXT
    )
""")
_db.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        role TEXT NOT NULL,             -- "user" | "assistant"
        module TEXT,                    -- module used to pre-process, if any
        content TEXT NOT NULL,
        session_id INTEGER REFERENCES sessions(id)
    )
""")
_db.commit()

# Keep a running session_id for this server run
_current_session_id: Optional[int] = None

def _ensure_session() -> int:
    """Return the current session id, creating one on first call."""
    global _current_session_id
    if _current_session_id is None:
        with _db_lock:
            cur = _db.execute(
                "INSERT INTO sessions (started_at, title) VALUES (?, ?)",
                (_now(), "Chat Session"),
            )
            _db.commit()
            _current_session_id = cur.lastrowid
    return _current_session_id

# ------------------------------------------------------------------
# Backend detection & generation
# ------------------------------------------------------------------
_ollama_ok: Optional[bool] = None

def ollama_available(force: bool = False) -> bool:
    global _ollama_ok
    if _ollama_ok is None or force:
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/version", timeout=3) as r:
                json.loads(r.read())
            _ollama_ok = True
        except Exception:
            _ollama_ok = False
    return _ollama_ok

def detect_backend() -> str:
    if BACKEND != "auto":
        return BACKEND
    return "ollama" if ollama_available() else "transformers"

# ------------------------------------------------------------------
# Agent Tools (Ollama Function Calling)
# ------------------------------------------------------------------
MAX_TOOL_STEPS = int(os.environ.get("MAX_TOOL_STEPS", str(_agent.get("max_tool_steps", 8))))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command in the terminal and return stdout, stderr, and returncode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run, e.g. 'ls -la' or 'python3 check_ports.py'"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file on disk (such as a script or a SKILL.md playbook).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read, e.g. 'skills/check_ports/SKILL.md'"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or completely overwrite an existing file with the provided content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to create or overwrite"},
                    "content": {"type": "string", "description": "The full text content to write to the file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact target text substring inside an existing file with replacement text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to modify"},
                    "target": {"type": "string", "description": "Exact text substring to search for and replace"},
                    "replacement": {"type": "string", "description": "New replacement text"},
                },
                "required": ["path", "target", "replacement"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories in a directory path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (defaults to .)"}
                },
            },
        },
    },
]

def resolve_path(p_str: str) -> Path:
    """Resolve file/directory paths across workspace, skills, and ~/.claude/skills."""
    clean = p_str.strip("'\" ")
    p = Path(os.path.expanduser(clean))
    if p.is_absolute():
        return p.resolve()
    cand = (BASE_DIR / p).resolve()
    if cand.exists():
        return cand
    skills_cand = (SKILLS_DIR / p).resolve()
    if skills_cand.exists():
        return skills_cand
    claude_cand = (Path(os.path.expanduser("~/.claude/skills")) / p).resolve()
    if claude_cand.exists():
        return claude_cand
    return cand

def dispatch_tool(name: str, args: dict) -> str:
    """Execute the requested tool and return a string result for the LLM."""
    try:
        if name == "run_command":
            cmd = args.get("command") or args.get("cmd") or ""
            if not cmd:
                return "[Error: command was empty]"
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = res.stdout
            if res.stderr:
                out += f"\n[stderr]\n{res.stderr}"
            if not out.strip():
                out = f"[Command completed with return code {res.returncode}]"
            return out[:4000]

        elif name == "read_file":
            fp = args.get("path") or args.get("filepath") or args.get("file") or args.get("filename") or ""
            if not fp:
                return "[Error: path was empty]"
            p = resolve_path(fp)
            if not p.is_file():
                return f"[Error: File '{fp}' not found at {p}]"
            return p.read_text(encoding="utf-8", errors="replace")[:6000]

        elif name == "write_file":
            fp = args.get("path") or args.get("filepath") or args.get("file") or args.get("filename") or ""
            content = args.get("content") or args.get("text") or args.get("data") or ""
            if not fp:
                return "[Error: path was empty]"
            p = resolve_path(fp)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"[Success: Wrote {len(content)} bytes to {fp}]"

        elif name == "edit_file":
            fp = args.get("path") or args.get("filepath") or args.get("file") or args.get("filename") or ""
            target = args.get("target") or args.get("old_string") or args.get("find") or ""
            replacement = args.get("replacement") or args.get("new_string") or args.get("replace") or ""
            if not fp:
                return "[Error: path was empty]"
            p = resolve_path(fp)
            if not p.is_file():
                return f"[Error: File '{fp}' not found at {p}]"
            data = p.read_text(encoding="utf-8")
            if target not in data:
                return f"[Error: Target string not found in '{fp}']"
            count = data.count(target)
            new_data = data.replace(target, replacement)
            p.write_text(new_data, encoding="utf-8")
            return f"[Success: Replaced {count} occurrence(s) in {fp}]"

        elif name == "list_directory":
            dp = args.get("path") or args.get("dir") or args.get("directory") or "."
            p = resolve_path(dp)
            if not p.is_dir():
                return f"[Error: Directory '{dp}' not found at {p}]"
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            items = [f"{e.name}/" if e.is_dir() else e.name for e in entries]
            return "\n".join(items) if items else "[Directory is empty]"

        # Fallback: if model called a skill directly or passed a command in args
        cmd = args.get("command") or args.get("cmd")
        if cmd:
            return dispatch_tool("run_command", {"command": cmd})

        for s in list_skills():
            if s.get("name") == name and s.get("command"):
                return dispatch_tool("run_command", {"command": s["command"]})

        return f"[Error: Unknown tool '{name}']"
    except subprocess.TimeoutExpired:
        return "[Error: Command timed out after 60 seconds]"
    except Exception as e:
        return f"[Tool execution error: {e}]"


def _extract_text_tool_calls(content: str) -> list[dict]:
    """Detect JSON function calls that smaller models emit as text instead of structured tool_calls."""
    if not content or "{" not in content:
        return []
    import re, time
    matches = re.findall(r'(\{(?:[^{}]|(?:\{[^{}]*\}))*\})', content, re.DOTALL)
    calls = []
    for m in matches:
        try:
            data = json.loads(m.strip())
            if isinstance(data, dict) and "name" in data:
                fn_name = data["name"]
                args = data.get("arguments") or data.get("parameters") or data.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                if not isinstance(args, dict):
                    args = {}
                calls.append({
                    "id": f"text_call_{int(time.time()*1000)}",
                    "function": {
                        "name": fn_name,
                        "arguments": args
                    }
                })
        except Exception:
            continue
    return calls

def generate(messages: List[dict], max_new_tokens: int, enable_tools: bool = True) -> tuple[str, list]:
    """Send chat messages to active backend. If tools are enabled and backend is Ollama, runs agent loop."""
    backend = detect_backend()
    if backend == "ollama":
        if not ollama_available():
            raise RuntimeError(
                f"Ollama not reachable at {OLLAMA_URL}. "
                "Install it (curl -fsSL https://ollama.com/install.sh | sh) "
                f"and pull the model: ollama pull {OLLAMA_MODEL}"
            )

        current_messages = [dict(m) for m in messages]
        tool_history = []

        if not enable_tools:
            payload = json.dumps({
                "model": OLLAMA_MODEL,
                "messages": current_messages,
                "stream": False,
                "options": {"num_predict": max_new_tokens, "temperature": 0.7, "num_ctx": 4096},
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                text = json.loads(resp.read().decode())["message"].get("content", "").strip()
                return text, []

        # Tool calling loop
        for step in range(MAX_TOOL_STEPS):
            payload = json.dumps({
                "model": OLLAMA_MODEL,
                "messages": current_messages,
                "tools": TOOLS,
                "stream": False,
                "options": {"num_predict": max_new_tokens, "temperature": 0.2, "num_ctx": 4096},
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/chat", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                msg = json.loads(resp.read().decode())["message"]

            current_messages.append(msg)
            tool_calls = msg.get("tool_calls", [])
            content_text = msg.get("content") or ""
            if not tool_calls and content_text:
                fallback_calls = _extract_text_tool_calls(content_text)
                if fallback_calls:
                    tool_calls = fallback_calls

            if not tool_calls:
                return content_text.strip(), tool_history

            for tc in tool_calls:
                call_id = tc.get("id")
                func = tc.get("function", {})
                func_name = func.get("name")
                func_args = func.get("arguments", {})
                if isinstance(func_args, str):
                    try:
                        func_args = json.loads(func_args)
                    except Exception:
                        func_args = {}

                result = dispatch_tool(func_name, func_args)
                tool_history.append({
                    "name": func_name,
                    "args": func_args,
                    "result": result
                })
                tool_msg = {"role": "tool", "content": str(result)}
                if call_id:
                    tool_msg["tool_call_id"] = call_id
                current_messages.append(tool_msg)

        # Reached MAX_TOOL_STEPS: request final summary
        summary_payload = json.dumps({
            "model": OLLAMA_MODEL,
            "messages": current_messages + [{"role": "user", "content": "Please summarize the actions taken and the final status."}],
            "stream": False,
            "options": {"num_predict": max_new_tokens, "temperature": 0.2, "num_ctx": 4096},
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=summary_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            final_text = json.loads(resp.read().decode())["message"].get("content", "").strip()
            return final_text or "Tool actions completed.", tool_history

    # transformers backend
    from transformers import pipeline
    if not hasattr(generate, "_pipe"):
        generate._pipe = pipeline(
            "text-generation",
            model=HF_MODEL_NAME,
            device_map="auto",
            torch_dtype="auto",
        )
    pipe = generate._pipe
    prompt = pipe.tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    output = pipe(prompt, max_new_tokens=max_new_tokens)[0]["generated_text"]
    text = output[len(prompt):].strip() if output.startswith(prompt) else output.strip()
    return text, []

# ------------------------------------------------------------------
# Request schema
# ------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    module: Optional[str] = None
    max_new_tokens: Optional[int] = 512
    enable_tools: Optional[bool] = True

# ------------------------------------------------------------------
# User-defined modules (Python files in ./modules/)
# ------------------------------------------------------------------
loaded_modules: Dict[str, Callable] = {}

def list_modules() -> List[str]:
    if not MODULES_DIR.is_dir():
        return []
    return sorted(f.stem for f in MODULES_DIR.glob("*.py") if f.stem != "__init__")

# ------------------------------------------------------------------
# Skills Discovery (Markdown playbooks in ./skills/<name>/SKILL.md)
# ------------------------------------------------------------------
def list_skills() -> List[dict]:
    """Scan skills/ directory and parse frontmatter metadata."""
    if not SKILLS_DIR.is_dir():
        return []
    skills = []
    for sdir in sorted(SKILLS_DIR.iterdir()):
        skill_md = sdir / "SKILL.md"
        if sdir.is_dir() and skill_md.is_file():
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            meta = {
                "name": sdir.name,
                "description": "",
                "command": "",
                "path": str(skill_md.relative_to(BASE_DIR)),
            }
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    for line in parts[1].splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip().lower()
                            if k in meta:
                                meta[k] = v.strip()
            if not meta["description"]:
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "---")):
                        meta["description"] = line
                        break
            skills.append(meta)
    return skills

def load_skills_summary() -> str:
    """Build a concise catalog of skills to inject into the system prompt."""
    skills = list_skills()
    if not skills:
        return ""
    lines = [
        "Available Skills Catalog (run read_file on any path below to inspect its full playbook & techniques):"
    ]
    for s in skills:
        desc = s.get("description", "")
        if len(desc) > 90:
            desc = desc[:87] + "..."
        cmd_str = f" [cmd: `{s['command']}`]" if s.get("command") else ""
        lines.append(f"- {s['name']}: {desc}{cmd_str} ({s['path']})")
    return "\n".join(lines)

def load_module(name: str) -> Callable:
    """Load a module by name; name is sanitized to block path traversal."""
    if name in loaded_modules:
        return loaded_modules[name]
    if "/" in name or "\\" in name or ".." in name or not name.replace("_", "").isalnum():
        raise ImportError(f"Invalid module name: {name!r}")
    try:
        mod = importlib.import_module(f"modules.{name}")
        importlib.reload(mod)            # pick up edits without server restart
        loaded_modules[name] = mod
        return mod
    except Exception as exc:
        raise ImportError(f"Module {name!r} could not be loaded: {exc}")

# ------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------
app = FastAPI(title="Local LLM with Module Extension")

# The site is served by serve_https.py on 8443 while this API listens on
# 8000/8444 -> different ports = cross-origin, so the browser needs CORS.
_cors_origins = CFG.get("cors", {}).get("allowed_origins", [
    "https://localhost:8443", "http://localhost:8443",
    "https://127.0.0.1:8443", "http://127.0.0.1:8443",
])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    backend = detect_backend()
    print(f"[ai_server] config={'config.json' if CONFIG_FILE.is_file() else 'defaults (no config.json)'}")
    print(f"[ai_server] backend={backend}")
    print(f"[ai_server] history_db={DB_PATH}")
    if backend == "ollama":
        if ollama_available():
            print(f"[ai_server] ollama up at {OLLAMA_URL}, model={OLLAMA_MODEL}")
        else:
            print(f"[ai_server] WARNING: ollama not reachable at {OLLAMA_URL}")
    else:
        print(f"[ai_server] transformers model={HF_MODEL_NAME} (lazy-loaded on first /chat)")

@app.get("/health")
def health():
    backend = detect_backend()
    return {
        "status": "ok",
        "backend": backend,
        "model": OLLAMA_MODEL if backend == "ollama" else HF_MODEL_NAME,
        "ollama_reachable": ollama_available() if backend == "ollama" else None,
        "tools_supported": backend == "ollama",
        "available_tools": [t["function"]["name"] for t in TOOLS] if backend == "ollama" else [],
        "modules": list_modules(),
        "skills": list_skills(),
    }

@app.get("/modules")
def modules():
    return {"modules": list_modules()}

@app.get("/skills")
def skills():
    return {"skills": list_skills()}

@app.post("/chat")
async def chat(req: ChatRequest):
    user_message = req.message

    # Run pre-processing module first (if requested)
    if req.module:
        try:
            mod = load_module(req.module)
            if not hasattr(mod, "process"):
                raise AttributeError(f"Module {req.module!r} has no 'process' function")
            user_message = mod.process(user_message)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    tools_on = bool(req.enable_tools)
    if tools_on:
        skills_summary = load_skills_summary()
        skills_block = f"\n\n{skills_summary}\nWhen a user request matches one of the skills above, refer to its instructions and run the corresponding commands." if skills_summary else ""
        system_content = (
            "You are an expert AI assistant with local tool access to inspect, run, and modify scripts. "
            "You have tools: run_command (terminal execution), read_file (read file), "
            "write_file (create/overwrite file), edit_file (replace string in file), and list_directory. "
            "When asked to test scripts, check system status, or create/edit code, use your tools to perform the actions "
            "and then clearly summarize what you did and the results.\n"
            "If the user simply says '?' or asks for help, introduce yourself, list key capabilities, and suggest 3-4 example commands they can try. "
            "Never output raw JSON function call mock text; always execute tools directly."
            f"{skills_block}"
        )
    else:
        system_content = "You are a helpful assistant."

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]
    try:
        answer, tools_used = generate(messages, req.max_new_tokens or 512, enable_tools=tools_on)
        _save_history(req.module, user_message, answer)
        return {
            "response": answer,
            "processed_message": user_message,
            "tools_used": tools_used,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------------------------------------------------------
# History endpoints
# ------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def _save_history(module: Optional[str], user_message: str, answer: str):
    sid = _ensure_session()
    with _db_lock:
        _db.execute(
            "INSERT INTO messages (ts, role, module, content, session_id) VALUES (?, 'user', ?, ?, ?)",
            (_now(), module, user_message, sid),
        )
        _db.execute(
            "INSERT INTO messages (ts, role, module, content, session_id) VALUES (?, 'assistant', NULL, ?, ?)",
            (_now(), answer, sid),
        )
        _db.commit()

@app.get("/history")
def history(limit: int = 500, offset: int = 0, session_id: int = None):
    _max = _hist.get("max_query_limit", 1000)
    _default = _hist.get("default_query_limit", 500)
    with _db_lock:
        if session_id:
            rows = _db.execute(
                "SELECT id, ts, role, module, content, session_id FROM messages "
                "WHERE session_id = ? ORDER BY id LIMIT ? OFFSET ?",
                (session_id, max(1, min(limit, _max)), max(0, offset)),
            ).fetchall()
        else:
            rows = _db.execute(
                "SELECT id, ts, role, module, content, session_id FROM messages "
                "ORDER BY id LIMIT ? OFFSET ?",
                (max(1, min(limit, _max)), max(0, offset)),
            ).fetchall()
    return {"messages": [
        {"id": r[0], "ts": r[1], "role": r[2], "module": r[3], "content": r[4], "session_id": r[5]}
        for r in rows
    ]}

@app.get("/sessions")
def sessions():
    with _db_lock:
        rows = _db.execute(
            "SELECT id, started_at, ended_at, title, summary FROM sessions ORDER BY id DESC"
        ).fetchall()
    return {"sessions": [
        {"id": r[0], "started_at": r[1], "ended_at": r[2], "title": r[3], "summary": r[4]}
        for r in rows
    ]}

@app.delete("/history")
def clear_history():
    with _db_lock:
        _db.execute("DELETE FROM messages")
        _db.commit()
    return {"cleared": True}

# ------------------------------------------------------------------
# Run
# ------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    _srv = CFG.get("server", {})
    _ssl_cfg = _srv.get("ssl", {})
    _default_host = _srv.get("host", "0.0.0.0")

    parser = argparse.ArgumentParser(description="Local LLM server with modules.")
    parser.add_argument("--port", type=int, default=None,
                        help=f"default: {_srv.get('api_port', 8000)} plain, {_srv.get('api_ssl_port', 8444)} with --ssl")
    parser.add_argument("--host", default=_default_host)
    parser.add_argument("--backend", choices=["auto", "ollama", "transformers"], default="auto")
    parser.add_argument("--model", help="model name (ollama tag or HF repo id)")
    parser.add_argument("--ssl", action="store_true",
                        default=_ssl_cfg.get("enabled", False),
                        help="serve over HTTPS using ./server.crt + ./server.key")
    args = parser.parse_args()

    if args.backend != "auto":
        os.environ["AI_BACKEND"] = args.backend
    if args.model:
        # Pre-decide which env var the model name lands in
        if args.model.startswith(("hf/", "meta-llama/", "Qwen/", "microsoft/")):
            os.environ["OLLAMA_MODEL"] = args.model.removeprefix("hf/")
            os.environ["HF_MODEL"] = args.model
            os.environ["AI_BACKEND"] = os.environ.get("AI_BACKEND", "transformers")
        else:
            os.environ["OLLAMA_MODEL"] = args.model

    ssl_kwargs = {}
    if args.ssl:
        ssl_kwargs = {
            "ssl_certfile": str(BASE_DIR / _ssl_cfg.get("cert_file", "server.crt")),
            "ssl_keyfile": str(BASE_DIR / _ssl_cfg.get("key_file", "server.key")),
        }
    port = args.port or (_srv.get("api_ssl_port", 8444) if args.ssl else _srv.get("api_port", 8000))
    print(f"[ai_server] listening on {args.host}:{port}{' (https)' if args.ssl else ''}")

    uvicorn.run("ai_server:app", host=args.host, port=port, reload=False,
                **ssl_kwargs)
