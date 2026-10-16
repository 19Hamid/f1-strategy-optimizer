import type { Decision, DecisionKey, PairedResult } from './types'

/** Exactly the case and output observed in the project's development smoke run. */
export const example: Decision = {
  season: 2024,
  session_id: '2024-04-R',
  event_name: 'Japanese Grand Prix',
  driver: 'HAM',
  driver_name: 'Lewis Hamilton',
  team: 'Mercedes',
  decision_lap: 38,
  total_laps: 53,
  target_compound: 'MEDIUM',
}

export const examplePointAdvantage = 1.749868914045237

/** Saved output fields known from the 100-scenario smoke run; unobserved fields are not fabricated. */
export const examplePaired = {
  recommendation: 'NO_CLEAR_ADVANTAGE',
  scenario_count: 100,
  root_seed: 42,
  advantage_p05_seconds: -34.5190981222608,
  advantage_p95_seconds: 69.85115477900862,
} satisfies Pick<PairedResult, 'recommendation' | 'scenario_count' | 'root_seed' | 'advantage_p05_seconds' | 'advantage_p95_seconds'>

export function identity(d: DecisionKey): string {
  return `${d.season}/${d.session_id}/${d.driver}/${d.decision_lap}/${d.target_compound}`
}

export function name(d: Decision): string {
  return d.driver_name ?? (d.driver === 'HAM' && d.season === 2024 ? 'Lewis Hamilton' : d.driver)
}
