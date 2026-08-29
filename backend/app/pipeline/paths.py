"""Path generation for raw Formula 1 datasets."""

from dataclasses import dataclass
from pathlib import Path

from app.pipeline.models import SessionKey


@dataclass(frozen=True, slots=True)
class SessionPaths:
    """Paths belonging to one extracted FastF1 session."""

    raw_root: Path
    session_key: SessionKey

    @property
    def directory(self) -> Path:
        """Return the final session directory."""
        return self.raw_root.joinpath(
            *self.session_key.partition_parts,
        )

    @property
    def temporary_directory(self) -> Path:
        """Return the temporary extraction directory."""
        return (
            self.raw_root
            / ".tmp"
            / self.session_key.identifier
        )

    @property
    def laps(self) -> Path:
        """Return the lap-table path."""
        return self.directory / "laps.parquet"

    @property
    def weather(self) -> Path:
        """Return the weather-table path."""
        return self.directory / "weather.parquet"

    @property
    def results(self) -> Path:
        """Return the results-table path."""
        return self.directory / "results.parquet"

    @property
    def metadata(self) -> Path:
        """Return the session-metadata path."""
        return self.directory / "metadata.json"

    @property
    def manifest(self) -> Path:
        """Return the completed extraction-manifest path."""
        return self.directory / "manifest.json"

    @property
    def table_paths(self) -> dict[str, Path]:
        """Return the expected Parquet table paths."""
        return {
            "laps": self.laps,
            "weather": self.weather,
            "results": self.results,
        }


@dataclass(frozen=True, slots=True)
class RawDataPaths:
    """Top-level paths for the FastF1 raw dataset."""

    raw_root: Path

    def __post_init__(self) -> None:
        """Normalize the configured root path."""
        object.__setattr__(
            self,
            "raw_root",
            Path(self.raw_root),
        )

    @property
    def catalog(self) -> Path:
        """Return the dataset-catalog path."""
        return self.raw_root / "catalog.parquet"

    @property
    def runs_directory(self) -> Path:
        """Return the pipeline-run record directory."""
        return self.raw_root / "runs"

    def for_session(self, session_key: SessionKey) -> SessionPaths:
        """Build paths for one session."""
        return SessionPaths(
            raw_root=self.raw_root,
            session_key=session_key,
        )