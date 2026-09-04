# F1 Race Strategy Optimizer — PostgreSQL Schema Contract

## Purpose

This document defines the logical and physical PostgreSQL design for Phase 4.

PostgreSQL provides queryable application storage, relational integrity,
version traceability and transaction-safe loading.

Parquet remains the authoritative analytical artifact.

The database must preserve the identities, values and semantic boundaries
defined by:

- `RAW_DATA_CONTRACT.md`
- `PROCESSED_DATA_CONTRACT.md`
- `DATASET_CONTRACT.md`

The database must not become an undocumented second cleaning or feature-building
pipeline.

## Contract versions

The initial database schema version is `1.0`.

It supports:

- Raw source contract `1.0`
- Processed contract `1.0`
- Cleaning-rule version `1.0`
- Dataset contract `1.0`

A database migration may change storage structure without changing analytical
meaning.

A change to decision identity, feature availability, target eligibility,
historical-action meaning or pit-duration meaning requires a new dataset
contract version.

## PostgreSQL namespace

All application tables are stored in the PostgreSQL schema:

```text
f1_strategy
```

Alembic owns creation and revision of this namespace.

Application code must not create tables implicitly with
`metadata.create_all()`.

## Source authority

Database values originate from verified artifacts.

| Database family | Authoritative source |
|---|---|
| Seasons, events and circuits | Raw `metadata.json` |
| Race-session identity | Raw and processed manifests |
| Drivers, teams and participation | Normalized processed tables |
| Processed laps | Processed `laps.parquet` |
| Reconstructed stints | Processed `stints.parquet` |
| Reconstructed pit events | Processed `pit_events.parquet` |
| Decision rows | Dataset `decision_rows.parquet` |
| Decision labels | Dataset `decision_labels.parquet` |
| Pit-duration targets | Dataset `pit_duration_observations.parquet` |
| Dataset session totals | Dataset `catalog.parquet` |
| Temporal assignments | Dataset `splits.parquet` |
| File provenance | Raw, processed and dataset manifests |

The loader must verify source manifests and file hashes before opening a
database transaction.

## Identity rules

Canonical external identifiers remain unchanged:

```text
session_id
    = season + zero-padded round number + session type

decision_id
    = session_id + driver + zero-padded decision lap

pit_event_id
    = processed pit-event identifier
```

Examples:

```text
2024-01-R
2024-01-R-VER-023
2024-01-R-VER-IN-022-OUT-023
```

Surrogate numeric keys may support joins, but they never replace the canonical
external identifiers in stored analytical records.

## Timestamp rules

Database-generated timestamps use PostgreSQL `timestamp with time zone`.

Application timestamps must be timezone-aware and normalized to UTC before
insertion.

Raw `event_date` is stored as a calendar date because the source does not
provide a verified event-start timezone.

Elapsed session times remain elapsed values rather than being converted into
wall-clock timestamps.

A non-null naive timestamp must be rejected instead of silently being labelled
as UTC.

## Reference entities

### `seasons`

One row represents one Formula 1 season.

Primary key:

```text
season
```

Constraints:

- `season` is a four-digit positive integer.
- Duplicate seasons are forbidden.

### `circuits`

One row represents a source-observed circuit location.

The raw contract provides `country` and `location`, but not a canonical circuit
identifier or verified circuit name.

Columns include:

- `circuit_id`
- `country`
- `location`
- `circuit_name`

Primary key:

```text
circuit_id
```

Natural uniqueness:

```text
country + location
```

`circuit_name` is nullable until an authoritative source supplies it.

The loader must not invent a circuit name from the event name.

### `events`

One row represents one scheduled race event in one season.

Columns include:

- `event_id`
- `season`
- `round_number`
- `circuit_id`
- `event_name`
- `official_event_name`
- `event_date`
- `event_format`

Primary key:

```text
event_id
```

Natural uniqueness:

```text
season + round_number
```

Foreign keys:

- `season` references `seasons`.
- `circuit_id` references `circuits`.

### `race_sessions`

One row represents one race session.

Columns include:

- `session_id`
- `event_id`
- `season`
- `round_number`
- `session_type`

Primary key:

```text
session_id
```

Natural uniqueness:

```text
season + round_number + session_type
```

Foreign keys:

- `event_id` references `events`.
- `season` and `round_number` reference the corresponding event identity.

V1 permits only session type `R`.

The stored `session_id` must match the canonical formatted identity.

### `drivers`

One row represents one source-observed driver code.

Columns include:

- `driver_id`
- `driver_code`
- `driver_name`

Primary key:

```text
driver_id
```

Natural uniqueness:

```text
driver_code
```

`driver_name` is nullable because it is not part of the processed dataset
contract.

### `teams`

One row represents one exact source-observed team name.

Columns include:

- `team_id`
- `team_name`

Primary key:

```text
team_id
```

Natural uniqueness:

```text
team_name
```

V1 does not merge, rename or reinterpret teams across seasons.

### `session_participants`

One row represents one driver participating for one team in one race session.

Columns include:

- `session_id`
- `driver_id`
- `team_id`
- `driver_number`

Primary key:

```text
session_id + driver_id
```

Foreign keys:

- `session_id` references `race_sessions`.
- `driver_id` references `drivers`.
- `team_id` references `teams`.

Within a session, a non-null driver number must be unique.

Team membership belongs here rather than on `drivers` because it changes over
time.

## Processed-source provenance

### `processed_session_partitions`

One row represents one verified processed partition for one race session and
one processed-rule combination.

Columns include:

- `processed_partition_id`
- `session_id`
- `source_contract_version`
- `processed_contract_version`
- `cleaning_rule_version`
- `created_at_utc`
- `session_directory`
- `source_manifest_sha256`
- `processed_manifest_sha256`
- `laps_sha256`
- `stints_sha256`
- `pit_events_sha256`
- `quality_report_sha256`
- Source and processed row counts
- Total stored bytes

Primary key:

```text
processed_partition_id
```

Natural uniqueness:

```text
session_id
+ source_contract_version
+ processed_contract_version
+ cleaning_rule_version
```

All SHA-256 values use exactly 64 lowercase hexadecimal characters.

## Processed analytical entities

### `processed_laps`

One row represents one normalized processed driver lap.

Primary key:

```text
processed_partition_id + source_row_number
```

Natural uniqueness:

```text
processed_partition_id + driver_id + lap_number
```

Foreign keys:

- `processed_partition_id` references `processed_session_partitions`.
- `session_id` and `driver_id` reference `session_participants`.

All 55 processed lap fields are preserved using deterministic snake-case
database names.

Source duration values are stored losslessly as integer nanoseconds.

Existing derived second values remain PostgreSQL double-precision values.

`lap_start_date_utc` is nullable. A future non-null value requires verified UTC
semantics.

No database expression may recalculate `IsEligible`, quality flags, exclusion
reasons, weather matching or timing fields.

### `reconstructed_stints`

One row represents one Phase 3 reconstructed stint.

Primary key:

```text
processed_partition_id + driver_id + stint_number
```

Foreign keys:

- `processed_partition_id` references `processed_session_partitions`.
- `session_id` and `driver_id` reference `session_participants`.

All 20 processed stint fields are preserved.

Checks include:

- Stint number is positive.
- Start and end laps are positive.
- End lap is not below start lap.
- Recorded laps are positive.
- Warning count is non-negative.

### `reconstructed_pit_events`

One row represents one Phase 3 reconstructed pit event.

Primary key:

```text
processed_partition_id + pit_event_id
```

Foreign keys:

- `processed_partition_id` references `processed_session_partitions`.
- `session_id` and `driver_id` reference `session_participants`.

All 33 processed pit-event fields are preserved.

Allowed event types are:

```text
MATCHED
ENTRY_ONLY
EXIT_ONLY
```

Checks preserve the difference between complete and incomplete events.

Observed pit-lane duration is not renamed or reinterpreted as stationary service
time or net racing-time loss.

## Dataset provenance

### `dataset_versions`

One row defines one immutable dataset contract version.

Columns include:

- `dataset_contract_version`
- `database_schema_version`
- `source_contract_version`
- `processed_contract_version`
- `cleaning_rule_version`
- `created_at_utc`

Primary key:

```text
dataset_contract_version
```

Version values must be non-empty.

A dataset version is immutable after rows reference it.

### `dataset_builds`

One row represents one dataset batch execution.

Columns include:

- `run_id`
- `dataset_contract_version`
- `started_at_utc`
- `completed_at_utc`
- `status`
- `requested_sessions`
- `written_sessions`
- `skipped_sessions`
- `failed_sessions`
- `catalog_sha256`
- `splits_sha256`
- `run_record_path`

Primary key:

```text
run_id
```

Foreign key:

- `dataset_contract_version` references `dataset_versions`.

Allowed statuses are:

```text
RUNNING
SUCCEEDED
FAILED
```

Count fields are non-negative.

A successful build must have zero failed sessions.

### `dataset_sessions`

One row represents one authoritative dataset session partition.

Primary key:

```text
dataset_contract_version + session_id
```

Foreign keys:

- `dataset_contract_version` references `dataset_versions`.
- `session_id` references `race_sessions`.
- `processed_partition_id` references `processed_session_partitions`.
- `created_by_run_id` references `dataset_builds`.

Stored provenance includes:

- Dataset manifest hash
- Decision-row hash
- Decision-label hash
- Pit-duration hash
- Quality-report hash
- Session directory
- Creation timestamp
- Row counts
- Eligible and ineligible totals
- Total stored bytes

These totals must match the dataset catalog and session manifest.

## Dataset analytical entities

### `decision_rows`

One row represents one driver decision at the start of lap `t`.

Primary key:

```text
dataset_contract_version + decision_id
```

Natural uniqueness:

```text
dataset_contract_version
+ session_id
+ driver_id
+ decision_lap
```

Foreign keys:

- Dataset version and session reference `dataset_sessions`.
- Session and driver reference `session_participants`.
- Source partition and source row reference `processed_laps`.

All 55 decision-row contract fields are preserved.

The database stores the supplied decision state. It does not rebuild:

- Current compound
- Tyre age
- Current stint
- Previous position
- Weather alignment
- Rolling features
- Decision eligibility

A decision eligible row must have zero decision exclusions.

An ineligible row must have at least one exclusion.

### `decision_labels`

One row stores labels separated from decision features.

Primary key:

```text
dataset_contract_version + decision_id
```

Foreign keys:

- Dataset version and decision ID reference `decision_rows`.
- A non-null pit-event reference points to `reconstructed_pit_events`.

Allowed historical actions are:

```text
PIT_NOW
STAY_OUT
```

Checks require:

- `PIT_NOW` corresponds to `did_pit = true`.
- `STAY_OUT` corresponds to `did_pit = false`.
- An eligible lap-time target has a non-null positive target.
- An ineligible lap-time target has a null target.

Label columns are never exposed by a generic feature query.

### `pit_duration_observations`

One row preserves one separated pit-duration observation.

Primary key:

```text
dataset_contract_version + pit_event_id
```

Foreign keys:

- Dataset version and session reference `dataset_sessions`.
- Source partition and pit-event ID reference
  `reconstructed_pit_events`.

All 28 pit-duration contract fields are preserved.

Checks require:

- An eligible target has a non-null positive duration.
- An ineligible target has a null duration.
- Exclusion counts are non-negative.

Observed pit-lane duration remains distinct from net pit loss.

## Temporal folds

### `temporal_folds`

One row defines one fold within one dataset version.

Primary key:

```text
dataset_contract_version + fold_id
```

The V1 fold identifiers are:

```text
development_fold_1
development_fold_2
final_development_fit
```

### `session_split_assignments`

One row assigns one complete race session to one fold role.

Primary key:

```text
dataset_contract_version + fold_id + session_id
```

Foreign keys:

- Dataset version and fold ID reference `temporal_folds`.
- Dataset version and session ID reference `dataset_sessions`.

Allowed roles are:

```text
TRAIN
VALIDATION
EXCLUDED
```

Every dataset session appears exactly once in every declared fold.

No driver or lap-level split is permitted.

## Quality reasons

### `quality_reasons`

One row defines one versioned quality reason.

Primary key:

```text
dataset_contract_version + scope + reason_code
```

Supported scopes are:

```text
PROCESSED_LAP
RECONSTRUCTED_STINT
RECONSTRUCTED_PIT_EVENT
DECISION
LAP_TARGET
PIT_DURATION_TARGET
```

The database stores reason definitions; it does not decide whether a reason
applies.

### Quality-reason link tables

The schema contains separate foreign-key-safe link tables:

- `processed_lap_quality_reasons`
- `stint_quality_reasons`
- `pit_event_quality_reasons`
- `decision_quality_reasons`
- `lap_target_quality_reasons`
- `pit_duration_quality_reasons`

Each link stores:

- Parent identity
- Dataset or processed version identity
- Reason code
- Deterministic reason ordinal

The original encoded reason string and declared reason count remain on the
parent analytical table.

During loading, splitting the canonical encoded string into link rows must be
lossless. Rejoining link rows in ordinal order must reproduce the exact source
string.

## Physical type mapping

| Source meaning | PostgreSQL type |
|---|---|
| Canonical external identifier | `varchar` |
| Free-form source text | `text` |
| Whole-number count | `bigint` |
| Season or small ordinal | `smallint` |
| Floating-point measurement | `double precision` |
| Boolean state | `boolean` |
| Calendar event date | `date` |
| UTC instant | `timestamp with time zone` |
| Exact elapsed duration | `bigint` nanoseconds |
| SHA-256 digest | `char(64)` |
| Surrogate key | `bigint generated by default as identity` |

Numeric types must not coerce fractional values into integers.

Empty strings are not substitutes for SQL null unless the source contract
explicitly defines the empty string as a canonical value.

## Required constraints

The initial migration must provide:

1. Primary keys for every table.
2. Foreign keys for every declared relationship.
3. Natural uniqueness constraints.
4. Positive lap and stint checks.
5. Non-negative count checks.
6. Allowed-value checks for session type, actions, event types, split roles,
   build statuses and reason scopes.
7. Target-value checks tied to target eligibility.
8. Decision-exclusion checks tied to decision eligibility.
9. SHA-256 format checks.
10. UTC-aware database timestamps.
11. Protected-season rejection in development loading interfaces.
12. Cascading deletes only between a parent artifact and its dependent link
    rows.

Reference entities, processed partitions and dataset versions must not be
silently deleted through cascading relationships.

## Required indexes

Indexes support the expected access paths:

- Events by season and round
- Sessions by season and round
- Participants by driver and team
- Processed laps by session, driver and lap
- Stints by session and driver
- Pit events by session, driver and pit lap
- Dataset sessions by version
- Eligible decision rows by version and session
- Decision rows by session, driver and decision lap
- Labels by historical action
- Eligible lap-time targets
- Eligible pit-duration targets
- Split assignments by fold and role
- Quality links by reason code
- Dataset builds by version and start time

PostgreSQL partial indexes are used for eligible decision and target
populations.

Indexes must support queries without changing dataset semantics.

## Transaction boundaries

One dataset-session load occurs in one database transaction.

The loader must:

1. Verify the source dataset partition before opening the transaction.
2. Upsert immutable reference rows safely.
3. Insert or verify processed provenance.
4. Insert processed analytical rows.
5. Insert the dataset-session record.
6. Insert decision rows.
7. Insert separated labels.
8. Insert pit-duration observations.
9. Insert quality-reason links.
10. Reconcile row counts and identities.
11. Commit only after every validation passes.

Any failure rolls back the entire session load.

A retry must either verify an identical completed load or replace it only when
explicit force behaviour is requested.

## Development boundary

Phase 4 development database interfaces accept only:

```text
2022
2023
2024
```

The protected evaluation season is:

```text
2025
```

Development loaders must reject 2025 before opening a write transaction.

The database schema may remain technically capable of storing future versions,
but Phase 4 development code must not access, load or summarize protected 2025
records.

## Reconciliation requirements

A complete V1 development load must prove:

- 68 race sessions
- 22 sessions from 2022
- 22 sessions from 2023
- 24 sessions from 2024
- 73,251 decision rows
- 73,251 decision labels
- 55,943 eligible decisions
- 17,308 ineligible decisions
- 1,776 eligible `PIT_NOW` rows
- 54,167 eligible `STAY_OUT` rows
- 52,483 eligible lap-time targets
- 2,693 pit-duration observations
- 1,465 eligible pit-duration targets
- 204 temporal split assignments
- 0 future weather matches
- 0 protected evaluation rows
- Matching database, catalog and manifest totals

Database row reconciliation is evidence of faithful loading. It is not
permission to redefine source values.

## Migration requirements

Alembic is the only schema migration mechanism.

The migration environment must:

- Use SQLAlchemy metadata as its schema source
- Include the `f1_strategy` PostgreSQL namespace
- Use deterministic constraint names
- Render PostgreSQL types explicitly
- Support online upgrade and offline SQL generation
- Never embed secrets in migration files
- Upgrade an empty database reproducibly
- Downgrade the initial schema completely
- Leave no unmanaged tables or types

The initial migration revision is immutable after Phase 4 is merged.

Future changes require a new revision.

## Testing requirements

Unit tests must verify:

- Exact table names
- Exact primary keys
- Foreign-key targets
- Natural uniqueness constraints
- Check constraints
- Required indexes
- PostgreSQL DDL compilation
- Metadata and migration parity
- Protected-season rejection
- UTC timestamp requirements

PostgreSQL integration tests must verify:

- Upgrade from an empty database
- Downgrade to an empty application schema
- Constraint rejection
- Transaction rollback
- Idempotent verified loading
- Dataset-to-database row reconciliation

Integration tests require a real PostgreSQL service. SQLite is not an acceptable
substitute for PostgreSQL-specific behaviour.