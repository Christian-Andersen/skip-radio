"""The main module for skip-radio."""

import logging
from pathlib import Path

import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


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


DATA_DIR = Path("./data/")
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
    """The User model representing the 'users' table."""

    __tablename__ = "songs"
    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)


engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
with Session() as session:
    try:
        session.add_all(
            [
                Song(id="SzJXikN_4wA", title="I Knew It, I Knew You", artist="Taylor Swift"),
                Song(id="oIv_Y2RPQ_A", title="Man I Need", artist="Olivia Dean"),
            ]
        )
        session.commit()
    except IntegrityError:
        pass


class TrackResponse(BaseModel):
    """Response model for a radio track."""

    id: str
    title: str
    artist: str


class RadioStation:
    """Manages the playlist of available tracks."""

    def __init__(self) -> None:
        """Scan the music directory for available tracks."""
        self.current_song = self._get_first_song()

    def _get_first_song(self) -> Song | None:
        """Get the first song, or `None` if there is not songs."""
        statement = select(Song).order_by(Song.id.asc())
        with Session() as session:
            return session.scalars(statement).first()

    def get_next_track(self) -> TrackResponse:
        """Return the next track in rotation."""
        if self.current_song is None:
            self.current_song = self._get_first_song()
        if self.current_song is None:
            raise HTTPException(status_code=404, detail="No tracks found")
        with Session() as session:
            statement = select(Song).where(Song.id > self.current_song.id).order_by(Song.id.asc())
            next_song = session.scalars(statement).first()
            if next_song is None:
                next_song = self._get_first_song()
        self.current_song = next_song
        if self.current_song is None:
            raise HTTPException(status_code=404, detail="No tracks found")
        return TrackResponse(id=self.current_song.id, title=self.current_song.title, artist=self.current_song.artist)


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
    return FileResponse("./src/skip_radio/index.html")


@app.post("/radio/next")
async def next_track() -> TrackResponse:
    """Frontend calls this to skip or when a song ends. The server decides what plays next."""
    return radio.get_next_track()


@app.get("/audio/{song_id}")
async def get_audio(song_id: str) -> FileResponse:
    """Serves the raw file so the browser can buffer ahead."""
    path = MUSIC_DIR / f"{song_id}.mp3"
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
