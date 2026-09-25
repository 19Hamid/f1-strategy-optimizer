from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_capabilities_publish_exact_v1_scope() -> None:
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_contract_version"] == "1.0"
    assert payload["analysis_scope"] == "CONTROLLED_DRY_GREEN_FLAG"
    assert payload["strategy_comparison"] == "PIT_NOW_VS_ONE_LAP_STAY_OUT"
    assert payload["optimization_objective"] == (
        "EXPECTED_REMAINING_RACE_TIME"
    )
    assert payload["development_seasons"] == [2022, 2023, 2024]
    assert payload["protected_evaluation_season"] == 2025
    assert payload["protected_evaluation_used_for_development"] is False
    assert payload["decision_actions"] == ["PIT_NOW", "STAY_OUT"]
    assert payload["recommendation_values"] == [
        "PIT_NOW",
        "STAY_OUT",
        "NO_CLEAR_ADVANTAGE",
    ]
    assert payload["execution_modes"] == [
        "DETERMINISTIC",
        "PAIRED_SCENARIO",
    ]
    assert payload["scenario_limits"] == {
        "minimum_for_stability": 100,
        "default": 10_000,
        "maximum": 100_000,
    }
    assert (
        payload["scenario_shares_are_correctness_probabilities"] is False
    )
    assert payload["counterfactual_strategy_accuracy_is_proven"] is False


def test_capabilities_are_documented_in_openapi() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/v1/capabilities"]["get"]
    assert operation["summary"] == "Describe supported V1 behavior"
    assert "200" in operation["responses"]
