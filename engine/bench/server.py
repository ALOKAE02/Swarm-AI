"""Swarm AI benchmark target: a small but tricky single-page app with 12 planted
bugs plus realistic noise (third-party script errors, favicon 404, benign
ResizeObserver warning, intentional scroll containers, a cookie banner and a
click-blocking modal).

    python bench/server.py            # serves http://localhost:8790/
    python bench/score.py findings.jsonl

The ground truth lives in bench/score.py. Never point the swarm at sites you
don't own; this is the safe "complex site" to tune against.
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent / "site"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/feed":
            try:
                page = int(parse_qs(u.query).get("page", ["1"])[0])
            except ValueError:
                page = 1
            if page >= 3:  # B10: truncated JSON from a flaky backend
                return self._send(200, '{"items":[{"id":41},')
            items = [{"id": (page - 1) * 10 + i, "title": f"Post #{(page - 1) * 10 + i}"} for i in range(1, 11)]
            return self._send(200, json.dumps({"items": items, "next": page + 1}))
        if u.path == "/api/products":
            time.sleep(0.15)
            names = ["Trail Runner", "City Sneaker", "Court Classic", "Hiking Boot", "Slip-on", "Sandal"]
            return self._send(200, json.dumps([{"sku": f"SKU-{i}", "name": n, "price": 1999 + i * 500}
                                               for i, n in enumerate(names, 1)]))
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if u.path == "/api/subscribe":
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                data = {}
            email = str(data.get("email", ""))
            if not email.strip():
                return self._send(422, json.dumps({"error": "email required"}))
            if any(c in email for c in "<>'\"") or len(email) > 120:  # B5: server crashes on hostile input
                return self._send(500, "Internal Server Error", "text/plain")
            return self._send(200, json.dumps({"message": f"subscribed {email}"}))
        return self._send(404, json.dumps({"error": "not found"}))


class DualStackServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        try:  # accept both localhost (::1) and 127.0.0.1
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def serve(port: int) -> None:
    try:
        DualStackServer.address_family = socket.AF_INET6
        httpd = DualStackServer(("::", port), Handler)
    except OSError:  # IPv6 disabled on this machine
        DualStackServer.address_family = socket.AF_INET
        httpd = DualStackServer(("0.0.0.0", port), Handler)
    print(f"Bench app on http://localhost:{port}/  (Ctrl+C to stop)")
    httpd.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    serve(ap.parse_args().port)
