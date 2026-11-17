# Project Skills Guide

This project includes custom skills and the full skill library synced from `~/.claude/skills/`. All skills are automatically discovered by `ai_server.py` and exposed to local models like `llama3.2:3b` and `qwen2.5-coder:7b`.

---

## Syncing Skills from Claude

All skills from `/home/fuck/.claude/skills/` are symlinked into `./skills/`. To re-sync anytime new skills are added:
```bash
python sync_skills.py
```

---

## Active Skills (40+ Available)

| Category / Skill | Description | Location |
| :--- | :--- | :--- |
| **`nftables_firewall`** | Unified nftables firewall, ARP whitelist & DoS defense | `skills/nftables_firewall/SKILL.md` |
| **`check_ports`** | Check listening TCP/UDP ports & process PIDs | `skills/check_ports/SKILL.md` |
| **`sys_health`** | Check RAM memory, disk space, and CPU load | `skills/sys_health/SKILL.md` |
| **`code_test`** | Validate syntax & run test execution | `skills/code_test/SKILL.md` |
| **`web-pentest`** | Web app & API assessment (injection, XSS, SSRF, JWT) | `skills/web-pentest/SKILL.md` |
| **`network-attack`** | Network protocol analysis and exploitation | `skills/network-attack/SKILL.md` |
| **`privesc-linux`** | Linux privilege escalation vectors | `skills/privesc-linux/SKILL.md` |
| **`recon-osint`** | Attack surface discovery and OSINT | `skills/recon-osint/SKILL.md` |
| **`cloud-security`** | Cloud and IAM security assessment | `skills/cloud-security/SKILL.md` |
| ... *(and 35+ more)* | ... | `skills/*/SKILL.md` |

---

## How it Works with Ollama (`llama3.2:3b` & `qwen2.5-coder:7b`)

1. **Auto-Discovery**: `ai_server.py` scans `skills/` on each request and injects a compact skills index into the model's system prompt.
2. **On-Demand Playbooks**: When you ask a question related to any skill (e.g. `web-pentest`), the model uses `read_file` to read that skill's `SKILL.md` and load full methodology and script references.
3. **Tool Execution**: The model uses `run_command`, `read_file`, `write_file`, and `edit_file` to perform tasks in your terminal.
