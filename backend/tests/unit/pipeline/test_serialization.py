"""Tests for raw-data serialization utilities."""

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
    sha256_file,
    write_json_document,
    write_parquet_table,
)


def test_parquet_round_trip_preserves_table(
    tmp_path: Path,
) -> None:
    original = pd.DataFrame(
        {
            "Driver": ["VER", "HAM"],
            "LapNumber": [1.0, 2.0],
            "LapTime": [
                pd.Timedelta(95, unit="s"),
                pd.Timedelta(96, unit="s"),
            ],
            "Rainfall": [False, True],
        }
    )
    path = tmp_path / "nested" / "laps.parquet"

    write_parquet_table(original, path)
    restored = read_parquet_table(path)

    assert path.is_file()
    pd.testing.assert_frame_equal(
        restored,
        original,
    )


def test_json_round_trip_preserves_document(
    tmp_path: Path,
) -> None:
    document: dict[str, object] = {
        "session_id": "2024-01-R",
        "rows": 1129,
        "valid": True,
        "files": {
            "laps": "laps.parquet",
            "weather": "weather.parquet",
        },
    }
    path = tmp_path / "nested" / "metadata.json"

    write_json_document(document, path)
    restored = read_json_document(path)

    assert restored == document
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_rejects_json_with_non_object_root(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        "[1, 2, 3]\n",
        encoding="utf-8",
    )

    with pytest.raises(
        TypeError,
        match="root must be an object",
    ):
        read_json_document(path)


def test_calculates_sha256_checksum(
    tmp_path: Path,
) -> None:
    content = b"Formula 1 race strategy"
    path = tmp_path / "sample.bin"
    path.write_bytes(content)

    expected = hashlib.sha256(
        content,
        usedforsecurity=False,
    ).hexdigest()

    assert sha256_file(path) == expected