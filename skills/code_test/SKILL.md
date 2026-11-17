---
name: code_test
description: Validate Python scripts for syntax errors and test script execution.
command: python3 -m py_compile <script.py>
---
# Code Test Skill

Use this skill whenever creating or editing Python scripts to test and verify code correctness before concluding tasks.

### Instructions:
1. Run `python3 -m py_compile <script.py>` using `run_command` to check for syntax errors.
2. If the user asks to test or run the script, execute `python3 <script.py>` with a safe timeout.
3. If an error is returned, inspect line numbers and use `edit_file` or `write_file` to fix the bug, then re-test.
