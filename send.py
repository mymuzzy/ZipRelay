"""ZipRelay sender: sends a folder or file to a receiver as verified ZIPs, one at a time. (by Muzkkir)"""
import argparse, hashlib, os, platform, shlex, stat, sys, time
from contextlib import closing
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

if sys.version_info < (3, 9):
    sys.exit("ZipRelay needs Python 3.9 or newer.")

# Each OS ships only one of these file-locking modules, so import whichever exists.
try: import msvcrt  # Windows
except ImportError: msvcrt = None
try: import fcntl   # Linux / macOS
except ImportError: fcntl = None

# ───────────── EDIT THIS SECTION (or use command-line flags) ─────────────
SOURCE = ""              # folder or file to send, e.g. "G:/" or "/home/me/Documents" (empty = ask)
HOST = ""                # the receiver's IP, printed when it starts (empty = ask)
MODE = ""                # "each" = one ZIP per item inside the folder, "whole" = one ZIP, empty = ask
PORT = 8765
TOKEN = ""               # optional shared secret, must match the receiver (or set ZIPRELAY_TOKEN)
STATE = "~/.ziprelay"    # staging area for ZIPs and resume info; keep it between runs
# ───────────── NOTHING BELOW NEEDS CHANGING ─────────────

BLOCK = 1 << 20
STORED = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".jpg", ".jpeg", ".png", ".webp",
          ".mp4", ".mkv", ".mov", ".zip", ".7z", ".rar", ".gz"}  # already compressed: skip the CPU work
last_draw = 0


def mb(n):
    return f"{n / 2**20:,.1f} MB"


def progress(done, total, note="", end=False):
    """Redraw a one-line bar (at most 5 times a second); end=True draws the final state and moves on."""
    global last_draw
    if not end and time.monotonic() - last_draw < 0.2:
        return
    last_draw, n = time.monotonic(), 24 * done // total
    print(f"\r[{'#' * n}{'-' * (24 - n)}] {done / total:6.1%}  {mb(done)}/{mb(total)}{note}   ",
          end="\n" if end else "", flush=True)


def sha256(path, show=False):
    h, done, total = hashlib.sha256(), 0, path.stat().st_size or 1
    with path.open("rb") as f:
        for block in iter(lambda: f.read(BLOCK), b""):
            h.update(block)
            done += len(block)
            if show: progress(done, total)
    if show: progress(total, total, end=True)
    return h.hexdigest()


def ask(question):
    """Prompt only when a person is at the keyboard; scripts and cron get an empty answer."""
    return input(question).strip() if sys.stdin.isatty() else ""


def clean_path(text):
    """Turn a drag-and-dropped path (quoted or backslash-escaped) into a plain one."""
    return text.strip("\"'") if os.name == "nt" else (shlex.split(text) or [""])[0]


def lock(f):
    """Stop two senders from using the same staging folder (raises OSError if busy)."""
    f.seek(0)
    if msvcrt: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    elif fcntl: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


def selected(path):
    """Visible regular files and folders only: no dotfiles, symlinks, cache dirs or Windows hidden/system items."""
    if path.name.startswith("."):
        return False
    info = path.lstat()
    if os.name == "nt" and info.st_file_attributes & (
            stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM | stat.FILE_ATTRIBUTE_REPARSE_POINT):
        return False
    if stat.S_ISDIR(info.st_mode):
        return path.name.casefold() not in {"cache", "__pycache__"}
    return stat.S_ISREG(info.st_mode)


def fail(error):
    raise error


def listing(item):
    """(path, size) for the item and everything selected under it; a folder comes before its contents."""
    if item.is_file():
        return [(item, item.stat().st_size)]
    found = []
    for folder, dirs, files in os.walk(item, onerror=fail):
        here = Path(folder)
        dirs[:] = sorted(d for d in dirs if selected(here / d))
        found.append((here, 0))
        found += [(here / f, (here / f).stat().st_size) for f in sorted(files) if selected(here / f)]
    return found


def pack(root, item, archive):
    tmp = archive.with_suffix(".tmp")  # only a finished ZIP ever gets the real name
    paths = listing(item)
    total = sum(size for _, size in paths) or 1
    print(f"  {len(paths):,} entries, {mb(total)} to pack", flush=True)
    done = 0
    try:
        with ZipFile(tmp, "w", ZIP_DEFLATED, compresslevel=1, strict_timestamps=False) as z:
            for i, (path, size) in enumerate(paths, 1):
                arc = path.name if item.is_file() else path.relative_to(root)  # ZIP always stores "/" separators
                z.write(path, arc, compress_type=ZIP_STORED if path.suffix.lower() in STORED else ZIP_DEFLATED)
                done += size
                progress(done, total, f"  {i:,}/{len(paths):,} entries")
        progress(total, total, f"  {len(paths):,}/{len(paths):,} entries", end=True)
        tmp.replace(archive)
    finally:
        tmp.unlink(missing_ok=True)


def chunks(archive, size, offset):
    """Yield the ZIP from `offset` onward, drawing a progress bar as we go."""
    sent = offset
    with archive.open("rb") as f:
        f.seek(offset)
        while sent < size:
            block = f.read(min(BLOCK, size - sent))
            if not block:
                raise OSError("The staging ZIP was truncated during upload.")
            yield block
            sent += len(block)
            progress(sent, size)
    progress(size, size, end=True)
    print("Waiting for the receiver to verify...", flush=True)


def request(a, method, name="", size=0, digest="", archive=None, offset=0):
    headers = {"X-Token": a.token, "X-Size": str(size), "X-SHA256": digest}
    body = None
    if method == "PUT":
        headers.update({"Content-Length": str(size - offset), "Upload-Offset": str(offset)})
        body = chunks(archive, size, offset)
    with closing(HTTPConnection(a.host, a.port, timeout=600)) as conn:
        conn.request(method, "/" + quote(name, safe=""), body=body, headers=headers)
        with conn.getresponse() as r:
            if r.status == 403:
                raise RuntimeError("Receiver rejected the token. Check both token settings (both set and equal, or both empty).")
            if r.getheader("ZipRelay-Version") != "1":
                raise RuntimeError("This address is not running a compatible ZipRelay receiver.")
            if r.status == 409:
                raise RuntimeError(f"Receiver reported a filename or resume conflict for {name!r}.")
            return r.status, r.headers


def transfer(a, item, archive):
    name, receipt = item.name + ".zip", archive.with_suffix(".sha256")
    # A receipt means this item was verified in an earlier run: just confirm the receiver still has it.
    if receipt.exists() and not archive.exists():
        size, digest = receipt.read_text().split()
        status, _ = request(a, "HEAD", name, int(size), digest)
        if status == 200:
            return print(f"Already verified: {name!r}", flush=True)
        if status != 204:
            raise RuntimeError(f"Receiver returned HTTP {status} for {name!r}.")
    if not archive.exists():
        print(f"Packing {item.name!r}", flush=True)
        pack(a.root, item, archive)
    print(f"Hashing {name!r}", flush=True)
    size, digest = archive.stat().st_size, sha256(archive, show=True)

    for attempt in range(2):  # a second pass only happens after a hash mismatch
        status, headers = request(a, "HEAD", name, size, digest)
        if status == 200:
            break
        offset = int(headers.get("Upload-Offset", "-1"))
        if status != 204 or not 0 <= offset <= size:
            raise RuntimeError(f"Receiver returned HTTP {status}, offset {offset}, for {name!r}.")
        print(f"Sending {name!r} at byte {offset:,} of {size:,}", flush=True)
        status, _ = request(a, "PUT", name, size, digest, archive, offset)
        if status == 201:
            break
        if status != 422 or attempt == 1:
            raise RuntimeError(f"Upload of {name!r} failed with HTTP {status}.")
        print("SHA-256 mismatch. Retrying from byte zero.", flush=True)

    tmp = receipt.with_suffix(".tmp")
    tmp.write_text(f"{size} {digest}\n")
    tmp.replace(receipt)
    archive.unlink()  # free the disk space only after the receiver confirmed the hash
    print(f"Verified {name!r}  SHA-256 {digest}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default=SOURCE, help="folder or file to send (asked for if missing)")
    p.add_argument("--host", default=HOST, help="receiver IP address or hostname (asked for if missing)")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--token", default=os.getenv("ZIPRELAY_TOKEN") or TOKEN)
    p.add_argument("--state", default=STATE, help="staging folder for ZIPs and resume info")
    p.add_argument("--mode", default=MODE, choices=("each", "whole"),
                   help="each = one ZIP per item inside the folder, whole = the folder as one ZIP")
    a = p.parse_args()
    a.source = a.source or clean_path(ask("Drag a folder or file here (or type its path): "))
    a.host = a.host or ask("Receiver IP address (receive.py prints it): ")
    if not a.source: p.error("choose what to send with --source or SOURCE at the top of this file")
    if not a.host: p.error("provide the receiver address with --host or HOST at the top of this file")
    if a.mode not in ("", "each", "whole"): p.error("MODE must be 'each', 'whole' or empty")
    if any(not 33 <= ord(c) <= 126 for c in a.token):
        p.error("the token must be printable ASCII with no spaces (or leave it empty for no token)")
    source = Path(a.source).expanduser()
    if not source.exists():
        p.error(f"not found: {source}")
    a.source, state = source.resolve(), Path(a.state).expanduser().resolve()
    if state == a.source or (state.is_relative_to(a.source) and not state.name.startswith(".")):
        p.error("use a state folder outside the source, or one whose name starts with a dot")
    if a.source.is_dir() and not a.mode:
        a.mode = "whole" if ask("Send [1] each item inside as its own ZIP (safer for big folders) or [2] the whole folder as one ZIP? [1]: ") == "2" else "each"
    whole = a.mode == "whole" and a.source.is_dir()
    if whole and a.source.parent == a.source:
        p.error("a drive root can't be sent as one ZIP; use --mode each")
    a.root = a.source.parent if whole else a.source  # ZIP paths are stored relative to this

    try:
        status, headers = request(a, "GET")
    except OSError as e:
        raise RuntimeError(f"can't reach {a.host}:{a.port} ({e}). Check the IP, the port, and the receiver's firewall.")
    if status != 200:
        raise RuntimeError(f"Receiver check failed with HTTP {status}.")
    print(f"{platform.system()} → {headers.get('ZipRelay-OS', 'unknown OS')}", flush=True)

    # One staging folder per (source, receiver) pair, so reruns find their own resume data.
    tag = "\0whole" if whole else ""
    profile = f"{a.source}\0{a.host.casefold()}\0{a.port}{tag}"
    staging = state / hashlib.sha256(os.fsencode(profile)).hexdigest()
    staging.mkdir(parents=True, exist_ok=True)
    with (staging / "transfer.lock").open("a+b") as lockfile:
        try:
            lock(lockfile)
        except OSError as e:
            raise RuntimeError("Could not lock the staging folder. Check for another sender.") from e
        found = [a.source] if whole or a.source.is_file() else [i for i in sorted(a.source.iterdir()) if selected(i)]
        items = [(i, staging / (hashlib.sha256(os.fsencode(i.name)).hexdigest() + ".zip")) for i in found]
        items.sort(key=lambda pair: not pair[1].exists())  # unfinished items first
        print(f"Sending {len(items)} ZIP(s) from {str(a.source)!r}, one at a time", flush=True)
        for item, archive in items:
            transfer(a, item, archive)
    print("All selected archives verified.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, HTTPException, EOFError, KeyboardInterrupt) as e:
        raise SystemExit(f"\nTransfer stopped ({e or 'interrupted'}). Rerun to resume.")
