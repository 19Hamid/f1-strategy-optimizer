from app.api.contracts import (
    API_CONTRACT_VERSION,
    API_PREFIX,
    DEVELOPMENT_SEASONS,
    PROTECTED_EVALUATION_SEASON,
    SUPPORTED_EXECUTION_MODES,
    validate_api_contract,
)


def test_api_contract_has_stable_v1_identities() -> None:
    validate_api_contract()

    assert API_CONTRACT_VERSION == "1.0"
    assert API_PREFIX == "/api/v1"
    assert DEVELOPMENT_SEASONS == (2022, 2023, 2024)
    assert PROTECTED_EVALUATION_SEASON == 2025
    assert PROTECTED_EVALUATION_SEASON not in DEVELOPMENT_SEASONS
    assert SUPPORTED_EXECUTION_MODES == (
        "DETERMINISTIC",
        "PAIRED_SCENARIO",
    )
