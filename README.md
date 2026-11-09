# ZipRelay

Send folders between computers on the same network as verified ZIP archives. Works on Windows, macOS and Linux with **Python 3.9+ and nothing else to install**. Built by Muzkkir.

## How it works

Two scripts, one job each:

- `receive.py` runs on the destination machine and waits for uploads.
- `send.py` runs on the source machine, zips every visible top-level item of a folder (`Desktop` becomes `Desktop.zip`), and uploads each ZIP in chunks.

Every ZIP is checked with SHA-256 before it counts as finished. Interrupted? Rerun the same command and it picks up at the byte where it stopped.

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

Use `py -3` on Windows or `python3` on macOS/Linux if that is how you launch Python. To send a drive, use `--source G:/`.

## Settings

Prefer editing a file over typing flags? Each script has a marked section at the top (`EDIT THIS SECTION`), so set `TOKEN`, `HOST`, `SOURCE` and the rest there and run the script with no arguments. The token is optional: leave it empty on both machines for no authentication. If you set one, both sides must match exactly (printable ASCII, no spaces). Priority: `--token` flag, then the `ZIPRELAY_TOKEN` environment variable, then the value in the script. Keep real tokens out of public commits.

| Option | Script | Default | Meaning |
|---|---|---|---|
| `--source` | send | none (required) | Folder to back up |
| `--host` | send | none (required) | Receiver's IP or hostname |
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
- Finished items are remembered, so a rerun skips them. Keep the sender's `--state` folder and the receiver's `.part` files between runs.
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
