"""Serialize raw Formula 1 data and calculate file checksums."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

PARQUET_ENGINE = "pyarrow"
PARQUET_COMPRESSION = "zstd"
CHECKSUM_CHUNK_SIZE = 1024 * 1024


def write_parquet_table(
    table: pd.DataFrame,
    path: Path,
) -> None:
    """Write a DataFrame as compressed Parquet without its index."""
    path = Path(path)
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    table.to_parquet(
        path,
        engine=PARQUET_ENGINE,
        compression=PARQUET_COMPRESSION,
        index=False,
    )


def read_parquet_table(path: Path) -> pd.DataFrame:
    """Read a Parquet table using PyArrow."""
    return pd.read_parquet(
        Path(path),
        engine=PARQUET_ENGINE,
    )


def write_json_document(
    document: Mapping[str, object],
    path: Path,
) -> None:
    """Write a deterministic UTF-8 JSON document."""
    path = Path(path)
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    serialized = json.dumps(
        document,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )

    path.write_text(
        f"{serialized}\n",
        encoding="utf-8",
    )


def read_json_document(path: Path) -> dict[str, object]:
    """Read a JSON document whose root must be an object."""
    document = json.loads(
        Path(path).read_text(encoding="utf-8")
    )

    if not isinstance(document, dict):
        raise TypeError("JSON document root must be an object")

    return document


def sha256_file(path: Path) -> str:
    """Calculate the SHA-256 checksum of one file."""
    digest = hashlib.sha256(usedforsecurity=False)

    with Path(path).open("rb") as file_stream:
        while chunk := file_stream.read(CHECKSUM_CHUNK_SIZE):
            digest.update(chunk)

    return digest.hexdigest()