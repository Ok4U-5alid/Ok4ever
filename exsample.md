# mystatic Project — Complete Guide & Script Reference

Welcome to the **mystatic** project! This repository is a self-hosted, offline-capable AI environment that integrates a local Large Language Model (Ollama or Transformers), an autonomous tool-calling agent, a modern HTTPS web chat interface, an interactive terminal client, and an advanced network defense and cybersecurity toolkit.

---

## Table of Contents
1. [Project Overview & Architecture](#project-overview--architecture)
2. [Prerequisites & Quick Setup](#prerequisites--quick-setup)
3. [Running the System (Server Setup)](#running-the-system-server-setup)
4. [Using the Web Chat from Your Browser](#using-the-web-chat-from-your-browser)
5. [Using the Terminal Client (`client.py`)](#using-the-terminal-client-clientpy)
6. [Complete Scripts Reference](#complete-scripts-reference)
   - [Core AI & Server Infrastructure](#core-ai--server-infrastructure)
   - [Network Defense & Firewall Scripts](#network-defense--firewall-scripts)
   - [Pre-Processing Modules (`modules/`)](#pre-processing-modules-modules)
   - [Skills & Security Playbooks (`skills/`)](#skills--security-playbooks-skills)
7. [How to Control Scripts Through the AI Agent](#how-to-control-scripts-through-the-ai-agent)
8. [Configuration & Customization (`config.json`)](#configuration--customization-configjson)
9. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## 1. Project Overview & Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │                      User Interfaces                   │
                    │                                                        │
                    │  [Web Browser] (HTTPS :8443)    [Terminal Client]      │
                    │   - Voice / Mic & TTS            (client.py)           │
                    │   - File Drag & Drop            - Interactive mode     │
                    │   - Module Selector             - History & Sessions   │
                    └───────────────┬────────────────────────┬───────────────┘
                                    │                        │
                                    ▼                        ▼
     ┌──────────────────────────────────────────┐            │
     │   Static & Reverse Proxy Server          │            │
     │   (serve_https.py on port 8443)          │            │
     │   - Serves www/ directory (index.html)   │            │
     │   - Proxies /chat, /history, /sessions   │            │
     └──────────────────────┬───────────────────┘            │
                            │                                │
                            ▼                                ▼
     ┌───────────────────────────────────────────────────────────────────────┐
     │   FastAPI Local AI Server (ai_server.py on :8000 or SSL :8444)        │
     │                                                                       │
     │   ├── History & Sessions Database: history.db                         │
     │   ├── Pre-processing Modules: modules/*.py                            │
     │   ├── Dynamic Skills Index: skills/*/SKILL.md                         │
     │   ├── Autonomous Agent Tools:                                         │
     │   │   run_command | read_file | write_file | edit_file | list_dir     │
     │   └── Model Engine: Ollama daemon (llama3.2:3b) or Transformers       │
     └───────────────────────────────────────────────────────────────────────┘
```

The system is organized into modular components:
- **`config.json`**: Central single source of truth for ports, paths, limits, and model parameters.
- **`ai_server.py`**: The intelligence engine. Exposes REST endpoints (`/chat`, `/health`, `/modules`, `/skills`, `/history`, `/sessions`).
- **`serve_https.py`**: Lightweight HTTPS server and reverse-proxy. Eliminates CORS issues and allows network access (LAN/WiFi) to the Web UI.
- **`client.py`**: Fast terminal CLI with auto-detection of server ports, colorized output, session management, and one-shot execution.
- **`history.db`**: SQLite database storing message history and conversation sessions.
- **`modules/`**: Pluggable Python pre-processors that can transform or enrich input before reaching the AI.
- **`skills/`**: Tactical operational playbooks that the AI agent reads on-demand to execute specialized tasks.
- **`scripts/`**: Standalone network defense, packet sniffing, DoS protection, and diagnostic tools.

---

## 2. Prerequisites & Quick Setup

Make sure your Python environment has the necessary packages installed:

```bash
cd /var/www/html/python/mystatic

# Activate your virtual environment if one is used
source venv/bin/activate    # or run with system python3

# Ensure Ollama is running and has your preferred model pulled:
ollama serve >/dev/null 2>&1 &
ollama pull llama3.2:3b
```

---

## 3. Running the System (Server Setup)

To use the system with either the browser or `client.py`, start the servers.

### Recommended 2-Server Setup (Browser + API)

Open two terminal tabs or run them in the background:

#### Terminal 1: Start the AI Server
```bash
python ai_server.py
```
*Listens on `http://0.0.0.0:8000` (plain HTTP). The reverse proxy handles SSL encryption for the browser.*

*(Optional)* If you want `ai_server.py` to serve TLS directly:
```bash
python ai_server.py --ssl
```
*Listens on `https://0.0.0.0:8444`.*

#### Terminal 2: Start the Web Server & Reverse Proxy
```bash
python serve_https.py --dir www
```
*Listens on `https://0.0.0.0:8443`. It automatically forwards all API requests (`/chat`, `/history`, `/modules`, `/sessions`, `/skills`) to `ai_server.py`.*

---

## 4. Using the Web Chat from Your Browser

### 4.1. Accessing the Web Page

1. Open your web browser (Chrome, Firefox, Brave, Safari, Edge).
2. Navigate to:
   - Local machine: **`https://localhost:8443`**
   - From any device on your LAN (phone, tablet, second PC): **`https://<YOUR-SERVER-IP>:8443`** *(e.g., `https://192.168.100.4:8443`)*

> [!NOTE]
> **Bypassing the Self-Signed Certificate Warning:**
> Because the server uses a private self-signed certificate (`server.crt`), your browser will show a warning: `"Your connection is not private"` or `"Potential Security Risk"`.
> - In Chrome/Brave/Edge: Click **Advanced** &rarr; **Proceed to localhost (unsafe)**.
> - In Firefox: Click **Advanced** &rarr; **Accept the Risk and Continue**.

### 4.2. Browser Features & Controls

| Feature | Where it is | What it does |
| :--- | :--- | :--- |
| **Chat Input** | Bottom text bar | Type your prompt and press **Enter** or click **Send**. |
| **Module Selector** | Bottom-left dropdown | Pick an optional pre-processing module (e.g. `math_utils`, `web_fetch`, `error`). Leave on *"no module"* for normal chat. |
| **File Attachments (📎)** | Bottom paperclip button | Attach one or multiple text/code/log files. You can also **drag and drop** files directly onto the page! |
| **Voice Dictation (🎤)** | Bottom microphone button | Click to record your voice using Web Speech Recognition. If *"auto-send voice"* is checked, sending happens automatically when you pause. |
| **Voice Language** | Top header dropdown | Select the recognition language (`English`, `العربية`, `Français`, `Español`, `Deutsch`). |
| **Speak Replies** | Top header checkbox | When checked, the browser uses Text-To-Speech to read the assistant's answers aloud. |
| **Clear History (🗑)** | Top header button | Deletes conversation records from `history.db` and clears the chat screen. |
| **Chat Log Persistence**| Main window | Automatically loads previous messages on page load. |

---

## 5. Using the Terminal Client (`client.py`)

`client.py` provides complete control over the system directly from your shell. It auto-detects whether `ai_server.py` is listening on plain HTTP (`:8000`) or SSL (`:8444`).

### 5.1. Interactive Chat Mode (`-i`)

Launch an interactive conversation session:
```bash
python client.py -i
```

Inside the interactive session, you have built-in slash commands:
- `/history` &mdash; View saved chat messages from `history.db`.
- `/sessions` &mdash; List past and active chat sessions.
- `/clear` &mdash; Erase stored chat history in `history.db`.
- `/config` &mdash; Show current server status and available tools.
- `exit` or `quit` &mdash; Exit interactive mode.

```
==================================================
  Local Ollama Agent Terminal (ai_server)
  Target: http://localhost:8000 🔓 Plain | Tools: ON
  Type your prompt, or type 'exit' or 'quit' to stop.
  Special commands: /history, /sessions, /clear, /config
==================================================

you> Check the local directory structure
[agent thinking / running tools...]

[Tools Executed: 1]
  (1) list_directory(path='.')
----------------------------------------

Here are the key directories and files in mystatic:
- ai_server.py: API server
- client.py: CLI client
- firewall-nftables.py: Unified firewall
- modules/: Preprocessing modules
- scripts/: Network defense scripts
- skills/: Operational playbooks
```

### 5.2. One-Shot Prompts

Send a single prompt directly from bash:
```bash
python client.py "What is the status of the local network interface?"
```

### 5.3. Using Pre-Processing Modules (`--module`)

Pass your prompt through any module located in `modules/`:
```bash
# Use math_utils to sanitize/preprocess math questions
python client.py --module math_utils "What is (45 * 12) / 3?"

# Use web_fetch to scrape or format a URL
python client.py --module web_fetch "https://example.com summarize content"
```

### 5.4. Controlling Autonomous Agent Tools

By default, the AI agent has tool calling enabled. It can read files, write files, inspect directories, and run terminal commands to solve your requests.

- **To run normal agent mode (with tools):**
  ```bash
  python client.py "Check listening TCP ports and summarize them"
  ```
- **To disable tools (pure LLM reasoning only):**
  ```bash
  python client.py --no-tools "Explain the difference between TCP and UDP"
  ```

### 5.5. Server Diagnostics & Inspection

- **Check backend model, status, and loaded tools:**
  ```bash
  python client.py --list
  ```
- **Display saved message history:**
  ```bash
  python client.py --history
  ```
- **Display conversation sessions:**
  ```bash
  python client.py --sessions
  ```
- **Adjust response length:**
  ```bash
  python client.py --tokens 1024 "Generate a comprehensive iptables to nftables migration plan"
  ```

---

## 6. Complete Scripts Reference

### Core AI & Server Infrastructure

| Script / File | Description | How to run |
| :--- | :--- | :--- |
| **`ai_server.py`** | FastAPI server running the local LLM. Supports tool-calling agent loops, dynamic skills loading, module pre-processing, and SQLite persistence. | `python ai_server.py`<br>`python ai_server.py --ssl` |
| **`serve_https.py`** | Multi-threaded HTTPS static server with built-in reverse proxy forwarding to `ai_server.py`. | `python serve_https.py --dir www` |
| **`client.py`** | Versatile terminal client supporting one-shot prompts, interactive mode, module processing, and history queries. | `python client.py -i`<br>`python client.py "..."`<br>`python client.py --agent-memory` |
| **`save_conversations.py`** | Continuous memory daemon & sync tool saving conversations with Antigravity into `history.db`. | `python save_conversations.py --sync`<br>`python save_conversations.py --watch`<br>`python save_conversations.py --search "keyword"` |
| **`config.json`** | Central configuration file for host, ports, timeouts, CORS origins, and paths. | Edited directly or via env vars. |
| **`history.db`** | SQLite database maintaining tables for `messages` and `sessions`. | Queried via `client.py` or `GET /history`. |
| **`sync_skills.py`** | Synchronizes all skills from `~/.claude/skills/` into `./skills/` as symbolic links. | `python sync_skills.py` |

---

### Network Defense & Firewall Scripts

These scripts provide packet filtering, rate limiting, and defensive countermeasures against malicious traffic.

#### 1. `firewall-nftables.py` (Unified Firewall Engine)
The primary all-in-one network defense program. Replaces legacy `iptables` and `ufw` with atomic `nftables` sets:
- **Dynamic Whitelist**: Discovers gateway, host IP, and ARP neighbors automatically from `ip neigh`.
- **Static Whitelist**: Protects user hardware MACs (e.g. `00:e0:4c:68:05:a0`) and local subnets.
- **Rate-Limiting**: Blocks aggressive traffic floods exceeding packet thresholds.
- **Payload Inspection**: Drops packets attempting to transfer forbidden extensions (`.exe`, `.bat`).
- **Fragmentation Protection**: Detects and drops Tear Drop attack offsets.

```bash
# Launch the interactive management menu:
sudo python firewall-nftables.py

# Launch background packet monitor & auto-defense:
sudo python firewall-nftables.py --monitor

# View current nftables rules & ARP whitelist:
python firewall-nftables.py --status

# Manually ban or unban an IP:
sudo python firewall-nftables.py --block-ip 192.168.1.100
sudo python firewall-nftables.py --unblock-ip 192.168.1.100

# Flush all active rules:
sudo python firewall-nftables.py --flush
```

#### 2. `scripts/interactive_menu.py`
A real-time CLI terminal dashboard with live Scapy sniffing, packet statistics, and on-demand IP/MAC banning through nftables.
```bash
sudo python scripts/interactive_menu.py
```

#### 3. `scripts/packet.py`
Standalone anti-DoS rate limiter. Continuously monitors incoming packet rates per IP and drops attackers with temporary timeout bans.
```bash
sudo python scripts/packet.py
```

#### 4. `scripts/router.py`
Promiscuous mode router and forwarding defender. Monitors packets across network interfaces and blocks illegal fragmentation and flood attempts on the forwarding chain.
```bash
sudo python scripts/router.py
```

#### 5. `scripts/route.py`
Specialized Tear Drop and illegal fragment offset detector with automatic ARP peer whitelisting.
```bash
sudo python scripts/route.py
```

#### 6. `scripts/snifF.py`
Interactive packet sniffer with colored Scapy output. Shows live traffic details across ARP, DHCPv6, ICMP, TCP, and UDP.
```bash
sudo python scripts/snifF.py -i eth0
```

#### 7. `scripts/error.py`
Traffic inspector that performs deep packet inspection (DPI) for malicious payload signatures and executes auto-expiring bans.
```bash
sudo python scripts/error.py
```

#### 8. Shell Scripts (`scripts/`)
- **`scripts/ip-mac-allow-block-nft.sh`**: Quick bash utility to ban or unban specific IPs and MAC addresses in nftables tables.
- **`scripts/mytargets-ip-nftable.sh`**: Batch script to load predefined lists of target IPs into nftables filtering sets.

#### 9. Diagnostic Utilities
- **`check_ports.py`**: Prints system listening ports, process names, and PIDs.
- **`process_check.py` / `pross.py`**: Diagnostic tools for process inspection and resource tracking.

---

### Pre-Processing Modules (`modules/`)

Modules in `modules/` expose a standard function:
```python
def process(text: str) -> str:
    ...
```
When invoked from the Web UI dropdown or via `client.py --module <name>`, the server runs `process()` before sending the text to the model.

- **`math_utils.py`**: Sanitizes and evaluates or structures arithmetic expressions.
- **`web_fetch.py`**: Parses URLs and extracts web content for context injection.
- **`net_check.py` / `net_check1.py`**: Gathers local network configuration and interface statistics to inject into the prompt.
- **`firewall_nftables.py` (module)**: Formats firewall queries and command instructions for the AI.

---

### Skills & Security Playbooks (`skills/`)

The `./skills/` directory contains over 40 structured playbooks (synced from `~/.claude/skills/`). Each skill contains a `SKILL.md` file describing tools, parameters, and workflows:
- **`nftables_firewall`**: Rules, sets, and commands for configuring network protection.
- **`check_ports`**: Methodology for inspecting open sockets and identifying rogue listening services.
- **`sys_health`**: Diagnostics for CPU, RAM memory, and disk health.
- **`code_test`**: Script validation and syntax checking workflows.
- **`web-pentest`**, **`recon-osint`**, **`network-attack`**, **`privesc-linux`**: Security auditing, reconnaissance, and penetration testing methodologies.

`ai_server.py` automatically indexes all skills and provides the summary to the model so it can reference the correct playbook during tasks.

---

## 7. How to Control Scripts Through the AI Agent

Because the AI agent in `ai_server.py` has autonomous tool access (`run_command`, `read_file`, `write_file`, `edit_file`, `list_directory`), you can ask the agent in plain language to inspect, test, or execute any script in the repository.

### Practical Examples via `client.py`

#### 1. Check open ports using `check_ports.py`:
```bash
python client.py "Run check_ports.py and tell me if port 8000 and 8443 are listening"
```
*What happens:* The AI uses `run_command` to execute `python3 check_ports.py`, parses the output, and returns a clear summary.

#### 2. Check firewall rules using `firewall-nftables.py`:
```bash
python client.py "Check the current nftables status using firewall-nftables.py"
```

#### 3. Read and explain a defense script:
```bash
python client.py "Read scripts/route.py and explain how it defends against Tear Drop attacks"
```
*What happens:* The AI calls `read_file(path='scripts/route.py')`, examines the fragmentation detection logic, and explains it in detail.

#### 4. Run packet inspection:
```bash
python client.py "Run scripts/packet.py with a short test or describe its whitelist mechanism"
```

### Practical Examples via the Browser

1. In the text box at `https://localhost:8443`, type:
   > *"Inspect `config.json` and tell me what the configured SSL ports and database path are."*
2. The agent reads `config.json` and outputs:
   - Web Port: `8443`
   - API Port: `8000` (plain) / `8444` (SSL)
   - DB File: `history.db`
3. Type:
   > *"List all scripts in the scripts/ directory and summarize what packet.py and snifF.py do."*

---

## 8. Configuration & Customization (`config.json`)

The entire system behavior can be customized by editing `config.json`:

```json
{
  "project": {
    "name": "mystatic",
    "version": "1.2.0"
  },
  "server": {
    "host": "0.0.0.0",
    "api_port": 8000,
    "api_ssl_port": 8444,
    "web_port": 8443,
    "ssl": {
      "enabled": true,
      "cert_file": "server.crt",
      "key_file": "server.key"
    }
  },
  "ai": {
    "backend": "auto",
    "ollama": {
      "url": "http://localhost:11434",
      "model": "llama3.2:3b",
      "options": {
        "num_predict": 512,
        "temperature": 0.7,
        "num_ctx": 4096
      }
    }
  },
  "agent": {
    "max_tool_steps": 8,
    "tool_timeout_seconds": 60,
    "enable_tools_default": true
  },
  "history": {
    "db_file": "history.db",
    "max_query_limit": 1000
  }
}
```

### Environment Variable Overrides
Any configuration setting can be overridden on the fly:
```bash
# Switch to another Ollama model:
OLLAMA_MODEL="qwen2.5-coder:7b" python ai_server.py

# Switch Ollama host:
OLLAMA_URL="http://192.168.100.10:11434" python ai_server.py

# Point client.py to a custom remote API:
AI_API_URL="http://192.168.100.4:8000" python client.py -i
```

---

## 9. Troubleshooting & FAQ

### Q1: `client.py` says `Connection refused`
- **Cause:** `ai_server.py` is not running.
- **Solution:** Start the server in another terminal: `python ai_server.py`.

### Q2: Browser shows `API upstream unreachable: 502`
- **Cause:** `serve_https.py` is running, but `ai_server.py` has not been started.
- **Solution:** Make sure `python ai_server.py` is running in the background.

### Q3: Audio / Microphone button doesn't work in the browser
- **Cause:** Web Speech API requires a secure context (**HTTPS** or **localhost**).
- **Solution:** Always access the web interface via `https://localhost:8443` or `https://<LAN-IP>:8443` rather than plain `http://`.

### Q4: Network scripts report `Permission denied`
- **Cause:** Raw socket sniffing (`scapy`) and modifying firewall rules (`nftables`) require root privileges.
- **Solution:** Run packet defense scripts with `sudo`:
  ```bash
  sudo python firewall-nftables.py
  sudo python scripts/packet.py
  ```

---

*Generated for the mystatic project workspace.*
