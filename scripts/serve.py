"""Static file server with HTTP Range support, for testing the MapLibre app
locally. Python's stdlib `http.server` does not honour `Range`, which causes
PMTiles to fail (the protocol relies on byte-range fetches against the
.pmtiles archive).

Usage:
    python scripts/serve.py            # serves ./app on http://localhost:8765/
    python scripts/serve.py --port 8000 --dir some/other/dir
"""

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
from functools import partial
from pathlib import Path


class RangeRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler that honours HTTP Range requests on files."""

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if "Range" in self.headers:
            self._handle_range()
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        # Advertise range support even for HEAD.
        if "Range" in self.headers:
            self._handle_range(head_only=True)
            return
        super().do_HEAD()

    def end_headers(self) -> None:
        # Always advertise byte-range support so clients try Range first.
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def _handle_range(self, head_only: bool = False) -> None:
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            # Fall back to default (which handles dir listings / index.html).
            if head_only:
                super().do_HEAD()
            else:
                super().do_GET()
            return

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return

        try:
            size = os.fstat(f.fileno()).st_size
            start, end = self._parse_range(self.headers["Range"], size)
            if start is None:
                self.send_response(416, "Requested Range Not Satisfiable")
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            length = end - start + 1

            self.send_response(206, "Partial Content")
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Last-Modified",
                             self.date_time_string(int(os.fstat(f.fileno()).st_mtime)))
            self.end_headers()

            if head_only:
                return

            f.seek(start)
            remaining = length
            buf_size = 64 * 1024
            while remaining > 0:
                chunk = f.read(min(buf_size, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    # Client closed early — normal for PMTiles when it's
                    # already read the bytes it wanted.
                    return
                remaining -= len(chunk)
        finally:
            f.close()

    @staticmethod
    def _parse_range(header: str, size: int) -> tuple[int | None, int | None]:
        """Parse a single-range `bytes=start-end` header. Returns (start, end)
        inclusive, or (None, None) on invalid input."""
        if not header.startswith("bytes="):
            return None, None
        spec = header[len("bytes="):].strip()
        if "," in spec:
            # Multipart ranges not supported; just take the first one.
            spec = spec.split(",", 1)[0].strip()
        if "-" not in spec:
            return None, None
        start_s, end_s = spec.split("-", 1)
        try:
            if start_s == "":
                # Suffix range: last N bytes.
                length = int(end_s)
                if length <= 0:
                    return None, None
                start = max(0, size - length)
                end = size - 1
            else:
                start = int(start_s)
                end = int(end_s) if end_s else size - 1
        except ValueError:
            return None, None
        if start < 0 or start >= size or end < start:
            return None, None
        if end >= size:
            end = size - 1
        return start, end


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--dir",
        default=str(Path(__file__).resolve().parent.parent / "app"),
    )
    args = parser.parse_args()

    handler = partial(RangeRequestHandler, directory=args.dir)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", args.port), handler) as httpd:
        print(f"Serving {args.dir} -> http://localhost:{args.port}/")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
