# Local AI Agent Plan & Implementation Guide

## Overview
Upgraded `ai_server.py` from a simple text-only LLM wrapper into an **autonomous agent** capable of:
1. Executing terminal / bash commands (`run_command`).
2. Inspecting directories (`list_directory`).
3. Reading files (`read_file`).
4. Writing / creating files (`write_file`).
5. Modifying existing code / scripts (`edit_file`).

---

## What Changed

### 1. `ai_server.py`
- Integrated Ollama native **Function Calling / Tool Calling**.
- Added tool definitions:
  - `run_command(command)`: runs bash command in workspace, returns stdout & stderr with timeout protection.
  - `read_file(filepath)`: reads file text.
  - `write_file(filepath, content)`: creates or replaces scripts.
  - `edit_file(filepath, target, replacement)`: finds and replaces code snippets.
  - `list_directory(path)`: lists directory entries.
- Added multi-turn agent execution loop: the model decides which tools to call, inspects outputs, and iterates until the task is complete.
- Added `tools_used` tracking to the `/chat` response and `/health` metadata.

### 2. `client.py`
- Added **Interactive Terminal Chat** mode:
  ```bash
  python client.py -i
  ```
- Displays live feedback when tools are triggered (`[Tools Executed: run_command, edit_file...]`).
- Added `--no-tools` option if plain text chat is preferred.
- Updated default token generation limit to 512.

### 3. Web UI (`www/index.html`)
- Displays tool execution badges/notes (`🔧 [Tool] run_command(...)`) in the chat stream before showing the bot's final reply.

---

## How to Test and Run

### 1. Restart `ai_server.py`
Since `ai_server.py` runs in your terminal, restart it:
```bash
# In your terminal tab running ai_server:
Ctrl + C
python ai_server.py
```

### 2. Test from Terminal (CLI)
- **Ask it to inspect system:**
  ```bash
  python client.py "Check python version and list files in current directory"
  ```
- **Ask it to create or edit a script:**
  ```bash
  python client.py "Create a python script named test_script.py that calculates 15 * 15 and prints it, then run it using the terminal"
  ```
- **Interactive Chat Session:**
  ```bash
  python client.py -i
  ```

### 3. Test from Web Browser
Open `https://localhost:8443` (or whatever host `serve_https.py` is serving) and type prompts into the chat box!
