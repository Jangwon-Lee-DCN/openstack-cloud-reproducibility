from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .delivery import ReplayCache, canonical_payload, verify_webhook
from .workflows import WorkflowError


class State:
    def __init__(self, key: bytes):
        self.key, self.replay = key, ReplayCache()
        self.lock = threading.Lock()
        self.webhooks, self.smtp, self.ids = [], [], set()
        self.failures = 0


def handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            return

        def reply(self, code, body):
            encoded = json.dumps(body, sort_keys=True).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)

        def do_GET(self):
            if self.path != "/records": return self.reply(404, {"error": "not_found"})
            with state.lock:
                return self.reply(200, {"webhooks": list(state.webhooks), "smtp": list(state.smtp)})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0")); raw = self.rfile.read(length)
            if self.path == "/control/fail-next":
                body = json.loads(raw or b"{}")
                with state.lock: state.failures = max(0, min(20, int(body.get("count", 0))))
                return self.reply(204, {})
            if self.path != "/events": return self.reply(404, {"error": "not_found"})
            delivery_id = self.headers.get("X-DCN-Delivery-ID", "")
            with state.lock:
                if state.failures:
                    state.failures -= 1
                    return self.reply(503, {"error": "injected_failure"})
                if delivery_id in state.ids:
                    return self.reply(200, {"status": "duplicate_suppressed"})
                try:
                    verify_webhook(state.key, "governance", int(self.headers["X-DCN-Timestamp"]),
                                   self.headers["X-DCN-Nonce"], raw, self.headers["X-DCN-Signature"],
                                   state.replay, now=int(time.time()))
                    payload = json.loads(raw)
                except (KeyError, ValueError, json.JSONDecodeError, WorkflowError):
                    return self.reply(401, {"error": "invalid_signature_or_replay"})
                state.ids.add(delivery_id); state.webhooks.append({"delivery_id": delivery_id, "payload": payload})
            return self.reply(202, {"status": "accepted"})
    return Handler


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 notification-sink ESMTP\r\n"); lines = []
        while True:
            line = self.rfile.readline(65536)
            if not line: break
            upper = line.upper()
            if upper.startswith((b"EHLO", b"HELO")): self.wfile.write(b"250-notification-sink\r\n250 8BITMIME\r\n")
            elif upper.startswith(b"MAIL FROM:") or upper.startswith(b"RCPT TO:"): self.wfile.write(b"250 OK\r\n")
            elif upper.startswith(b"DATA"):
                self.wfile.write(b"354 End with .\r\n")
                while True:
                    item = self.rfile.readline(65536)
                    if item == b".\r\n": break
                    lines.append(item)
                with self.server.state.lock: self.server.state.smtp.append(b"".join(lines).decode(errors="replace"))
                self.wfile.write(b"250 queued\r\n")
            elif upper.startswith(b"QUIT"): self.wfile.write(b"221 bye\r\n"); break
            else: self.wfile.write(b"250 OK\r\n")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--http", type=int, default=8081); parser.add_argument("--smtp", type=int, default=8025)
    args = parser.parse_args()
    import os
    state = State(os.environ["GOVERNANCE_WEBHOOK_SIGNING_KEY"].encode())
    http = ThreadingHTTPServer(("0.0.0.0", args.http), handler(state))
    smtp = socketserver.ThreadingTCPServer(("0.0.0.0", args.smtp), SMTPHandler); smtp.state = state
    threading.Thread(target=smtp.serve_forever, daemon=True).start(); http.serve_forever()


if __name__ == "__main__": main()
