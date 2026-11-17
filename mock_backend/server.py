#!/usr/bin/env python3
"""Minimal mock backend for the TapGate firmware.

Implements just enough of the two endpoints the device talks to, so the
firmware can be exercised end-to-end without the real server:

    GET  /employees?last_sync=<unixts>   -> {"server_time": ..., "changes": [...]}
    POST /events  {"rfid_uid": ..., "authorized": ...}
    GET  /health

Stdlib only. Run it on the same LAN as the device:

    python3 mock_backend/server.py --port 8000

Then point APP_SERVER_HOST / APP_SERVER_PORT in src/server_config.h at the
IP this prints.
"""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Starting authorised personnel list (RFID UIDs as uppercase hex strings).
SEED = {
    "04A1B2C3": True,
    "11223344": True,
    "DEADBEEF": True,
}

EVENTS_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.jsonl")


class Handler(BaseHTTPRequestHandler):
    server_version = "TapGateMock/1.0"

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _server_time(self):
        return int(time.time())

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/health":
            self._send(200, {"status": "ok"})
            return

        if url.path == "/employees":
            last_sync = int(parse_qs(url.query).get("last_sync", ["0"])[0])
            now = self._server_time()

            # First sync (cursor 0): dump the whole whitelist as "added".
            # Later syncs: report no changes, just advance the cursor.
            if last_sync == 0:
                changes = [
                    {"rfid_uid": uid, "updated_at": now, "deleted": False}
                    for uid in SEED
                ]
            else:
                changes = []

            self._send(200, {"server_time": now, "changes": changes})
            print(f"GET /employees last_sync={last_sync} -> {len(changes)} change(s)")
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/events":
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""

        try:
            event = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        with open(EVENTS_LOG, "a") as f:
            f.write(json.dumps(event) + "\n")

        print(
            f"POST /events uid={event.get('rfid_uid')} "
            f"authorized={event.get('authorized')}"
        )
        self._send(200, {"status": "logged"})

    def log_message(self, fmt, *args):
        pass  # keep the console to our own one-line summaries


def main():
    parser = argparse.ArgumentParser(description="TapGate mock backend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"TapGate mock backend on http://{args.host}:{args.port}")
    print(f"Events are appended to {EVENTS_LOG}")
    print("Point APP_SERVER_HOST/APP_SERVER_PORT in src/server_config.h here.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
