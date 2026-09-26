# API and Dashboard Contract

## Purpose

Phase 10 exposes the verified strategy system without changing its modelling,
simulation or recommendation semantics. The API and dashboard are presentation
and orchestration layers over the completed Phase 6–9 contracts.

The public API contract version is `1.0` and every versioned route is below
`/api/v1`.

## V1 decision scope

The first public version supports one controlled decision:

- Analyse a dry green-flag state at the start of a race lap.
- Compare pitting after the current lap with staying out for one additional lap.
- Use one shared target dry compound and one shared pit-loss assumption.
- Simulate both actions to the flag.
- Minimize expected remaining race time.
- Return `NO_CLEAR_ADVANTAGE` when the evidence does not separate the actions.

The dashboard must not imply support for weather transitions, Safety Cars,
traffic interactions, failures, rival reactions, automatic compound selection
or advanced multi-stop optimization.

## Evidence language

Phase 9 scenario shares describe how often an action was faster inside the
declared simulated worlds. They are not probabilities that an action is correct
in a real race.

The dashboard must use the labels:

- `PIT_NOW scenario share`
- `STAY_OUT scenario share`
- `central 90% paired-advantage interval`
- `NO_CLEAR_ADVANTAGE`

It must not relabel those values as confidence, accuracy, win probability,
success probability or certainty.

Counterfactual strategy accuracy remains unproven because only the historical
action was observed. The alternative action has no real-world ground-truth
outcome.

## Temporal boundary

Development evidence is limited to the 2022, 2023 and 2024 seasons. The 2025
season remains the protected temporal evaluation set until the final Phase 11
gate.

API services must reject attempts to load protected 2025 records through
development-only endpoints. Dashboard fixtures and screenshots must not
quietly use protected data.

## Execution boundary

The deterministic comparison and paired-scenario comparison are separate
execution modes.

Paired-scenario requests inherit the Phase 9 limits:

| Limit | Scenarios |
|---|---:|
| Minimum population for interval stability | 100 |
| Frozen default batch | 10,000 |
| Maximum legal batch | 100,000 |

Large scenario runs are not suitable for a synchronous browser request. Phase
10 must expose expensive work through bounded background jobs or verified
stored evidence. Request cancellation, failure and incomplete output must never
be presented as a valid recommendation.

The measured Phase 9 audit showed that four workers were fastest on the project
machine. The API must not assume that more workers always improve performance.

## Initial endpoints

### `GET /health`

Returns a minimal liveness response:

```json
{"status": "healthy"}
```

This unversioned route remains stable for container and deployment health
checks.

### `GET /api/v1/capabilities`

Returns the machine-readable V1 scope, action and recommendation values,
execution modes, scenario limits and protected-evaluation boundary.

This endpoint lets the React client render supported behavior from the backend
contract rather than duplicate hidden assumptions.

### `GET /api/v1/evidence/development`

Independently verifies the final Phase 6 model artifact and the immutable Phase
7, Phase 8 and Phase 9 reports before returning their identities and artifact
counts. It never exposes local filesystem paths.

### `GET /api/v1/reports/concurrent-simulation/{run_id}`

Returns one compact decision summary from a fully verified Phase 9 report. The
response includes the decision state, calibration scales, complete action-time
means, paired-advantage interval, scenario shares, recommendation and fastest
measured concurrent configuration.

Unsafe run identities are rejected during request validation. Missing or
invalid evidence returns the stable `EVIDENCE_UNAVAILABLE` error without
leaking internal paths.

### `POST /api/v1/analysis/deterministic`

Accepts only the exact season, session, driver, decision lap and target compound
of an existing Phase 8 development decision. It verifies the Phase 6–9 evidence
bundle, the development dataset, the selected processed race and model dataset
identity before reconstructing the historical start-of-lap context.

The response contains complete `PIT_NOW` and one-lap `STAY_OUT` trajectories,
separately accounted racing time and pit loss, a signed advantage where positive
seconds favor `PIT_NOW`, and a point-estimate recommendation. Its
`recommendation_basis` is `POINT_ESTIMATE_ONLY`; uncertainty and real-world
counterfactual accuracy are explicitly not claimed. Absent decisions return
`404 DECISION_NOT_AVAILABLE`, invalid evidence returns
`503 EVIDENCE_UNAVAILABLE` and 2025 inputs fail request validation.

### `POST /api/v1/analysis/paired/jobs`

Starts a bounded background job for one recorded Phase 8 development decision.
The request accepts 100–1,000 paired scenarios, a deterministic root seed and
one to four workers. The interactive default is 100 scenarios; the stored
Phase 9 report still provides the verified 10,000-scenario example. The
capabilities response distinguishes these interactive limits from the frozen
Phase 9 generator limits.

At most one job runs and one waits in each API process. A full queue returns
`429 ANALYSIS_QUEUE_FULL`. Invalid and protected inputs fail before entering
the queue. A `202` response supplies a job ID and status without implying that
an analysis result already exists.

### `GET /api/v1/analysis/paired/jobs/{job_id}`

Returns `QUEUED`, `RUNNING`, `CANCEL_REQUESTED`, `CANCELLED`, `COMPLETED` or
`FAILED`, along with completed scenario count. A result is present only for a
fully completed run. The final result includes paired action means, signed
advantage interval, scenario shares and the stability-based recommendation.
The shares remain descriptive simulated-world evidence, not correctness
probabilities. Failed jobs expose stable error codes without local paths.

### `DELETE /api/v1/analysis/paired/jobs/{job_id}`

Requests cancellation. Waiting jobs can stop immediately; running jobs check
for cancellation between small scenario chunks. Partial output never becomes a
valid recommendation. A missing or evicted job returns `404 JOB_NOT_FOUND`.

Jobs are in-memory and disappear on process restart. Phase 11 deployment must
run a single API worker until job state moves to shared persistent storage.

## Remaining Phase 10 endpoints

The React client and final integrated audit remain. Additional assumption
controls require separate validation before entering the V1 contract.

Route names and payload schemas become frozen only when their implementation
and tests land. This document does not pretend that planned endpoints already
exist.

## Dashboard requirements

The React dashboard must:

1. Show the selected race state and every user-controlled assumption.
2. Display both complete remaining-race action times.
3. Display advantage with an explicit sign convention.
4. Show scenario shares beside, not instead of, the uncertainty interval.
5. Make `NO_CLEAR_ADVANTAGE` a first-class result.
6. Separate model error, scenario uncertainty and recommendation language.
7. Display data season, artifact version, contract version and random seed.
8. Show loading, failure, cancellation and stale-result states.
9. Remain usable on laptop and mobile-width screens.
10. Never fabricate unsupported live timing or protected-evaluation results.

## Phase 10 milestones

| Milestone | Result | Phase 10 completion |
|---|---|---:|
| 1. API contract | Freeze scope, versioning, language and capabilities | 10% |
| 2. Evidence services | Load and verify stored Phase 6–9 artifacts | 25% |
| 3. Read-only endpoints | Expose reports, decisions and summaries | 40% |
| 4. Analysis orchestration | Run deterministic and bounded scenario work | 60% |
| 5. React foundation | Build typed client, layout and system states | 72% |
| 6. Strategy dashboard | Visualize actions, intervals and provenance | 88% |
| 7. Integration and tests | Verify backend/frontend behavior together | 96% |
| 8. Final audit | Publish reproducible Phase 10 evidence | 100% |

## Acceptance gates

Phase 10 is complete only when:

1. Public routes are versioned and documented through OpenAPI.
2. Request and response schemas reject malformed or unsupported values.
3. The API preserves all Phase 6–9 contract semantics.
4. Protected 2025 development access fails closed.
5. Artifact responses come only from independently verified reports.
6. Expensive scenario work cannot block an unbounded synchronous request.
7. Concurrent and sequential evidence remain semantically identical.
8. API errors are stable, explicit and tested.
9. The React client consumes the public API rather than backend internals.
10. The UI displays assumptions, provenance and uncertainty honestly.
11. Loading, error, cancellation and no-clear-advantage states are tested.
12. Accessibility and responsive-layout checks pass.
13. Backend tests pass with warnings treated as errors.
14. Frontend lint, type, unit and production-build checks pass.
15. A real development audit produces zero integrity issues.
16. Protected evaluation remains unopened until Phase 11.
