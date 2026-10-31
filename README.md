# Bard

Text to speech for Ember. Piper synthesizes an English voice on the CPU, ffmpeg encodes MP3, and Armory proxies the tools as the `bard` extension. Ember plays the result in chat through `GET /api/bard/audio/{file_id}`.

## Tools

| Tool | Purpose |
| --- | --- |
| `tool_bard_speak` | Turn text into an MP3 owned by the asking user. Returns `file_id`, `duration_s`, `size_bytes`, `cached`, `message`. |
| `tool_bard_listVoices` | List installed voices and the default. Read-only. Open to every user. |
| `tool_bard_listDownloadable` | Admins only. List the Piper catalog voices (language, quality, size, installed), optionally filtered by `language` and `quality`. Read-only. |
| `tool_bard_downloadVoice` | Admins only. Download one catalog voice onto the Bard host. Refuses an installed voice. |
| `tool_bard_deleteVoice` | Needs `bard.delete` (separate from `bard.admin`). Delete one installed voice from the Bard host. Refuses the default voice. |

## Admins

Admin means the account holds the `bard.admin` permission in ember_api (the Administrator role has it; grant it to other roles on the roles page). Bard asks ember_api through `POST /api/bard/internal/admin-check` with the shared `INTERNAL_API_TOKEN`, and caches each answer for 30 seconds, so a grant or revoke applies within about half a minute. Any failure, such as ember_api being down, counts as "not an admin". `BARD_ADMINS` lists usernames that are admins even then (a break-glass list; leave it empty normally).

Deleting a voice needs the separate `bard.delete` permission, granted the same way (the Administrator role has it). `bard.admin` does not imply it, and `BARD_ADMINS` does not grant it, so with ember_api down nobody can delete. The default voice (`BARD_VOICE`) is never deleted; the voice's files go, cached audio stays until it expires.

Downloads come from the Piper voice catalog on Hugging Face: a name must be in the catalog, files are staged, checked against the catalog's size and MD5 and then moved into `.data/voices/`. One voice, `pt_PT-tugão-medium`, has a non-ASCII name and cannot be installed this way; use `python -m piper.download_voices` for it.

## Setup

1. `python -m venv .venv_bard` and `.venv_bard/Scripts/python.exe -m pip install -e ".[dev]"`
2. Download the voice: `.venv_bard/Scripts/python.exe -m piper.download_voices en_US-lessac-medium --download-dir .data/voices`
3. Copy `.env.example` to `.env` and set `INTERNAL_API_TOKEN` to the value Armory and ember_api use.
4. `.venv_bard/Scripts/python.exe -m src.run`, then start Armory (it connects to Bard at startup, so Bard goes first).
5. Register it in Armory's `configs/config_extensions.json` (see `config_extensions.json.example`, entry `bard`) and set `bard_url` in ember_api's `configs/config_app.json` if Bard is not on `http://127.0.0.1:8090`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `INTERNAL_API_TOKEN` | empty | Shared token for `/mcp` and `/api/*`. Required when `BARD_HOST` is not loopback. |
| `BARD_HOST` / `BARD_PORT` | `127.0.0.1` / `8090` | Listen address. |
| `BARD_DATA_DIR` | `.data` | Holds `voices/` and `audio/` (both gitignored). |
| `BARD_VOICE` | `en_US-lessac-medium` | Default voice. |
| `BARD_MAX_CHARS` | `5000` | Longest text accepted after Markdown is stripped. |
| `BARD_TTL_HOURS` | `24` | How long audio is kept. |
| `BARD_QUOTA_MB` | `200` | Audio storage per user. |
| `BARD_MAX_CONCURRENT` | `1` | Simultaneous syntheses. |
| `BARD_FFMPEG` | `ffmpeg` | ffmpeg executable. |
| `EMBER_API_URL` | `http://127.0.0.1:8030` | Where Bard asks who holds `bard.admin`. |
| `BARD_ADMINS` | empty | Comma-separated usernames that are always admins. |

## Notes

- Audio is private to the asking user (their username from Armory's `forward_requester`) and expires after the time-to-live.
- Check the voice's licence before redistributing it; voices are downloaded, not committed.

## HTTP speech for Ember

`POST /api/speak` accepts JSON `{text, voice?}` and returns `{file_id, duration_s, voice}` through `BardService.speak`. Markdown cleanup, the 5,000 cleaned-character cap, owner cache, quota and synthesis semaphore all apply. `GET /api/voices` returns `{voices: string[]}` containing installed voices only. Both require `X-Requester-Username` and the configured internal token, just like `/api/files/{file_id}`. Invalid text/voice is 400, quota is 413 and synthesis failure is 503.

Ember proxies these routes with `tools.execute` and `files.download`. Its Read aloud action asks for a voice on every run, strips Markdown, batches at 3,500 characters and synthesizes one batch ahead during playback. Stop aborts pending browser requests and playback; already completed audio retains the existing owner and TTL rules. Agent-triggered audio cards and all MCP tools keep their existing behavior.

### Releasing

A plain publish (`tools\deploy.bat` option 1) only updates the `live` branch, so it is fine for test deploys. A release is a separate step: set `VERSION` (and `pyproject.toml` where it has a version, to the same number), commit, then run `tools\deploy.bat` option R or `py tools\publish_live.py --release`. That publishes to `live` and tags the `main` commit `vX.Y.Z` and the live commit `live-vX.Y.Z`. A version already released with different live files is refused, so bump `VERSION`. While a version is not officially released yet, add `--replace` to move its tags.

`tools\make_zip.bat` then builds `zip_versions\Bard-<VERSION>.zip` (no `tools/`, no git-ignored files, no older ZIPs; `.env.example` is included) and opens GitHub's new-release page for the tag.
