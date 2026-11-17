#!/usr/bin/env python3
"""Static file server over HTTPS with a reverse-proxy for the AI API.

Static files are served from --dir; API paths (/chat, /modules, /health)
are transparently forwarded to the ai_server.py backend, so the page and
the API share one origin -> no CORS, works from any host (localhost or LAN).

API paths:
    GET  /health   -> backend health
    GET  /modules  -> module list
    POST /chat     -> chat completion
"""

import http.server
import ssl
import argparse
import os
import urllib.error
import urllib.request

PROXY_PATHS = ("/chat", "/modules", "/health", "/history", "/skills", "/sessions")
UPSTREAM = os.environ.get("API_UPSTREAM", "http://127.0.0.1:8000")
UPSTREAM_CONTEXT = None   # TLS context when upstream is https


def detect_upstream(explicit: str) -> str:
    """Probe candidates in order; keep the first that answers /health.
    Covers both launch styles: plain (8000) and --ssl (8444)."""
    global UPSTREAM_CONTEXT
    candidates = [explicit]
    # only auto-fall back between the two default ports when relevant
    if explicit.endswith(":8000"):
        candidates.append("https://127.0.0.1:8444")
    elif explicit.endswith(":8444"):
        candidates.append("http://127.0.0.1:8000")

    for url in candidates:
        ctx = None
        if url.startswith("https://"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE     # local loopback hop only
        try:
            urllib.request.urlopen(f"{url}/health", timeout=3,
                                   **({"context": ctx} if ctx else {}))
        except urllib.error.HTTPError:
            pass                                 # alive, /health status not 200
        except Exception:
            continue                             # dead port, try next
        UPSTREAM_CONTEXT = ctx
        return url

    UPSTREAM_CONTEXT = None
    return explicit                              # keep flag, 502s will show why


class RouterHandler(http.server.SimpleHTTPRequestHandler):
    """Static files + reverse proxy to the AI API on one HTTPS origin."""

    def _is_api(self) -> bool:
        return self.path.split("?", 1)[0] in PROXY_PATHS

    def do_GET(self):
        if self._is_api():
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self._is_api():
            self._proxy("POST")
        else:
            self.send_error(404, "POST only allowed on API paths")

    def do_DELETE(self):
        if self._is_api():
            self._proxy("DELETE")
        else:
            self.send_error(404, "DELETE only allowed on API paths")

    def _proxy(self, method: str):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            f"{UPSTREAM}{self.path}",
            data=body,
            method=method,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        try:
            kwargs = {"context": UPSTREAM_CONTEXT} if UPSTREAM_CONTEXT else {}
            with urllib.request.urlopen(req, timeout=600, **kwargs) as resp:   # long: model inference
                self._relay(resp.status, resp)
        except urllib.error.HTTPError as exc:
            self._relay(exc.code, exc)
        except Exception as exc:
            self.send_error(502, f"API upstream unreachable: {exc}")

    def _relay(self, status: int, resp):
        self.send_response(status)
        self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
        self.end_headers()
        self.wfile.write(resp.read())

    def log_message(self, fmt, *args):
        # keep logs readable: skip the favicon noise
        if "/favicon" not in (args[0] if isinstance(args[0], str) else ""):
            super().log_message(fmt, *args)


def main():
    global UPSTREAM
    parser = argparse.ArgumentParser(description="Serve a directory over HTTPS.")
    parser.add_argument("--port", type=int, default=8443, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (0.0.0.0 = LAN too, 127.0.0.1 = local only)")
    parser.add_argument("--dir", default=os.getcwd(), help="Directory to serve")
    parser.add_argument("--certdir", default=None,
                        help="Directory containing server.crt/server.key "
                             "(default: the original working directory)")
    parser.add_argument("--upstream", default=UPSTREAM,
                        help="ai_server base URL (default: http://127.0.0.1:8000)")
    args = parser.parse_args()

    UPSTREAM = detect_upstream(args.upstream)

    certdir = args.certdir or os.getcwd()
    os.chdir(args.dir)

    httpd = http.server.HTTPServer((args.host, args.port), RouterHandler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile=os.path.join(certdir, "server.crt"),
        keyfile=os.path.join(certdir, "server.key"),
    )
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    print(f"Serving {args.dir} on https://{args.host}:{args.port} "
          f"(API proxy -> {UPSTREAM})")
    httpd.serve_forever()

if __name__ == "__main__":
    main()
