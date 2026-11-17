# Fix Log — mystatic project

## Status: ✅ Fixed (2026-11-15)

---

## Fix #1: SSL client connection refused
**Problem:** `python client.py --module math_utils "What is 1 + 1?"` failed with
`Error: <urlopen error [Errno 111] Connection refused>` when `ai_server.py` was
running with `--ssl` (listening on `https://localhost:8444` instead of `http://localhost:8000`).

**Root cause:** `client.py` was hardcoded to `http://localhost:8000` — it never
tried the SSL port.

**Fix applied:**
- `client.py` now **auto-detects** the API: probes plain `:8000` first, then
  SSL `:8444`, picks whichever answers.
- Reads port numbers from `config.json` so they stay in sync.
- Handles self-signed certs (skips verification for localhost).
- Added `--history` and `--sessions` CLI flags.
- Added interactive commands: `/history`, `/sessions`, `/clear`, `/config`.

---

## Fix #2: Missing `config.json`
**Added:** `/var/www/html/python/mystatic/config.json`

Central config for the whole project. All scripts load it:
- `ai_server.py` — ports, model, backend, paths, CORS, history DB, agent limits
- `client.py` — API ports for auto-detection
- Settings can still be overridden by environment variables (env > config > defaults).

---

## Fix #3: `chat_history.db` → `history.db`
**Problem:** DB file was named `chat_history.db`; user wanted `history.db` with
full session tracking.

**Fix applied:**
- Migrated all 100 existing messages into `history.db`.
- Added `sessions` table (id, started_at, ended_at, title, summary).
- Added `session_id` foreign key on `messages` table.
- Each `ai_server.py` run creates a new session automatically.
- New endpoints: `GET /sessions`, `GET /history?session_id=N`.
- `serve_https.py` proxy now forwards `/sessions` too.
- Web UI updated to reference `history.db`.
- Old `chat_history.db` kept as backup.

---

## Fix #4: `serve_https.py` missing `DELETE` proxy
**Problem:** The web UI's "🗑 clear" button sends `DELETE /history` through
the reverse proxy, but `serve_https.py` had no `do_DELETE` handler — the
request silently failed or 404'd.

**Fix applied:** Added `do_DELETE` method to `RouterHandler`.
Added `/sessions` to `PROXY_PATHS`.

---

## Quick-start commands

```bash
# Start the AI API server (plain HTTP — recommended, proxy handles TLS):
cd /var/www/html/python/mystatic
python ai_server.py

# OR with SSL directly:
python ai_server.py --ssl

# Start the HTTPS web server (serves page + proxies API):
python serve_https.py --dir www

# Terminal client (auto-detects plain or SSL):
python client.py -i                           # interactive chat
python client.py "What time is it?"           # one-shot
python client.py --module math_utils "1+1"    # with module
python client.py --list                       # server status
python client.py --history                    # view history
python client.py --sessions                   # view sessions

# URLs:
# Local:  https://localhost:8443
# LAN:    https://192.168.100.4:8443
```

---

## Files changed
| File | Change |
|------|--------|
| `config.json` | **NEW** — central project configuration |
| `history.db` | **NEW** — migrated from `chat_history.db` + sessions table |
| `ai_server.py` | Loads `config.json`, uses `history.db`, sessions support, new `/sessions` endpoint |
| `client.py` | Auto-detect plain/SSL API, self-signed cert support, `--history`/`--sessions` flags |
| `serve_https.py` | Added `do_DELETE` handler, added `/sessions` to proxy paths |
| `www/index.html` | Updated DB name references to `history.db` |
| `fix.md` | This file — updated with all fixes |
