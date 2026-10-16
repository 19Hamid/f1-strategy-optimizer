'use strict';

const $ = id => document.getElementById(id);
const app = {data: null, extended: null, prePit: null, rows: [], catalog: [], entry: null, selected: null, path: 'now', tab: 'answer'};
let toolsRegistered = false;
const VALID_TYRES = new Set(['SOFT', 'MEDIUM', 'HARD']);
const VALID_VERDICTS = new Set(['PIT_NOW', 'STAY_OUT', 'NO_CLEAR_ADVANTAGE']);

function fixed(n, digits = 2) { return Number(n).toFixed(digits); }
function time(n) { return `${Math.floor(n / 60)}:${fixed(n % 60).padStart(5, '0')}`; }
function sign(n) { return `${n > 0 ? '+' : ''}${fixed(n)}`; }
function wordTyre(v) { return v[0] + v.slice(1).toLowerCase(); }
function el(tag, className, value) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (value !== undefined) result.textContent = value;
  return result;
}
function fillSelect(select, options, value) {
  select.replaceChildren(...options.map(([key, label]) => {
    const option = new Option(label, String(key));
    return option;
  }));
  select.value = String(value);
  select.disabled = options.length < 2;
}
function validate(data) {
  if (!data || !Array.isArray(data.decisions) || data.decisions.length !== 124 || data.count !== 124 || data.paired_checkpoints !== 62 || !/^[a-f0-9]{64}$/.test(data.source_sha256)) throw new Error('Unexpected data catalog');
  if (new Set(data.decisions.map(row => row.id)).size !== 124) throw new Error('Duplicate decision');
  const pairs = new Map();
  for (const row of data.decisions) {
    if (![2022, 2023, 2024].includes(row.season) || !VALID_TYRES.has(row.current_tyre) || !VALID_TYRES.has(row.target_tyre) || !VALID_VERDICTS.has(row.verdict) || !row.race || !row.name || !row.team || !Number.isInteger(row.lap) || !Number.isInteger(row.total_laps) || row.lap >= row.total_laps) throw new Error('Unsupported decision');
    for (const key of ['pit_now_seconds', 'wait_seconds', 'advantage_seconds', 'band_low_seconds', 'band_high_seconds', 'margin_per_path_seconds', 'pit_loss_assumption_seconds']) if (!Number.isFinite(row[key])) throw new Error('Missing numeric evidence');
    if (Math.abs((row.wait_seconds - row.pit_now_seconds) - row.advantage_seconds) > .00001 || row.band_low_seconds > row.band_high_seconds) throw new Error('Inconsistent evidence');
    const key = `${row.race_id}/${row.driver}`;
    const pair = pairs.get(key) || [];
    pair.push(row);
    pairs.set(key, pair);
  }
  if (pairs.size !== 62 || [...pairs.values()].some(pair => pair.length !== 2 || Math.abs(pair[0].lap - pair[1].lap) !== 1)) throw new Error('Invalid checkpoints');
}
function validateExtended(data, audit) {
  if (!data || !Array.isArray(data.decisions) || data.count !== data.decisions.length || data.count % 2 !== 0 || data.paired_checkpoints !== data.count / 2 || data.model_id !== audit.model_id || data.phase8_source_sha256 !== audit.source_sha256 || !/^[a-f0-9]{64}$/.test(data.dataset_catalog_sha256)) throw new Error('Invalid additional estimates');
  const auditIds = new Set(audit.decisions.map(row => row.id));
  const pairs = new Map();
  for (const row of data.decisions) {
    if (auditIds.has(row.id) || !/^(2022|2023|2024)-\d{2}-R$/.test(row.race_id) || row.season !== Number(row.race_id.slice(0, 4)) || !VALID_TYRES.has(row.current_tyre) || !VALID_TYRES.has(row.target_tyre) || row.verdict !== 'UNREVIEWED' || row.source_tier !== 'EXPLORATORY' || !row.race || !row.name || !row.team || !Number.isInteger(row.lap) || row.lap >= row.total_laps) throw new Error('Invalid additional decision');
    for (const key of ['pit_now_seconds', 'wait_seconds', 'advantage_seconds', 'band_low_seconds', 'band_high_seconds', 'margin_per_path_seconds', 'pit_loss_assumption_seconds']) if (!Number.isFinite(row[key])) throw new Error('Missing additional evidence');
    if (Math.abs(row.wait_seconds - row.pit_now_seconds - row.advantage_seconds) > .00001 || row.band_low_seconds > row.band_high_seconds) throw new Error('Inconsistent additional estimate');
    const key = `${row.race_id}/${row.driver}`;
    pairs.set(key, [...(pairs.get(key) || []), row]);
  }
  if (pairs.size !== data.paired_checkpoints || [...pairs.values()].some(pair => pair.length !== 2 || Math.abs(pair[0].lap - pair[1].lap) !== 1)) throw new Error('Additional checkpoints do not pair');
}
function validatePrePit(data, audit, extended) {
  if (!data || !Array.isArray(data.decisions) || !Array.isArray(data.unavailable) || data.count !== data.decisions.length || data.model_id !== audit.model_id || data.phase8_source_sha256 !== audit.source_sha256 || data.dataset_catalog_sha256 !== extended.dataset_catalog_sha256) throw new Error('Invalid pre-pit report');
  const occupied = new Set([...audit.decisions, ...extended.decisions].map(row => `${row.race_id}/${row.driver}`));
  const ids = new Set();
  const cases = new Map();
  for (const row of data.decisions) {
    if (occupied.has(`${row.race_id}/${row.driver}`) || ids.has(row.id) || !/^(2022|2023|2024)-\d{2}-R$/.test(row.race_id) || row.season !== Number(row.race_id.slice(0, 4)) || !VALID_TYRES.has(row.current_tyre) || !VALID_TYRES.has(row.target_tyre) || row.verdict !== 'UNREVIEWED' || row.source_tier !== 'PRE_PIT_EXPLORATORY' || !row.race || !row.name || !row.team || !Number.isInteger(row.lap) || !Number.isInteger(row.recorded_pit_lap) || row.lap >= row.recorded_pit_lap || row.lap >= row.total_laps - 1 || !Number.isInteger(row.leader_total_laps) || row.leader_total_laps < row.total_laps || !['LEADER_LAP_FINISH', 'LAPPED_FINISH_TIMING'].includes(row.finish_evidence) || (row.leader_total_laps === row.total_laps) !== (row.finish_evidence === 'LEADER_LAP_FINISH')) throw new Error('Invalid pre-pit comparison');
    for (const key of ['pit_now_seconds', 'wait_seconds', 'advantage_seconds', 'band_low_seconds', 'band_high_seconds', 'margin_per_path_seconds', 'pit_loss_assumption_seconds']) if (!Number.isFinite(row[key])) throw new Error('Missing pre-pit evidence');
    if (Math.abs(row.wait_seconds - row.pit_now_seconds - row.advantage_seconds) > .00001 || row.band_low_seconds > row.band_high_seconds) throw new Error('Inconsistent pre-pit estimate');
    ids.add(row.id);
    const key = `${row.race_id}/${row.driver}`;
    cases.set(key, [...(cases.get(key) || []), row]);
  }
  if (cases.size !== data.case_count || data.paired_checkpoints + data.single_checkpoints !== data.case_count || data.count !== data.paired_checkpoints * 2 + data.single_checkpoints) throw new Error('Wrong pre-pit counts');
  if ([...cases.values()].some(group => group.length > 2 || group.length === 2 && (Math.abs(group[0].lap - group[1].lap) !== 1 || group[0].recorded_pit_lap !== group[1].recorded_pit_lap))) throw new Error('Invalid pre-pit checkpoints');
  const unavailable = new Set();
  const reasons = new Set(['INCOMPLETE_HORIZON', 'NO_RECORDED_DRY_TYRE', 'NO_SAFE_DECISION_LAP']);
  for (const item of data.unavailable) {
    const key = `${item.race_id}/${item.driver}`;
    if (unavailable.has(key) || cases.has(key) || occupied.has(key) || !reasons.has(item.reason)) throw new Error('Invalid unavailability reason');
    unavailable.add(key);
  }
  if (unavailable.size + cases.size + occupied.size !== 1350) throw new Error('Unaccounted race starters');
}
function validateCatalog(data) {
  if (!data || !Array.isArray(data.entries) || data.entries.length !== 1350 || JSON.stringify(data.seasons) !== '[2022,2023,2024]') throw new Error('Incomplete historical race catalog');
  const moments = new Set(app.rows.map(row => row.id));
  if (moments.size !== app.rows.length) throw new Error('Duplicate analysis identity');
  const keys = new Set();
  let supported = 0;
  const races = new Set();
  for (const entry of data.entries) {
    if (!data.seasons.includes(entry.season) || !entry.race_id.startsWith(`${entry.season}-`) || !/^[A-Z]{3}$/.test(entry.driver) || !entry.race || !entry.name || !entry.team || !Array.isArray(entry.decision_ids) || !entry.recorded || !Number.isInteger(entry.recorded.laps) || !Number.isInteger(entry.recorded.race_laps) || !Array.isArray(entry.recorded.pit_entry_laps) || !Array.isArray(entry.recorded.stints)) throw new Error('Invalid race entry');
    const key = `${entry.race_id}/${entry.driver}`;
    if (keys.has(key)) throw new Error('Duplicate race entry');
    keys.add(key); races.add(entry.race_id);
    if (entry.decision_ids.length) {
      if (entry.decision_ids.length > 2 || entry.decision_ids.some(id => !moments.has(id)) || entry.availability_reason !== null) throw new Error('Invalid linked decision');
      supported++;
    } else if (!new Set(['INCOMPLETE_HORIZON', 'NO_RECORDED_DRY_TYRE', 'NO_SAFE_DECISION_LAP']).has(entry.availability_reason)) throw new Error('Missing unavailable reason');
  }
  if (supported !== 62 + app.extended.paired_checkpoints + app.prePit.case_count || races.size !== 68) throw new Error('Historical race catalog does not match decisions');
  for (const row of app.rows) {
    const entry = data.entries.find(item => item.race_id === row.race_id && item.driver === row.driver);
    if (!entry || !entry.decision_ids.includes(row.id) || entry.name !== row.name || entry.team !== row.team) throw new Error('Decision and race catalog differ');
  }
}
function groupPair(row) { return app.rows.filter(item => item.race_id === row.race_id && item.driver === row.driver).sort((a, b) => a.lap - b.lap); }
function unique(items) { return [...new Set(items)]; }
function choose(row) {
  const entry = app.catalog.find(item => item.race_id === row.race_id && item.driver === row.driver);
  chooseEntry(entry, row);
}
function chooseEntry(entry, row = null) {
  if (!entry) return;
  app.entry = entry;
  app.selected = row || app.rows.find(item => entry.decision_ids.includes(item.id)) || null;
  app.path = 'now';
  const current = new URL(location.href);
  current.searchParams.delete('moment');
  current.searchParams.delete('race');
  current.searchParams.delete('driver');
  if (app.selected) current.searchParams.set('moment', app.selected.id);
  else {
    current.searchParams.set('race', entry.race_id);
    current.searchParams.set('driver', entry.driver);
  }
  history.replaceState(null, '', current);
  render();
}
function firstEntry(season, driver) {
  const options = app.catalog.filter(item => item.season === season && item.driver === driver);
  return options.find(item => item.decision_ids.length) || options[0];
}
function updatePickers() {
  const entry = app.entry;
  fillSelect($('season'), [2022, 2023, 2024].map(year => [year, String(year)]), entry.season);
  const drivers = [...new Map(app.catalog.filter(item => item.season === entry.season).map(item => [item.driver, item.name])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  fillSelect($('driver'), drivers.map(([code, name]) => [code, `${name} · ${code}`]), entry.driver);
  const races = app.catalog.filter(item => item.season === entry.season && item.driver === entry.driver);
  fillSelect($('race'), races.map(item => [item.race_id, `${item.race} · ${item.decision_ids.length ? 'Comparison' : 'Race record'}`]), entry.race_id);
}
function renderScene(entry, row) {
  const scene = $('scene-tile');
  scene.replaceChildren();
  scene.append(el('span', 'scene-overline', `RACE ENTRY · ${entry.season}`), el('strong', 'scene-name', `${entry.name}  ·  ${entry.driver}`), el('span', 'scene-team', `${entry.team} · ${entry.race}`), el('span', 'scene-bottom', row ? `${row.verdict === 'UNREVIEWED' ? 'Exploratory' : 'Audited'} lap ${row.lap} of ${row.total_laps}    /    ${wordTyre(row.current_tyre)} → ${wordTyre(row.target_tyre)}` : `${entry.recorded.laps} laps recorded · ${entry.recorded.pit_entry_laps.length} pit lane entries`));
}
function renderLaps(pair, row) {
  const container = $('lap-buttons');
  container.replaceChildren();
  $('checkpoint-title').textContent = pair.length === 1 ? 'One usable race moment.' : 'One driver. Two recorded laps.';
  pair.forEach((item, index) => {
    const button = el('button', '', `Lap ${item.lap}`);
    button.type = 'button';
    button.setAttribute('aria-pressed', String(item.id === row.id));
    button.setAttribute('aria-label', `Show comparison at recorded lap ${item.lap}${index === 1 ? ', one lap later' : ''}`);
    button.addEventListener('click', () => choose(item));
    container.append(button);
  });
}
function verdictText(row) {
  if (row.verdict === 'UNREVIEWED') return 'A first estimate.';
  if (row.verdict === 'PIT_NOW') return 'Pit after this lap.';
  if (row.verdict === 'STAY_OUT') return 'Wait one more lap.';
  return 'No clear winner.';
}
function renderVerdict(row) {
  const firstFavor = row.advantage_seconds > 0 ? 'pitting now' : row.advantage_seconds < 0 ? 'waiting one lap' : 'neither choice';
  $('verdict-title').textContent = verdictText(row);
  $('verdict-lap').textContent = `LAP ${row.lap} / ${row.total_laps}`;
  $('verdict-copy').textContent = row.verdict === 'UNREVIEWED'
    ? `The model's first estimate favors ${firstFavor} by ${fixed(Math.abs(row.advantage_seconds))} seconds. This added race moment has not passed the full sensitivity audit, so this is not a firm pit call.`
    : row.verdict === 'NO_CLEAR_ADVANTAGE'
    ? `The first estimate favors ${firstFavor} by ${fixed(Math.abs(row.advantage_seconds))} seconds. That gap is too small compared with this model’s development-replay margin, so we cannot call either choice clearly quicker.`
    : `The first estimate favors ${firstFavor} by ${fixed(Math.abs(row.advantage_seconds))} seconds. Its review margin stays on the same side of a tie.`;
  $('verdict-foot').replaceChildren(el('strong', '', row.verdict === 'UNREVIEWED' ? 'Exploratory model estimate.' : row.verdict === 'NO_CLEAR_ADVANTAGE' ? 'A useful answer can be “too close.”' : 'The estimated gap clears the review margin.'), document.createTextNode('The other choice was simulated, not observed.'));
}
function renderPaths(row) {
  $('time-now').textContent = time(row.pit_now_seconds);
  $('time-wait').textContent = time(row.wait_seconds);
  const lapped = row.finish_evidence === 'LAPPED_FINISH_TIMING';
  $('paths-intro').textContent = lapped
    ? `Both clocks run to this driver's recorded finish after lap ${row.total_laps}; the leader completed ${row.leader_total_laps} laps. The same stop-cost assumption applies to both.`
    : 'Both clocks start here and run to the end of the race. The stop costs are included.';
  $('detail-now').textContent = `${lapped ? 'To driver’s recorded finish' : 'Full remaining time'} · ${wordTyre(row.target_tyre)} after stop`;
  $('detail-wait').textContent = `${lapped ? 'To driver’s recorded finish' : 'Full remaining time'} · one extra lap on ${wordTyre(row.current_tyre)}`;
  $('gap-line').textContent = `${fixed(Math.abs(row.advantage_seconds))} seconds apart in the first estimate`;
  $('path-now').setAttribute('aria-pressed', String(app.path === 'now'));
  $('path-wait').setAttribute('aria-pressed', String(app.path === 'wait'));
  const tyre = wordTyre(row.target_tyre).toLowerCase();
  $('selected-explain').textContent = app.path === 'now'
    ? `Pit after lap ${row.lap}: add the ${fixed(row.pit_loss_assumption_seconds, 0)}-second stop-cost assumption and fit ${tyre} tyres. ${row.recorded_pit_lap ? `The real stop was after lap ${row.recorded_pit_lap}; this earlier stop is simulated.` : 'The alternative is simulated.'}`
    : `Wait one lap: complete lap ${row.lap + 1} on the current ${wordTyre(row.current_tyre).toLowerCase()} tyres, then test a stop for ${tyre} tyres.`;
}
function renderShift(pair, current) {
  const container = $('shift-chart');
  container.replaceChildren();
  $('shift-kicker').textContent = pair.length === 1 ? 'ONE RACE MOMENT' : 'A LAP LATER';
  $('shift-title').textContent = pair.length === 1 ? 'The available checkpoint' : 'See the estimate move';
  $('shift-hint').textContent = pair.length === 1 ? 'One historical checkpoint' : 'Two historical checkpoints';
  const top = el('div', 'shift-axis');
  top.append(el('span', '', 'WAITING FASTER'), el('strong', '', 'ZERO = TIE'), el('span', '', 'PITTING FASTER'));
  container.append(top);
  const maximum = Math.max(...pair.map(item => Math.abs(item.advantage_seconds)), 1) * 1.25;
  pair.forEach(row => {
    const button = el('button', 'shift-row');
    button.type = 'button';
    button.setAttribute('aria-current', row.id === current.id ? 'step' : 'false');
    button.setAttribute('aria-label', `Lap ${row.lap}, first estimate ${fixed(Math.abs(row.advantage_seconds))} seconds favors ${row.advantage_seconds >= 0 ? 'pitting' : 'waiting'}. Show this lap.`);
    const track = el('span', 'shift-track');
    const x = 50 + 43 * row.advantage_seconds / maximum;
    const gap = el('span', `shift-fill ${row.advantage_seconds >= 0 ? 'toward-now' : 'toward-wait'}`);
    gap.style.left = `${Math.min(x, 50)}%`;
    gap.style.width = `${Math.abs(x - 50)}%`;
    const dot = el('span', `shift-dot ${row.id === current.id ? 'active' : ''}`);
    dot.style.left = `${x}%`;
    track.append(gap, dot);
    button.append(el('strong', 'shift-lap', `LAP ${row.lap}`), track, el('span', 'shift-number', `${sign(row.advantage_seconds)}s`));
    button.addEventListener('click', () => choose(row));
    container.append(button);
  });
  const summary = el('p', 'shift-summary', pair.length === 1
    ? `Only lap ${pair[0].lap} passed this comparison’s input checks. This is a precomputed estimate, not a live forecast.`
    : `From lap ${pair[0].lap} to ${pair[1].lap}, the first estimated gap moved by ${fixed(Math.abs(pair[1].advantage_seconds - pair[0].advantage_seconds))} seconds. Both points are precomputed snapshots, not a live forecast.`);
  container.append(summary);
}
function fact(label, value) { const block = el('div'); block.append(el('span', '', label), el('strong', '', value)); return block; }
function renderRecorded(entry) {
  const record = entry.recorded;
  $('recorded-facts').replaceChildren(
    fact('LAPS RECORDED', `${record.laps} of ${record.race_laps}`),
    fact('LAST RECORDED POSITION', record.last_position === null ? 'Not recorded' : `P${record.last_position}`),
    fact('PIT LANE ENTRIES', record.pit_entry_laps.length ? record.pit_entry_laps.map(lap => `lap ${lap}`).join(', ') : 'None recorded'),
  );
  const stints = $('recorded-stints'); stints.replaceChildren();
  for (const stint of record.stints) {
    const part = el('span', `recorded-stint ${stint.compound.toLowerCase()}`);
    const length = stint.end_lap - stint.start_lap + 1;
    part.style.flexGrow = String(length);
    part.textContent = length > Math.max(3, record.laps / 14) ? stint.compound : '';
    part.title = `${stint.compound}, laps ${stint.start_lap}–${stint.end_lap}`;
    stints.append(part);
  }
  $('recorded-stints-description').textContent = record.stints.map(stint => `${stint.compound.toLowerCase()}, laps ${stint.start_lap}–${stint.end_lap}`).join(' · ');
}
function renderRace(row, pair) {
  $('race-heading').textContent = `${row.race} · ${row.name}`;
  $('race-lap').textContent = `LAP ${row.lap}`;
  $('progress-bar').style.width = `${Math.min(100, 100 * row.lap / row.total_laps)}%`;
  $('race-progress-left').textContent = `Lap ${row.lap} completed`;
  $('race-progress-right').textContent = `${row.total_laps - row.lap} laps to ${row.finish_evidence === 'LAPPED_FINISH_TIMING' ? 'driver’s recorded finish' : 'go'}`;
  $('race-facts').replaceChildren(fact('LAST RECORDED POSITION', row.position === null ? 'Not recorded' : `P${row.position}`), fact('TYRE AGE', `${row.tyre_age} laps`), fact('TRACK TEMPERATURE', row.track_celsius === null ? 'Not recorded' : `${fixed(row.track_celsius, 1)}°C`), fact('LAST LAP TIME', row.last_lap_seconds === null ? 'Not recorded' : `${fixed(row.last_lap_seconds, 3)} s`));
  $('current-tyre').textContent = wordTyre(row.current_tyre);
  $('target-tyre').textContent = wordTyre(row.target_tyre);
  $('tyre-age').textContent = `Used for ${row.tyre_age} laps`;
  $('pit-cost').textContent = `${fixed(row.pit_loss_assumption_seconds, 0)}-second stop-cost assumption`;
  $('tyre-context').textContent = row.recorded_pit_lap
    ? `In the real race, ${wordTyre(row.target_tyre).toLowerCase()} tyres went on after lap ${row.recorded_pit_lap}. Here we test fitting them after lap ${row.lap} or lap ${row.lap + 1} instead. That earlier plan was simulated.`
    : `The target tyre is the one recorded after the historical stop; the other pit timing is simulated.`;
  $('current-tyre-mark').className = `tyre-ring ${row.current_tyre.toLowerCase()}`;
  $('target-tyre-mark').className = `tyre-ring ${row.target_tyre.toLowerCase()}`;
  const context = $('context-change'); context.replaceChildren();
  $('context-title').textContent = pair.length === 1 ? 'The recorded context' : 'What changed?';
  $('context-caveat').textContent = pair.length === 1
    ? 'This is recorded context for one decision, not proof of why the time estimate favors either path.'
    : 'These measurements changed together. This is context, not proof that any one measurement caused the new estimate.';
  if (pair.length === 1) {
    context.append(el('div', 'change-headers', `LAP ${row.lap} · ONE ELIGIBLE CHECKPOINT`),
      el('p', '', `Current tyres: ${wordTyre(row.current_tyre)} after ${row.tyre_age} laps. The model has no adjacent safe checkpoint for this driver and race.`));
    return;
  }
  const [a, b] = pair;
  const values = [
    ['Tyre age', `${a.tyre_age} laps`, `${b.tyre_age} laps`],
    ['Last lap time', a.last_lap_seconds === null ? 'Not recorded' : `${fixed(a.last_lap_seconds, 2)} s`, b.last_lap_seconds === null ? 'Not recorded' : `${fixed(b.last_lap_seconds, 2)} s`],
    ['Track temperature', a.track_celsius === null ? 'Not recorded' : `${fixed(a.track_celsius, 1)}°C`, b.track_celsius === null ? 'Not recorded' : `${fixed(b.track_celsius, 1)}°C`],
    ['Recorded position', a.position === null ? 'Not recorded' : `P${a.position}`, b.position === null ? 'Not recorded' : `P${b.position}`],
    ['First estimated gap', `${sign(a.advantage_seconds)} s`, `${sign(b.advantage_seconds)} s`],
  ];
  context.append(el('div', 'change-headers', `LAP ${a.lap}  →  LAP ${b.lap}`));
  values.forEach(([label, before, after]) => {
    const item = el('div');
    item.append(el('span', 'change-label', label), el('strong', '', before), el('strong', '', after));
    context.append(item);
  });
}
function renderMethod(row, meta) {
  const low = row.band_low_seconds, high = row.band_high_seconds;
  const extent = Math.max(Math.abs(low), Math.abs(high), Math.abs(row.advantage_seconds), 1) * 1.2;
  const pos = n => 50 + n * 44 / extent;
  const chart = $('margin-chart'); chart.replaceChildren();
  const labels = el('div', 'margin-labels');
  labels.append(el('strong', '', `${sign(low)} s`), el('span', '', 'ZERO = TIE'), el('strong', '', `${sign(high)} s`));
  const rail = el('div', 'margin-rail');
  const band = el('div', 'margin-band'); band.style.left = `${pos(low)}%`; band.style.width = `${pos(high) - pos(low)}%`;
  const zero = el('span', 'margin-zero'); zero.style.left = `${pos(0)}%`;
  const point = el('span', 'margin-point'); point.style.left = `${pos(row.advantage_seconds)}%`;
  rail.append(band, zero, point);
  const directions = el('div', 'margin-directions');
  directions.append(el('span', '', 'WAITING FASTER'), el('span', '', 'PITTING FASTER'));
  chart.append(labels, rail, directions);
  chart.setAttribute('role', 'img');
  chart.setAttribute('aria-label', `${row.verdict === 'UNREVIEWED' ? 'Exploratory replay error allowance' : 'Review margin'} from ${fixed(low)} to ${fixed(high)} seconds; zero is tie and the first estimate is ${fixed(row.advantage_seconds)} seconds. ${low <= 0 && high >= 0 ? 'The allowance crosses zero.' : 'The allowance stays to one side of zero.'}`);
  $('margin-facts').replaceChildren(fact('FIRST ESTIMATED GAP', `${sign(row.advantage_seconds)} s`), fact('REPLAY ERROR PER PATH', `±${fixed(row.margin_per_path_seconds)} s`), fact(row.verdict === 'UNREVIEWED' ? 'ERROR ALLOWANCE' : 'REVIEW BAND', `${sign(low)} to ${sign(high)} s`));
  const exploratory = row.verdict === 'UNREVIEWED';
  $('method-heading').textContent = exploratory ? 'How far could this first estimate move?' : 'The difference has a wide review margin';
  $('method-caveat').textContent = exploratory
    ? 'This bracket applies the development replay error allowance to each simulated path. It does not include the full pit-loss and tyre-age sensitivity audit and is not a confidence interval.'
    : 'This band adds a development-replay error allowance to sensitivity cases. It is a descriptive stress test, not a 90% confidence interval or a probability of being right.';
  const prePit = row.source_tier === 'PRE_PIT_EXPLORATORY';
  $('provenance').replaceChildren(
    el('p', '', prePit
      ? `This is one of ${app.prePit.case_count} additional earlier dry, green-flag checkpoints. The recorded stop was after lap ${row.recorded_pit_lap}, when the driver fitted ${wordTyre(row.target_tyre).toLowerCase()} tyres. This model comparison imagines using that tyre earlier, after lap ${row.lap} or ${row.lap + 1}. It was computed from past-only race features and has not passed the immutable Phase 8 sensitivity audit.`
      : exploratory
      ? `This is one of ${app.extended.paired_checkpoints} additional reconstructed dry pit-window pairs in 2022–2024. Its two point estimates use the frozen model and recorded next tyre. It was computed for this site and has not been through the immutable Phase 8 full sensitivity audit.`
      : `Based on ${meta.count} audited dry, green-flag development decisions at ${meta.paired_checkpoints} pairs of adjacent laps from 2022–2024. The shown results were calculated before this site was published; no model runs in your browser.`),
    el('p', '', `Model artifact: ${meta.model_id}; training seasons: ${meta.training_seasons.join(', ')}. All displayed pit stops use an explicit 20-second cost assumption. ${exploratory ? 'The bracket is only a replay-error allowance.' : 'The band also includes sensitivity checks.'} Neither is calibrated future-race uncertainty.`),
    ...(row.finish_evidence === 'LAPPED_FINISH_TIMING' ? [el('p', '', `This driver’s last recorded crossing came after the leader’s finish. Both hypothetical paths use the driver’s ${row.total_laps}-lap recorded horizon; the leader completed ${row.leader_total_laps} laps. This does not estimate a finishing position.`)] : []),
    el('p', '', `Phase 8 decisions report SHA-256: ${meta.source_sha256}. The protected 2025 evaluation remains unopened for this site.`)
  );
}
function setTab(name, focus = false) {
  app.tab = name;
  for (const tab of document.querySelectorAll('[role=tab]')) {
    const selected = tab.dataset.tab === name;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  }
  for (const panel of document.querySelectorAll('.tab-panel')) panel.hidden = panel.id !== `panel-${name}`;
}
function render() {
  const entry = app.entry;
  const row = app.selected;
  updatePickers(); renderScene(entry, row);
  $('loaded').hidden = !row;
  $('unavailable-selection').hidden = Boolean(row);
  if (!row) {
    $('unavailable-title').textContent = `${entry.name} · ${entry.race}`;
    $('unavailable-team').textContent = `${entry.season} · ${entry.driver} · ${entry.team}`;
    const explanations = {
      INCOMPLETE_HORIZON: `This driver has ${entry.recorded.laps} recorded laps while the race leader has ${entry.recorded.race_laps}. The lap record does not establish a usable finish crossing for this comparison, so a complete remaining-time estimate is unavailable.`,
      NO_RECORDED_DRY_TYRE: 'No next dry tyre was recorded for this driver. This version uses the tyre the driver later fitted; choosing one here would be a guess.',
      NO_SAFE_DECISION_LAP: 'The recorded dry tyre change has no eligible green, dry decision lap and legal two-compound plan under this model’s checks. A time estimate here would exceed the tested conditions.',
    };
    $('unavailable-copy').textContent = explanations[entry.availability_reason];
    renderRecorded(entry);
    return;
  }
  const pair = groupPair(row);
  renderLaps(pair, row); renderVerdict(row); renderPaths(row); renderShift(pair, row); renderRace(row, pair); renderMethod(row, app.data);
  $('race-label').textContent = `${row.season}  /  ${row.race.toUpperCase()}  /  ${row.driver}`;
  $('record-index').textContent = row.verdict === 'UNREVIEWED'
    ? `EXPLORATORY COMPARISON · ${row.recorded_pit_lap ? 'EARLIER PIT MOMENT' : 'RECORDED PIT WINDOW'}`
    : `124 AUDITED MOMENTS · RECORD ${app.data.decisions.findIndex(item => item.id === row.id) + 1}`;
  setTab(app.tab);
}
function registerTools() {
  const context = document.modelContext;
  if (toolsRegistered || !context?.registerTool) return;
  toolsRegistered = true;
  const tools = [
    {
      name: 'list_verified_moments',
      title: 'List historical pit decisions',
      description: 'List available verified historical decisions; optionally filter by 2022, 2023 or 2024. Results are precomputed research snapshots.',
      inputSchema: {type: 'object', properties: {season: {type: 'integer', enum: [2022, 2023, 2024]}}, additionalProperties: false},
      annotations: {readOnlyHint: true},
      execute(input) {
        if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(key => key !== 'season') || (input.season !== undefined && ![2022, 2023, 2024].includes(input.season))) throw new TypeError('Choose a supported season or omit the filter');
        return app.data.decisions.filter(row => input.season === undefined || row.season === input.season).map(row => ({id: row.id, race: row.race, driver: row.name, lap: row.lap}));
      },
    },
    {
      name: 'show_verified_moment',
      title: 'Show a pit decision',
      description: 'Select one listed historical decision and show its two estimated remaining times and research verdict in the visible dashboard.',
      inputSchema: {type: 'object', properties: {id: {type: 'string'}}, required: ['id'], additionalProperties: false},
      annotations: {readOnlyHint: false},
      execute(input) {
        if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length !== 1 || typeof input.id !== 'string') throw new TypeError('Provide exactly one decision id');
        const row = app.data.decisions.find(item => item.id === input.id);
        if (!row) throw new RangeError('Decision is not in the verified catalog');
        choose(row);
        return {id: row.id, race: row.race, driver: row.name, lap: row.lap, pit_now_seconds: row.pit_now_seconds, wait_seconds: row.wait_seconds, verdict: row.verdict};
      },
    },
  ];
  for (const tool of tools) {
    try { void Promise.resolve(context.registerTool(tool)).catch(() => { toolsRegistered = false; }); }
    catch { toolsRegistered = false; }
  }
}
async function load() {
  $('load-state').hidden = false; $('error-state').hidden = true; $('loaded').hidden = true; $('unavailable-selection').hidden = true;
  try {
    const [response, extendedResponse, prePitResponse, catalogResponse] = await Promise.all([
      fetch('./decisions.json', {cache: 'no-store'}),
      fetch('./extended_decisions.json', {cache: 'no-store'}),
      fetch('./pre_pit_decisions.json', {cache: 'no-store'}),
      fetch('./catalog.json', {cache: 'no-store'}),
    ]);
    if (!response.ok || !extendedResponse.ok || !prePitResponse.ok || !catalogResponse.ok) throw new Error('Could not load reports');
    const [data, extended, prePit, catalog] = await Promise.all([response.json(), extendedResponse.json(), prePitResponse.json(), catalogResponse.json()]);
    validate(data);
    validateExtended(extended, data);
    validatePrePit(prePit, data, extended);
    app.data = data; app.extended = extended; app.prePit = prePit; app.rows = [...data.decisions, ...extended.decisions, ...prePit.decisions];
    validateCatalog(catalog);
    app.catalog = catalog.entries;
    const compared = app.catalog.filter(entry => entry.decision_ids.length).length;
    $('picker-help').textContent = `All ${app.catalog.length.toLocaleString()} recorded driver/race entries are listed. ${compared.toLocaleString()} have model comparisons; other entries show the race record and explain the missing estimate.`;
    const params = new URLSearchParams(location.search);
    const deepLink = params.get('moment');
    const chosen = app.rows.find(item => item.id === deepLink) || app.rows.find(item => item.race_id === '2024-04-R' && item.driver === 'HAM' && item.lap === 38) || app.rows[0];
    const saved = deepLink ? null : app.catalog.find(item => item.race_id === params.get('race') && item.driver === params.get('driver'));
    app.entry = saved || app.catalog.find(item => item.race_id === chosen.race_id && item.driver === chosen.driver);
    app.selected = saved ? app.rows.find(item => saved.decision_ids.includes(item.id)) || null : chosen;
    render();
    registerTools();
    $('load-state').hidden = true;
  } catch (error) {
    console.error('Verified catalog unavailable:', error);
    app.data = null; app.extended = null; app.prePit = null; app.rows = []; app.catalog = []; app.entry = null; app.selected = null;
    for (const id of ['season', 'driver', 'race']) fillSelect($(id), [['', 'Data unavailable']], '');
    $('load-state').hidden = true; $('error-state').hidden = false;
  }
}
$('season').addEventListener('change', event => {
  const season = Number(event.target.value);
  const driver = app.catalog.some(item => item.season === season && item.driver === app.entry.driver) ? app.entry.driver : app.catalog.find(item => item.season === season).driver;
  chooseEntry(firstEntry(season, driver));
});
$('driver').addEventListener('change', event => chooseEntry(firstEntry(app.entry.season, event.target.value)));
$('race').addEventListener('change', event => chooseEntry(app.catalog.find(item => item.race_id === event.target.value && item.driver === app.entry.driver)));
$('view-verified').addEventListener('click', () => {
  const next = app.rows.find(row => row.driver === app.entry.driver && row.season === app.entry.season)
    || app.rows.find(row => row.driver === app.entry.driver)
    || app.rows[0];
  choose(next);
});
$('path-now').addEventListener('click', () => { app.path = 'now'; renderPaths(app.selected); });
$('path-wait').addEventListener('click', () => { app.path = 'wait'; renderPaths(app.selected); });
$('retry').addEventListener('click', load);
for (const tab of document.querySelectorAll('[role=tab]')) {
  tab.addEventListener('click', () => setTab(tab.dataset.tab));
  tab.addEventListener('keydown', event => {
    const tabs = [...document.querySelectorAll('[role=tab]')];
    const index = tabs.indexOf(tab);
    const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
    if (next !== -1) { event.preventDefault(); setTab(tabs[next].dataset.tab, true); }
  });
}
load();
