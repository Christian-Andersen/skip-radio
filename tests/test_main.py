"""Tests for the main module."""

from __future__ import annotations

import importlib

skip_radio_main = importlib.import_module("skip_radio.main")


def test_import() -> None:
    """Test that the module can be imported."""
    assert skip_radio_main is not None  # noqa: S101


def test_song_model_has_skip_fields() -> None:
    """Verify Song model has the skip-tracking columns."""
    assert hasattr(skip_radio_main.Song, "skip_count")  # noqa: S101
    assert hasattr(skip_radio_main.Song, "complete_count")  # noqa: S101
    assert hasattr(skip_radio_main.Song, "total_elapsed")  # noqa: S101


def test_score_prefers_completed_songs() -> None:
    """A completed song scores higher than a skipped song."""
    completed = skip_radio_main.Song(
        id="c",
        title="c",
        artist="c",
        complete_count=5,
        skip_count=0,
    )
    skipped = skip_radio_main.Song(
        id="s",
        title="s",
        artist="s",
        complete_count=0,
        skip_count=5,
    )
    assert skip_radio_main.RadioStation.song_score(completed) > skip_radio_main.RadioStation.song_score(skipped)  # noqa: S101


def test_score_demotes_frequent_skips() -> None:
    """Skip weight (2x) means one skip cancels two completions."""
    song = skip_radio_main.Song(
        id="x",
        title="x",
        artist="x",
        complete_count=2,
        skip_count=1,
    )
    assert skip_radio_main.RadioStation.song_score(song) == 0.0  # noqa: S101
