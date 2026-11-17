---
name: sys_health
description: Check system RAM memory, swap space, disk usage, and CPU load.
command: free -h && df -h / && uptime
---
# System Health Skill

Use this skill whenever the user asks about system resources, memory, RAM, disk space, swap usage, or CPU load.

### Instructions:
1. Run `free -h && df -h / && uptime` using the `run_command` tool.
2. Analyze total, used, and available RAM memory.
3. Check used and free disk space on the root filesystem `/`.
4. Report memory and disk health clearly. If available RAM is below 1 GB, explicitly alert the user.
