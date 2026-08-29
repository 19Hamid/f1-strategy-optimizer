"""End-to-end audit of the Phase 2 raw-data pipeline."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.pipeline.batch import RawBatchRunner
from app.pipeline.catalog import RawCatalogBuilder
from app.pipeline.integrity import verify_session_partition
from app.pipeline.models import SessionKey
from app.pipeline.paths import RawDataPaths
from app.pipeline.runner import RawPipelineRunner
from app.pipeline.serialization import (
    read_json_document,
    read_parquet_table,
)
from app.pipeline.source import RawSessionData
from app.pipeline.telemetry import (
    TelemetryDataPaths,
    TelemetryRequest,
)
from app.pipeline.telemetry_source import TelemetryLapData
from app.pipeline.telemetry_storage import TelemetryWriter


@dataclass(slots=True)
class FakeRawSource:
    """Return complete raw sessions without network access."""

    sessions: dict[SessionKey, RawSessionData]
    calls: list[SessionKey] = field(
        default_factory=list
    )

    def extract(
        self,
        session_key: SessionKey,
    ) -> RawSessionData:
        """Return the selected fake session."""
        self.calls.append(session_key)
        return self.sessions[session_key]


def make_raw_session(
    session_key: SessionKey,
    event_name: str,
) -> RawSessionData:
    """Create one contract-valid raw race session."""
    provenance: dict[str, object] = {
        "Season": session_key.season,
        "RoundNumber": session_key.round_number,
        "SessionType": session_key.session_type,
        "EventName": event_name,
    }

    pit_time = pd.Series(
        [pd.NaT],
        dtype="timedelta64[ns]",
    )

    laps = pd.DataFrame(
        {
            **{
                column: [value]
                for column, value in provenance.items()
            },
            "Driver": ["VER"],
            "Team": ["Red Bull Racing"],
            "LapNumber": [1.0],
            "LapTime": pd.to_timedelta(
                [95.0],
                unit="s",
            ),
            "Stint": [1.0],
            "Compound": ["SOFT"],
            "TyreLife": [1.0],
            "PitInTime": pit_time,
            "PitOutTime": pit_time.copy(),
            "TrackStatus": ["1"],
            "LapStartTime": pd.to_timedelta(
                [0.0],
                unit="s",
            ),
        }
    )

    weather = pd.DataFrame(
        {
            **{
                column: [value]
                for column, value in provenance.items()
            },
            "Time": pd.to_timedelta(
                [0.0],
                unit="s",
            ),
            "AirTemp": [25.0],
            "TrackTemp": [35.0],
            "Humidity": [40.0],
            "Pressure": [1010.0],
            "Rainfall": [False],
            "WindDirection": [180],
            "WindSpeed": [2.5],
        }
    )

    results = pd.DataFrame(
        {
            **{
                column: [value]
                for column, value in provenance.items()
            },
            "Abbreviation": ["VER"],
            "TeamName": ["Red Bull Racing"],
            "Position": [1.0],
            "ClassifiedPosition": ["1"],
            "GridPosition": [1.0],
            "Status": ["Finished"],
            "Points": [25.0],
        }
    )

    metadata: dict[str, object] = {
        "season": session_key.season,
        "round_number": session_key.round_number,
        "session_type": session_key.session_type,
        "event_name": event_name,
        "telemetry_loaded": False,
        "fastf1_version": "integration-test",
    }

    return RawSessionData(
        session_key=session_key,
        laps=laps,
        weather=weather,
        results=results,
        metadata=metadata,
    )


def write_unrelated_telemetry(
    raw_root: Path,
    session_key: SessionKey,
) -> None:
    """Store telemetry beside raw sessions for catalog isolation."""
    request = TelemetryRequest(
        session_key=session_key,
        driver="VER",
        lap_number=1,
    )

    telemetry = pd.DataFrame(
        {
            "Season": [session_key.season],
            "RoundNumber": [
                session_key.round_number
            ],
            "SessionType": [
                session_key.session_type
            ],
            "EventName": [
                "Bahrain Grand Prix"
            ],
            "Driver": ["VER"],
            "LapNumber": [1],
            "Speed": [250.0],
        }
    )

    data = TelemetryLapData(
        request=request,
        telemetry=telemetry,
        metadata={
            "telemetry_id": request.identifier,
            "session_id": session_key.identifier,
            "event_name": "Bahrain Grand Prix",
            "sample_count": len(telemetry),
        },
    )

    TelemetryWriter(
        TelemetryDataPaths(
            raw_root=raw_root,
        )
    ).write(data)


def test_phase_two_raw_pipeline_end_to_end(
    tmp_path: Path,
) -> None:
    """Audit the complete raw-session pipeline lifecycle."""
    raw_root = tmp_path / "raw"
    raw_paths = RawDataPaths(raw_root)

    bahrain_key = SessionKey(2024, 1)
    saudi_key = SessionKey(2024, 2)

    source = FakeRawSource(
        sessions={
            bahrain_key: make_raw_session(
                bahrain_key,
                "Bahrain Grand Prix",
            ),
            saudi_key: make_raw_session(
                saudi_key,
                "Saudi Arabian Grand Prix",
            ),
        }
    )

    session_runner = RawPipelineRunner(
        raw_paths=raw_paths,
        source=source,
    )
    batch_runner = RawBatchRunner(
        raw_paths=raw_paths,
        session_runner=session_runner,
    )

    first_batch = batch_runner.run(
        (
            bahrain_key,
            saudi_key,
        )
    )

    assert first_batch.succeeded
    assert first_batch.written_count == 2
    assert first_batch.skipped_count == 0
    assert first_batch.failed_count == 0
    assert first_batch.record_path.is_file()
    assert source.calls == [
        bahrain_key,
        saudi_key,
    ]

    run_document = read_json_document(
        first_batch.record_path
    )

    assert run_document["run_id"] == first_batch.run_id

    for session_key in (
        bahrain_key,
        saudi_key,
    ):
        integrity = verify_session_partition(
            raw_paths,
            session_key,
        )

        assert integrity.is_valid
        assert integrity.issues == ()

    write_unrelated_telemetry(
        raw_root,
        bahrain_key,
    )

    catalog_result = RawCatalogBuilder(
        raw_paths
    ).build()
    catalog = read_parquet_table(
        catalog_result.path
    )

    assert catalog_result.session_count == 2
    assert catalog["session_id"].is_unique
    assert catalog["session_id"].tolist() == [
        "2024-01-R",
        "2024-02-R",
    ]
    assert catalog["event_name"].tolist() == [
        "Bahrain Grand Prix",
        "Saudi Arabian Grand Prix",
    ]

    second_batch = batch_runner.run(
        (
            bahrain_key,
            saudi_key,
        )
    )

    assert second_batch.succeeded
    assert second_batch.written_count == 0
    assert second_batch.skipped_count == 2
    assert second_batch.failed_count == 0
    assert second_batch.record_path.is_file()

    assert source.calls == [
        bahrain_key,
        saudi_key,
    ]