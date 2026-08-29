"""Configuration for historical Formula 1 data extraction."""

from dataclasses import dataclass

from app.pipeline.models import SessionKey

DEVELOPMENT_SEASONS = (2022, 2023, 2024)
EVALUATION_SEASONS = (2025,)
CORE_STUDY_SEASONS = DEVELOPMENT_SEASONS + EVALUATION_SEASONS

MIN_STUDY_SEASON = min(CORE_STUDY_SEASONS)
MAX_STUDY_SEASON = max(CORE_STUDY_SEASONS)


@dataclass(frozen=True, slots=True)
class ExtractionPlan:
    """Describe which seasons and data types should be extracted."""

    seasons: tuple[int, ...] = CORE_STUDY_SEASONS
    session_type: str = "R"
    include_telemetry: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize the extraction plan."""
        if not isinstance(self.seasons, tuple):
            raise TypeError("seasons must be provided as a tuple")

        if not self.seasons:
            raise ValueError("at least one season must be selected")

        for season in self.seasons:
            if isinstance(season, bool) or not isinstance(season, int):
                raise TypeError("every season must be an integer")

            if season not in CORE_STUDY_SEASONS:
                raise ValueError(
                    "V1 seasons must be between "
                    f"{MIN_STUDY_SEASON} and {MAX_STUDY_SEASON}"
                )

        if len(set(self.seasons)) != len(self.seasons):
            raise ValueError("seasons must not contain duplicates")

        if not isinstance(self.include_telemetry, bool):
            raise TypeError("include_telemetry must be a boolean")

        normalized_seasons = tuple(sorted(self.seasons))

        normalized_session_type = SessionKey(
            season=normalized_seasons[0],
            round_number=1,
            session_type=self.session_type,
        ).session_type

        object.__setattr__(self, "seasons", normalized_seasons)
        object.__setattr__(
            self,
            "session_type",
            normalized_session_type,
        )

    @property
    def is_core_study(self) -> bool:
        """Return whether the plan covers the complete V1 study period."""
        return self.seasons == CORE_STUDY_SEASONS