"""Generate paths for versioned Formula 1 modelling datasets."""

from dataclasses import dataclass
from pathlib import Path

from app.datasets.contracts import (
    DATASET_CONTRACT_VERSION,
    DATASET_DIRECTORY_NAME,
    DEVELOPMENT_SEASONS,
    PROTECTED_EVALUATION_SEASON,
)
from app.pipeline import SessionKey


def _normalize_path_segment(
    value: str,
    *,
    field_name: str,
) -> str:
    """Validate one user-controlled path segment."""
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must not be empty"
        )

    if normalized in {".", ".."}:
        raise ValueError(
            f"{field_name} must not be a relative path"
        )

    if (
        "/" in normalized
        or "\\" in normalized
        or Path(normalized).name != normalized
    ):
        raise ValueError(
            f"{field_name} must be one path segment"
        )

    return normalized


def _normalize_dataset_contract_version(
    value: str,
) -> str:
    """Validate a dataset-contract version used in a path."""
    return _normalize_path_segment(
        value,
        field_name="dataset_contract_version",
    )


def _validate_development_session_key(
    session_key: SessionKey,
) -> None:
    """Require one supported development race identity."""
    if not isinstance(session_key, SessionKey):
        raise TypeError(
            "session_key must be a SessionKey"
        )

    if session_key.season == (
        PROTECTED_EVALUATION_SEASON
    ):
        raise ValueError(
            f"{session_key.identifier} belongs to the "
            "protected evaluation season"
        )

    if session_key.season not in DEVELOPMENT_SEASONS:
        raise ValueError(
            f"{session_key.identifier} is outside the "
            "development seasons"
        )

    if session_key.session_type != "R":
        raise ValueError(
            f"{session_key.identifier} is not a race session"
        )


@dataclass(frozen=True, slots=True)
class DatasetSessionPaths:
    """Paths belonging to one modelling-dataset race session."""

    datasets_root: Path
    dataset_contract_version: str
    session_key: SessionKey

    def __post_init__(self) -> None:
        """Normalize and validate path configuration."""
        _validate_development_session_key(
            self.session_key
        )
        object.__setattr__(
            self,
            "datasets_root",
            Path(self.datasets_root),
        )
        object.__setattr__(
            self,
            "dataset_contract_version",
            _normalize_dataset_contract_version(
                self.dataset_contract_version
            ),
        )

    @property
    def dataset_root(self) -> Path:
        """Return the root shared by all contract versions."""
        return (
            self.datasets_root
            / DATASET_DIRECTORY_NAME
        )

    @property
    def version_root(self) -> Path:
        """Return the root for one dataset-contract version."""
        return self.dataset_root / (
            "dataset_contract_version="
            f"{self.dataset_contract_version}"
        )

    @property
    def relative_directory(self) -> Path:
        """Return the session partition relative to its version root."""
        return Path(*self.session_key.partition_parts)

    @property
    def directory(self) -> Path:
        """Return the authoritative session directory."""
        return (
            self.version_root
            / self.relative_directory
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
    def decision_rows(self) -> Path:
        """Return the leakage-controlled decision-row path."""
        return (
            self.directory
            / "decision_rows.parquet"
        )

    @property
    def decision_labels(self) -> Path:
        """Return the separated decision-label path."""
        return (
            self.directory
            / "decision_labels.parquet"
        )

    @property
    def pit_duration_observations(self) -> Path:
        """Return the separated pit-duration target path."""
        return (
            self.directory
            / "pit_duration_observations.parquet"
        )

    @property
    def quality_report(self) -> Path:
        """Return the session quality-report path."""
        return self.directory / "quality_report.json"

    @property
    def manifest(self) -> Path:
        """Return the completed dataset-manifest path."""
        return self.directory / "manifest.json"

    @property
    def table_paths(self) -> dict[str, Path]:
        """Return all authoritative session tables."""
        return {
            "decision_rows": self.decision_rows,
            "decision_labels": self.decision_labels,
            "pit_duration_observations": (
                self.pit_duration_observations
            ),
        }

    @property
    def document_paths(self) -> dict[str, Path]:
        """Return authoritative session JSON documents."""
        return {
            "quality_report": self.quality_report,
            "manifest": self.manifest,
        }


@dataclass(frozen=True, slots=True)
class DatasetPaths:
    """Top-level paths for modelling-dataset artifacts."""

    datasets_root: Path
    dataset_contract_version: str = (
        DATASET_CONTRACT_VERSION
    )

    def __post_init__(self) -> None:
        """Normalize and validate path configuration."""
        object.__setattr__(
            self,
            "datasets_root",
            Path(self.datasets_root),
        )
        object.__setattr__(
            self,
            "dataset_contract_version",
            _normalize_dataset_contract_version(
                self.dataset_contract_version
            ),
        )

    @property
    def dataset_root(self) -> Path:
        """Return the named modelling-dataset root."""
        return (
            self.datasets_root
            / DATASET_DIRECTORY_NAME
        )

    @property
    def version_root(self) -> Path:
        """Return the configured versioned dataset root."""
        return self.dataset_root / (
            "dataset_contract_version="
            f"{self.dataset_contract_version}"
        )

    @property
    def catalog(self) -> Path:
        """Return the global dataset-catalog path."""
        return self.version_root / "catalog.parquet"

    @property
    def splits(self) -> Path:
        """Return the frozen temporal-split path."""
        return self.version_root / "splits.parquet"

    @property
    def runs_directory(self) -> Path:
        """Return the dataset-build run-record directory."""
        return self.version_root / "runs"

    def run_record(
        self,
        run_id: str,
    ) -> Path:
        """Return one validated run-record path."""
        normalized_run_id = _normalize_path_segment(
            run_id,
            field_name="run_id",
        )
        return (
            self.runs_directory
            / f"{normalized_run_id}.json"
        )

    def for_session(
        self,
        session_key: SessionKey,
    ) -> DatasetSessionPaths:
        """Build paths for one development race session."""
        return DatasetSessionPaths(
            datasets_root=self.datasets_root,
            dataset_contract_version=(
                self.dataset_contract_version
            ),
            session_key=session_key,
        )