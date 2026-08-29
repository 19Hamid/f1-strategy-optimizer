"""Core models used by the historical-data pipeline."""

from dataclasses import dataclass

# FastF1 provides its complete detailed data backend from 2018 onward.
MIN_FULL_DATA_SEASON = 2018
MAX_REASONABLE_ROUND = 30
SUPPORTED_SESSION_TYPES = frozenset({"R"})


@dataclass(frozen=True, slots=True)
class SessionKey:
    """Uniquely identify one FastF1 session."""

    season: int
    round_number: int
    session_type: str = "R"

    def __post_init__(self) -> None:
        """Validate and normalize the session identity."""
        if isinstance(self.season, bool) or not isinstance(self.season, int):
            raise TypeError("season must be an integer")

        if (
            isinstance(self.round_number, bool)
            or not isinstance(self.round_number, int)
        ):
            raise TypeError("round_number must be an integer")

        if not isinstance(self.session_type, str):
            raise TypeError("session_type must be a string")

        normalized_session_type = self.session_type.strip().upper()

        if self.season < MIN_FULL_DATA_SEASON:
            raise ValueError(
                f"season must be at least {MIN_FULL_DATA_SEASON}"
            )

        if not 1 <= self.round_number <= MAX_REASONABLE_ROUND:
            raise ValueError(
                "round_number must be between "
                f"1 and {MAX_REASONABLE_ROUND}"
            )

        if normalized_session_type not in SUPPORTED_SESSION_TYPES:
            supported = ", ".join(sorted(SUPPORTED_SESSION_TYPES))
            raise ValueError(
                f"unsupported session_type; expected one of: {supported}"
            )

        object.__setattr__(
            self,
            "session_type",
            normalized_session_type,
        )

    @property
    def identifier(self) -> str:
        """Return a compact stable identifier."""
        return (
            f"{self.season}-"
            f"{self.round_number:02d}-"
            f"{self.session_type}"
        )

    @property
    def partition_parts(self) -> tuple[str, str, str]:
        """Return Hive-style directory partition names."""
        return (
            f"season={self.season}",
            f"round={self.round_number:02d}",
            f"session={self.session_type}",
        )