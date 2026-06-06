# skip-radio

A personal internet radio server. Add songs to the database, and it streams them one at a time -- downloading from YouTube on demand when a track hasn't been cached yet.

## Quickstart

```sh
uv run skip-radio
```

Open http://localhost:8000. Press Skip to advance to the next track.

## How it works

- Songs are stored in an SQLite database (`data/songs.db`).
- Audio files are cached in `data/music/` as MP3s.
- When a track is requested but not yet downloaded, it is fetched from YouTube via yt-dlp.
- The web UI calls `POST /radio/next` to get the next track and streams it from `GET /audio/{id}`.
