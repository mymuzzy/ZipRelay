"""ZipRelay receiver: run this on the machine that will store the backup. (by Muzkkir)"""
import argparse, hashlib, hmac, os, platform, re, socket, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote

if sys.version_info < (3, 9):
    sys.exit("ZipRelay needs Python 3.9 or newer.")

# ───────────── EDIT THIS SECTION (or use command-line flags) ─────────────
DEST = "received"  # where finished ZIPs are kept; use one folder per source
BIND = "0.0.0.0"   # 0.0.0.0 = listen on the whole local network
PORT = 8765
TOKEN = ""         # optional shared secret, identical on both machines (or set ZIPRELAY_TOKEN)
# ───────────── NOTHING BELOW NEEDS CHANGING ─────────────

BLOCK = 1 << 20


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def lan_ip():
    """Best guess at this machine's LAN address (no packet is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "unknown"


class Receiver(BaseHTTPRequestHandler):
    timeout = 120

    def log_message(self, *args):  # we print our own, shorter log lines
        pass

    def reply(self, status, offset=0):
        self.send_response(status)
        for key, value in (("Content-Length", 0), ("Upload-Offset", offset),
                           ("ZipRelay-Version", 1), ("ZipRelay-OS", platform.system())):
            self.send_header(key, str(value))
        self.end_headers()

    def handle_request(self):
        try:
            if not hmac.compare_digest(self.headers.get("X-Token", "").encode(), self.server.token):
                return self.reply(403)
            if self.command == "GET":  # plain "is anyone home?" check
                return self.reply(200 if self.path == "/" else 404)
            self.archive_request(self.command == "PUT")
        except (EOFError, ConnectionError, socket.timeout) as e:
            print(f"Connection interrupted: {e or 'timed out'}", flush=True)
        except OSError as e:
            print(f"Receiver error: {e}", flush=True)
            self.reply(500)

    def archive_request(self, upload):
        # 1) validate the request
        try:
            name = unquote(self.path[1:], errors="strict")
            digest = self.headers.get("X-SHA256", "")
            size = int(self.headers["X-Size"])
            bad = (not name.endswith(".zip") or name.startswith(".") or any(c in name for c in "/\\\0")
                   or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest))
            if upload:
                offset = int(self.headers["Upload-Offset"])
                bad = bad or not 0 <= offset <= size or int(self.headers["Content-Length"]) != size - offset
            if bad:
                raise ValueError
        except (ValueError, TypeError):
            return self.reply(400)
        if os.name == "nt" and (any(c in '<>:"|?*' or ord(c) < 32 for c in name) or Path(name).is_reserved()):
            return self.reply(400)

        # 2) make sure the name is safe to write (no symlinks, no case-insensitive clashes)
        dest = self.server.dest
        final = dest / name
        if final.is_symlink() or (final.exists() and (not final.is_file() or name not in os.listdir(dest))):
            print(f"Destination name conflict: {name!r}", flush=True)
            return self.reply(409)
        partial = dest / f".{hashlib.sha256(name.encode()).hexdigest()}.{digest}.part"
        if partial.is_symlink():
            return self.reply(409)
        saved = partial.stat().st_size if partial.exists() else 0
        if saved > size:
            partial.unlink()
            saved = 0

        # 3) HEAD = "what do you already have?"
        if not upload:
            if final.is_file() and final.stat().st_size == size and sha256(final) == digest:
                return self.reply(200)  # already complete and verified
            return self.reply(204, saved)  # send me everything after byte `saved`
        if offset != saved:
            return self.reply(409, saved)

        # 4) PUT = append bytes, then verify the whole file
        print(f"Receiving {name!r} at byte {offset:,} of {size:,}", flush=True)
        with partial.open("ab") as f:
            remaining = size - offset
            while remaining:
                block = self.rfile.read1(min(BLOCK, remaining))
                if not block:
                    raise EOFError(f"Partial archive kept for {name!r}")
                f.write(block)
                remaining -= len(block)
            f.flush()
            os.fsync(f.fileno())
        if sha256(partial) != digest:
            partial.unlink()
            print(f"SHA-256 mismatch: {name!r}", flush=True)
            return self.reply(422)
        partial.replace(final)
        print(f"Verified {name!r}  SHA-256 {digest}", flush=True)
        self.reply(201)

    do_GET = do_HEAD = do_PUT = handle_request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest", type=Path, default=Path(DEST), help="folder for received ZIPs")
    p.add_argument("--bind", default=BIND, help="address to listen on")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--token", default=os.getenv("ZIPRELAY_TOKEN") or TOKEN)
    a = p.parse_args()
    if any(not 33 <= ord(c) <= 126 for c in a.token):
        p.error("the token must be printable ASCII with no spaces (or leave it empty for no token)")
    dest = a.dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with HTTPServer((a.bind, a.port), Receiver) as server:
        server.dest, server.token = dest, a.token.encode()
        print(f"ZipRelay receiver ({platform.system()}) saving to {str(dest)!r}")
        if not a.token:
            print("No token set: any device on this network can send files here.")
        print(f"Tell the sender: --host {lan_ip()} --port {a.port}   (Ctrl+C to stop)", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nReceiver stopped.")
    except OSError as e:
        raise SystemExit(f"Receiver stopped: {e}")
