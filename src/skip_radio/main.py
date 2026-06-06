from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
import yt_dlp
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

# from platformdirs import user_cache_path, user_config_path

if TYPE_CHECKING:
    from collections.abc import Generator

CURRENT_FORMAT = {"codec": "m4a", "media_type": "audio/mp4", "ydl_format": "m4a/bestaudio/best"}
# CURRENT_FORMAT = {"codec": "mp3", "media_type": "audio/mp3", "ydl_format": "bestaudio/best"}
# CURRENT_FORMAT = {"codec": "opus", "media_type": "audio/ogg", "ydl_format": "bestaudio/best"}

ydl_opts = {
    "format": CURRENT_FORMAT["ydl_format"],
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": CURRENT_FORMAT["codec"],
        }
    ],
    "outtmpl": f"downloads/%(id)s.{CURRENT_FORMAT['codec']}",
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download(["https://www.youtube.com/watch?v=SzJXikN_4wA"])
app = FastAPI()


@app.get("/")
async def get_index() -> FileResponse:
    return FileResponse("./src/skip_radio/index.html")


def audio_streamer() -> Generator[bytes]:
    for path in Path("./data/").iterdir():
        with path.open("rb") as f:
            while chunk := f.read(1024 * 64):
                yield chunk


@app.get("/stream")
async def stream_audio() -> StreamingResponse:
    return StreamingResponse(audio_streamer(), media_type="audio/mp3")


def main() -> int:
    """The main entry point for skip-radio."""
    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
    return 0
