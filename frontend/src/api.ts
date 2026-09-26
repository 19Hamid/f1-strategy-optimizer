import { example } from './data'
import type { Decision, DecisionKey, PairedJob, PointResult } from './types'

const base = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

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
  return response.json() as Promise<T>
}

export async function checkApi(): Promise<'connected' | 'preview' | 'unavailable'> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 3600)
  try {
    await request('/api/v1/capabilities', { signal: controller.signal })
    return 'connected'
  } catch (error) {
    if (error instanceof ApiProblem && error.status >= 500) return 'unavailable'
    return 'preview'
  } finally {
    window.clearTimeout(timeout)
  }
}

export async function getDecisions(): Promise<{ decisions: Decision[]; catalogReady: boolean }> {
  try {
    const body = await request<{ decisions: Decision[] }>('/api/v1/analysis/decisions')
    if (!Array.isArray(body.decisions) || body.decisions.length === 0) {
      throw new ApiProblem('EVIDENCE_UNAVAILABLE', 'The verified race catalog is empty or invalid.', 503)
    }
    return { decisions: body.decisions, catalogReady: true }
  } catch (error) {
    if (error instanceof ApiProblem && error.status === 404) return { decisions: [example], catalogReady: false }
    throw error
  }
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
