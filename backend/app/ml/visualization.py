"""Build a human-readable browser review of immutable Phase 6 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Final
from uuid import uuid4

import pandas as pd

from app.ml.artifacts import ModelArtifactPaths, verify_model_artifact
from app.ml.reports import ModelReportPaths, verify_model_report

MODEL_REVIEW_DIRECTORY_NAME: Final = "model_review"
MODEL_REVIEW_FORMAT_VERSION: Final = "1.0"
MODEL_REVIEW_CHART_FILES: Final = (
    "candidate_comparison.svg",
    "temporal_fold_comparison.svg",
    "compound_error.svg",
    "race_error.svg",
    "degradation_curve.svg",
    "identity_ablation.svg",
)
MODEL_REVIEW_PAYLOAD_FILES: Final = (
    "index.html",
    *MODEL_REVIEW_CHART_FILES,
)
_FULL_FEATURE_SET_ID: Final = "full"
_CHART_COLORS: Final = (
    "#e10600",
    "#00a19c",
    "#ffd166",
    "#7b61ff",
    "#4cc9f0",
    "#f72585",
)


class ModelReviewError(RuntimeError):
    """Raised when a safe Phase 6 visual review cannot be produced."""


@dataclass(frozen=True, slots=True)
class ModelReviewPaths:
    """Canonical paths for one generated, replaceable browser review."""

    output_root: Path
    run_id: str

    def __post_init__(self) -> None:
        """Normalize paths and reject traversal through the run identity."""
        object.__setattr__(self, "output_root", Path(self.output_root))
        normalized = self.run_id.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or Path(normalized).name != normalized
            or "/" in normalized
            or "\\" in normalized
        ):
            raise ModelReviewError("run_id must be one safe path segment")
        object.__setattr__(self, "run_id", normalized)

    @property
    def root(self) -> Path:
        """Return the separate directory containing browser-ready outputs."""
        return (
            self.output_root
            / MODEL_REVIEW_DIRECTORY_NAME
            / f"format_version={MODEL_REVIEW_FORMAT_VERSION}"
            / f"run_id={self.run_id}"
        )

    @property
    def index(self) -> Path:
        """Return the dashboard entry point."""
        return self.root / "index.html"

    @property
    def manifest(self) -> Path:
        """Return the generated-output integrity manifest."""
        return self.root / "manifest.json"


@dataclass(frozen=True, slots=True)
class ModelReviewData:
    """Persisted Phase 6 tables required by the browser review."""

    selection: pd.DataFrame
    fold_metrics: pd.DataFrame
    slice_metrics: pd.DataFrame
    degradation_curve: pd.DataFrame
    identity_dependence: pd.DataFrame
    provenance: dict[str, object]

    def __post_init__(self) -> None:
        """Reject incomplete evidence before rendering any visuals."""
        frame_columns = (
            (
                self.selection,
                {
                    "formulation",
                    "model_family",
                    "candidate_id",
                    "full_mean_absolute_error_seconds",
                    "full_common_mean_absolute_error_seconds",
                    "ablated_common_mean_absolute_error_seconds",
                    "baseline_common_mean_absolute_error_seconds",
                    "coverage_rate",
                    "meets_selection_contract",
                    "selected",
                },
                "selection",
            ),
            (
                self.fold_metrics,
                {
                    "fold_id",
                    "formulation",
                    "model_family",
                    "candidate_id",
                    "feature_set_id",
                    "common_mean_absolute_error_seconds",
                    "baseline_common_mean_absolute_error_seconds",
                },
                "fold metrics",
            ),
            (
                self.slice_metrics,
                {
                    "feature_set_id",
                    "dimension",
                    "value",
                    "rows",
                    "mean_absolute_error_seconds",
                },
                "slice metrics",
            ),
            (
                self.degradation_curve,
                {
                    "current_compound",
                    "tyre_age_band",
                    "rows",
                    "mean_observed_lap_time_delta_seconds",
                    "mean_predicted_lap_time_delta_seconds",
                },
                "degradation curve",
            ),
            (
                self.identity_dependence,
                {
                    "feature_set_id",
                    "rows",
                    "mean_absolute_error_seconds",
                },
                "identity dependence",
            ),
        )
        for frame, required, name in frame_columns:
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise ModelReviewError(f"{name} must be a non-empty DataFrame")
            missing = required.difference(frame.columns)
            if missing:
                joined = ", ".join(sorted(missing))
                raise ModelReviewError(f"{name} is missing columns: {joined}")
        if not isinstance(self.provenance, dict) or not self.provenance:
            raise ModelReviewError("provenance must be a non-empty JSON object")


@dataclass(frozen=True, slots=True)
class ModelReviewVerification:
    """Integrity result for generated browser-review files."""

    valid: bool
    artifact_count: int
    issues: tuple[str, ...]

    def raise_for_errors(self) -> None:
        """Fail when generated output is incomplete or altered."""
        if self.issues:
            raise ModelReviewError(
                "model review verification failed: " + "; ".join(self.issues)
            )


def build_model_review(
    *,
    artifacts_root: Path,
    run_id: str,
    output_root: Path | None = None,
    replace: bool = False,
) -> ModelReviewPaths:
    """Verify immutable evidence and publish a separate visual review."""
    artifacts_root = Path(artifacts_root)
    report_paths = ModelReportPaths(artifacts_root, run_id)
    report_verification = verify_model_report(report_paths)
    report_verification.raise_for_errors()

    model_paths = ModelArtifactPaths(artifacts_root, f"{run_id}-lap-time")
    model_verification = verify_model_artifact(model_paths)
    model_verification.raise_for_errors()

    data = ModelReviewData(
        selection=pd.read_parquet(report_paths.root / "selection.parquet"),
        fold_metrics=pd.read_parquet(report_paths.root / "fold_metrics.parquet"),
        slice_metrics=pd.read_parquet(report_paths.root / "slice_metrics.parquet"),
        degradation_curve=pd.read_parquet(
            report_paths.root / "degradation_curve.parquet"
        ),
        identity_dependence=pd.read_parquet(
            report_paths.root / "identity_dependence.parquet"
        ),
        provenance=json.loads(
            (report_paths.root / "provenance.json").read_text(encoding="utf-8")
        ),
    )
    paths = ModelReviewPaths(output_root or artifacts_root, run_id)
    return write_model_review(paths=paths, data=data, replace=replace)


def write_model_review(
    *,
    paths: ModelReviewPaths,
    data: ModelReviewData,
    replace: bool = False,
) -> ModelReviewPaths:
    """Atomically write HTML, SVG charts and their integrity manifest."""
    if paths.root.exists() and not replace:
        raise ModelReviewError(
            f"model review already exists: {paths.root}; use --replace to rebuild"
        )
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.root.parent / f".tmp-{paths.run_id}-{uuid4().hex}"
    backup = paths.root.parent / f".backup-{paths.run_id}-{uuid4().hex}"
    temporary.mkdir()
    moved_existing = False
    try:
        selected = _selected_row(data.selection)
        charts = _chart_documents(data, selected=selected)
        for name, document in charts.items():
            (temporary / name).write_text(document, encoding="utf-8")
        (temporary / "index.html").write_text(
            _html_document(data, selected=selected),
            encoding="utf-8",
        )
        manifest = {
            "format_version": MODEL_REVIEW_FORMAT_VERSION,
            "run_id": paths.run_id,
            "source_model_contract_version": data.provenance.get(
                "model_contract_version"
            ),
            "artifacts": {
                name: {
                    "sha256": _sha256(temporary / name),
                    "size_bytes": (temporary / name).stat().st_size,
                }
                for name in MODEL_REVIEW_PAYLOAD_FILES
            },
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if paths.root.exists():
            os.replace(paths.root, backup)
            moved_existing = True
        os.replace(temporary, paths.root)
        if moved_existing:
            shutil.rmtree(backup)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if moved_existing and backup.exists() and not paths.root.exists():
            os.replace(backup, paths.root)
        raise

    verification = verify_model_review(paths)
    verification.raise_for_errors()
    return paths


def verify_model_review(paths: ModelReviewPaths) -> ModelReviewVerification:
    """Verify the exact visual file set, sizes and SHA-256 digests."""
    issues: list[str] = []
    if not paths.manifest.is_file():
        return ModelReviewVerification(False, 0, ("missing manifest.json",))
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ModelReviewVerification(False, 0, (f"invalid manifest: {error}",))
    if not isinstance(manifest, dict):
        return ModelReviewVerification(False, 0, ("manifest must be an object",))
    if manifest.get("format_version") != MODEL_REVIEW_FORMAT_VERSION:
        issues.append("unexpected format_version")
    if manifest.get("run_id") != paths.run_id:
        issues.append("manifest run_id mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        issues.append("manifest artifacts must be an object")
        artifacts = {}
    expected = {*MODEL_REVIEW_PAYLOAD_FILES, "manifest.json"}
    try:
        actual = {item.name for item in paths.root.iterdir() if item.is_file()}
        if actual != expected:
            issues.append("stored artifact file set mismatch")
        if any(item.is_dir() for item in paths.root.iterdir()):
            issues.append("stored review contains an unexpected directory")
    except OSError as error:
        issues.append(f"review directory read failed: {error}")
    for name in MODEL_REVIEW_PAYLOAD_FILES:
        path = paths.root / name
        evidence = artifacts.get(name)
        if not path.is_file():
            issues.append(f"missing artifact: {name}")
            continue
        if not isinstance(evidence, dict):
            issues.append(f"missing manifest evidence: {name}")
            continue
        if path.stat().st_size != evidence.get("size_bytes"):
            issues.append(f"size mismatch: {name}")
        if _sha256(path) != evidence.get("sha256"):
            issues.append(f"hash mismatch: {name}")
    return ModelReviewVerification(
        valid=not issues,
        artifact_count=len(artifacts),
        issues=tuple(issues),
    )


def _chart_documents(
    data: ModelReviewData,
    *,
    selected: pd.Series,
) -> dict[str, str]:
    """Build the six standalone SVG charts displayed by the review."""
    candidates = data.selection.sort_values(
        "full_common_mean_absolute_error_seconds",
        kind="stable",
    ).head(15)
    candidate_rows = [
        (
            f"{row.candidate_id} · {row.formulation}",
            float(row.full_common_mean_absolute_error_seconds),
            bool(row.selected),
        )
        for row in candidates.itertuples(index=False)
    ]
    baseline = float(selected["baseline_common_mean_absolute_error_seconds"])

    selected_folds = _selected_fold_rows(data.fold_metrics, selected=selected)
    fold_rows: list[tuple[str, float, bool]] = []
    for row in selected_folds.itertuples(index=False):
        fold_rows.extend(
            (
                (
                    f"{row.fold_id} · selected model",
                    float(row.common_mean_absolute_error_seconds),
                    True,
                ),
                (
                    f"{row.fold_id} · frozen baseline",
                    float(row.baseline_common_mean_absolute_error_seconds),
                    False,
                ),
            )
        )

    compound = _weighted_metric(
        data.slice_metrics.loc[
            data.slice_metrics["dimension"].eq("current_compound")
            & data.slice_metrics["feature_set_id"].eq(_FULL_FEATURE_SET_ID)
        ],
        group_column="value",
        value_column="mean_absolute_error_seconds",
    )
    compound_rows = [
        (str(row.value), float(row.metric), False)
        for row in compound.itertuples(index=False)
    ]

    races = _weighted_metric(
        data.slice_metrics.loc[
            data.slice_metrics["dimension"].eq("session_id")
            & data.slice_metrics["feature_set_id"].eq(_FULL_FEATURE_SET_ID)
        ],
        group_column="value",
        value_column="mean_absolute_error_seconds",
    ).sort_values("metric", ascending=False, kind="stable").head(15)
    race_rows = [
        (str(row.value), float(row.metric), False)
        for row in races.itertuples(index=False)
    ]

    identity_rows = [
        (
            str(row.feature_set_id).replace("_", " ").title(),
            float(row.mean_absolute_error_seconds),
            str(row.feature_set_id) == _FULL_FEATURE_SET_ID,
        )
        for row in data.identity_dependence.itertuples(index=False)
    ]
    degradation = _degradation_summary(data.degradation_curve)
    labels = [
        f"{row.current_compound} · {row.tyre_age_band}"
        for row in degradation.itertuples(index=False)
    ]

    return {
        "candidate_comparison.svg": _horizontal_bar_svg(
            "Top candidate comparable-row MAE",
            candidate_rows,
            threshold=baseline,
            threshold_label="Frozen baseline",
        ),
        "temporal_fold_comparison.svg": _horizontal_bar_svg(
            "Selected model versus baseline by temporal fold",
            fold_rows,
        ),
        "compound_error.svg": _horizontal_bar_svg(
            "Selected-model MAE by tyre compound",
            compound_rows,
        ),
        "race_error.svg": _horizontal_bar_svg(
            "Hardest held-out races by MAE",
            race_rows,
        ),
        "degradation_curve.svg": _line_chart_svg(
            "Observed versus predicted lap-time change",
            labels,
            {
                "Observed": degradation[
                    "mean_observed_lap_time_delta_seconds"
                ].astype(float).tolist(),
                "Predicted": degradation[
                    "mean_predicted_lap_time_delta_seconds"
                ].astype(float).tolist(),
            },
        ),
        "identity_ablation.svg": _horizontal_bar_svg(
            "Driver/team identity ablation",
            identity_rows,
            threshold=baseline,
            threshold_label="Selection gate",
        ),
    }


def _html_document(data: ModelReviewData, *, selected: pd.Series) -> str:
    """Return one self-contained navigation page for tables and charts."""
    model_mae = float(selected["full_common_mean_absolute_error_seconds"])
    pooled_mae = float(selected["full_mean_absolute_error_seconds"])
    baseline = float(selected["baseline_common_mean_absolute_error_seconds"])
    improvement = 100.0 * (baseline - model_mae) / baseline
    coverage = 100.0 * float(selected["coverage_rate"])
    provenance = data.provenance
    selection_table = data.selection.copy()
    selection_table.insert(
        0,
        "status",
        selection_table.apply(_selection_status, axis=1),
    )
    selection_table = selection_table.sort_values(
        "full_common_mean_absolute_error_seconds",
        kind="stable",
    )
    selection_columns = [
        "status",
        "formulation",
        "model_family",
        "candidate_id",
        "full_common_mean_absolute_error_seconds",
        "ablated_common_mean_absolute_error_seconds",
        "baseline_common_mean_absolute_error_seconds",
        "coverage_rate",
    ]
    fold_table = _selected_fold_rows(data.fold_metrics, selected=selected)[
        [
            "fold_id",
            "common_mean_absolute_error_seconds",
            "baseline_common_mean_absolute_error_seconds",
        ]
    ]
    compound_table = _weighted_metric(
        data.slice_metrics.loc[
            data.slice_metrics["dimension"].eq("current_compound")
            & data.slice_metrics["feature_set_id"].eq(_FULL_FEATURE_SET_ID)
        ],
        group_column="value",
        value_column="mean_absolute_error_seconds",
    ).rename(columns={"value": "compound", "metric": "MAE seconds"})
    cards = (
        ("Selected model", f"{selected['candidate_id']}"),
        ("Formulation", str(selected["formulation"])),
        ("Comparable MAE", f"{model_mae:.6f} s"),
        ("Frozen baseline", f"{baseline:.6f} s"),
        ("Relative improvement", f"{improvement:.2f}%"),
        ("Coverage", f"{coverage:.2f}%"),
        ("Pooled all-row MAE", f"{pooled_mae:.6f} s"),
        ("Execution device", str(provenance.get("execution_device", "unknown"))),
    )
    card_html = "".join(
        "<article class='card'>"
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong>"
        "</article>"
        for label, value in cards
    )
    chart_sections = (
        (
            "Candidate comparison",
            "candidate_comparison.svg",
            "Lower MAE is better. The red bar is the selected configuration.",
        ),
        (
            "Temporal validation",
            "temporal_fold_comparison.svg",
            "Fold 1 validates on 2023; Fold 2 validates on 2024.",
        ),
        (
            "Tyre compound stability",
            "compound_error.svg",
            "Held-out error grouped by the compound known at decision time.",
        ),
        (
            "Race stability",
            "race_error.svg",
            "The fifteen most difficult held-out sessions reveal where the "
            "model struggles.",
        ),
        (
            "Tyre-age association",
            "degradation_curve.svg",
            "Observed and predicted changes are associations, not pure causal "
            "degradation.",
        ),
        (
            "Identity ablation",
            "identity_ablation.svg",
            "The model is retrained without driver and team; both results stay "
            "under the gate.",
        ),
    )
    charts_html = "".join(
        "<section class='panel'>"
        f"<h2>{escape(title)}</h2><p>{escape(note)}</p>"
        f"<a href='{file_name}' target='_blank'>"
        f"<img src='{file_name}' alt='{escape(title)}'></a>"
        "</section>"
        for title, file_name, note in chart_sections
    )
    provenance_json = escape(json.dumps(provenance, indent=2, sort_keys=True))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phase 6 Model Review</title>
  <style>
    :root {{ color-scheme: dark; --bg:#090b10; --panel:#121621; --line:#252b3a;
      --text:#f5f7fb; --muted:#aeb7c9; --red:#e10600; --green:#2dd4bf; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:linear-gradient(145deg,#090b10,#12131a);
      color:var(--text); font:15px/1.55 Inter,Segoe UI,Arial,sans-serif; }}
    main {{ max-width:1240px; margin:auto; padding:40px 24px 80px; }}
    header {{ padding:30px; border:1px solid var(--line); border-radius:20px;
      background:linear-gradient(120deg,#171b27,#10131c); }}
    h1 {{ margin:0 0 8px; font-size:clamp(30px,5vw,58px); letter-spacing:-2px; }}
    h1 em {{ color:var(--red); font-style:normal; }}
    h2 {{ margin:0 0 4px; font-size:24px; }}
    p {{ color:var(--muted); }}
    .notice {{ border-left:4px solid var(--green); padding:12px 16px;
      background:#0d211f; border-radius:8px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
      gap:12px; margin:22px 0; }}
    .card,.panel {{ border:1px solid var(--line); background:var(--panel);
      border-radius:16px; }}
    .card {{ padding:18px; }} .card span {{ color:var(--muted); display:block; }}
    .card strong {{ display:block; margin-top:5px; font-size:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(440px,1fr));
      gap:18px; }}
    .panel {{ padding:22px; margin-top:18px; overflow:hidden; }}
    .panel img {{ width:100%; background:#0e1119; border-radius:10px; margin-top:8px; }}
    .table-wrap {{ overflow:auto; max-height:620px; border:1px solid var(--line);
      border-radius:10px; }}
    table {{ width:100%; border-collapse:collapse; background:#0e1119; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left;
      white-space:nowrap; }}
    th {{ position:sticky; top:0; background:#1a1f2c; color:#fff; }}
    tr:hover td {{ background:#171c28; }}
    details {{ margin-top:18px; }}
    pre {{ overflow:auto; padding:18px; background:#080a0f;
      border-radius:10px; color:#c8d2e6; }}
    footer {{ margin-top:34px; color:var(--muted); }}
    @media (max-width:600px) {{ main {{ padding:20px 12px 50px; }}
      .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <header>
    <h1>Phase 6 <em>Model Review</em></h1>
    <p>Browser-ready evidence generated from the verified, immutable
      development audit.</p>
    <p class="notice"><strong>Interpretation:</strong> the honest comparison is
      {model_mae:.6f} s versus {baseline:.6f} s on the same held-out rows.
      The 2025 protected season remains excluded.</p>
  </header>
  <section class="cards">{card_html}</section>
  <div class="grid">{charts_html}</div>
  <section class="panel">
    <h2>Complete candidate leaderboard</h2>
    <p>Every direct and residual-hybrid candidate is retained—not only the winner.</p>
    <div class="table-wrap">{_table_html(selection_table[selection_columns])}</div>
  </section>
  <section class="panel">
    <h2>Selected-model fold results</h2>
    <div class="table-wrap">{_table_html(fold_table)}</div>
  </section>
  <section class="panel">
    <h2>Compound summary</h2>
    <div class="table-wrap">{_table_html(compound_table)}</div>
  </section>
  <section class="panel">
    <h2>Reproducibility evidence</h2>
    <p>This records the dataset identity, model parameters, seed, dependencies
      and device.</p>
    <details><summary>Show provenance JSON</summary>
      <pre>{provenance_json}</pre></details>
  </section>
  <footer>Generated from Phase 6 report contract
    {escape(str(provenance.get('model_contract_version', 'unknown')))}.
    SVG charts can be opened or saved individually.</footer>
</main></body></html>
"""


def _selected_row(selection: pd.DataFrame) -> pd.Series:
    """Return the one contract-approved winner."""
    selected = selection.loc[selection["selected"].eq(True)]
    if len(selected) != 1:
        raise ModelReviewError("selection must identify exactly one winner")
    return selected.iloc[0]


def _selected_fold_rows(
    fold_metrics: pd.DataFrame,
    *,
    selected: pd.Series,
) -> pd.DataFrame:
    """Return full-feature fold evidence for the selected candidate."""
    rows = fold_metrics.loc[
        fold_metrics["formulation"].eq(selected["formulation"])
        & fold_metrics["model_family"].eq(selected["model_family"])
        & fold_metrics["candidate_id"].eq(selected["candidate_id"])
        & fold_metrics["feature_set_id"].eq(_FULL_FEATURE_SET_ID)
    ].sort_values("fold_id", kind="stable")
    if rows.empty:
        raise ModelReviewError("selected candidate has no full-feature fold evidence")
    return rows


def _selection_status(row: pd.Series) -> str:
    """Return a concise human-readable selection result."""
    if bool(row["selected"]):
        return "SELECTED"
    if bool(row["meets_selection_contract"]):
        return "PASSED"
    return "REJECTED"


def _weighted_metric(
    frame: pd.DataFrame,
    *,
    group_column: str,
    value_column: str,
) -> pd.DataFrame:
    """Pool fold-level means using their underlying row counts."""
    if frame.empty:
        raise ModelReviewError(f"no rows available for {group_column} chart")
    records: list[dict[str, object]] = []
    for value, group in frame.groupby(group_column, sort=True, dropna=False):
        weights = pd.to_numeric(group["rows"], errors="raise").astype(float)
        values = pd.to_numeric(group[value_column], errors="raise").astype(float)
        total = float(weights.sum())
        if total <= 0:
            raise ModelReviewError("chart weights must be positive")
        records.append(
            {
                "value": str(value),
                "rows": int(total),
                "metric": float((values * weights).sum() / total),
            }
        )
    return pd.DataFrame.from_records(records, columns=("value", "rows", "metric"))


def _degradation_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Pool observed and predicted degradation summaries across folds."""
    age_order = {"NEW_0_5": 0, "USED_6_15": 1, "OLD_16_PLUS": 2}
    records: list[dict[str, object]] = []
    grouped = frame.groupby(
        ["current_compound", "tyre_age_band"],
        sort=True,
        dropna=False,
    )
    for (compound, age), group in grouped:
        weights = pd.to_numeric(group["rows"], errors="raise").astype(float)
        total = float(weights.sum())
        if total <= 0:
            raise ModelReviewError("degradation weights must be positive")
        record: dict[str, object] = {
            "current_compound": str(compound),
            "tyre_age_band": str(age),
            "age_order": age_order.get(str(age), 99),
            "rows": int(total),
        }
        for column in (
            "mean_observed_lap_time_delta_seconds",
            "mean_predicted_lap_time_delta_seconds",
        ):
            values = pd.to_numeric(group[column], errors="raise").astype(float)
            record[column] = float((values * weights).sum() / total)
        records.append(record)
    return pd.DataFrame.from_records(records).sort_values(
        ["current_compound", "age_order"],
        kind="stable",
    )


def _horizontal_bar_svg(
    title: str,
    rows: list[tuple[str, float, bool]],
    *,
    threshold: float | None = None,
    threshold_label: str = "Threshold",
) -> str:
    """Render an accessible horizontal bar chart without new dependencies."""
    clean = [(label, _finite(value), highlighted) for label, value, highlighted in rows]
    if not clean:
        raise ModelReviewError(f"{title} has no chart rows")
    maximum = max([value for _, value, _ in clean] + ([threshold] if threshold else []))
    maximum = maximum * 1.12 if maximum > 0 else 1.0
    width = 1100
    left = 330
    right = 110
    top = 88
    row_height = 38
    bottom = 55
    height = top + len(clean) * row_height + bottom
    plot_width = width - left - right
    elements = [
        _svg_text(28, 42, title, size=24, weight=700),
        _svg_text(28, 68, "Mean absolute error in seconds · lower is better", size=14),
    ]
    for index, (label, value, highlighted) in enumerate(clean):
        y = top + index * row_height
        bar_width = max(1.0, value / maximum * plot_width)
        color = _CHART_COLORS[0] if highlighted else "#41506b"
        elements.extend(
            (
                _svg_text(left - 12, y + 20, label, anchor="end", size=13),
                f'<rect x="{left}" y="{y + 5}" width="{bar_width:.2f}" '
                f'height="22" rx="5" fill="{color}"/>',
                _svg_text(
                    left + bar_width + 9,
                    y + 21,
                    f"{value:.6f}",
                    size=12,
                    color="#f5f7fb",
                ),
            )
        )
    if threshold is not None:
        threshold = _finite(threshold)
        x = left + threshold / maximum * plot_width
        elements.append(
            f'<line x1="{x:.2f}" y1="{top - 8}" x2="{x:.2f}" '
            f'y2="{height - bottom + 5}" stroke="#ffd166" stroke-width="2" '
            'stroke-dasharray="7 5"/>'
        )
        elements.append(
            _svg_text(x, height - 18, threshold_label, anchor="middle", size=12)
        )
    return _svg_document(width, height, elements)


def _line_chart_svg(
    title: str,
    labels: list[str],
    series: dict[str, list[float]],
) -> str:
    """Render observed and predicted degradation as an SVG line chart."""
    if not labels or not series:
        raise ModelReviewError(f"{title} has no chart values")
    if any(len(values) != len(labels) for values in series.values()):
        raise ModelReviewError("line-chart series lengths differ")
    clean = {
        name: [_finite(value) for value in values]
        for name, values in series.items()
    }
    all_values = [value for values in clean.values() for value in values]
    minimum = min(all_values + [0.0])
    maximum = max(all_values + [0.0])
    padding = max((maximum - minimum) * 0.12, 0.05)
    minimum -= padding
    maximum += padding
    width = 1100
    height = 570
    left = 92
    right = 50
    top = 92
    bottom = 155
    plot_width = width - left - right
    plot_height = height - top - bottom

    def point(index: int, value: float) -> tuple[float, float]:
        x = left + index * plot_width / max(len(labels) - 1, 1)
        y = top + (maximum - value) / (maximum - minimum) * plot_height
        return x, y

    elements = [
        _svg_text(28, 42, title, size=24, weight=700),
        _svg_text(28, 68, "Mean lap-time change in seconds", size=14),
    ]
    for tick in range(6):
        value = minimum + tick * (maximum - minimum) / 5
        y = top + (maximum - value) / (maximum - minimum) * plot_height
        elements.extend(
            (
                f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" '
                f'y2="{y:.2f}" stroke="#252b3a" stroke-width="1"/>',
                _svg_text(left - 10, y + 4, f"{value:.2f}", anchor="end", size=12),
            )
        )
    for index, label in enumerate(labels):
        x, _ = point(index, minimum)
        compound, _, age = label.partition(" · ")
        elements.extend(
            (
                _svg_text(x, height - bottom + 28, compound, anchor="middle", size=11),
                _svg_text(x, height - bottom + 46, age, anchor="middle", size=10),
            )
        )
    for series_index, (name, values) in enumerate(clean.items()):
        color = _CHART_COLORS[series_index]
        points = [point(index, value) for index, value in enumerate(values)]
        path = " ".join(
            ("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}"
            for index, (x, y) in enumerate(points)
        )
        elements.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="4"/>'
        )
        for x, y in points:
            elements.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"/>'
            )
        legend_x = left + series_index * 180
        elements.append(
            f'<rect x="{legend_x}" y="{height - 48}" width="24" height="5" '
            f'rx="2" fill="{color}"/>'
        )
        elements.append(
            _svg_text(legend_x + 34, height - 42, name, size=13, color="#f5f7fb")
        )
    return _svg_document(width, height, elements)


def _svg_document(width: int, height: int, elements: list[str]) -> str:
    """Wrap chart elements in one standalone SVG image."""
    body = "\n  ".join(elements)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" role="img">\n'
        f'  <rect width="{width}" height="{height}" rx="16" fill="#0e1119"/>\n'
        f"  {body}\n</svg>\n"
    )


def _svg_text(
    x: float,
    y: float,
    value: object,
    *,
    anchor: str = "start",
    size: int = 14,
    weight: int = 400,
    color: str = "#aeb7c9",
) -> str:
    """Return one escaped SVG text element."""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="Segoe UI,Arial,sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{color}">{escape(str(value))}</text>'
    )


def _table_html(frame: pd.DataFrame) -> str:
    """Render a browser table with consistent numeric precision."""
    display = frame.copy()
    for column in display.select_dtypes(include="number").columns:
        display[column] = display[column].map(
            lambda value: f"{float(value):.6f}" if not pd.isna(value) else ""
        )
    return display.to_html(
        index=False,
        border=0,
        classes="data-table",
        escape=True,
    )


def _finite(value: float) -> float:
    """Return one finite chart number."""
    number = float(value)
    if not math.isfinite(number):
        raise ModelReviewError("chart values must be finite")
    return number


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one generated file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone Phase 6 visualization command parser."""
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.visualization",
        description="Build a browser dashboard from verified Phase 6 evidence.",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=project_root / "artifacts",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_root / "artifacts",
    )
    parser.add_argument("--run-id", default="phase-6-final-audit")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="atomically replace a previously generated visual review",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Generate and verify one browser-ready model review."""
    arguments = build_parser().parse_args(argv)
    paths = build_model_review(
        artifacts_root=arguments.artifacts_root,
        output_root=arguments.output_root,
        run_id=arguments.run_id,
        replace=arguments.replace,
    )
    verification = verify_model_review(paths)
    verification.raise_for_errors()
    print("PHASE 6 MODEL REVIEW")
    print("====================")
    print("Status: valid")
    print(f"Visual artifacts: {verification.artifact_count}")
    print(f"Dashboard: {paths.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
