export type Compound = 'SOFT' | 'MEDIUM' | 'HARD'
export type ActionName = 'PIT_NOW' | 'STAY_OUT'
export type Recommendation = ActionName | 'NO_CLEAR_ADVANTAGE'
export type DecisionKey = {
  season: 2022 | 2023 | 2024
  session_id: string
  driver: string
  decision_lap: number
  target_compound: Compound
}
export type Decision = DecisionKey & {
  event_name: string
  team: string
  total_laps?: number
  current_compound?: Compound
  driver_name?: string
}
export type AnalysisLap = {
  lap_number: number
  compound: Compound
  tyre_age_laps: number
  predicted_lap_time_seconds: number
  pit_loss_seconds: number
  total_lap_time_seconds: number
  elapsed_time_after_lap_seconds: number
  pitted_after_lap: boolean
}
export type Action = {
  action: ActionName
  expected_remaining_time_seconds: number
  racing_time_seconds: number
  pit_loss_seconds: number
  laps: AnalysisLap[]
}
export type PointResult = Decision & {
  mode: 'DETERMINISTIC'
  total_laps: number
  current_compound: Compound
  assumed_pit_loss_seconds: number
  pit_now: Action
  stay_out: Action
  pit_now_advantage_seconds: number
  recommendation: Recommendation
  recommendation_basis: 'POINT_ESTIMATE_ONLY'
  uncertainty_evaluated: false
}
export type PairedResult = DecisionKey & {
  scenario_count: number
  root_seed: number
  calibration_id: string
  point_advantage_seconds: number
  pit_now_mean_seconds: number
  stay_out_mean_seconds: number
  advantage_mean_seconds: number
  advantage_p05_seconds: number
  advantage_median_seconds: number
  advantage_p95_seconds: number
  pit_now_scenario_share: number
  stay_out_scenario_share: number
  tie_scenario_share: number
  recommendation: Recommendation
  recommendation_is_stable: boolean
  scenario_shares_are_correctness_probabilities: false
  counterfactual_strategy_accuracy_is_proven: false
}
export type JobStatus = 'QUEUED' | 'RUNNING' | 'CANCEL_REQUESTED' | 'CANCELLED' | 'COMPLETED' | 'FAILED'
export type PairedJob = DecisionKey & {
  job_id: string
  status: JobStatus
  scenario_count: number
  completed_scenarios: number
  result: PairedResult | null
  error_code: string | null
}
export type DevelopmentEvidence = {
  status: 'valid'
  protected_evaluation_rows: 0
  artifacts: { kind: 'MODEL' | 'SIMULATION' | 'OPTIMIZER' | 'CONCURRENT_SIMULATION'; identifier: string; artifact_count: number; verification_rows: number | null }[]
}
