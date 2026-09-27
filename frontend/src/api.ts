import { identity } from './data'
import type { Decision, DecisionKey, PairedJob, PointResult } from './types'

const configuredBase = import.meta.env.VITE_API_BASE_URL as string | undefined
const base = configuredBase?.replace(/\/$/, '') ?? ''

export class ApiProblem extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiProblem('CONNECTION_FAILED', 'The analysis service is unreachable.', 0)
  }
  if (!response.ok) {
    const problem = await response.json().catch(() => ({})) as { code?: string; message?: string }
    throw new ApiProblem(problem.code ?? `HTTP_${response.status}`, problem.message ?? 'The request failed.', response.status)
  }
  try {
    return await response.json() as T
  } catch {
    throw new ApiProblem('INVALID_RESPONSE', 'The analysis service returned an invalid response.', 502)
  }
}

export async function checkApi(): Promise<'connected' | 'preview' | 'unavailable'> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 3600)
  try {
    const response = await fetch(`${base}/api/v1/capabilities`, { signal: controller.signal })
    if (!response.ok) return !configuredBase && response.status === 404 ? 'preview' : 'unavailable'
    const body = await response.json().catch(() => null) as { api_contract_version?: unknown } | null
    if (body?.api_contract_version !== '1.0') {
      return !configuredBase && response.headers.get('content-type')?.includes('text/html') ? 'preview' : 'unavailable'
    }
    return 'connected'
  } catch {
    return 'unavailable'
  } finally {
    window.clearTimeout(timeout)
  }
}

export async function getDecisions(): Promise<{ decisions: Decision[]; catalogReady: boolean }> {
  const body = await request<{ decisions: Decision[] }>('/api/v1/analysis/decisions')
  const decisions = body?.decisions
  const validCompound = (value: unknown) => value === 'SOFT' || value === 'MEDIUM' || value === 'HARD'
  if (!Array.isArray(decisions) || decisions.length === 0 || decisions.some(d =>
    ![2022, 2023, 2024].includes(d?.season) ||
    d.session_id?.slice(0, 4) !== String(d.season) ||
    !/^20\d{2}-\d{2}-R$/.test(d.session_id) ||
    !/^[A-Z]{3}$/.test(d.driver) ||
    !Number.isInteger(d.decision_lap) || d.decision_lap < 1 ||
    !Number.isInteger(d.total_laps) || d.total_laps! <= d.decision_lap ||
    !d.event_name?.trim() || !d.team?.trim() ||
    !validCompound(d.current_compound) || !validCompound(d.target_compound)
  ) || new Set(decisions.map(identity)).size !== decisions.length) {
    throw new ApiProblem('EVIDENCE_UNAVAILABLE', 'The verified race catalog is empty or invalid.', 503)
  }
  return { decisions, catalogReady: true }
}

export function quickAnalysis(key: DecisionKey): Promise<PointResult> {
  return request('/api/v1/analysis/deterministic', { method: 'POST', body: JSON.stringify(key) })
}

export function startPaired(key: DecisionKey): Promise<PairedJob> {
  return request('/api/v1/analysis/paired/jobs', {
    method: 'POST',
    body: JSON.stringify({ ...key, scenario_count: 100, root_seed: 42, max_workers: 4 }),
  })
}

export function getPaired(jobId: string): Promise<PairedJob> {
  return request(`/api/v1/analysis/paired/jobs/${encodeURIComponent(jobId)}`)
}

export function cancelPaired(jobId: string): Promise<PairedJob> {
  return request(`/api/v1/analysis/paired/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
}
