#!/usr/bin/env python3
"""Simple HTTP server for the UptimeDown dashboard.

Serves the dashboard HTML and exposes JSON data files from the collected-data directory.

Usage:
    python3 dashboard/server.py [--port PORT] [--data-dir PATH] [--max-files N]

Defaults:
    port:      8080
    data-dir:  ../collected-data  (relative to this script)
    max-files: 60
"""
import sys
sys.dont_write_bytecode = True
import os
import json
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parent
DEFAULT_DATA_DIR = DASHBOARD_DIR.parent / "collected-data"
DEFAULT_PORT = 8080
DEFAULT_MAX_FILES = 60


class DashboardHandler(BaseHTTPRequestHandler):
    data_dir = DEFAULT_DATA_DIR
    max_files = DEFAULT_MAX_FILES

    def do_GET(self):
        path = self.path.split("?")[0]  # strip query string
        if path in ("/", "/index.html"):
            self._serve_file(DASHBOARD_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/api/files":
            self._serve_file_list()
        elif path.startswith("/api/data/"):
            filename = path[len("/api/data/"):]
            self._serve_json_file(filename)
        else:
            self.send_error(404, "Not found")

    def _serve_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404, "File not found")

    def _serve_file_list(self):
        try:
            data_dir = Path(self.data_dir)
            if not data_dir.exists():
                names = []
            else:
                files = sorted(
                    data_dir.glob("*.json"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                names = [f.name for f in files[: self.max_files]]
            payload = json.dumps(names).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            self.send_error(500, str(e))

    def _serve_json_file(self, filename):
        # Reject path traversal attempts
        if "/" in filename or "\\" in filename or ".." in filename:
            self.send_error(400, "Invalid filename")
            return
        try:
            path = Path(self.data_dir) / filename
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404, "File not found")

    def log_message(self, fmt, *args):
        # Print minimal access log to stdout
        print(f"{self.address_string()} - {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="UptimeDown dashboard server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help=f"Path to collected-data directory (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                        help=f"Maximum number of recent files to serve (default: {DEFAULT_MAX_FILES})")
    args = parser.parse_args()

    DashboardHandler.data_dir = args.data_dir
    DashboardHandler.max_files = args.max_files

    print(f"Dashboard : http://localhost:{args.port}/ (or http://<your-ip>:{args.port}/)")
    print(f"Data dir  : {args.data_dir}")
    print(f"Max files : {args.max_files}")
    print("Press Ctrl+C to stop.")

    HTTPServer(("", args.port), DashboardHandler).serve_forever()


if __name__ == "__main__":
    main()
