"""Serve the MCR reader locally with an optional LLM Q&A endpoint.

Usage:
    export MCR_API_KEY=sk-...                      # optional, enables Q&A
    export MCR_BASE_URL=https://api.minimaxi.com/v1  # optional (default)
    export MCR_MODEL=minimax-m3.1-flash            # optional (default)
    python -m mcr.serve <repo_path> --annotations <dir> [--port 8765]

Any OpenAI-compatible chat-completions endpoint works. Answers are streamed
token-by-token (SSE upstream, plain-text chunks downstream) and upstream HTTPS
connections are pooled and pre-warmed at startup to minimize first-token latency.
"""

import argparse
import http.client
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .build import load_payload, render

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "minimax-m3.1-flash"
MAX_TOKENS = 2048

SYSTEM_PROMPT = """You are a patient, precise code-reading assistant embedded in a dual-pane code reader.
The user is reading a source file with line-by-line explanations and has selected a piece of code to ask about.
Explain clearly and concretely: what the code does, why it is written this way, and any non-obvious details.
Be concise by default: short paragraphs, no filler, code snippets only when they add clarity.
Reply in {lang_name}. Use Markdown (inline code and fenced code blocks) for code."""


class LLMError(Exception):
    pass


class ConnectionPool:
    """Tiny keep-alive pool for one upstream host (stdlib http.client)."""

    def __init__(self, host, timeout=120):
        self.host = host
        self.timeout = timeout
        self._idle = []
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._idle:
                return self._idle.pop()
        return self._connect()

    def _connect(self):
        proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
        bypass = any(host and (host == "*" or self.host.endswith(host.lstrip(".")))
                     for host in (h.strip() for h in no_proxy.split(",")) if host)
        if proxy and not bypass:
            # The environment requires an HTTP proxy; tunnel TLS through CONNECT.
            p = urllib.parse.urlparse(proxy)
            conn = http.client.HTTPSConnection(p.netloc, timeout=self.timeout)
            conn.set_tunnel(self.host)
            return conn
        return http.client.HTTPSConnection(self.host, timeout=self.timeout)

    def put(self, conn):
        with self._lock:
            self._idle.append(conn)

    def discard(self, conn):
        try:
            conn.close()
        except OSError:
            pass


class LLMConfig:
    def __init__(self):
        self.api_key = os.environ.get("MCR_API_KEY", "")
        self.base_url = os.environ.get("MCR_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.model = os.environ.get("MCR_MODEL", DEFAULT_MODEL)
        parsed = urllib.parse.urlparse(self.base_url)
        self._host = parsed.netloc
        self._path = parsed.path.rstrip("/") + "/chat/completions"
        self._pool = ConnectionPool(self._host) if self._host else None

    @property
    def available(self):
        return bool(self.api_key)

    def _post(self, body):
        """Send one chat-completions request on a pooled connection."""
        conn = self._pool.get()
        try:
            conn.request("POST", self._path, body=body, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
                "Accept": "text/event-stream",
            })
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            self._pool.discard(conn)
            raise LLMError(f"LLM connection failed: {e}")
        return conn, resp

    def warmup(self):
        """Pre-establish TLS + DNS at startup so the first user question is fast."""
        if not self.available:
            return
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode("utf-8")
        try:
            conn, resp = self._post(body)
            resp.read()
            self._pool.put(conn)
            print(f"[mcr] LLM warmup: HTTP {resp.status}")
        except LLMError as e:
            print(f"[mcr] LLM warmup failed: {e}", file=sys.stderr)

    def build_messages(self, payload):
        lang_name = "Chinese (中文)" if payload.get("lang", "zh") == "zh" else "English"
        ctx_parts = []
        if payload.get("file"):
            ctx_parts.append("File: " + payload["file"])
        if payload.get("language"):
            ctx_parts.append("Language: " + payload["language"])
        if payload.get("line"):
            line_end = payload.get("line_end")
            if line_end and line_end != payload["line"]:
                ctx_parts.append("Selected lines: %s-%s" % (payload["line"], line_end))
            else:
                ctx_parts.append("Near line: " + str(payload["line"]))
        selection = payload.get("selection") or ""
        if selection:
            ctx_parts.append("Selected code:\n```\n" + selection + "\n```")
        context = "\n".join(ctx_parts)

        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(lang_name=lang_name)}]
        if context:
            messages.append({"role": "user", "content": "Context for this conversation:\n" + context})
            messages.append({"role": "assistant", "content": "Understood. I will answer based on this code context."})
        for h in (payload.get("history") or [])[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": payload.get("question", "")})
        return messages

    def ask_stream(self, payload):
        """Yield answer text chunks as the model generates them."""
        body = json.dumps({
            "model": self.model,
            "messages": self.build_messages(payload),
            "stream": True,
            "max_tokens": MAX_TOKENS,
        }).encode("utf-8")
        conn, resp = self._post(body)
        if resp.status != 200:
            detail = resp.read().decode("utf-8", "replace")[:500]
            self._pool.put(conn)
            raise LLMError(f"LLM API HTTP {resp.status}: {detail}")

        def generate():
            try:
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or [{}]
                    piece = (choices[0].get("delta") or {}).get("content")
                    if piece:
                        yield piece
            finally:
                # Streaming responses are not safely reusable (the upstream may
                # keep the socket half-open after [DONE]); always close them.
                resp.close()
                self._pool.discard(conn)

        return generate()


def make_handler(html, llm):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("[mcr] " + fmt % args + "\n")

        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path in ("/", "/index.html", "/reader.html"):
                self._send(200, html, "text/html; charset=utf-8")
            elif self.path == "/api/health":
                self._json(200, {"ok": True, "llm": llm.available, "model": llm.model if llm.available else None})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/ask":
                self._json(404, {"error": "not found"})
                return
            if not llm.available:
                self._json(503, {"error": "MCR_API_KEY is not set; Q&A is disabled."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON body"})
                return
            if not (payload.get("question") or "").strip():
                self._json(400, {"error": "empty question"})
                return
            try:
                stream = llm.ask_stream(payload)
            except LLMError as e:
                self._json(502, {"error": str(e)})
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for piece in stream:
                    self.wfile.write(piece.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(prog="mcr.serve", description=__doc__)
    p.add_argument("repo", help="path to the source repository")
    p.add_argument("--annotations", required=True, help="directory of annotation JSON files")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--out", help="also write the self-contained HTML to this path")
    args = p.parse_args(argv)

    payload = load_payload(args.repo, args.annotations)
    html = render(payload)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html)

    llm = LLMConfig()
    if llm.available:
        threading.Thread(target=llm.warmup, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(html, llm))
    print(f"MCR reader for '{payload['repo']}': http://{args.host}:{args.port}/")
    print(f"Q&A: {'enabled (' + llm.model + ')' if llm.available else 'disabled — set MCR_API_KEY to enable'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()


if __name__ == "__main__":
    main()
