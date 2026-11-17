# modules/math_utils.py
"""Pre-processing module: evaluates simple arithmetic expressions
in the user message before it reaches the LLM.

Example: "Compute 5 + 7 for me" -> "Compute 12 for me"
"""

import re


def process(text: str) -> str:
    pattern = r"(\d+)\s*([+\-*/])\s*(\d+)"

    def repl(match):
        a, op, b = match.groups()
        a, b = int(a), int(b)
        if op == "+":
            return str(a + b)
        if op == "-":
            return str(a - b)
        if op == "*":
            return str(a * b)
        if op == "/":
            return str(a / b if b != 0 else "inf")

    return re.sub(pattern, repl, text)
