"""Export the 2022–2024 race/driver picker without inventing pit decisions.

Usage: python tools/export_catalog.py /path/to/review-bundle
The archived processed race partitions are hash-checked. The protected 2025
evaluation partition is never opened.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from export_decisions import driver_names, verified_file

SITE = Path(__file__).resolve().parents[1]
# Codes missing from the historical API's verified-decision-only name map.
# Checked against the official Formula 1 2022–2024 driver standings.
ADDITIONAL_NAMES = {
    "BEA": "Oliver Bearman",
    "BOT": "Valtteri Bottas",
    "DEV": "Nyck de Vries",
    "DOO": "Jack Doohan",
    "LAW": "Liam Lawson",
    "MAG": "Kevin Magnussen",
    "MSC": "Mick Schumacher",
    "OCO": "Esteban Ocon",
    "SAR": "Logan Sargeant",
    "STR": "Lance Stroll",
    "VET": "Sebastian Vettel",
}


def main(bundle: Path) -> None:
    decisions = json.loads((SITE / "dist" / "decisions.json").read_text())
    extended_path = SITE / "dist" / "extended_decisions.json"
    extended = json.loads(extended_path.read_text()) if extended_path.exists() else {"decisions": []}
    pre_pit_path = SITE / "dist" / "pre_pit_decisions.json"
    pre_pit = json.loads(pre_pit_path.read_text()) if pre_pit_path.exists() else {"decisions": [], "unavailable": [], "case_count": 0}
    unavailable = {(item["race_id"], item["driver"]): item["reason"] for item in pre_pit["unavailable"]}
    verified = {}
    for row in (*decisions["decisions"], *extended["decisions"], *pre_pit["decisions"]):
        assert row["season"] in (2022, 2023, 2024)
        verified.setdefault((row["race_id"], row["driver"]), []).append(row)
    names = driver_names(bundle / "backend" / "app" / "api" / "historical.py")
    assert not (names.keys() & ADDITIONAL_NAMES.keys())
    names.update(ADDITIONAL_NAMES)

    rows = []
    archive = bundle / "data" / "processed" / "fastf1" / "cleaning_version=1.0"
    folders = sorted(archive.glob("season=*/round=*/session=R"))
    assert len(folders) == 68
    for folder in folders:
        season = int(folder.parents[1].name.split("=")[1])
        assert season in (2022, 2023, 2024)
        manifest = json.loads((folder / "manifest.json").read_text())
        session = manifest["session"]
        race_id = session["identifier"]
        assert session["season"] == season and session["session_type"] == "R"
        assert manifest["validation"]["status"] == "passed"
        path = verified_file(folder, "laps.parquet", manifest["files"]["laps.parquet"])
        laps = pd.read_parquet(path, columns=[
            "Season", "RoundNumber", "EventName", "Driver", "Team",
            "LapNumber", "Compound", "PitInTime", "Position",
        ])
        assert len(laps) == manifest["files"]["laps.parquet"]["rows"]
        assert set(laps["Season"]) == {season}
        assert set(laps["RoundNumber"]) == {session["round_number"]}
        assert set(laps["EventName"]) == {session["event_name"]}
        # A recorded lap identifies a race starter; this excludes cars that did not start.
        starters = laps.loc[laps["LapNumber"].ge(1), ["Driver", "Team"]].drop_duplicates()
        assert len(starters) in (18, 19, 20)
        assert starters["Driver"].is_unique and starters["Team"].notna().all()
        for driver, team in starters.itertuples(index=False, name=None):
            assert driver in names, f"Unknown driver code: {driver} in {race_id}"
            pair = sorted(verified.pop((race_id, driver), []), key=lambda item: item["lap"])
            assert len(pair) in (0, 1, 2)
            reason = unavailable.pop((race_id, driver), None)
            assert (not pair) == (reason is not None), f"Missing availability evidence for {race_id}/{driver}"
            for item in pair:
                assert item["season"] == season and item["race"] == session["event_name"]
                assert item["name"] == names[driver] and item["team"] == team
            driver_laps = laps.loc[laps["Driver"].eq(driver)].sort_values("LapNumber", kind="stable")
            recorded_laps = int(driver_laps["LapNumber"].max())
            pit_entries = [
                int(value) for value in driver_laps.loc[
                    driver_laps["PitInTime"].notna(), "LapNumber"
                ]
            ]
            stints = []
            for lap in driver_laps.itertuples(index=False):
                compound = str(lap.Compound).upper() if pd.notna(lap.Compound) else "UNKNOWN"
                lap_number = int(lap.LapNumber)
                if stints and stints[-1]["compound"] == compound and stints[-1]["end_lap"] + 1 == lap_number:
                    stints[-1]["end_lap"] = lap_number
                else:
                    stints.append({"compound": compound, "start_lap": lap_number, "end_lap": lap_number})
            last_position = driver_laps.iloc[-1]["Position"]
            rows.append({
                "season": season, "race_id": race_id, "race": session["event_name"],
                "driver": driver, "name": names[driver], "team": team,
                "source": "Verified FastF1 processed race laps",
                "decision_ids": [item["id"] for item in pair],
                "availability_reason": reason,
                "recorded": {
                    "laps": recorded_laps,
                    "race_laps": int(laps["LapNumber"].max()),
                    "last_position": int(last_position) if pd.notna(last_position) else None,
                    "pit_entry_laps": pit_entries,
                    "stints": stints,
                },
            })

    assert not verified, "A verified decision is missing from the race catalog"
    assert not unavailable, "An unavailable driver is missing from the race catalog"
    rows.sort(key=lambda item: (item["season"], item["race_id"], item["name"]))
    assert len({(r["race_id"], r["driver"]) for r in rows}) == len(rows)
    assert {r["season"] for r in rows} == {2022, 2023, 2024}
    assert sum(bool(r["decision_ids"]) for r in rows) == 62 + extended.get("paired_checkpoints", 0) + pre_pit["case_count"]
    result = {"seasons": [2022, 2023, 2024], "entries": rows}
    target = SITE / "dist" / "catalog.json"
    target.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"Exported {len(rows)} race starters from 68 Grands Prix to {target}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/export_catalog.py /path/to/review-bundle")
    main(Path(sys.argv[1]).resolve())
