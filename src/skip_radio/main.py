"""The main module for skip-radio."""

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

import uvicorn
import yt_dlp
import ytmusicapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

REFILL_THRESHOLD = 5
CHARTS_COUNTRY = "AU"
NON_SONG_VIDEO_TYPES = {"MUSIC_VIDEO_TYPE_PODCAST_EPISODE", "MUSIC_VIDEO_TYPE_UGC"}


class InterceptHandler(logging.Handler):
    """Route standard-library logs through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a standard logging record to loguru."""
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        if frame is None:
            frame = logging.currentframe()
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


HERE = Path(__file__).parent
DATA_DIR = HERE.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / ".gitignore").write_text("*")
logger.info(f"{DATA_DIR=}")
MUSIC_DIR = DATA_DIR / "music"
MUSIC_DIR.mkdir(exist_ok=True)
logger.info(f"{MUSIC_DIR=}")
DATABASE_URL = f"sqlite:///{DATA_DIR}/songs.db"
logger.info(f"{DATABASE_URL=}")


class Base(DeclarativeBase):
    """Base class for all schema definitions."""


class Song(Base):
    """A song stored in the local database."""

    __tablename__ = "songs"
    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    skip_count: Mapped[int] = mapped_column(default=0)
    complete_count: Mapped[int] = mapped_column(default=0)
    total_elapsed: Mapped[float] = mapped_column(default=0.0)


engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


class TrackResponse(BaseModel):
    """Response model for a radio track."""

    id: str
    title: str
    artist: str


class NextTrackRequest(BaseModel):
    """Request body for the next-track endpoint."""

    action: str = "next"
    elapsed: float = 0.0


class RadioStation:
    """Manages the playlist and skip-aware predictions."""

    def __init__(self) -> None:
        """Initialize the YT Music client."""
        self.yt = ytmusicapi.YTMusic()
        self.queue: list[Song] = []
        self.current_song: Song | None = None
        self._seeded = False
        self.pending_downloads: set[str] = set()

    def _pre_download_next(self) -> None:
        """Download the next queued song in a background thread if not cached."""
        if not self.queue:
            return
        song_id = self.queue[0].id
        path = MUSIC_DIR / f"{song_id}.mp3"
        if path.exists() or song_id in self.pending_downloads:
            return
        self.pending_downloads.add(song_id)
        t = threading.Thread(target=self._do_download, args=(song_id,), daemon=True)
        t.start()

    def _do_download(self, song_id: str) -> None:
        """Run download_song in a thread, tracking completion."""
        try:
            download_song(song_id)
        except Exception:  # noqa: BLE001
            logger.exception(f"Failed to pre-download {song_id}")
        finally:
            self.pending_downloads.discard(song_id)

    def _seed_from_charts(self) -> None:
        """Fetch trending charts and populate the database."""
        if self._seeded:
            return
        try:
            charts = self.yt.get_charts(country=CHARTS_COUNTRY)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to fetch charts")
            return
        if not charts or "videos" not in charts or not charts["videos"]:
            logger.warning("No charts data available")
            return
        playlist_id = charts["videos"][0]["playlistId"]
        try:
            playlist = self.yt.get_playlist(playlist_id, limit=50)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to fetch chart playlist")
            return
        with Session() as session:
            for track in playlist.get("tracks", []):
                if not isinstance(track, dict) or track.get("videoType") in NON_SONG_VIDEO_TYPES:
                    continue
                video_id = track.get("videoId")
                if not video_id:
                    continue
                title = track.get("title", "Unknown")
                artist_name = track["artists"][0]["name"] if track.get("artists") else "Unknown"
                if session.get(Song, video_id) is None:
                    session.add(Song(id=video_id, title=title, artist=artist_name))
            session.commit()
        with Session() as session:
            self.queue = list(session.scalars(select(Song)).all())
        self._seeded = True
        self._pre_download_next()

    def _refill_queue(self) -> None:
        """Fetch related recommendations and add new songs to the database."""
        seed_id: str | None = self.current_song.id if self.current_song else None
        if not seed_id:
            with Session() as session:
                first = session.scalars(select(Song).limit(1)).first()
                if first is not None:
                    seed_id = first.id
        if not seed_id:
            return
        try:
            playlist: dict[str, Any] = self.yt.get_watch_playlist(videoId=seed_id, limit=20)  # type: ignore[assignment]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to fetch watch playlist")
            return
        tracks: Any = playlist.get("tracks", [])
        if not isinstance(tracks, list):
            return
        with Session() as session:
            for track in tracks:
                if not isinstance(track, dict) or track.get("videoType") in NON_SONG_VIDEO_TYPES:
                    continue
                video_id: Any = track.get("videoId")
                if not video_id:
                    continue
                title: Any = track.get("title", "Unknown")
                artists: Any = track.get("artists")
                artist_name = artists[0]["name"] if isinstance(artists, list) and artists else "Unknown"
                if session.get(Song, video_id) is None:
                    session.add(Song(id=video_id, title=title, artist=artist_name))
            session.commit()
        with Session() as session:
            self.queue = list(session.scalars(select(Song)).all())
        self._pre_download_next()

    @staticmethod
    def song_score(song: Song) -> float:
        """Calculate a play-priority score for a song.

        Higher scores indicate songs the user is more likely to enjoy.
        """
        return song.complete_count - (song.skip_count * 2)

    def get_next_track(self, action: str = "next", elapsed: float = 0.0) -> TrackResponse:
        """Return the next track, recording feedback for the previous one."""
        self._seed_from_charts()

        if self.current_song is not None:
            with Session() as session:
                song = session.get(Song, self.current_song.id)
                if song is not None:
                    if action == "skip":
                        song.skip_count += 1
                        song.total_elapsed += elapsed
                    else:
                        song.complete_count += 1
                session.commit()

        if len(self.queue) < REFILL_THRESHOLD:
            self._refill_queue()

        if not self.queue:
            with Session() as session:
                self.queue = list(session.scalars(select(Song)).all())

        if not self.queue:
            raise HTTPException(status_code=404, detail="No tracks found")

        self.queue.sort(key=self.song_score, reverse=True)
        self.current_song = self.queue.pop(0)

        self._pre_download_next()

        return TrackResponse(
            id=self.current_song.id,
            title=self.current_song.title,
            artist=self.current_song.artist,
        )


radio = RadioStation()


def download_song(song_id: str) -> Path:
    """Download a song from YouTube."""
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }
        ],
        "outtmpl": f"{MUSIC_DIR}/%(id)s.%(ext)s",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={song_id}", download=False)
        pre_processed_path = ydl.prepare_filename(info)
        final_filename = Path(pre_processed_path).with_suffix(".mp3")
        ydl.process_info(info)
        return final_filename


app = FastAPI()


@app.get("/")
async def get_index() -> FileResponse:
    """Serve the index page."""
    return FileResponse(HERE / "index.html")


@app.post("/radio/next")
async def next_track(body: NextTrackRequest) -> TrackResponse:
    """Frontend calls this to skip or when a song ends. The server decides what plays next."""
    return radio.get_next_track(action=body.action, elapsed=body.elapsed)


@app.get("/audio/{song_id}")
async def get_audio(song_id: str) -> FileResponse:
    """Serves the raw file so the browser can buffer ahead."""
    path = MUSIC_DIR / f"{song_id}.mp3"
    if not path.exists():
        if song_id in radio.pending_downloads:
            for _ in range(30):
                await asyncio.sleep(1)
                if path.exists():
                    break
        if not path.exists():
            path = download_song(song_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="audio/mp3")


def main() -> int:
    """The main entry point for skip-radio."""
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger_ = logging.getLogger(name)
        logger_.handlers = [InterceptHandler()]
        logger_.propagate = False
        logger_.setLevel(logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)  # noqa: S104
    return 0
