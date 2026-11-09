# ZipRelay

Send folders between computers on the same network as verified ZIP archives. Works on Windows, macOS and Linux with **Python 3.9+ and nothing else to install**. Built by Muzkkir.

## How it works

- `receive.py` runs on the destination machine, waits for uploads, and keeps the verified ZIPs.
- `send.py` runs on the source machine and sends **one ZIP at a time**.

Point `send.py` at a folder (or a single file) and choose a mode with `--mode` or by answering its prompt:

| Mode | What you get | Best for |
|---|---|---|
| `each` | One ZIP per visible item inside the folder, sent one after another (`Desktop.zip`, `Photos.zip`, `notes.txt.zip`) | Big folders: small uploads, little spare disk space, cheap retries |
| `whole` | The folder itself as a single ZIP | Small folders you want as one file |

**What happens in `each` mode:** the sender packs the next item into a ZIP, uploads it in chunks, and the receiver checks its SHA-256. Once the receiver confirms, the sender deletes its temporary ZIP, saves a tiny receipt, and moves on. A folder holding 15 files and 10 subfolders becomes 25 ZIPs (each subfolder's contents stay inside its own ZIP), and the sender never holds more than one at a time. The receiver keeps every verified ZIP.

**Stop and continue:** press Ctrl+C whenever you like and rerun the same command. Items already delivered are confirmed with the receiver and skipped, the interrupted one continues from its last byte, and the rest are packed fresh.

## Quick start

1. *(Optional, recommended)* Make a token and use the same one on both machines. Skip this step and every `--token` flag below on a network you fully trust:

   ```sh
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. On the destination machine (use a separate folder for each source):

   ```sh
   python receive.py --dest "/path/to/backup" --token YOUR_TOKEN
   ```

   It prints the IP address to give the sender.

3. On the source machine:

   ```sh
   python send.py --source "/path/to/source" --host 192.168.1.50 --token YOUR_TOKEN
   ```

Run `python send.py` with no arguments and it asks for what is missing: drag a folder or file into the terminal window to paste its path, enter the receiver's IP, then pick `each` or `whole`.

Use `py -3` on Windows or `python3` on macOS/Linux if that is how you launch Python. To send a drive, use `--source G:/`.

## Settings

Prefer editing a file over typing flags? Each script has a marked section at the top (`EDIT THIS SECTION`), so set `TOKEN`, `HOST`, `SOURCE` and the rest there and run the script with no arguments. The token is optional: leave it empty on both machines for no authentication. If you set one, both sides must match exactly (printable ASCII, no spaces). Priority: `--token` flag, then the `ZIPRELAY_TOKEN` environment variable, then the value in the script. Keep real tokens out of public commits.

| Option | Script | Default | Meaning |
|---|---|---|---|
| `--source` | send | asked if missing | Folder or file to send |
| `--host` | send | asked if missing | Receiver's IP or hostname |
| `--mode` | send | asked if missing | `each` (one ZIP per item) or `whole` (folder as one ZIP) |
| `--dest` | receive | `received` | Where finished ZIPs are kept |
| `--bind` | receive | `0.0.0.0` | Interface to listen on |
| `--port` | both | `8765` | TCP port |
| `--state` | send | `~/.ziprelay` | Staging folder for ZIPs and resume data |

Run either script with `--help` for the full list.

## What gets copied

- Visible files and folders only. Skipped: dotfiles and dot folders, `cache` and `__pycache__` folders, symlinks, special files, and on Windows anything hidden, system or a reparse point (junctions included).
- Folder structure inside each ZIP is preserved.
- The sender builds each ZIP on disk first, so keep free space for the largest single item.

## Resume and verification

- The receiver keeps unfinished uploads as hidden `.part` files and tells the sender how many bytes it has.
- A bad hash triggers one retry from byte zero. The sender deletes its staged ZIP only after the receiver confirms the hash.
- Finished items are remembered, so a rerun skips them (the receiver is asked to confirm it still has the same hash). Keep the sender's `--state` folder and the receiver's `.part` files between runs.
- A rerun continues the *same* backup. If the source changed since the first run, start a new snapshot with a fresh `--state` and a fresh `--dest`, and close programs that write to the source while it runs.
- Use one receiver per destination. A verified upload replaces an existing ZIP of the same name. Names that clash on a case-insensitive destination, or that the receiver's filesystem can't store, must be renamed first.

## Troubleshooting

- **Can't reach the receiver:** check the IP, the port, and that the receiver's firewall allows incoming TCP on that port.
- **Token rejected:** the two sides differ. Either both use the same token, or both use none.
- **Could not lock the staging folder:** another sender is already using it.

## Network safety

Use this on a trusted private network only. Traffic is plain HTTP, so the token and file contents are not encrypted. With a token, only senders that know it can upload; without one, any device on the network can. SHA-256 only proves the archive arrived intact.

## License

Dedicated to the public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Swap this section if you prefer a different license.
