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
    """HTTP request handler for the UptimeDown dashboard.

    Serves the dashboard HTML frontend and provides JSON API endpoints for
    accessing collected system metrics from the data directory.

    Class attributes:
        data_dir (Path): Directory containing JSON metric files to serve.
        max_files (int): Maximum number of recent files to expose via /api/files.
    """
    data_dir = DEFAULT_DATA_DIR
    max_files = DEFAULT_MAX_FILES

    def do_GET(self):
        """Handle HTTP GET requests with path-based routing."""
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
        """Serve a file with the specified content type.

        Args:
            path (Path): File path to serve.
            content_type (str): MIME type for the Content-Type header.
        """
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
        except (IsADirectoryError, PermissionError, OSError):
            # Catch other IO errors (directory instead of file, permissions, etc.)
            self.send_error(400, "Cannot read file")

    def _serve_file_list(self):
        """List the most recent JSON files in the data directory.

        Returns a JSON array of filenames, sorted by modification time (newest first),
        limited to max_files entries. Returns an empty list if data directory doesn't exist.
        """
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
        """Serve a JSON file from the data directory.

        Path traversal is prevented by validating that the filename contains no
        path separators (/ or \) or parent directory references (..).

        Args:
            filename (str): Requested filename from the URL.
        """
        # Reject path traversal attempts (/, \, and .. sequences)
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
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
        except (IsADirectoryError, PermissionError, OSError):
            # Catch other IO errors (directory instead of file, permissions, etc.)
            self.send_error(400, "Cannot read file")

    def log_message(self, fmt, *args):
        """Log HTTP requests to stdout in a minimal format."""
        print(f"{self.address_string()} - {fmt % args}")


def main():
    """Parse command-line arguments and start the HTTP server.

    Configures the DashboardHandler with the specified data directory and
    max files limit, then starts an HTTP server listening on all interfaces.
    """
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
