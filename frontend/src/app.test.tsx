// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App } from './main'
import { example } from './data'
import type { Decision, PairedJob, PairedResult, PointResult } from './types'

const api = vi.hoisted(() => ({
  checkApi: vi.fn(),
  getDecisions: vi.fn(),
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
}

function pointFor(decision: Decision): PointResult {
  return { ...decision, pit_now_advantage_seconds: 1.75 } as PointResult
}

beforeEach(() => {
  vi.clearAllMocks()
  api.checkApi.mockResolvedValue('preview')
  api.getDecisions.mockResolvedValue({ decisions: [example], catalogReady: true })
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
    await screen.findByText('Second test race · Lap 20')
    finishCancellation({ ...oldJob, status: 'COMPLETED', result: { recommendation: 'NO_CLEAR_ADVANTAGE' } as PairedResult })
    await waitFor(() => expect(api.cancelPaired).toHaveBeenCalledWith('first-job'))
    expect(screen.queryByText('No clear winner.')).toBeNull()
    expect(screen.queryByText('0 / 100')).toBeNull()
  })
})
