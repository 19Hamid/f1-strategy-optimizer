'use strict';

const $ = id => document.getElementById(id);
const app = {data: null, rows: [], selected: null, path: 'now', tab: 'answer'};
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
function groupPair(row) { return app.rows.filter(item => item.race_id === row.race_id && item.driver === row.driver).sort((a, b) => a.lap - b.lap); }
function firstRow(filter) { return app.rows.find(filter) || app.rows[0]; }
function unique(items) { return [...new Set(items)]; }
function choose(row) {
  app.selected = row;
  app.path = 'now';
  const current = new URL(location.href);
  current.searchParams.set('moment', row.id);
  history.replaceState(null, '', current);
  render();
}
function updatePickers() {
  const row = app.selected;
  fillSelect($('season'), unique(app.rows.map(item => item.season)).map(y => [y, String(y)]), row.season);
  const drivers = unique(app.rows.filter(item => item.season === row.season).map(item => item.driver));
  fillSelect($('driver'), drivers.map(code => { const item = firstRow(r => r.season === row.season && r.driver === code); return [code, `${item.name} · ${code}`]; }), row.driver);
  const races = unique(app.rows.filter(item => item.season === row.season && item.driver === row.driver).map(item => item.race_id));
  fillSelect($('race'), races.map(id => { const item = firstRow(r => r.race_id === id && r.driver === row.driver); return [id, item.race]; }), row.race_id);
}
function renderScene(row) {
  const scene = $('scene-tile');
  scene.replaceChildren();
  scene.append(el('span', 'scene-overline', `RACE MOMENT · ${row.season}`), el('strong', 'scene-name', `${row.name}  ·  ${row.driver}`), el('span', 'scene-team', `${row.team} · ${row.race}`), el('span', 'scene-bottom', `Lap ${row.lap} of ${row.total_laps}    /    ${wordTyre(row.current_tyre)} → ${wordTyre(row.target_tyre)}`));
}
function renderLaps(pair, row) {
  const container = $('lap-buttons');
  container.replaceChildren();
  pair.forEach((item, index) => {
    const button = el('button', '', `Lap ${item.lap}`);
    button.type = 'button';
    button.setAttribute('aria-pressed', String(item.id === row.id));
    button.setAttribute('aria-label', `Show recorded lap ${item.lap}${index === 1 ? ', one lap later' : ''}`);
    button.addEventListener('click', () => choose(item));
    container.append(button);
  });
}
function verdictText(row) {
  if (row.verdict === 'PIT_NOW') return 'Pit after this lap.';
  if (row.verdict === 'STAY_OUT') return 'Wait one more lap.';
  return 'No clear winner.';
}
function renderVerdict(row) {
  const firstFavor = row.advantage_seconds > 0 ? 'pitting now' : row.advantage_seconds < 0 ? 'waiting one lap' : 'neither choice';
  $('verdict-title').textContent = verdictText(row);
  $('verdict-lap').textContent = `LAP ${row.lap} / ${row.total_laps}`;
  $('verdict-copy').textContent = row.verdict === 'NO_CLEAR_ADVANTAGE'
    ? `The first estimate favors ${firstFavor} by ${fixed(Math.abs(row.advantage_seconds))} seconds. That gap is too small compared with this model’s development-replay margin, so we cannot call either choice clearly quicker.`
    : `The first estimate favors ${firstFavor} by ${fixed(Math.abs(row.advantage_seconds))} seconds. Its review margin stays on the same side of a tie.`;
  $('verdict-foot').replaceChildren(el('strong', '', row.verdict === 'NO_CLEAR_ADVANTAGE' ? 'A useful answer can be “too close.”' : 'The estimated gap clears the review margin.'), document.createTextNode('The other choice was simulated, not observed.'));
}
function renderPaths(row) {
  $('time-now').textContent = time(row.pit_now_seconds);
  $('time-wait').textContent = time(row.wait_seconds);
  $('detail-now').textContent = `Full remaining time · ${wordTyre(row.target_tyre)} after stop`;
  $('detail-wait').textContent = `Full remaining time · one extra lap on ${wordTyre(row.current_tyre)}`;
  $('gap-line').textContent = `${fixed(Math.abs(row.advantage_seconds))} seconds apart in the first estimate`;
  $('path-now').setAttribute('aria-pressed', String(app.path === 'now'));
  $('path-wait').setAttribute('aria-pressed', String(app.path === 'wait'));
  $('selected-explain').textContent = app.path === 'now'
    ? `Pit after lap ${row.lap}: add the 20-second pit-loss assumption, then use the recorded ${wordTyre(row.target_tyre).toLowerCase()} tyre for the remaining laps.`
    : `Wait one lap: complete lap ${row.lap + 1} on the current ${wordTyre(row.current_tyre).toLowerCase()} tyre, then test the same recorded ${wordTyre(row.target_tyre).toLowerCase()} tyre.`;
}
function renderShift(pair, current) {
  const container = $('shift-chart');
  container.replaceChildren();
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
  const summary = el('p', 'shift-summary', `From lap ${pair[0].lap} to ${pair[1].lap}, the first estimated gap moved by ${fixed(Math.abs(pair[1].advantage_seconds - pair[0].advantage_seconds))} seconds. Both points are precomputed snapshots, not a live forecast.`);
  container.append(summary);
}
function fact(label, value) { const block = el('div'); block.append(el('span', '', label), el('strong', '', value)); return block; }
function renderRace(row, pair) {
  $('race-heading').textContent = `${row.race} · ${row.name}`;
  $('race-lap').textContent = `LAP ${row.lap}`;
  $('progress-bar').style.width = `${Math.min(100, 100 * row.lap / row.total_laps)}%`;
  $('race-progress-left').textContent = `Lap ${row.lap} completed`;
  $('race-progress-right').textContent = `${row.total_laps - row.lap} laps to go`;
  $('race-facts').replaceChildren(fact('LAST RECORDED POSITION', `P${row.position}`), fact('TYRE AGE', `${row.tyre_age} laps`), fact('TRACK TEMPERATURE', row.track_celsius === null ? 'Not recorded' : `${fixed(row.track_celsius, 1)}°C`), fact('LAST LAP TIME', row.last_lap_seconds === null ? 'Not recorded' : `${fixed(row.last_lap_seconds, 3)} s`));
  $('current-tyre').textContent = wordTyre(row.current_tyre);
  $('target-tyre').textContent = wordTyre(row.target_tyre);
  $('tyre-age').textContent = `Used for ${row.tyre_age} laps`;
  $('pit-cost').textContent = `${fixed(row.pit_loss_assumption_seconds, 0)}-second stop-cost assumption`;
  $('current-tyre-mark').className = `tyre-ring ${row.current_tyre.toLowerCase()}`;
  $('target-tyre-mark').className = `tyre-ring ${row.target_tyre.toLowerCase()}`;
  const context = $('context-change'); context.replaceChildren();
  const [a, b] = pair;
  const values = [
    ['Tyre age', `${a.tyre_age} laps`, `${b.tyre_age} laps`],
    ['Last lap time', a.last_lap_seconds === null ? 'Not recorded' : `${fixed(a.last_lap_seconds, 2)} s`, b.last_lap_seconds === null ? 'Not recorded' : `${fixed(b.last_lap_seconds, 2)} s`],
    ['Track temperature', a.track_celsius === null ? 'Not recorded' : `${fixed(a.track_celsius, 1)}°C`, b.track_celsius === null ? 'Not recorded' : `${fixed(b.track_celsius, 1)}°C`],
    ['Recorded position', `P${a.position}`, `P${b.position}`],
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
  chart.setAttribute('aria-label', `Review margin from ${fixed(low)} to ${fixed(high)} seconds; zero is tie and the first estimate is ${fixed(row.advantage_seconds)} seconds. ${low <= 0 && high >= 0 ? 'Margin crosses zero.' : 'Margin stays to one side of zero.'}`);
  $('margin-facts').replaceChildren(fact('FIRST ESTIMATED GAP', `${sign(row.advantage_seconds)} s`), fact('REPLAY ERROR PER PATH', `±${fixed(row.margin_per_path_seconds)} s`), fact('REVIEW BAND', `${sign(low)} to ${sign(high)} s`));
  $('provenance').replaceChildren(
    el('p', '', `Based on ${meta.count} verified dry, green-flag development decisions at ${meta.paired_checkpoints} pairs of adjacent laps from 2022–2024. The shown results were calculated before this site was published; no model runs in your browser.`),
    el('p', '', `Model artifact: ${meta.model_id}; training seasons: ${meta.training_seasons.join(', ')}. All displayed pit stops use an explicit 20-second cost assumption. The band is based on development replay error and sensitivity checks; it is not calibrated future-race uncertainty.`),
    el('p', '', `Decisions report SHA-256: ${meta.source_sha256}. The protected 2025 evaluation remains unopened for this site.`)
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
  const row = app.selected;
  const pair = groupPair(row);
  updatePickers(); renderScene(row); renderLaps(pair, row); renderVerdict(row); renderPaths(row); renderShift(pair, row); renderRace(row, pair); renderMethod(row, app.data);
  $('race-label').textContent = `${row.season}  /  ${row.race.toUpperCase()}  /  ${row.driver}`;
  $('record-index').textContent = `124 VERIFIED MOMENTS · RECORD ${app.rows.findIndex(item => item.id === row.id) + 1}`;
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
        return app.rows.filter(row => input.season === undefined || row.season === input.season).map(row => ({id: row.id, race: row.race, driver: row.name, lap: row.lap}));
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
        const row = app.rows.find(item => item.id === input.id);
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
  $('load-state').hidden = false; $('error-state').hidden = true; $('loaded').hidden = true;
  try {
    const response = await fetch('./decisions.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('Could not load report');
    const data = await response.json();
    validate(data);
    app.data = data; app.rows = data.decisions;
    const deepLink = new URLSearchParams(location.search).get('moment');
    const chosen = app.rows.find(item => item.id === deepLink) || app.rows.find(item => item.race_id === '2024-04-R' && item.driver === 'HAM' && item.lap === 38) || app.rows[0];
    app.selected = chosen;
    render();
    registerTools();
    $('load-state').hidden = true; $('loaded').hidden = false;
  } catch (error) {
    console.error('Verified catalog unavailable:', error);
    $('load-state').hidden = true; $('error-state').hidden = false;
  }
}
$('season').addEventListener('change', event => { const season = Number(event.target.value); choose(app.rows.find(item => item.season === season && item.driver === app.selected.driver) || firstRow(item => item.season === season)); });
$('driver').addEventListener('change', event => choose(firstRow(item => item.season === app.selected.season && item.driver === event.target.value)));
$('race').addEventListener('change', event => choose(firstRow(item => item.race_id === event.target.value && item.driver === app.selected.driver)));
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
