# Development Data Profile

## Purpose

This report records the initial quality profile of the Formula 1 development
data collected during Phase 2.

The investigation covers only the development seasons:

- 2022
- 2023
- 2024

The protected 2025 final-evaluation season was not inspected.

## Dataset scale

The development dataset contains:

| Table | Records |
|---|---:|
| Race sessions | 68 |
| Lap records | 74,601 |
| Weather observations | 11,115 |
| Driver-result records | 1,359 |

The development seasons contain:

- 22 races from 2022
- 22 races from 2023
- 24 races from 2024

## Structural quality

The initial audit found:

- Zero duplicate lap identities
- Zero missing driver values
- Zero missing team values
- Zero missing lap numbers
- Zero missing stint numbers
- Zero missing track-status values
- Zero missing lap-start times
- Zero missing accuracy indicators
- Zero non-positive lap times
- Zero invalid non-null tyre-life values
- Zero deleted race laps

This indicates that the raw dataset has strong structural consistency.

## Lap-quality findings

| Finding | Records | Approximate share |
|---|---:|---:|
| Missing lap time | 1,187 | 1.6% |
| Marked inaccurate | 10,122 | 13.6% |
| First lap of race | 1,350 | 1.8% |
| Pit-entry lap | 2,628 | 3.5% |
| Pit-exit lap | 2,604 | 3.5% |
| Missing at least one sector time | 1,676 | 2.2% |
| Missing tyre life | 555 | 0.7% |
| FastF1-generated lap | 105 | 0.1% |

These categories overlap. They must not be added together to calculate the
number of unusable laps.

A lap may simultaneously be inaccurate, contain a pit stop and have a missing
sector time.

## Missing lap times

Missing lap times appear in 54 of the 68 development races.

This does not automatically mean that the affected sessions are unusable.
Missing times may be associated with retirements, incomplete laps, timing
interruptions or other race events.

Rows with missing lap times will remain traceable but cannot serve as lap-time
prediction targets.

## Accuracy indicator

FastF1 marks 10,122 laps as inaccurate.

The initial version-one rule will exclude these laps from controlled lap-time
modelling while preserving them in the flagged-lap output.

The reasons behind inaccurate laps will be explored before the rule is frozen.

## Sector times

A total of 1,676 laps are missing at least one sector time.

A missing sector does not automatically invalidate a lap when its complete lap
time remains available. Sector availability will be recorded separately from
lap-time eligibility.

## Track status

Exactly 66,766 laps, approximately 89.5% of the development data, have track
status `1`.

The remaining records include individual and combined status values.

The most common values include:

| Track status | Records |
|---|---:|
| `1` | 66,766 |
| `12` | 2,401 |
| `4` | 1,912 |
| `41` | 742 |
| `124` | 530 |
| `671` | 362 |
| `126` | 304 |
| `21` | 249 |
| `26` | 158 |
| `6` | 145 |

Combined values indicate that track conditions changed or that multiple
statuses applied during the recorded lap.

For the initial controlled dataset, only the exact value `1` will be considered
normal green-flag running. Other values will be preserved and flagged rather
than interpreted as fully green.

## Tyre compounds

| Compound | Lap records | Approximate share |
|---|---:|---:|
| HARD | 33,514 | 44.9% |
| MEDIUM | 26,455 | 35.5% |
| SOFT | 9,455 | 12.7% |
| INTERMEDIATE | 4,347 | 5.8% |
| WET | 461 | 0.6% |
| NONE | 369 | 0.5% |

Dry compounds account for most of the dataset.

INTERMEDIATE and WET records will be classified as wet-condition laps and
excluded from the initial controlled modelling dataset.

The `NONE` value is a source category rather than a null value. It will be
treated as an unsupported compound and investigated before exclusion.

## Rainfall observations

Rainfall was recorded during 16 development sessions:

- 2022-05-R
- 2022-07-R
- 2022-10-R
- 2022-13-R
- 2022-17-R
- 2022-18-R
- 2023-06-R
- 2023-09-R
- 2023-12-R
- 2023-13-R
- 2023-20-R
- 2024-09-R
- 2024-10-R
- 2024-11-R
- 2024-12-R
- 2024-21-R

A rainy session is not necessarily wet for its entire duration. Rainfall
observations must be aligned to individual laps before wet-condition
eligibility is determined.

## Wet-compound sessions

Wet-weather compounds were used during nine development sessions:

- 2022-04-R
- 2022-07-R
- 2022-17-R
- 2022-18-R
- 2023-06-R
- 2023-13-R
- 2024-09-R
- 2024-12-R
- 2024-21-R

The difference between rainfall sessions and wet-compound sessions confirms
that entire races should not be discarded only because one rainfall
observation exists.

Lap-level classification is required.

## Data-type consistency

One lap column has inconsistent stored data types across sessions:

- `IsPersonalBest`: `bool` in some sessions and `object` in others

The cleaning pipeline will normalize this field to a nullable boolean type.

No other lap-column data-type conflicts were detected.

## Result-status observations

The most common driver-result statuses are:

| Status | Driver results |
|---|---:|
| Finished | 870 |
| Lapped | 208 |
| Retired | 102 |
| +1 Lap | 80 |
| Collision damage | 14 |
| Accident | 11 |
| Collision | 10 |
| Engine | 7 |
| Power Unit | 6 |
| +2 Laps | 6 |
| Did not start | 6 |
| Gearbox | 4 |

Result status will provide context for incomplete races and missing lap times.
It will not be used to insert missing lap-time targets.

## Initial decisions

The audit supports the following initial decisions:

1. Preserve the raw dataset unchanged.
2. Classify eligibility at lap level instead of immediately excluding complete
   races.
3. Treat only exact track status `1` as controlled green-flag running.
4. Align weather observations to laps before applying rainfall exclusions.
5. Retain only SOFT, MEDIUM and HARD for the initial controlled analysis.
6. Preserve missing lap-time rows for auditing but not as prediction targets.
7. Initially exclude laps marked inaccurate from lap-time modelling.
8. Keep laps with missing sectors when valid total lap time remains available.
9. Normalize `IsPersonalBest` to a consistent nullable boolean type.
10. Preserve FastF1-generated laps and examine their relationship with the
    accuracy indicator before deciding whether they need a separate exclusion.

## Important limitation

The current counts describe individual quality conditions. They do not yet
represent the final number of eligible laps because:

- Several conditions overlap
- Weather has not yet been aligned to laps
- Pit-entry and pit-exit classifications may overlap other exclusions
- Statistical outliers have not been investigated
- Final eligibility rules have not been frozen

The cleaning pipeline will calculate reason combinations and the final eligible
development population reproducibly.

## Next action

The next step is to implement a tested, repeatable development-data profiler so
that these quality statistics can be regenerated automatically from the
immutable raw dataset.