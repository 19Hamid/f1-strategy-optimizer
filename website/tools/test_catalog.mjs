// Regression for every 2022–2024 starter/race, including exploratory estimates.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const records = JSON.parse(fs.readFileSync(path.join(root, 'dist/catalog.json')));
const prePit = JSON.parse(fs.readFileSync(path.join(root, 'dist/pre_pit_decisions.json')));
const nodes = new Map();
class Element {
  constructor() { this.children = []; this.events = {}; this.style = {}; this.hidden = false; this.value = ''; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, listener) { this.events[key] = listener; }
  focus() {}
}
const get = id => {
  if (!nodes.has(id)) nodes.set(id, new Element());
  return nodes.get(id);
};
const document = {
  getElementById: get,
  createElement: () => new Element(),
  createTextNode: text => ({textContent: text}),
  querySelectorAll: () => [],
};
const location = {
  href: 'http://localhost/',
  get search() { return new URL(this.href).search; },
};
const context = vm.createContext({
  document, location, URL, URLSearchParams, Option: class { constructor(label, value) { this.textContent = label; this.value = value; } },
  history: {replaceState(_state, _title, url) { location.href = String(url); }},
  fetch: async filename => ({
    ok: true,
    json: async () => JSON.parse(fs.readFileSync(path.join(root, 'dist', filename.replace('./', '')))),
  }),
  console,
});
const code = fs.readFileSync(path.join(root, 'dist/app.js'), 'utf8').replace(/\nload\(\);\s*$/, '\nglobalThis.testApp = app; globalThis.testLoad = load;');
vm.runInContext(code, context);
await context.testLoad();
assert.equal(get('error-state').hidden, true);
assert.equal(context.testApp.rows.length, 1152 + prePit.count);
assert.equal(context.testApp.catalog.length, 1350);
assert.equal(get('season').children.length, 3);
const change = (id, value) => {
  const field = get(id);
  field.value = String(value);
  field.events.change({target: field});
};

for (const year of records.seasons) {
  change('season', year);
  const drivers = [...new Set(records.entries.filter(entry => entry.season === year).map(entry => entry.driver))];
  assert.equal(get('driver').children.length, drivers.length);
  for (const driver of drivers) {
    change('driver', driver);
    const races = records.entries.filter(entry => entry.season === year && entry.driver === driver);
    assert.deepEqual(get('race').children.map(item => item.value), races.map(item => item.race_id));
    for (const race of races) {
      change('race', race.race_id);
      assert.equal(context.testApp.entry.race_id, race.race_id);
      assert.equal(context.testApp.entry.driver, driver);
      assert.equal(Boolean(context.testApp.selected), race.decision_ids.length > 0);
      assert.equal(get('loaded').hidden, race.decision_ids.length === 0);
      assert.equal(get('unavailable-selection').hidden, race.decision_ids.length > 0);
    }
  }
}

change('season', 2024);
change('driver', 'HAM');
change('race', '2024-18-R'); // Singapore: previously a dead-end; now a reconstructed pair.
assert.equal(get('loaded').hidden, false);
assert.equal(context.testApp.selected.verdict, 'UNREVIEWED');
assert.equal(get('lap-buttons').children.length, 2);
change('season', 2022);
change('driver', 'HAM');
change('race', '2022-05-R'); // Miami: recorded pit lap 22 had no eligible adjacent pit window.
assert.equal(get('loaded').hidden, false);
assert.equal(context.testApp.selected.recorded_pit_lap, 22);
assert.equal(context.testApp.selected.target_tyre, 'HARD');
assert.ok(context.testApp.selected.lap < 22);
assert.equal(get('lap-buttons').children.length, 2);
assert.match(get('tyre-context').textContent, /real race.*lap 22/);
assert.ok(Number.isFinite(context.testApp.selected.wait_seconds));
const lappedMoment = prePit.decisions.find(row => row.finish_evidence === 'LAPPED_FINISH_TIMING');
assert.ok(lappedMoment);
change('season', lappedMoment.season);
change('driver', lappedMoment.driver);
change('race', lappedMoment.race_id);
assert.equal(context.testApp.selected.finish_evidence, 'LAPPED_FINISH_TIMING');
assert.match(get('paths-intro').textContent, /driver's recorded finish/);
assert.ok(context.testApp.selected.total_laps < context.testApp.selected.leader_total_laps);
const single = records.entries.find(entry => entry.decision_ids.length === 1);
assert.ok(single);
change('season', single.season);
change('driver', single.driver);
change('race', single.race_id);
assert.equal(get('loaded').hidden, false);
assert.equal(get('lap-buttons').children.length, 1);
assert.equal(get('context-title').textContent, 'The recorded context');
const reasons = new Set(records.entries.filter(entry => !entry.decision_ids.length).map(entry => entry.availability_reason));
assert.deepEqual(reasons, new Set(['INCOMPLETE_HORIZON', 'NO_RECORDED_DRY_TYRE', 'NO_SAFE_DECISION_LAP']));
const unavailable = records.entries.find(entry => entry.season === 2024 && entry.driver === 'HAM' && !entry.decision_ids.length);
assert.ok(unavailable);
change('season', unavailable.season);
change('driver', unavailable.driver);
change('race', unavailable.race_id);
assert.equal(get('loaded').hidden, true);
assert.equal(context.testApp.selected, null);
assert.equal(new URL(location.href).searchParams.has('moment'), false);
assert.equal(get('unavailable-selection').hidden, false);
assert.ok(get('unavailable-copy').textContent.length > 30);
assert.ok(get('recorded-facts').children.length > 0);
assert.ok(get('recorded-stints').children.length > 0);
get('view-verified').events.click();
assert.equal(get('loaded').hidden, false);
console.log(`Picker smoke passed: all 1,350 entries, ${62 + 514 + prePit.case_count} compared entries, Hamilton Miami/Singapore, single checkpoint, unavailable reasons, and stale-result removal.`);
