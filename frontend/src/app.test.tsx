// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from './main'
import { ApiProblem } from './api'
import { example } from './data'
import type { ActionName, Decision, PairedJob, PairedResult, PointResult } from './types'

const api = vi.hoisted(() => ({
  checkApi: vi.fn(),
  getDecisions: vi.fn(),
  getDevelopmentEvidence: vi.fn(),
  quickAnalysis: vi.fn(),
  startPaired: vi.fn(),
  getPaired: vi.fn(),
  cancelPaired: vi.fn(),
}))

vi.mock('./api', () => ({
  ...api,
  ApiProblem: class ApiProblem extends Error {
    constructor(public code: string, message: string, public status: number) { super(message) }
  },
}))

const another: Decision = {
  ...example,
  season: 2023,
  session_id: '2023-05-R',
  event_name: 'Second test race',
  driver: 'VER',
  driver_name: 'Second test driver',
  team: 'Second test team',
  decision_lap: 20,
  current_compound: 'SOFT',
  target_compound: 'HARD',
}

function pointFor(decision: Decision): PointResult {
  function action(actionName: ActionName) {
    const stopLap = decision.decision_lap + (actionName === 'STAY_OUT' ? 1 : 0)
    const laps = Array.from({ length: decision.total_laps! - decision.decision_lap + 1 }, (_, index) => {
      const lapNumber = decision.decision_lap + index
      const pit = lapNumber === stopLap ? 20 : 0
      return {
        lap_number: lapNumber, compound: lapNumber <= stopLap ? 'SOFT' as const : decision.target_compound,
        tyre_age_laps: index + 1, predicted_lap_time_seconds: 90, pit_loss_seconds: pit,
        total_lap_time_seconds: 90 + pit, elapsed_time_after_lap_seconds: 90 * (index + 1) + (lapNumber >= stopLap ? 20 : 0),
        pitted_after_lap: lapNumber === stopLap,
      }
    })
    return { action: actionName, expected_remaining_time_seconds: 1440 + (actionName === 'STAY_OUT' ? 1.75 : 0), racing_time_seconds: 1420, pit_loss_seconds: 20, laps }
  }
  return { ...decision, mode: 'DETERMINISTIC', total_laps: decision.total_laps!, current_compound: 'SOFT',
    assumed_pit_loss_seconds: 20, pit_now: action('PIT_NOW'), stay_out: action('STAY_OUT'),
    pit_now_advantage_seconds: 1.75, recommendation: 'PIT_NOW',
    recommendation_basis: 'POINT_ESTIMATE_ONLY', uncertainty_evaluated: false }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.checkApi.mockResolvedValue('preview')
  api.getDecisions.mockResolvedValue({ decisions: [example], catalogReady: true })
  api.getDevelopmentEvidence.mockResolvedValue({ status: 'valid', protected_evaluation_rows: 0, artifacts: [
    { kind: 'MODEL', identifier: 'test-model', artifact_count: 1, verification_rows: 5 },
    { kind: 'SIMULATION', identifier: 'test-simulation', artifact_count: 1, verification_rows: null },
    { kind: 'OPTIMIZER', identifier: 'test-optimizer', artifact_count: 1, verification_rows: null },
    { kind: 'CONCURRENT_SIMULATION', identifier: 'test-concurrent', artifact_count: 1, verification_rows: null },
  ] })
  api.quickAnalysis.mockResolvedValue(pointFor(example))
  api.startPaired.mockResolvedValue(null)
  api.getPaired.mockResolvedValue(null)
  api.cancelPaired.mockResolvedValue(null)
})

afterEach(cleanup)

describe('dashboard state', () => {
  it('lets visitors explore either choice and inspect the recorded result', async () => {
    render(<App />)
    expect(await screen.findByText(/Recorded example/)).toBeTruthy()
    expect(screen.getByRole('combobox', { name: 'Season' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('combobox', { name: 'Driver' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText(/Other cases need a live verified API/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /CHOICE 02/ }))
    expect(screen.getByText('Wait until after lap 39')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /See the recorded 100-test result/ }))
    expect(await screen.findByText('No clear winner.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'THE EVIDENCE' }))
    expect(screen.getByText('Zero is inside the range.')).toBeTruthy()
  })

  it('retries the paired job after a full queue without rerunning the point estimate', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.startPaired.mockRejectedValue(new Error('The analysis queue is full.'))
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    const retry = await screen.findByRole('button', { name: /Try the wider test again/ })
    fireEvent.click(retry)
    await waitFor(() => expect(api.startPaired).toHaveBeenCalledTimes(2))
    expect(api.quickAnalysis).toHaveBeenCalledTimes(1)
  })

  it('does not show an old job when the selected decision changes', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.getDecisions.mockResolvedValue({ decisions: [example, another], catalogReady: true })
    api.quickAnalysis.mockImplementation((decision: Decision) => Promise.resolve(pointFor(decision)))
    const oldJob: PairedJob = { ...example, job_id: 'first-job', status: 'RUNNING', completed_scenarios: 0, scenario_count: 100, result: null, error_code: null }
    let finishCancellation!: (job: PairedJob) => void
    api.startPaired.mockResolvedValue(oldJob)
    api.cancelPaired.mockImplementation(() => new Promise<PairedJob>(resolve => { finishCancellation = resolve }))
    render(<App />)
    await screen.findByRole('combobox', { name: 'Season' })
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    await screen.findByText('0 / 100')
    fireEvent.change(screen.getByRole('combobox', { name: 'Season' }), { target: { value: '2023' } })
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Season' }) as HTMLSelectElement).value).toBe('2023'))
    expect(screen.queryByText(/This recorded case uses hard tyres/)).toBeNull()
    expect(screen.getByText(/On soft now; fit hard at the stop/)).toBeTruthy()
    await waitFor(() => expect(api.quickAnalysis).toHaveBeenCalledWith(another))
    finishCancellation({ ...oldJob, status: 'COMPLETED', result: { recommendation: 'NO_CLEAR_ADVANTAGE' } as PairedResult })
    await waitFor(() => expect(api.cancelPaired).toHaveBeenCalledWith('first-job'))
    expect(screen.queryByText('No clear winner.')).toBeNull()
    expect(screen.queryByText('0 / 100')).toBeNull()
  })

  it('never treats an unverified API catalog as a usable live choice', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.getDecisions.mockRejectedValueOnce(new Error('No verified catalog'))
      .mockResolvedValue({ decisions: [example, another], catalogReady: true })
    render(<App />)
    expect(await screen.findByText('Race browsing is unavailable.')).toBeTruthy()
    expect(screen.queryByRole('combobox', { name: 'Season' })).toBeNull()
    expect(screen.queryByRole('heading', { name: /Should Lewis Hamilton/ })).toBeNull()
    expect(api.quickAnalysis).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /Run 100 paired tests/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }))
    expect(await screen.findByRole('combobox', { name: 'Season' })).toBeTruthy()
    await waitFor(() => expect(api.quickAnalysis).toHaveBeenCalledWith(example))
  })

  it('keeps progress, cancellation and a failed-job retry visible while exploring Race and Evidence', async () => {
    api.checkApi.mockResolvedValue('connected')
    const running: PairedJob = { ...example, job_id: 'running-job', status: 'RUNNING', completed_scenarios: 24, scenario_count: 100, result: null, error_code: null }
    const failed: PairedJob = { ...running, job_id: 'failed-job', status: 'FAILED', result: null, error_code: 'ANALYSIS_FAILED' }
    api.startPaired.mockResolvedValueOnce(running).mockResolvedValueOnce(failed)
    api.cancelPaired.mockResolvedValue({ ...running, status: 'CANCELLED', result: null })
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    await screen.findByText('24 / 100')
    fireEvent.click(screen.getByRole('button', { name: 'THE RACE' }))
    expect(screen.getByRole('button', { name: 'Cancel analysis' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel analysis' }))
    await screen.findByText(/The test was cancelled/)
    fireEvent.click(screen.getByRole('button', { name: 'THE EVIDENCE' }))
    fireEvent.click(screen.getByRole('button', { name: 'Run it again' }))
    expect(await screen.findByText(/The paired test failed/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Run again' })).toBeTruthy()
  })

  it('retries a failed cancellation without submitting a second job', async () => {
    api.checkApi.mockResolvedValue('connected')
    const running: PairedJob = { ...example, job_id: 'first-job', status: 'RUNNING', completed_scenarios: 16, scenario_count: 100, result: null, error_code: null }
    api.startPaired.mockResolvedValue(running)
    api.cancelPaired.mockRejectedValueOnce(new Error('Connection interrupted'))
      .mockResolvedValue({ ...running, status: 'CANCELLED' })
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    await screen.findByText('16 / 100')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel analysis' }))
    expect(await screen.findByRole('button', { name: 'Retry cancellation' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Try the wider test again/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry cancellation' }))
    expect(await screen.findByText(/The test was cancelled/)).toBeTruthy()
    expect(api.startPaired).toHaveBeenCalledTimes(1)
  })

  it('retains an active job after a temporary polling error', async () => {
    api.checkApi.mockResolvedValue('connected')
    const running: PairedJob = { ...example, job_id: 'first-job', status: 'RUNNING', completed_scenarios: 8, scenario_count: 100, result: null, error_code: null }
    api.startPaired.mockResolvedValue(running)
    api.getPaired.mockRejectedValue(new Error('Connection interrupted'))
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    expect(await screen.findByText('8 / 100')).toBeTruthy()
    const retry = await screen.findByRole('button', { name: 'Check again' }, { timeout: 2500 })
    expect(screen.getByRole('button', { name: 'Cancel analysis' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Try the wider test again/ })).toBeNull()
    fireEvent.click(retry)
    await waitFor(() => expect(api.getPaired).toHaveBeenCalledTimes(2), { timeout: 2500 })
    expect(api.startPaired).toHaveBeenCalledTimes(1)
  })

  it('treats a job lost after restart as gone and offers a fresh run', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.startPaired.mockResolvedValue({ ...example, job_id: 'lost-job', status: 'RUNNING', completed_scenarios: 8, scenario_count: 100, result: null, error_code: null })
    api.getPaired.mockRejectedValue(new ApiProblem('JOB_NOT_FOUND', 'The analysis job is unavailable.', 404))
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    expect(await screen.findByText(/Jobs can disappear when the service restarts/, {}, { timeout: 2500 })).toBeTruthy()
    expect(screen.queryByText('8 / 100')).toBeNull()
    expect(screen.getByRole('button', { name: 'Try the wider test again' })).toBeTruthy()
  })

  it('shows a full queue as a retryable paired error without losing the point estimate', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.startPaired.mockRejectedValue(new ApiProblem('ANALYSIS_QUEUE_FULL', 'The queue is full.', 429))
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    expect(await screen.findByText('The analysis queue is busy. Try again shortly.')).toBeTruthy()
    expect(screen.getByText('Stopping this lap looked quicker.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try the wider test again' })).toBeTruthy()
  })

  it('calls a zero-second point difference a tie, not a faster wait', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.quickAnalysis.mockResolvedValue({ ...pointFor(example), pit_now_advantage_seconds: 0 })
    render(<App />)
    expect(await screen.findByText('Both stops look equally quick.')).toBeTruthy()
    expect(screen.getByText('A tie in the first estimate')).toBeTruthy()
  })

  it('shows complete point times and plots the lap that includes pit time', async () => {
    api.checkApi.mockResolvedValue('connected')
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    expect(screen.getAllByText('24:00.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('24:01.75').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'THE EVIDENCE' }))
    expect(screen.getByRole('img', { name: /including the stop on each lap/ })).toBeTruthy()
    expect(screen.getByText(/Total for this lap 110.00 s/)).toBeTruthy()
    expect(await screen.findByText(/test-model · 5 verification rows/)).toBeTruthy()
  })

  it.each([
    { low: 3, high: 9, recommendation: 'PIT_NOW', position: 'stays above zero' },
    { low: -9, high: -3, recommendation: 'STAY_OUT', position: 'stays below zero' },
  ] as const)('describes a $recommendation interval on the correct side of zero', async ({ low, high, recommendation, position }) => {
    api.checkApi.mockResolvedValue('connected')
    const paired: PairedResult = {
      ...example, scenario_count: 100, root_seed: 42, calibration_id: 'test-calibration',
      point_advantage_seconds: 1.75, pit_now_mean_seconds: 1440, stay_out_mean_seconds: 1441,
      advantage_mean_seconds: 1, advantage_p05_seconds: low, advantage_median_seconds: 1,
      advantage_p95_seconds: high, pit_now_scenario_share: .7, stay_out_scenario_share: .3,
      tie_scenario_share: 0, recommendation, recommendation_is_stable: true,
      scenario_shares_are_correctness_probabilities: false, counterfactual_strategy_accuracy_is_proven: false,
    }
    api.startPaired.mockResolvedValue({ ...example, job_id: 'completed-job', status: 'COMPLETED', completed_scenarios: 100, scenario_count: 100, result: paired, error_code: null } satisfies PairedJob)
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    await screen.findByText(/The 100-test result above/)
    fireEvent.click(screen.getByRole('button', { name: 'THE EVIDENCE' }))
    expect(screen.getByRole('img', { name: new RegExp(position) })).toBeTruthy()
  })

  it('offers one retry after a cancelled test without a second duplicate action', async () => {
    api.checkApi.mockResolvedValue('connected')
    api.startPaired.mockResolvedValue({ ...example, job_id: 'cancelled-job', status: 'CANCELLED', completed_scenarios: 0, scenario_count: 100, result: null, error_code: null })
    render(<App />)
    await screen.findByText('Stopping this lap looked quicker.')
    fireEvent.click(screen.getByRole('button', { name: /Run 100 paired tests/ }))
    expect(await screen.findByRole('button', { name: 'Run it again' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Run 100 paired tests/ })).toBeNull()
  })
})
