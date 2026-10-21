"""Loopback-only static audit artifacts, byte ranges for native video seeking."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "out/crossing_evidence_20261020"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/review/")
            self.end_headers()
            return
        target = Path(self.translate_path(self.path)).resolve()
        if not target.is_relative_to(ROOT.resolve()):
            self.send_error(403)
            return
        raw = self.headers.get("Range")
        if raw and target.is_file():
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", raw)
            size = target.stat().st_size
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else size-1, size-1)
            if start > end:
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(str(target)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end-start+1))
            self.end_headers()
            try:
                with target.open("rb") as f:
                    f.seek(start)
                    left = end-start+1
                    while left:
                        data = f.read(min(left, 256*1024))
                        if not data:
                            break
                        self.wfile.write(data)
                        left -= len(data)
            except (ConnectionError, BrokenPipeError):
                pass
            return
        super().do_GET()

    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8134)
    args = parser.parse_args()
    print(f"http://127.0.0.1:{args.port}/review/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
