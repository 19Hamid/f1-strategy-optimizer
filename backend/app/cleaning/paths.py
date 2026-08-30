"""Generate paths for versioned processed Formula 1 datasets."""

from dataclasses import dataclass
from pathlib import Path

from app.cleaning.processing import CLEANING_RULE_VERSION
from app.pipeline.models import SessionKey


def _normalize_cleaning_rule_version(
    value: str,
) -> str:
    """Validate a cleaning-rule version used in a path."""
    if not isinstance(value, str):
        raise TypeError(
            "cleaning_rule_version must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            "cleaning_rule_version must not be empty"
        )

    if normalized in {".", ".."}:
        raise ValueError(
            "cleaning_rule_version must not be a relative path"
        )

    if (
        "/" in normalized
        or "\\" in normalized
        or Path(normalized).name != normalized
    ):
        raise ValueError(
            "cleaning_rule_version must be one path segment"
        )

    return normalized


@dataclass(frozen=True, slots=True)
class ProcessedSessionPaths:
    """Paths belonging to one processed race session."""

    processed_root: Path
    cleaning_rule_version: str
    session_key: SessionKey

    def __post_init__(self) -> None:
        """Normalize and validate path configuration."""
        if not isinstance(
            self.session_key,
            SessionKey,
        ):
            raise TypeError(
                "session_key must be a SessionKey"
            )

        object.__setattr__(
            self,
            "processed_root",
            Path(self.processed_root),
        )
        object.__setattr__(
            self,
            "cleaning_rule_version",
            _normalize_cleaning_rule_version(
                self.cleaning_rule_version
            ),
        )

    @property
    def version_root(self) -> Path:
        """Return the root for one cleaning-rule version."""
        return self.processed_root / (
            "cleaning_version="
            f"{self.cleaning_rule_version}"
        )

    @property
    def directory(self) -> Path:
        """Return the final processed session directory."""
        return self.version_root.joinpath(
            *self.session_key.partition_parts,
        )

    @property
    def temporary_directory(self) -> Path:
        """Return the temporary atomic-write directory."""
        return (
            self.version_root
            / ".tmp"
            / self.session_key.identifier
        )

    @property
    def backup_directory(self) -> Path:
        """Return the recoverable replacement directory."""
        return (
            self.version_root
            / ".backup"
            / self.session_key.identifier
        )

    @property
    def laps(self) -> Path:
        """Return the processed lap-table path."""
        return self.directory / "laps.parquet"

    @property
    def stints(self) -> Path:
        """Return the reconstructed stint-table path."""
        return self.directory / "stints.parquet"

    @property
    def pit_events(self) -> Path:
        """Return the reconstructed pit-event path."""
        return self.directory / "pit_events.parquet"

    @property
    def quality_report(self) -> Path:
        """Return the session quality-report path."""
        return self.directory / "quality_report.json"

    @property
    def manifest(self) -> Path:
        """Return the completed processing-manifest path."""
        return self.directory / "manifest.json"

    @property
    def table_paths(self) -> dict[str, Path]:
        """Return the authoritative processed tables."""
        return {
            "laps": self.laps,
            "stints": self.stints,
            "pit_events": self.pit_events,
        }


@dataclass(frozen=True, slots=True)
class ProcessedDataPaths:
    """Top-level paths for the processed FastF1 dataset."""

    processed_root: Path
    cleaning_rule_version: str = (
        CLEANING_RULE_VERSION
    )

    def __post_init__(self) -> None:
        """Normalize and validate path configuration."""
        object.__setattr__(
            self,
            "processed_root",
            Path(self.processed_root),
        )
        object.__setattr__(
            self,
            "cleaning_rule_version",
            _normalize_cleaning_rule_version(
                self.cleaning_rule_version
            ),
        )

    @property
    def version_root(self) -> Path:
        """Return the configured versioned dataset root."""
        return self.processed_root / (
            "cleaning_version="
            f"{self.cleaning_rule_version}"
        )

    @property
    def catalog(self) -> Path:
        """Return the processed dataset-catalog path."""
        return self.version_root / "catalog.parquet"

    @property
    def runs_directory(self) -> Path:
        """Return the processing-run record directory."""
        return self.version_root / "runs"

    def for_session(
        self,
        session_key: SessionKey,
    ) -> ProcessedSessionPaths:
        """Build paths for one processed session."""
        return ProcessedSessionPaths(
            processed_root=self.processed_root,
            cleaning_rule_version=(
                self.cleaning_rule_version
            ),
            session_key=session_key,
        )