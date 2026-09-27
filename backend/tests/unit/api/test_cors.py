"""Browser access stays limited to explicit dashboard origins."""

from __future__ import annotations

import pytest

from app.api.main import dashboard_origins


def test_dashboard_origins_only_uses_configured_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("F1_DASHBOARD_ORIGINS", raising=False)
    assert dashboard_origins() == ()
    monkeypatch.setenv(
        "F1_DASHBOARD_ORIGINS",
        "https://dashboard.example.com, http://localhost:5173",
    )
    assert dashboard_origins() == (
        "https://dashboard.example.com",
        "http://localhost:5173",
    )


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://example.com/path",
        "https://example.com@attacker.test",
        "javascript:alert(1)",
    ],
)
def test_dashboard_origins_rejects_invalid_entries(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    monkeypatch.setenv("F1_DASHBOARD_ORIGINS", origin)
    with pytest.raises(ValueError, match="F1_DASHBOARD_ORIGINS"):
        dashboard_origins()
