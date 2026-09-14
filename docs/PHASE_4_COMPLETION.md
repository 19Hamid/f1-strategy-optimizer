# Phase 4 Completion Report — Dataset and Database Design

## Outcome

Phase 4 produced a versioned, leakage-controlled, integrity-checked modelling
dataset and a PostgreSQL persistence layer for all 68 development races from
2022 to 2024.

The protected 2025 temporal holdout was rejected by development interfaces and
contributed zero rows to the Phase 4 dataset and database.

Phase 4 was completed on 14 September 2026.

## Versioned deliverables

- Dataset contract: `1.0`
- Cleaning-rule source: `1.0`
- Processed-data source contract: `1.0`
- Database schema: `1.0`
- Alembic revision: `20260914_0001`

## Dataset summary

| Measure | Value |
|---|---:|
| Development sessions | 68 |
| 2022 sessions | 22 |
| 2023 sessions | 22 |
| 2024 sessions | 24 |
| Candidate decision rows | 73,251 |
| Eligible decisions | 55,943 |
| Ineligible decisions | 17,308 |
| Eligible historical `PIT_NOW` actions | 1,776 |
| Eligible historical `STAY_OUT` actions | 54,167 |
| Eligible lap-time targets | 52,483 |
| Pit-duration observations | 2,693 |
| Eligible pit-duration targets | 1,465 |
| Temporal split assignments | 204 |

Decision rows represent information available at the start of lap `t`.
Decision eligibility and target eligibility are stored separately.

Historical actions remain diagnostic labels. They are not treated as optimal
counterfactual strategy ground truth.

## Decision-time and leakage controls

Phase 4 implemented:

- Canonical decision identities by session, driver and decision lap
- Current tyre and stint state reconstructed from past evidence
- Previous position taken from completed lap `t - 1`
- Weather aligned at or before the decision timestamp
- Track state reconstructed from information known before the decision
- Rolling features shifted to completed prior laps
- Separate decision, lap-target and pit-duration eligibility
- Explicit quality-reason definitions and normalized links
- Whole-race temporal splits
- Fail-closed rejection of protected 2025 development records

The final database audit found:

- Zero future weather matches
- Zero protected evaluation rows
- Exact agreement between decision rows and labels
- Exact agreement with every frozen development total

## Temporal folds

| Fold | Training | Validation | Excluded |
|---|---|---|---|
| 1 | 2022 | 2023 | 2024 |
| 2 | 2022–2023 | 2024 | None |
| Final development | 2022–2024 | None | None |

Every race remains wholly within one role for each fold. No race is split
between training and validation.

## Stored artifacts

Each dataset session contains:

- `decision_rows.parquet`
- `decision_labels.parquet`
- `pit_duration_observations.parquet`
- `quality_report.json`
- `manifest.json`

Global artifacts contain:

- Verified 68-session catalog
- Frozen temporal split assignments
- Dataset build run records

Writes are atomic, manifests include SHA-256 identities, and integrity checks
fail closed on missing, altered or contradictory artifacts.

Generated Parquet files remain the authoritative analytical artifacts.
PostgreSQL preserves their values and provenance; it does not perform a second
cleaning pipeline.

## PostgreSQL implementation

The database layer includes:

- Versioned SQLAlchemy models
- Primary, foreign, uniqueness and check constraints
- PostgreSQL-specific types and partial indexes
- Immutable insert-or-verify repositories
- Bounded bulk insertion
- Transaction-safe per-session loading
- Dataset-version and build provenance
- Quality-reason normalization
- Temporal-fold persistence
- Exact global reconciliation
- Runtime and audit command-line interfaces
- Reproducible Alembic upgrade and downgrade
- Isolated Docker-based PostgreSQL testing

A real load wrote all 68 sessions into a fresh PostgreSQL 17 database and
completed with status `SUCCEEDED`.

## Final real-data audit

The final audit command was:

```bash
bash ./scripts/run_development_database_audit.sh
```

It performed:

1. Isolated PostgreSQL startup
2. Dependency verification
3. Alembic upgrade from an empty database
4. Complete 68-session database load
5. Exact database reconciliation
6. Independent read-only audit
7. PostgreSQL integration tests
8. Automatic container and volume cleanup

The complete load reconciled:

- 73,251 decision rows
- 73,251 decision labels
- 55,943 eligible decisions
- 17,308 ineligible decisions
- 52,483 eligible lap-time targets
- 2,693 pit-duration observations
- 1,465 eligible pit-duration targets
- 204 split assignments
- Zero future weather matches
- Zero protected 2025 rows

## Defects discovered by the real audit

The real audit identified and corrected two issues that unit-only verification
did not expose:

1. Reconstructed pit-event persistence initially omitted
   `entry_rainfall`, `exit_rainfall` and `is_dry_weather_pair`.
   The ORM, migration, constraints, mappings and tests now preserve them.
2. The first reconciliation query counted lap-target eligibility alone.
   It now correctly counts the intersection of decision eligibility and
   lap-target eligibility.

Both failures rolled back safely. The isolated database was removed after each
attempt.

## Automated quality evidence

At completion:

- 1,030 backend tests passed in the normal warning-as-error suite
- Five PostgreSQL-specific tests are isolated behind the `postgresql` marker
- Ruff checks passed
- Alembic generated 26 application tables
- ORM and migration metadata had no schema drift
- Real PostgreSQL loading and reconciliation passed
- Working tree verification remained clean after each reviewed checkpoint

Automated tests provide strong evidence of the specified behaviour but do not
prove that no undiscovered defect exists.

## Known limitations

- The dataset is restricted to controlled dry-race version-one conditions.
- Historical pit actions are observed behaviour, not optimal decisions.
- Observed pit-lane duration is not automatically net race-time loss.
- Fuel load, traffic, driver intent and team instruction remain partly
  unobserved.
- Wet-weather, Safety Car, red-flag and advanced multi-stop optimization remain
  outside version one.
- The 2025 season has not yet undergone final temporal model evaluation.
- One 2025 Japanese Grand Prix session received limited feasibility inspection
  during Phase 1 and must remain disclosed.

## Acceptance criteria

All Phase 4 acceptance criteria were satisfied:

1. Canonical decision rows are defined and versioned.
2. Every input feature has a decision-time source.
3. Decision and target eligibility are separate.
4. Whole-race temporal folds are deterministic.
5. Leakage tests reject forbidden future and target-lap information.
6. Protected 2025 records are rejected.
7. Dataset artifacts are atomic and verified.
8. Manifests, reports and catalogs reconcile.
9. PostgreSQL entities and relationships are documented.
10. Alembic creates the schema reproducibly.
11. Database constraints reject invalid data.
12. Development datasets load transactionally.
13. Unit, lint and PostgreSQL checks pass.
14. Real 68-race dataset and database audits pass.
15. Assumptions, limitations and commands are documented.

## Phase 5 handoff

Phase 5 will use the frozen Phase 4 interfaces to:

1. Define simple, reproducible baselines.
2. Evaluate at whole-race temporal folds.
3. Compare against meaningful naive predictors.
4. Establish metrics and acceptance thresholds before advanced modelling.
5. Preserve the protected 2025 season for final evaluation.
