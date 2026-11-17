# modules/web_fetch.py
"""Pre-processing module: fetches the first URL found in the message
and appends its text content, so the LLM can answer questions about
a live web page.

Example: "Summarize https://example.com" -> message + fetched page text
"""

import ipaddress
import re
import socket
import urllib.parse
import urllib.request

MAX_BYTES = 20_000        # keep prompts small
TIMEOUT = 15              # seconds
USER_AGENT = "mystatic-modules/1.0"

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def _resolves_to_public(url: str) -> bool:
    """Reject URLs whose hostname resolves to private/loopback/link-local
    addresses. Stops prompt-injection SSRF attacks like
    http://169.254.169.254/ (cloud metadata) or http://127.0.0.1:8000/chat."""
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                return False
    except OSError:
        return False
    return True


def process(text: str) -> str:
    match = URL_PATTERN.search(text)
    if not match:
        return text                                  # no URL -> pass through

    url = match.group(0).rstrip(".,;)")
    if not _resolves_to_public(url):
        return f"{text}\n\n[web_fetch blocked non-public host: {url}]"

    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype or "text/plain" in ctype:
                raw = resp.read(MAX_BYTES * 4).decode("utf-8", "ignore")
            else:
                return f"{text}\n\n[web_fetch skipped non-text content: {ctype}]"
    except Exception as exc:
        return f"{text}\n\n[web_fetch failed for {url}: {exc}]"

    # crude HTML -> text for a stdlib-only implementation
    body = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", raw)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()

    return (f"{text}\n\n--- content of {url} ---\n{body[:MAX_BYTES]}")
