// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiProblem, checkApi, getDecisions, getDevelopmentEvidence } from './api'
import { example } from './data'

afterEach(() => vi.unstubAllGlobals())

describe('API availability', () => {
  it('shows the recorded preview only when the static host has no API route', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Missing', { status: 404 })))
    expect(await checkApi()).toBe('preview')
  })

  it('does not turn a failing server into a seemingly working preview', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Unavailable', { status: 503 })))
    expect(await checkApi()).toBe('unavailable')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')))
    expect(await checkApi()).toBe('unavailable')
  })

  it('accepts the expected API contract and rejects a missing catalog', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ api_contract_version: '1.0' }), {
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response('{}', { status: 404 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await checkApi()).toBe('connected')
    await expect(getDecisions()).rejects.toMatchObject({ status: 404 } satisfies Partial<ApiProblem>)
  })

  it('rejects malformed or protected race choices before showing them', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      decisions: [{ ...example, season: 2025 }],
    }))))
    await expect(getDecisions()).rejects.toMatchObject({ code: 'EVIDENCE_UNAVAILABLE' })
  })

  it('rejects an empty catalog and evidence missing one verified report', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ decisions: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: 'valid', protected_evaluation_rows: 0,
        artifacts: [{ kind: 'MODEL', identifier: 'only-model', artifact_count: 1, verification_rows: 10 }],
      }))))
    await expect(getDecisions()).rejects.toMatchObject({ code: 'EVIDENCE_UNAVAILABLE' })
    await expect(getDevelopmentEvidence()).rejects.toMatchObject({ code: 'EVIDENCE_UNAVAILABLE' })
  })
})
