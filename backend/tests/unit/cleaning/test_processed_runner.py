"""Tests for processed-session pipeline execution."""

from pathlib import Path

import pandas as pd
import pytest

import app.cleaning.runner as runner_module
from app.cleaning.integrity import (
    verify_processed_partition,
)
from app.cleaning.paths import ProcessedDataPaths
from app.cleaning.processing import (
    PROCESSED_CONTRACT_VERSION,
    ProcessedSessionData,
)
from app.cleaning.runner import (
    ProcessedPipelineError,
    ProcessedPipelineRunner,
)
from app.cleaning.storage import (
    ProcessedSessionWriter,
)
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths


class PassingRawIntegrity:
    """Represent a valid raw partition in runner tests."""

    def raise_for_errors(self) -> None:
        """Accept the simulated raw partition."""


class FailingRawIntegrity:
    """Represent an invalid raw partition in runner tests."""

    def raise_for_errors(self) -> None:
        """Reject the simulated raw partition."""
        raise RuntimeError(
            "raw integrity failed"
        )


def make_processed_data() -> ProcessedSessionData:
    """Build one valid processed-session fixture."""
    session_key = SessionKey(2024, 1)

    laps = pd.DataFrame(
        {
            "Season": [2024, 2024],
            "RoundNumber": [1, 1],
            "SessionType": ["R", "R"],
            "EventName": [
                "Bahrain Grand Prix",
                "Bahrain Grand Prix",
            ],
            "Driver": ["VER", "VER"],
            "LapNumber": [1.0, 2.0],
            "IsEligible": [False, True],
            "QualityReasons": [
                "FIRST_LAP",
                "",
            ],
            "Rainfall": [False, False],
        }
    )

    stints = pd.DataFrame(
        {
            "season": [2024],
            "round_number": [1],
            "session_type": ["R"],
            "event_name": [
                "Bahrain Grand Prix"
            ],
            "driver": ["VER"],
            "stint_number": [1],
            "recorded_laps": [2],
            "is_complete": [True],
            "warnings": [""],
        }
    )

    pit_events = pd.DataFrame(
        {
            "pit_event_id": [
                "2024-01-R-VER-P001"
            ],
            "season": [2024],
            "round_number": [1],
            "session_type": ["R"],
            "event_name": [
                "Bahrain Grand Prix"
            ],
            "driver": ["VER"],
            "pit_in_lap": [1.0],
            "pit_out_lap": [2.0],
            "is_complete": [True],
            "entry_rainfall": [False],
            "exit_rainfall": [False],
            "is_dry_weather_pair": [True],
            "is_duration_analysis_candidate": [
                True
            ],
            "warnings": [""],
        }
    )

    quality_report: dict[str, object] = {
        "processed_contract_version": (
            PROCESSED_CONTRACT_VERSION
        ),
        "cleaning_rule_version": "1.0",
        "source_contract_version": "1.0",
        "session": {
            "identifier": session_key.identifier,
            "season": session_key.season,
            "round_number": (
                session_key.round_number
            ),
            "session_type": (
                session_key.session_type
            ),
            "event_name": (
                "Bahrain Grand Prix"
            ),
        },
        "tables": {
            "laps_rows": len(laps),
            "stints_rows": len(stints),
            "pit_events_rows": len(
                pit_events
            ),
        },
        "validation": {
            "status": "passed",
        },
    }

    return ProcessedSessionData(
        session_key=session_key,
        laps=laps,
        stints=stints,
        pit_events=pit_events,
        quality_report=quality_report,
    )


def make_runner(
    tmp_path: Path,
) -> ProcessedPipelineRunner:
    """Build a runner with isolated roots."""
    return ProcessedPipelineRunner(
        raw_paths=RawDataPaths(
            tmp_path / "raw"
        ),
        processed_paths=ProcessedDataPaths(
            tmp_path / "processed"
        ),
    )


def install_passing_raw_pipeline(
    *,
    monkeypatch: pytest.MonkeyPatch,
    data: ProcessedSessionData,
) -> dict[str, int]:
    """Install successful raw and processing fakes."""
    calls = {
        "raw_verify": 0,
        "raw_read": 0,
        "process": 0,
    }

    def fake_verify_session_partition(
        raw_paths: RawDataPaths,
        session_key: SessionKey,
    ) -> PassingRawIntegrity:
        assert isinstance(
            raw_paths,
            RawDataPaths,
        )
        assert session_key == data.session_key

        calls["raw_verify"] += 1

        return PassingRawIntegrity()

    def fake_read_parquet_table(
        path: Path,
    ) -> pd.DataFrame:
        calls["raw_read"] += 1

        if path.name == "laps.parquet":
            return pd.DataFrame(
                {
                    "source": ["laps"],
                }
            )

        if path.name == "weather.parquet":
            return pd.DataFrame(
                {
                    "source": ["weather"],
                }
            )

        raise AssertionError(
            f"unexpected raw path: {path}"
        )

    def fake_process_session_tables(
        session_key: SessionKey,
        laps: pd.DataFrame,
        weather: pd.DataFrame,
    ) -> ProcessedSessionData:
        assert session_key == data.session_key
        assert laps["source"].tolist() == [
            "laps"
        ]
        assert weather["source"].tolist() == [
            "weather"
        ]

        calls["process"] += 1

        return data

    monkeypatch.setattr(
        runner_module,
        "verify_session_partition",
        fake_verify_session_partition,
    )
    monkeypatch.setattr(
        runner_module,
        "read_parquet_table",
        fake_read_parquet_table,
    )
    monkeypatch.setattr(
        runner_module,
        "process_session_tables",
        fake_process_session_tables,
    )

    return calls


def install_forbidden_raw_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail immediately if a cheap skip touches raw data."""
    def forbidden_verify(
        raw_paths: RawDataPaths,
        session_key: SessionKey,
    ) -> None:
        del raw_paths, session_key

        pytest.fail(
            "verified processed skip touched raw integrity"
        )

    def forbidden_read(
        path: Path,
    ) -> pd.DataFrame:
        del path

        pytest.fail(
            "verified processed skip read raw data"
        )

    def forbidden_process(
        session_key: SessionKey,
        laps: pd.DataFrame,
        weather: pd.DataFrame,
    ) -> ProcessedSessionData:
        del session_key, laps, weather

        pytest.fail(
            "verified processed skip ran processing"
        )

    monkeypatch.setattr(
        runner_module,
        "verify_session_partition",
        forbidden_verify,
    )
    monkeypatch.setattr(
        runner_module,
        "read_parquet_table",
        forbidden_read,
    )
    monkeypatch.setattr(
        runner_module,
        "process_session_tables",
        forbidden_process,
    )


def test_skips_verified_partition_before_raw_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed partition must skip all raw work."""
    data = make_processed_data()
    runner = make_runner(tmp_path)

    written = ProcessedSessionWriter(
        runner.processed_paths
    ).write(data)

    install_forbidden_raw_pipeline(
        monkeypatch
    )

    result = runner.run_session(
        data.session_key
    )

    assert result.status == "skipped"
    assert result.directory == written.directory
    assert result.manifest == written.manifest


def test_processes_and_then_cheaply_skips_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing output is built once and then resumed cheaply."""
    data = make_processed_data()
    runner = make_runner(tmp_path)

    calls = install_passing_raw_pipeline(
        monkeypatch=monkeypatch,
        data=data,
    )

    first = runner.run_session(
        data.session_key
    )
    second = runner.run_session(
        data.session_key
    )

    assert first.status == "written"
    assert second.status == "skipped"

    assert calls == {
        "raw_verify": 1,
        "raw_read": 2,
        "process": 1,
    }

    integrity = verify_processed_partition(
        runner.processed_paths,
        data.session_key,
    )

    assert integrity.is_valid


def test_blocks_corrupt_partition_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corruption must block instead of being overwritten."""
    data = make_processed_data()
    runner = make_runner(tmp_path)

    result = ProcessedSessionWriter(
        runner.processed_paths
    ).write(data)

    with (
        result.directory / "laps.parquet"
    ).open("ab") as stream:
        stream.write(b"corruption")

    install_forbidden_raw_pipeline(
        monkeypatch
    )

    with pytest.raises(
        ProcessedPipelineError,
        match=r"Use force=True",
    ):
        runner.run_session(
            data.session_key
        )


def test_force_rebuilds_corrupt_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A controlled force rebuild must repair corruption."""
    data = make_processed_data()
    runner = make_runner(tmp_path)

    result = ProcessedSessionWriter(
        runner.processed_paths
    ).write(data)

    with (
        result.directory / "laps.parquet"
    ).open("ab") as stream:
        stream.write(b"corruption")

    calls = install_passing_raw_pipeline(
        monkeypatch=monkeypatch,
        data=data,
    )

    rebuilt = runner.run_session(
        data.session_key,
        force=True,
    )

    assert rebuilt.status == "written"
    assert calls == {
        "raw_verify": 1,
        "raw_read": 2,
        "process": 1,
    }

    integrity = verify_processed_partition(
        runner.processed_paths,
        data.session_key,
    )

    assert integrity.is_valid


def test_blocks_incomplete_processed_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incomplete output requires an explicit force rebuild."""
    data = make_processed_data()
    runner = make_runner(tmp_path)

    session_paths = (
        runner.processed_paths.for_session(
            data.session_key
        )
    )
    session_paths.directory.mkdir(
        parents=True
    )

    install_forbidden_raw_pipeline(
        monkeypatch
    )

    with pytest.raises(
        ProcessedPipelineError,
        match="MISSING_MANIFEST",
    ):
        runner.run_session(
            data.session_key
        )


def test_propagates_raw_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid raw data must stop before table loading."""
    data = make_processed_data()
    runner = make_runner(tmp_path)

    def fake_verify_session_partition(
        raw_paths: RawDataPaths,
        session_key: SessionKey,
    ) -> FailingRawIntegrity:
        del raw_paths, session_key

        return FailingRawIntegrity()

    def forbidden_read(
        path: Path,
    ) -> pd.DataFrame:
        del path

        pytest.fail(
            "invalid raw partition was read"
        )

    monkeypatch.setattr(
        runner_module,
        "verify_session_partition",
        fake_verify_session_partition,
    )
    monkeypatch.setattr(
        runner_module,
        "read_parquet_table",
        forbidden_read,
    )

    with pytest.raises(
        RuntimeError,
        match="raw integrity failed",
    ):
        runner.run_session(
            data.session_key
        )


def test_rejects_invalid_runner_dependencies(
    tmp_path: Path,
) -> None:
    """Runner roots must use their validated path models."""
    raw_paths = RawDataPaths(
        tmp_path / "raw"
    )
    processed_paths = ProcessedDataPaths(
        tmp_path / "processed"
    )

    with pytest.raises(TypeError):
        ProcessedPipelineRunner(
            raw_paths=tmp_path,  # type: ignore[arg-type]
            processed_paths=processed_paths,
        )

    with pytest.raises(TypeError):
        ProcessedPipelineRunner(
            raw_paths=raw_paths,
            processed_paths=tmp_path,  # type: ignore[arg-type]
        )


def test_rejects_invalid_run_arguments(
    tmp_path: Path,
) -> None:
    """Session identity and force must be explicit types."""
    runner = make_runner(tmp_path)

    with pytest.raises(TypeError):
        runner.run_session(
            "2024-01-R",  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        runner.run_session(
            SessionKey(2024, 1),
            force=1,  # type: ignore[arg-type]
        )