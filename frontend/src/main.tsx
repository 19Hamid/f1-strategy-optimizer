import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ApiProblem, cancelPaired, checkApi, getDecisions, getPaired, quickAnalysis, startPaired } from './api'
import { example, examplePaired, examplePointAdvantage, identity, name } from './data'
import type { AnalysisLap, Decision, PairedJob, PointResult, Recommendation } from './types'
import './style.css'

type Depth = 'answer' | 'race' | 'evidence'
type Availability = 'checking' | 'connected' | 'preview' | 'unavailable'

function seconds(value: number, digits = 2): string {
  return `${Math.abs(value).toFixed(digits)} s`
}

function raceTime(value: number): string {
  const minutes = Math.floor(value / 60)
  return `${minutes}:${(value % 60).toFixed(2).padStart(5, '0')}`
}

function problemMessage(error: unknown): string {
  if (error instanceof ApiProblem) {
    if (error.code === 'ANALYSIS_QUEUE_FULL' || error.status === 429) return 'The analysis queue is busy. Try again shortly.'
    if (error.code === 'DECISION_NOT_AVAILABLE') return 'This race moment is no longer available. Choose another supported moment.'
    if (error.code === 'JOB_NOT_FOUND') return 'This test is no longer available. Jobs can disappear when the service restarts. Run it again.'
    if (error.code === 'EVIDENCE_UNAVAILABLE') return 'The historical records could not be verified. No recommendation is available right now.'
    return error.message
  }
  return 'Something went wrong. Please try again.'
}

function readout(result: Recommendation): string {
  if (result === 'PIT_NOW') return 'Stopping this lap looks quicker.'
  if (result === 'STAY_OUT') return 'Waiting one more lap looks quicker.'
  return 'No clear winner.'
}

function advantageText(value: number): string {
  return value === 0 ? 'A tie in the first estimate' : `${seconds(value)} toward ${value > 0 ? 'stopping' : 'waiting'}`
}

function Choice({ number, title, detail, later = false, selected, onClick }: { number: string; title: string; detail: string; later?: boolean; selected: boolean; onClick: () => void }) {
  return <button type="button" aria-pressed={selected} onClick={onClick} className={`choice ${later ? 'choice-later' : ''} ${selected ? 'choice-selected' : ''}`}>
    <span className="choice-label">CHOICE {number}</span>
    <strong>{title}</strong>
    <p>{detail}</p>
  </button>
}

function CompoundMark({ compound }: { compound: string }) {
  return <span className={`compound compound-${compound.toLowerCase()}`}><span className="compound-dot" />{compound.toLowerCase()}</span>
}

function Interval({ low, high, point }: { low: number; high: number; point: number | null }) {
  const minimum = Math.min(low, point ?? 0, 0)
  const maximum = Math.max(high, point ?? 0, 0)
  const padding = Math.max((maximum - minimum) * .13, 5)
  const left = minimum - padding
  const right = maximum + padding
  const x = (value: number) => 50 + ((value - left) / (right - left)) * 700
  return <section className="interval-panel" aria-label={`Central 90 percent paired advantage interval: ${low.toFixed(2)} to ${high.toFixed(2)} seconds. Zero is a tie.`}>
    <div className="panel-eyebrow">THE TESTED TIME DIFFERENCE</div>
    <div className="interval-values"><strong>{low > 0 ? '+' : ''}{low.toFixed(2)} s</strong><span>ZERO = TIE</span><strong>{high > 0 ? '+' : ''}{high.toFixed(2)} s</strong></div>
    <svg className="interval-svg" viewBox="0 0 800 106" role="img" aria-label="Range goes from waiting faster, through zero, to stopping faster">
      <line x1="50" x2="750" y1="50" y2="50" className="chart-track" />
      <line x1={x(low)} x2={x(high)} y1="50" y2="50" className="chart-range" />
      <line x1={x(0)} x2={x(0)} y1="13" y2="88" className="chart-zero" />
      <circle cx={x(low)} cy="50" r="8" className="chart-end" />
      <circle cx={x(high)} cy="50" r="8" className="chart-end" />
      {point !== null && <circle cx={x(point)} cy="91" r="5" className="chart-point" />}
    </svg>
    <div className="interval-ends"><span>WAITING ONE LAP FASTER</span><span>STOPPING THIS LAP FASTER</span></div>
    {point !== null && <p className="interval-point">The small dot below the range shows the first estimate: {advantageText(point)}.</p>}
  </section>
}

function LapChart({ now, later, selectedLap, onSelect }: { now: AnalysisLap[]; later: AnalysisLap[]; selectedLap: number; onSelect: (lap: number) => void }) {
  const values = [...now, ...later].map(lap => lap.predicted_lap_time_seconds)
  const min = Math.min(...values) - 1
  const max = Math.max(...values) + 1
  const first = now[0]?.lap_number ?? 0
  const last = now.at(-1)?.lap_number ?? 0
  const scaleX = (index: number) => 52 + (index / Math.max(now.length - 1, 1)) * 682
  const scaleY = (value: number) => 175 - ((value - min) / (max - min)) * 130
  const points = (laps: AnalysisLap[]) => laps.map((lap, index) => `${scaleX(index)},${scaleY(lap.predicted_lap_time_seconds)}`).join(' ')
  const selected = now.findIndex(lap => lap.lap_number === selectedLap)
  return <div className="lap-chart">
    <div className="chart-key"><span className="key-now">Stop after this lap</span><span className="key-later">Wait one lap</span></div>
    <svg viewBox="0 0 790 226" role="img" aria-label={`Predicted racing time in seconds for each lap from ${first} to ${last}, comparing both pit timings`}>
      <line x1="52" x2="734" y1="178" y2="178" className="lap-axis" />
      <line x1="52" x2="52" y1="36" y2="178" className="lap-axis" />
      <polyline points={points(now)} className="lap-path-now" />
      <polyline points={points(later)} className="lap-path-later" />
      {selected >= 0 && <>
        <line x1={scaleX(selected)} x2={scaleX(selected)} y1="35" y2="178" className="lap-guide" />
        <circle cx={scaleX(selected)} cy={scaleY(now[selected].predicted_lap_time_seconds)} r="6" className="lap-dot-now" />
        <circle cx={scaleX(selected)} cy={scaleY(later[selected].predicted_lap_time_seconds)} r="6" className="lap-dot-later" />
      </>}
      <text x="52" y="213" className="lap-axis-label">LAP {first}</text>
      <text x="734" y="213" textAnchor="end" className="lap-axis-label">LAP {last}</text>
      <text x="55" y="23" className="lap-axis-label">PREDICTED LAP TIME (SECONDS)</text>
    </svg>
    <label className="lap-select">Inspect a lap
      <select value={selectedLap} onChange={event => onSelect(Number(event.target.value))}>
        {now.map(lap => <option key={lap.lap_number} value={lap.lap_number}>Lap {lap.lap_number}</option>)}
      </select>
    </label>
  </div>
}

export function App() {
  const [availability, setAvailability] = useState<Availability>('checking')
  const [catalogReady, setCatalogReady] = useState(false)
  const [choices, setChoices] = useState<Decision[]>([example])
  const [decision, setDecision] = useState<Decision>(example)
  const [view, setView] = useState<Depth>('answer')
  const [pointState, setPointState] = useState<PointResult | null>(null)
  const [jobState, setJobState] = useState<PairedJob | null>(null)
  const [pairedShown, setPairedShown] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorStage, setErrorStage] = useState<'point' | 'paired' | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [selectedLap, setSelectedLap] = useState(38)
  const [selectedRoute, setSelectedRoute] = useState<'PIT_NOW' | 'STAY_OUT'>('PIT_NOW')
  const version = useRef(0)
  const jobRef = useRef<PairedJob | null>(null)
  const point = pointState && identity(pointState) === identity(decision) ? pointState : null
  const job = jobState && identity(jobState) === identity(decision) ? jobState : null
  jobRef.current = jobState

  useEffect(() => {
    let active = true
    void (async () => {
      const service = await checkApi()
      if (!active) return
      setAvailability(service)
      if (service !== 'connected') return
      try {
        const catalog = await getDecisions()
        if (!active) return
        setCatalogReady(catalog.catalogReady)
        if (catalog.catalogReady && catalog.decisions.length) {
          setChoices(catalog.decisions)
          const first = catalog.decisions.find(d => identity(d) === identity(example)) ?? catalog.decisions[0]
          setDecision(first)
          setSelectedLap(first.decision_lap)
        }
      } catch (reason) {
        if (active) { setCatalogError(problemMessage(reason)); setAvailability('unavailable') }
      }
    })()
    return () => { active = false }
  }, [])

  useEffect(() => {
    version.current += 1
    const current = version.current
    const old = jobRef.current
    if (old && ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(old.status)) void cancelPaired(old.job_id).catch(() => undefined)
    setPointState(null)
    setJobState(null)
    setPairedShown(false)
    setSubmitting(false)
    setError(null)
    setErrorStage(null)
    setSelectedLap(decision.decision_lap)
    setSelectedRoute('PIT_NOW')
    if (availability !== 'connected' || !catalogReady) return
    void quickAnalysis(decision).then(result => {
      if (version.current === current && identity(result) === identity(decision)) setPointState(result)
    }).catch(reason => {
      if (version.current === current) { setError(problemMessage(reason)); setErrorStage('point') }
    })
  }, [decision, availability, catalogReady])

  useEffect(() => {
    if (!job || !['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status)) return
    const current = version.current
    const timer = window.setTimeout(() => {
      void getPaired(job.job_id).then(next => {
        if (current === version.current && identity(next) === identity(decision)) setJobState(next)
      }).catch(reason => {
        if (current === version.current) { setJobState(null); setError(problemMessage(reason)); setErrorStage('paired') }
      })
    }, 1100)
    return () => window.clearTimeout(timer)
  }, [job])

  const firstAdvantage = point?.pit_now_advantage_seconds ?? (availability === 'preview' && identity(decision) === identity(example) ? examplePointAdvantage : null)
  const paired = job?.status === 'COMPLETED' ? job.result : null
  const showingExample = availability === 'preview' && pairedShown && identity(decision) === identity(example)
  const recommendation = showingExample ? examplePaired.recommendation : paired?.recommendation
  const interval = showingExample ? examplePaired : paired
  const busy = job && ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status)
  const hasPaired = pairedShown && Boolean(recommendation)

  const bySeason = useMemo(() => [...new Set(choices.map(d => d.season))].sort(), [choices])
  const byRace = choices.filter(d => d.season === decision.season)
  const races = [...new Set(byRace.map(d => d.session_id))]
  const byDriver = byRace.filter(d => d.session_id === decision.session_id)
  const drivers = [...new Set(byDriver.map(d => d.driver))]
  const moments = byDriver.filter(d => d.driver === decision.driver)

  function choose(next: Decision) {
    if (identity(next) === identity(decision)) return
    version.current += 1
    const old = jobRef.current
    if (old && ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(old.status)) void cancelPaired(old.job_id).catch(() => undefined)
    jobRef.current = null
    setPointState(null)
    setJobState(null)
    setPairedShown(false)
    setSubmitting(false)
    setError(null)
    setErrorStage(null)
    setDecision(next)
    setView('answer')
  }

  async function runPaired() {
    if (submitting) return
    setError(null)
    setErrorStage(null)
    setPairedShown(true)
    if (availability === 'preview') return
    const current = version.current
    setSubmitting(true)
    try {
      const next = await startPaired(decision)
      if (current === version.current && identity(next) === identity(decision)) setJobState(next)
      else void cancelPaired(next.job_id).catch(() => undefined)
    } catch (reason) {
      if (current === version.current) { setError(problemMessage(reason)); setErrorStage('paired') }
    } finally {
      if (current === version.current) setSubmitting(false)
    }
  }

  async function cancelJob() {
    if (!job) return
    const current = version.current
    try {
      const cancelled = await cancelPaired(job.job_id)
      if (current === version.current && identity(cancelled) === identity(decision)) setJobState(cancelled)
    } catch (reason) {
      if (current === version.current) { setError(problemMessage(reason)); setErrorStage('paired') }
    }
  }

  async function retryPoint() {
    const current = version.current
    setError(null)
    setErrorStage(null)
    try {
      const result = await quickAnalysis(decision)
      if (current === version.current && identity(result) === identity(decision)) setPointState(result)
    } catch (reason) {
      if (current === version.current) { setError(problemMessage(reason)); setErrorStage('point') }
    }
  }

  const liveUnavailable = availability === 'connected' && !point && !error
  const plainResult = hasPaired ? readout(recommendation!) : error && errorStage === 'point' ? 'Estimate unavailable.' : firstAdvantage === null ? availability === 'unavailable' ? 'Analysis unavailable.' : 'Checking this race moment…' : firstAdvantage === 0 ? 'Both stops look equally quick.' : firstAdvantage > 0 ? 'Stopping this lap looked quicker.' : 'Waiting one more lap looked quicker.'

  return <div className="app-shell">
    <header className="site-header">
      <div className="site-header-inner">
        <div className="brand"><span className="brand-bar" /><div><strong>F1 RACE STRATEGY OPTIMIZER</strong><small>HISTORICAL PIT STOP DECISIONS</small></div></div>
        <nav className="depth-nav" aria-label="Explore this decision">
          {(['answer', 'race', 'evidence'] as Depth[]).map(depth => <button type="button" key={depth} className={view === depth ? 'nav-active' : ''} aria-current={view === depth ? 'page' : undefined} onClick={() => setView(depth)}>{depth === 'answer' ? 'THE ANSWER' : depth === 'race' ? 'THE RACE' : 'THE EVIDENCE'}</button>)}
        </nav>
      </div>
    </header>

    <main>
      <section className="decision-hero" aria-label="Current historical race moment">
        <div className="hero-inner">
          <span className="hero-eyebrow">A REAL RACE MOMENT  <span>·</span>  TWO PIT TIMINGS</span>
          <h1>Should {name(decision)}<br />pit after this lap?</h1>
          <p>See what changes if the stop happens one lap later.</p>
          <div className="hero-chips"><span>{decision.event_name}, {decision.season}</span><span>{name(decision)} · {decision.team}</span><span>Lap {decision.decision_lap}{decision.total_laps ? ` / ${decision.total_laps}` : ''}</span><CompoundMark compound={decision.target_compound} /></div>
        </div>
      </section>

      <div className="workspace">
        {availability === 'preview' && <div className="service-note" role="status"><span className="note-dot" /><span><strong>Recorded example.</strong> The live analysis service is not hosted here. These are saved results from one verified development run; no new simulation runs in this preview.</span></div>}
        {availability === 'checking' && <div className="service-note" role="status">Checking whether the historical analysis service is available…</div>}
        {availability === 'unavailable' && !catalogError && <div className="error-panel" role="alert"><strong>The analysis service is unavailable.</strong><p>The verified race choices could not be loaded. No current recommendation is available.</p></div>}
        {availability === 'connected' && !catalogReady && <div className="service-note" role="status">Checking the verified race and driver choices…</div>}
        {catalogError && <div className="error-panel" role="alert"><strong>Race browsing is unavailable.</strong><p>{catalogError}</p></div>}

        <section className="picker" aria-label="Pick a supported decision">
          <div className="section-head"><div><span className="eyebrow">01 / THE MOMENT</span><h2>{catalogReady ? 'Choose a race moment' : 'Explore this race moment'}</h2></div><span className="picker-constraint">{catalogReady ? `${choices.length} verified moments available` : 'ONE RECORDED EXAMPLE ON THIS LINK'}</span></div>
          <div className="picker-row">
            <label>Season<select value={decision.season} disabled={!catalogReady || bySeason.length < 2} onChange={event => choose(choices.find(d => d.season === Number(event.target.value))!)}>{bySeason.map(s => <option key={s} value={s}>{s}</option>)}</select></label>
            <label>Race<select value={decision.session_id} disabled={!catalogReady || races.length < 2} onChange={event => choose(byRace.find(d => d.session_id === event.target.value)!)}>{races.map(id => <option key={id} value={id}>{byRace.find(d => d.session_id === id)?.event_name}</option>)}</select></label>
            <label>Driver<select value={decision.driver} disabled={!catalogReady || drivers.length < 2} onChange={event => choose(byDriver.find(d => d.driver === event.target.value)!)}>{drivers.map(driver => <option key={driver} value={driver}>{name(byDriver.find(d => d.driver === driver)!)}</option>)}</select></label>
            <label>Moment<select value={identity(decision)} disabled={!catalogReady || moments.length < 2} onChange={event => choose(moments.find(d => identity(d) === event.target.value)!)}>{moments.map(d => <option value={identity(d)} key={identity(d)}>Lap {d.decision_lap} · fit {d.target_compound.toLowerCase()}</option>)}</select></label>
            <div className="picked-moment"><span className="picked-label">TYRE AT THE STOP · HISTORICALLY FITTED</span><strong><CompoundMark compound={decision.target_compound} /></strong><span>{name(decision)} · {decision.team} · lap {decision.decision_lap}. {catalogReady ? 'Pick another verified moment above to change the recorded tyre.' : `This recorded case uses ${decision.target_compound.toLowerCase()} tyres. Other cases need a live verified API.`}</span></div>
          </div>
        </section>

        {error && <div className="error-panel" role="alert"><strong>{errorStage === 'paired' ? 'The wider test could not start or finish.' : 'We cannot show the first estimate.'}</strong><p>{error}</p>{availability === 'connected' && <button type="button" className="text-button" onClick={() => { if (errorStage === 'paired') void runPaired(); else void retryPoint() }}>Try {errorStage === 'paired' ? 'the wider test' : 'the first estimate'} again</button>}</div>}

        {view === 'answer' && <>
          <section className="answer-section" aria-live="polite">
            <div className="section-head"><div><span className="eyebrow">02 / THE ANSWER</span><h2>Which stop looks quicker?</h2></div><span className="answer-source">{hasPaired ? 'AFTER 100 PAIRED TESTS' : 'THE FIRST ESTIMATE'}</span></div>
            <div className={`answer-card ${hasPaired ? 'answer-settled' : ''}`}>
              <div className="answer-main"><span className="answer-kicker">{hasPaired ? 'TESTED RESULT' : 'FIRST CALCULATION ONLY'}</span><h3>{plainResult}</h3><p>{hasPaired ? recommendation === 'NO_CLEAR_ADVANTAGE' ? 'Some tested race versions favor stopping now. Others favor waiting one more lap. Neither clearly wins.' : 'The simulated race versions support this direction. A real-world outcome is not guaranteed.' : !point && (error || availability === 'unavailable') ? 'There is no current estimate to compare yet.' : liveUnavailable ? 'Loading both pit timings from the recorded race moment.' : 'This uses one fixed version of the race. The wider test can give a different answer.'}</p></div>
              <div className="answer-detail">{hasPaired ? <><strong>What this means</strong><p>{recommendation === 'NO_CLEAR_ADVANTAGE' ? 'Neither timing clearly wins. You can inspect the time range and assumptions in Evidence.' : 'This is the conclusion of the simulated comparison. You can inspect its time range in Evidence.'}</p></> : <><strong>{firstAdvantage === null ? 'Estimate pending' : advantageText(firstAdvantage)}</strong><p>Both routes use the same fitted tyre: {decision.target_compound.toLowerCase()}.</p></>}</div>
            </div>
          </section>

          <section className="choices-section"><div className="section-head compact"><h2>Explore the two choices</h2><span>Same driver · same race · same fitted tyre</span></div><div className="choice-grid"><Choice number="01" title={`Stop after lap ${decision.decision_lap}`} detail={`Pit at the end of this lap and fit ${decision.target_compound.toLowerCase()} tyres.`} selected={selectedRoute === 'PIT_NOW'} onClick={() => setSelectedRoute('PIT_NOW')} /><Choice number="02" title={`Drive lap ${decision.decision_lap + 1} first`} detail={`Wait one more lap, then pit and fit the same ${decision.target_compound.toLowerCase()} tyres.`} later selected={selectedRoute === 'STAY_OUT'} onClick={() => setSelectedRoute('STAY_OUT')} /></div><div className="route-focus" aria-live="polite"><span>YOU'RE EXPLORING</span><strong>{selectedRoute === 'PIT_NOW' ? `Stop after lap ${decision.decision_lap}` : `Wait until after lap ${decision.decision_lap + 1}`}</strong><p>Both routes use {decision.target_compound.toLowerCase()} tyres at the stop. Selecting a route highlights it; the answer above still compares both.</p></div></section>

          <div className="action-row">{!hasPaired && !busy && !submitting && !error && !job && <button className="primary-action" type="button" onClick={() => void runPaired()} disabled={availability === 'checking' || availability === 'unavailable' || !catalogReady && availability === 'connected' || liveUnavailable}>{availability === 'preview' ? 'See the recorded 100-test result' : 'Run 100 paired tests'} <span aria-hidden="true">→</span></button>}{hasPaired && <button className="primary-action" type="button" onClick={() => setView('race')}>See what happens on track <span aria-hidden="true">→</span></button>}<button className="secondary-action" type="button" onClick={() => setView('evidence')}>How does this work?</button></div>

          {submitting && <div className="service-note" role="status">Starting the wider test for this race moment…</div>}
          {busy && <div className="progress-panel" role="status"><div className="progress-header"><strong>{job!.status === 'QUEUED' ? 'Waiting for a free analysis slot' : job!.status === 'CANCEL_REQUESTED' ? 'Stopping the test…' : 'Checking more race versions…'}</strong><span>{job!.completed_scenarios} / {job!.scenario_count}</span></div><div className="progress-track"><div style={{ width: `${job!.completed_scenarios / job!.scenario_count * 100}%` }} /></div><p>No final result yet. The first estimate remains provisional.</p><button type="button" className="text-button" disabled={job!.status === 'CANCEL_REQUESTED'} onClick={() => void cancelJob()}>Cancel analysis</button></div>}
          {!submitting && job?.status === 'FAILED' && <div className="error-panel" role="alert">The paired test failed. No partial recommendation is available. <button type="button" className="text-button" onClick={() => void runPaired()}>Run again</button></div>}
          {!submitting && job?.status === 'CANCELLED' && <div className="service-note" role="status">The test was cancelled. No partial result is shown. <button type="button" className="text-button" onClick={() => void runPaired()}>Run it again</button></div>}
          {hasPaired && <div className="result-next"><strong>The first estimate was {firstAdvantage === null ? 'one fixed calculation' : advantageText(firstAdvantage)}.</strong><span>The 100-test result above is the broader assessment for this moment.</span></div>}
        </>}

        {view === 'race' && <section className="race-view">
          <div className="section-head"><div><span className="eyebrow">02 / THE RACE</span><h2>One more lap changes the timing.</h2></div><button className="small-link" type="button" onClick={() => setView('evidence')}>Inspect the evidence <span aria-hidden="true">↗</span></button></div>
          <p className="section-intro">Both estimates cover the entire time from the selected moment to the finish. The fitted tyre stays {decision.target_compound.toLowerCase()} in both.</p>
          <div className="race-comparison"><div className="race-route"><span className="route-number">01 / STOP THIS LAP</span><h3>Pit after lap {decision.decision_lap}</h3><strong className="race-time">{point ? raceTime(point.pit_now.expected_remaining_time_seconds) : '—'}</strong><span className="time-caption">{point ? 'ESTIMATED TIME TO THE FINISH' : 'FULL TIME NEEDS THE LIVE ANALYSIS RESPONSE'}</span><div className="route-sequence"><span>LAP {decision.decision_lap}</span><span>PIT</span><CompoundMark compound={decision.target_compound} /></div></div><div className="race-route route-wait"><span className="route-number">02 / WAIT ONE LAP</span><h3>Pit after lap {decision.decision_lap + 1}</h3><strong className="race-time">{point ? raceTime(point.stay_out.expected_remaining_time_seconds) : '—'}</strong><span className="time-caption">{point ? 'ESTIMATED TIME TO THE FINISH' : 'FULL TIME NEEDS THE LIVE ANALYSIS RESPONSE'}</span><div className="route-sequence"><span>LAP {decision.decision_lap}</span><span>LAP {decision.decision_lap + 1}</span><span>PIT</span></div></div></div>
          <div className="race-callout"><div><span className="panel-eyebrow">FIRST ESTIMATE</span><strong>{firstAdvantage === null ? 'Waiting for the live service' : advantageText(firstAdvantage)}</strong></div><p>{hasPaired ? `The wider test concludes: ${readout(recommendation!)}` : 'One calculation cannot establish that this is the best real-world decision.'}</p></div>
          {point && <div className="breakdown"><h3>What makes up the complete times</h3><div><span>Pit after lap {decision.decision_lap}</span><b>Racing {raceTime(point.pit_now.racing_time_seconds)} · pit {seconds(point.pit_now.pit_loss_seconds)}</b></div><div><span>Pit after lap {decision.decision_lap + 1}</span><b>Racing {raceTime(point.stay_out.racing_time_seconds)} · pit {seconds(point.stay_out.pit_loss_seconds)}</b></div></div>}
        </section>}

        {view === 'evidence' && <section className="evidence-view"><div className="section-head"><div><span className="eyebrow">03 / THE EVIDENCE</span><h2>Why does the result say that?</h2></div><span className="evidence-status">{hasPaired ? `${interval!.scenario_count} PAIRED TESTS` : 'TEST NOT RUN YET'}</span></div>
          <p className="section-intro">For the same race moment, we estimate both routes to the finish. The paired test checks how their time difference changes across simulated race versions.</p>
          {hasPaired && interval ? <><Interval low={interval.advantage_p05_seconds} high={interval.advantage_p95_seconds} point={firstAdvantage} /><div className="explanation-strip"><strong>{interval.advantage_p05_seconds <= 0 && interval.advantage_p95_seconds >= 0 ? 'Zero is inside the range.' : 'The range stays on one side of zero.'}</strong><span>{interval.advantage_p05_seconds <= 0 && interval.advantage_p95_seconds >= 0 ? 'The tested outcomes include a faster stop and a faster wait. This is why the result is “No clear winner.”' : `The tested time differences support this direction: ${readout(recommendation!)}`}</span></div></> : <div className="empty-evidence"><strong>The first estimate does not test uncertainty.</strong><p>{availability === 'preview' ? 'Open the recorded 100-test result from The Answer to see its measured range.' : 'Run the paired analysis from The Answer to examine the result range.'}</p><button type="button" className="secondary-action" onClick={() => setView('answer')}>Back to the answer</button></div>}
          <div className="evidence-grid"><div className="evidence-block"><span className="eyebrow">HOW THE TWO PATHS ARE BUILT</span><h3>Same start. Same tyre. Different stop.</h3><ol><li>Start from the recorded race moment.</li><li>Simulate pitting after this lap and after one more lap.</li><li>Predict each later lap using the tyre compound and its age.</li><li>Add the pit time and compare the complete time to the finish.</li></ol></div><div className="evidence-block"><span className="eyebrow">WHAT THIS DOESN'T CLAIM</span><h3>A measured model, not an oracle.</h3><p>The tested range is uncertainty across the declared simulated scenarios. It is different from the model's single-lap prediction error. The site cannot claim which strategy would really have won: only one action happened in history.</p><p>No live weather, Safety Car, traffic response, rival reaction or alternative tyre optimization is modeled here.</p></div></div>
          {point && <div className="lap-detail"><div className="section-head compact"><h3>Inspect the projected laps</h3><span>Values come from this analysis response</span></div><LapChart now={point.pit_now.laps} later={point.stay_out.laps} selectedLap={selectedLap} onSelect={setSelectedLap} /><div className="lap-pair">{[point.pit_now, point.stay_out].map(action => { const lap = action.laps.find(item => item.lap_number === selectedLap); return <div key={action.action}><span>{action.action === 'PIT_NOW' ? 'STOP THIS LAP' : 'WAIT ONE LAP'}</span><strong>Lap {selectedLap}</strong>{lap && <p>{lap.compound.toLowerCase()} tyre · age {lap.tyre_age_laps} laps<br />Predicted lap {seconds(lap.predicted_lap_time_seconds)} · pit time {seconds(lap.pit_loss_seconds)}<br />Elapsed from decision {raceTime(lap.elapsed_time_after_lap_seconds)}</p>}</div> })}</div></div>}
          {paired && <div className="shares"><span className="eyebrow">DESCRIPTIVE SCENARIO SHARES</span><p>Pit this lap was quicker in {(paired.pit_now_scenario_share * 100).toFixed(0)}% of simulated versions; waiting was quicker in {(paired.stay_out_scenario_share * 100).toFixed(0)}%.</p><small>These are shares of modeled scenarios, not the probability that a real pit call is correct.</small></div>}
          <div className="provenance"><span>DEVELOPMENT RACES: 2022–2024</span><span>{hasPaired ? `SCENARIOS: ${interval!.scenario_count} · SEED: ${interval!.root_seed}` : 'PAIRED SCENARIOS: NOT YET RUN'}</span><span>{paired ? `CALIBRATION: ${paired.calibration_id}` : availability === 'preview' ? 'SOURCE: SAVED DEVELOPMENT SMOKE RUN' : 'SOURCE: VERIFIED DEVELOPMENT API'}</span></div>
        </section>}
      </div>
    </main>
    <footer className="footer"><div><strong>F1 RACE STRATEGY OPTIMIZER</strong><span>Historical analysis, 2022–2024 · dry green-flag decisions only.</span></div><p>This website is unofficial and is not associated in any way with the Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX and related marks are trade marks of Formula One Licensing B.V.</p></footer>
  </div>
}

const root = document.getElementById('root')
if (root) createRoot(root).render(<React.StrictMode><App /></React.StrictMode>)
