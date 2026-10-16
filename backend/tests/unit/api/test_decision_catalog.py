"""The picker lists verified development keys and fails closed on bad rows."""

from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from app.api import historical
from app.api.main import app


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2024,
                "session_id": "2024-04-R",
                "event_name": "Japanese Grand Prix",
                "driver": "HAM",
                "team": "Mercedes",
                "decision_lap": 38,
                "total_laps": 53,
                "current_compound": "HARD",
                "target_compound": "MEDIUM",
            },
            {
                "season": 2023,
                "session_id": "2023-05-R",
                "event_name": "Example race",
                "driver": "VER",
                "team": "Example team",
                "decision_lap": 15,
                "total_laps": 57,
                "current_compound": "MEDIUM",
                "target_compound": "HARD",
            },
        ]
    )


def test_catalog_contains_only_verified_report_rows(monkeypatch) -> None:
    checked = []
    monkeypatch.setattr(
        historical, "verify_development_evidence_bundle",
        lambda **kwargs: checked.append(kwargs),
    )
    monkeypatch.setattr(historical, "read_parquet_table", lambda _path: _rows())

    response = TestClient(app).get("/api/v1/analysis/decisions")

    assert response.status_code == 200
    options = response.json()["decisions"]
    assert len(options) == 2
    assert [item["season"] for item in options] == [2023, 2024]
    assert options[1]["driver"] == "HAM"
    assert options[1]["driver_name"] == "Lewis Hamilton"
    assert options[0]["driver_name"] == "Max Verstappen"
    assert options[1]["target_compound"] == "MEDIUM"
    assert checked


def test_catalog_rejects_protected_season(monkeypatch) -> None:
    monkeypatch.setattr(
        historical, "verify_development_evidence_bundle", lambda **_kwargs: None
    )
    invalid = _rows()
    invalid.loc[0, ["season", "session_id"]] = [2025, "2025-04-R"]
    monkeypatch.setattr(historical, "read_parquet_table", lambda _path: invalid)

    response = TestClient(app).get("/api/v1/analysis/decisions")

    assert response.status_code == 503
    assert response.json()["code"] == "EVIDENCE_UNAVAILABLE"


def test_catalog_rejects_driver_without_verified_full_name(monkeypatch) -> None:
    monkeypatch.setattr(
        historical, "verify_development_evidence_bundle", lambda **_kwargs: None
    )
    invalid = _rows()
    invalid.loc[0, "driver"] = "ZZZ"
    monkeypatch.setattr(historical, "read_parquet_table", lambda _path: invalid)

    response = TestClient(app).get("/api/v1/analysis/decisions")

    assert response.status_code == 503
    assert response.json()["code"] == "EVIDENCE_UNAVAILABLE"
