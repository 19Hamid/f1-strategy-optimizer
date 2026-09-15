"""Tests for the Phase 6 model-audit command line."""

from types import SimpleNamespace

from app.ml import cli


def test_parser_defaults_to_repository_data_and_artifact_roots() -> None:
    """Keep the reproducible audit command aligned with project paths."""
    arguments = cli.build_parser().parse_args(["audit"])

    assert arguments.datasets_root == cli.DEFAULT_DATASETS_ROOT
    assert arguments.artifacts_root == cli.DEFAULT_ARTIFACTS_ROOT
    assert arguments.run_id == cli.DEFAULT_RUN_ID


def test_main_dispatches_audit_command(monkeypatch) -> None:
    """Route parsed audit arguments through the registered handler."""
    seen = []
    monkeypatch.setattr(
        cli,
        "_run_audit",
        lambda arguments: seen.append(arguments.run_id) or 0,
    )

    assert cli.main(["audit", "--run-id", "reviewed-run"]) == 0
    assert seen == ["reviewed-run"]


def test_verify_reports_both_valid_artifact_sets(monkeypatch, capsys) -> None:
    """Expose report and model verification counts to reviewers."""
    monkeypatch.setattr(
        cli,
        "verify_model_report",
        lambda _: SimpleNamespace(valid=True, artifact_count=7, issues=()),
    )
    monkeypatch.setattr(
        cli,
        "verify_model_artifact",
        lambda _: SimpleNamespace(
            valid=True,
            artifact_count=3,
            verification_rows=128,
            issues=(),
        ),
    )

    assert cli.main(["verify", "--run-id", "reviewed-run"]) == 0
    output = capsys.readouterr().out
    assert "Status: valid" in output
    assert "Report artifacts: 7" in output
    assert "Model artifacts: 3" in output
    assert "Model verification rows: 128" in output


def test_verify_returns_failure_when_either_bundle_is_invalid(
    monkeypatch,
    capsys,
) -> None:
    """Return a nonzero process code and print integrity issues."""
    monkeypatch.setattr(
        cli,
        "verify_model_report",
        lambda _: SimpleNamespace(
            valid=False,
            artifact_count=7,
            issues=("hash mismatch",),
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_model_artifact",
        lambda _: SimpleNamespace(
            valid=True,
            artifact_count=3,
            verification_rows=128,
            issues=(),
        ),
    )

    assert cli.main(["verify"]) == 1
    output = capsys.readouterr().out
    assert "Status: invalid" in output
    assert "hash mismatch" in output
