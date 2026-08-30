from pathlib import Path

import pandas as pd
import pytest

from app.cleaning import (
    LapCleaningError,
    LapQualityReason,
    classify_laps,
)


def _valid_laps() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Season": [2024],
            "RoundNumber": [1],
            "SessionType": [" r "],
            "EventName": [" Bahrain Grand Prix "],
            "Driver": [" ver "],
            "Team": [" Red Bull Racing "],
            "LapNumber": [2.0],
            "LapTime": pd.to_timedelta(
                [90.5],
                unit="s",
            ),
            "Stint": [1.0],
            "Compound": [" soft "],
            "TyreLife": [2.0],
            "PitInTime": pd.to_timedelta(
                [None],
                unit="s",
            ),
            "PitOutTime": pd.to_timedelta(
                [None],
                unit="s",
            ),
            "Sector1Time": pd.to_timedelta(
                [30.0],
                unit="s",
            ),
            "Sector2Time": pd.to_timedelta(
                [30.2],
                unit="s",
            ),
            "Sector3Time": pd.to_timedelta(
                [30.3],
                unit="s",
            ),
            "TrackStatus": [" 1 "],
            "IsAccurate": [True],
            "IsPersonalBest": pd.Series(
                [None],
                dtype="object",
            ),
        }
    )


def _reason_codes(value: str) -> set[str]:
    if not value:
        return set()

    return set(value.split("|"))


def test_classifies_valid_lap_without_mutating_input(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    original_laps = raw_laps.copy(deep=True)

    result = classify_laps(raw_laps)
    repeated_result = classify_laps(raw_laps)

    pd.testing.assert_frame_equal(
        raw_laps,
        original_laps,
    )
    pd.testing.assert_frame_equal(
        result.laps,
        repeated_result.laps,
    )

    classified = result.laps.iloc[0]

    assert classified["SourceRowNumber"] == 0
    assert classified["SessionType"] == "R"
    assert classified["EventName"] == "Bahrain Grand Prix"
    assert classified["Driver"] == "VER"
    assert classified["Team"] == "Red Bull Racing"
    assert classified["Compound"] == "SOFT"
    assert classified["TrackStatus"] == "1"
    assert classified["LapTimeSeconds"] == pytest.approx(90.5)
    assert classified["Sector1TimeSeconds"] == pytest.approx(30.0)
    assert classified["Sector2TimeSeconds"] == pytest.approx(30.2)
    assert classified["Sector3TimeSeconds"] == pytest.approx(30.3)
    assert classified["QualityFlags"] == ""
    assert classified["ExclusionReasons"] == ""
    assert classified["QualityFlagCount"] == 0
    assert classified["ExclusionReasonCount"] == 0
    assert bool(classified["IsEligible"])

    assert str(result.laps["IsAccurate"].dtype) == "boolean"
    assert str(result.laps["IsPersonalBest"].dtype) == "boolean"
    assert result.input_count == 1
    assert result.eligible_count == 1
    assert result.flagged_count == 0
    assert result.excluded_count == 0
    assert all(
        count == 0
        for count in result.quality_counts.values()
    )


def test_records_multiple_quality_reasons(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    raw_laps.loc[0, "Driver"] = None
    raw_laps.loc[0, "LapTime"] = pd.NaT
    raw_laps.loc[0, "IsAccurate"] = False
    raw_laps.loc[0, "LapNumber"] = 1.0
    raw_laps.loc[0, "PitInTime"] = pd.to_timedelta(
        100,
        unit="s",
    )
    raw_laps.loc[0, "PitOutTime"] = pd.to_timedelta(
        110,
        unit="s",
    )
    raw_laps.loc[0, "TrackStatus"] = "X"
    raw_laps.loc[0, "Compound"] = "NONE"
    raw_laps.loc[0, "TyreLife"] = 0.0
    raw_laps.loc[0, "Sector1Time"] = pd.NaT

    result = classify_laps(raw_laps)
    classified = result.laps.iloc[0]

    expected_flags = {
        LapQualityReason.MISSING_IDENTITY.value,
        LapQualityReason.MISSING_LAP_TIME.value,
        LapQualityReason.INACCURATE_LAP.value,
        LapQualityReason.FIRST_LAP.value,
        LapQualityReason.PIT_IN_LAP.value,
        LapQualityReason.PIT_OUT_LAP.value,
        LapQualityReason.NON_GREEN_TRACK.value,
        LapQualityReason.UNSUPPORTED_COMPOUND.value,
        LapQualityReason.INVALID_TYRE_LIFE.value,
        LapQualityReason.MISSING_SECTOR_TIME.value,
        LapQualityReason.UNKNOWN_TRACK_STATUS.value,
    }
    expected_exclusions = (
        expected_flags
        - {
            LapQualityReason.MISSING_SECTOR_TIME.value,
        }
    )

    assert _reason_codes(
        classified["QualityFlags"]
    ) == expected_flags
    assert _reason_codes(
        classified["ExclusionReasons"]
    ) == expected_exclusions
    assert classified["QualityFlagCount"] == len(
        expected_flags
    )
    assert classified["ExclusionReasonCount"] == len(
        expected_exclusions
    )
    assert not bool(classified["IsEligible"])
    assert result.input_count == 1
    assert result.eligible_count == 0
    assert result.flagged_count == 1
    assert result.excluded_count == 1

    for reason in expected_flags:
        assert result.quality_counts[reason] == 1


def test_missing_sector_time_does_not_exclude_lap(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    raw_laps.loc[0, "Sector2Time"] = pd.NaT

    result = classify_laps(raw_laps)
    classified = result.laps.iloc[0]

    assert classified["QualityFlags"] == (
        LapQualityReason.MISSING_SECTOR_TIME.value
    )
    assert classified["ExclusionReasons"] == ""
    assert bool(classified["IsEligible"])
    assert result.flagged_count == 1
    assert result.eligible_count == 1
    assert result.excluded_count == 0


def test_wet_compound_excludes_lap(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    raw_laps.loc[0, "Compound"] = " intermediate "

    result = classify_laps(raw_laps)
    classified = result.laps.iloc[0]

    assert classified["Compound"] == "INTERMEDIATE"
    assert classified["QualityFlags"] == (
        LapQualityReason.WET_CONDITION.value
    )
    assert classified["ExclusionReasons"] == (
        LapQualityReason.WET_CONDITION.value
    )
    assert not bool(classified["IsEligible"])


def test_duplicate_lap_identities_are_all_excluded(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = (
        _valid_laps()
        .iloc[[0, 0]]
        .reset_index(drop=True)
    )

    result = classify_laps(raw_laps)

    assert result.input_count == 2
    assert result.eligible_count == 0
    assert result.flagged_count == 2
    assert result.excluded_count == 2
    assert result.quality_counts[
        LapQualityReason.DUPLICATE_LAP.value
    ] == 2
    assert result.laps["SourceRowNumber"].tolist() == [0, 1]
    assert result.laps["IsEligible"].eq(False).all()


def test_unknown_track_status_is_reported(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    raw_laps.loc[0, "TrackStatus"] = "18"

    result = classify_laps(raw_laps)
    classified = result.laps.iloc[0]
    flags = _reason_codes(classified["QualityFlags"])

    assert flags == {
        LapQualityReason.NON_GREEN_TRACK.value,
        LapQualityReason.UNKNOWN_TRACK_STATUS.value,
    }
    assert not bool(classified["IsEligible"])


def test_reports_missing_required_column(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps().drop(columns="Team")

    with pytest.raises(
        LapCleaningError,
        match="lap table is missing required columns: Team",
    ):
        classify_laps(raw_laps)


def test_rejects_non_timedelta_duration(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    raw_laps["LapTime"] = [90.5]

    with pytest.raises(
        LapCleaningError,
        match="LapTime must use a timedelta dtype",
    ):
        classify_laps(raw_laps)


def test_rejects_invalid_boolean_value(
    tmp_path: Path,
) -> None:
    del tmp_path

    raw_laps = _valid_laps()
    raw_laps["IsAccurate"] = pd.Series(
        ["definitely"],
        dtype="object",
    )

    with pytest.raises(
        LapCleaningError,
        match="IsAccurate contains invalid boolean values",
    ):
        classify_laps(raw_laps)