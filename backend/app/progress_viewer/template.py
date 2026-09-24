"""Self-contained HTML presentation for the development progress viewer."""

from __future__ import annotations

import json
from collections.abc import Mapping


def render_progress_viewer(payload: Mapping[str, object]) -> str:
    """Embed one JSON payload into the dependency-free browser report."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    safe = (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return _DOCUMENT.replace("__VIEWER_DATA__", safe)


_DOCUMENT = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>F1 Strategy Optimizer · Development Evidence</title>
  <style>
    :root {
      --bg: #070a0f;
      --panel: #0d121b;
      --panel-2: #111925;
      --line: #243043;
      --muted: #8e9aac;
      --text: #edf3fa;
      --red: #ff3b4f;
      --red-soft: rgba(255, 59, 79, .16);
      --cyan: #30d5f2;
      --cyan-soft: rgba(48, 213, 242, .13);
      --green: #48e59b;
      --amber: #ffc857;
      --radius: 18px;
      --shadow: 0 22px 65px rgba(0, 0, 0, .34);
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at 80% 0%, rgba(255, 59, 79, .11), transparent 28rem),
        radial-gradient(circle at 8% 24%, rgba(48, 213, 242, .08), transparent 26rem),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }

    a { color: inherit; text-decoration: none; }
    button, select { font: inherit; }
    .shell { width: min(1240px, calc(100% - 32px)); margin: 0 auto; }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid rgba(255, 255, 255, .06);
      background: rgba(7, 10, 15, .82);
      backdrop-filter: blur(18px);
    }
    .topbar-inner {
      min-height: 62px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
    }
    .brand { display: flex; align-items: center; gap: 11px; font-weight: 800; letter-spacing: -.02em; }
    .brand-mark {
      width: 30px;
      height: 30px;
      border-radius: 9px;
      background: linear-gradient(135deg, var(--red), #a70019);
      box-shadow: 0 0 30px rgba(255, 59, 79, .28);
      display: grid;
      place-items: center;
      font-size: 12px;
    }
    nav { display: flex; gap: 18px; color: var(--muted); font-size: 13px; }
    nav a:hover { color: var(--text); }

    .hero {
      padding: 72px 0 38px;
      display: grid;
      grid-template-columns: 1.5fr .8fr;
      gap: 38px;
      align-items: center;
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 11px;
      border: 1px solid rgba(72, 229, 155, .28);
      border-radius: 999px;
      color: var(--green);
      background: rgba(72, 229, 155, .07);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 14px currentColor; }
    h1 {
      margin: 20px 0 14px;
      font-size: clamp(40px, 6vw, 76px);
      line-height: .98;
      letter-spacing: -.055em;
      max-width: 850px;
    }
    .hero-copy { color: var(--muted); font-size: clamp(16px, 2vw, 20px); max-width: 760px; margin: 0; }
    .hero-meta { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 26px; color: var(--muted); font-size: 13px; }
    .hero-meta strong { color: var(--text); }

    .progress-panel {
      min-height: 310px;
      border: 1px solid var(--line);
      background: linear-gradient(145deg, rgba(17, 25, 37, .96), rgba(9, 14, 21, .96));
      border-radius: 28px;
      box-shadow: var(--shadow);
      display: grid;
      place-items: center;
      position: relative;
      overflow: hidden;
    }
    .progress-panel::before {
      content: "";
      position: absolute;
      inset: -40% 45% 40% -25%;
      background: var(--red-soft);
      filter: blur(30px);
      transform: rotate(20deg);
    }
    .progress-ring {
      --progress: 0;
      width: 210px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: conic-gradient(var(--red) calc(var(--progress) * 1%), #202938 0);
      display: grid;
      place-items: center;
      position: relative;
      box-shadow: 0 0 42px rgba(255, 59, 79, .16);
    }
    .progress-ring::after {
      content: "";
      position: absolute;
      width: 164px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: #0c121b;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .04);
    }
    .progress-value { position: relative; z-index: 1; text-align: center; }
    .progress-value strong { display: block; font-size: 48px; line-height: 1; letter-spacing: -.05em; }
    .progress-value span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .12em; }

    section { padding: 34px 0; scroll-margin-top: 78px; }
    .section-head { display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-bottom: 20px; }
    .section-kicker { color: var(--red); text-transform: uppercase; letter-spacing: .14em; font-size: 11px; font-weight: 900; }
    h2 { margin: 4px 0 0; font-size: clamp(28px, 4vw, 42px); letter-spacing: -.035em; }
    .section-note { max-width: 520px; color: var(--muted); font-size: 14px; margin: 0; }

    .grid { display: grid; gap: 16px; }
    .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .two-col { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .card {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: linear-gradient(150deg, rgba(17, 25, 37, .86), rgba(11, 16, 24, .92));
      box-shadow: 0 14px 38px rgba(0, 0, 0, .18);
      padding: 20px;
      min-width: 0;
    }
    .kpi-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
    .kpi-value { font-size: clamp(26px, 4vw, 38px); font-weight: 850; letter-spacing: -.04em; margin-top: 8px; line-height: 1.05; }
    .kpi-foot { color: var(--muted); font-size: 12px; margin-top: 8px; }
    .accent { color: var(--cyan); }
    .positive { color: var(--green); }
    .danger { color: var(--red); }

    .phase-list { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .phase {
      position: relative;
      padding: 16px;
      min-height: 148px;
      border: 1px solid var(--line);
      border-radius: 15px;
      background: rgba(13, 18, 27, .75);
      overflow: hidden;
    }
    .phase.completed { border-color: rgba(72, 229, 155, .24); }
    .phase.in-progress { border-color: rgba(56, 189, 248, .34); }
    .phase.planned { opacity: .76; }
    .phase-no { color: var(--muted); font-size: 11px; letter-spacing: .1em; text-transform: uppercase; }
    .phase h3 { font-size: 16px; margin: 8px 0 7px; letter-spacing: -.01em; }
    .phase p { color: var(--muted); font-size: 12px; margin: 0 0 24px; }
    .phase-bottom { position: absolute; left: 16px; right: 16px; bottom: 13px; display: flex; align-items: center; justify-content: space-between; }
    .phase-status { font-size: 11px; font-weight: 800; }
    .completed .phase-status { color: var(--green); }
    .in-progress .phase-status { color: var(--cyan); }
    .phase-weight { color: var(--muted); font-size: 11px; }

    .integrity-row { display: flex; flex-wrap: wrap; gap: 10px; }
    .integrity-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid rgba(72, 229, 155, .22);
      background: rgba(72, 229, 155, .06);
      color: var(--green);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 750;
    }

    .card-title { display: flex; justify-content: space-between; align-items: start; gap: 16px; margin-bottom: 18px; }
    .card-title h3 { margin: 0; font-size: 18px; }
    .card-title p { color: var(--muted); font-size: 12px; margin: 4px 0 0; }
    .pill { border-radius: 999px; padding: 5px 9px; color: var(--cyan); background: var(--cyan-soft); font-size: 11px; white-space: nowrap; }

    .compare-row { margin: 18px 0; }
    .compare-head { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; margin-bottom: 7px; }
    .compare-head span:last-child { color: var(--muted); font-variant-numeric: tabular-nums; }
    .track { height: 11px; background: #202938; border-radius: 999px; overflow: hidden; }
    .track > div { height: 100%; border-radius: inherit; min-width: 3px; }
    .baseline-bar { background: #69788f; }
    .winner-bar { background: linear-gradient(90deg, var(--red), #ff7a65); box-shadow: 0 0 18px rgba(255, 59, 79, .28); }
    .gain { margin-top: 16px; padding: 13px; border-radius: 12px; background: rgba(72, 229, 155, .07); color: var(--green); font-weight: 750; font-size: 13px; }

    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th { color: var(--muted); text-align: left; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; font-size: 10px; background: rgba(255, 255, 255, .025); }
    th, td { padding: 11px 12px; border-bottom: 1px solid rgba(255, 255, 255, .055); white-space: nowrap; }
    tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: rgba(255, 255, 255, .025); }
    .winner-row { background: rgba(255, 59, 79, .075); }
    .status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
    .status-dot.pass { background: var(--green); }
    .status-dot.fail { background: #657184; }

    .control {
      color: var(--text);
      background: #0a1018;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
      max-width: 100%;
    }
    .chart { width: 100%; min-height: 320px; position: relative; }
    .chart svg { display: block; width: 100%; height: auto; overflow: visible; }
    .chart-empty { min-height: 250px; display: grid; place-items: center; color: var(--muted); }
    .legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 10px; color: var(--muted); font-size: 12px; }
    .legend span { display: inline-flex; align-items: center; gap: 7px; }
    .swatch { width: 18px; height: 3px; border-radius: 2px; }
    .chart-meta { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--muted); font-size: 12px; margin: 10px 0 2px; }
    .chart-meta strong { color: var(--text); }

    .horizon-grid { display: grid; gap: 12px; }
    .horizon-item { display: grid; grid-template-columns: 150px 1fr 74px; gap: 12px; align-items: center; font-size: 12px; }
    .horizon-track { height: 9px; background: #202938; border-radius: 999px; overflow: hidden; }
    .horizon-track > div { height: 100%; background: linear-gradient(90deg, var(--cyan), #657cff); border-radius: inherit; }
    .horizon-value { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }

    .disclosure {
      border-left: 3px solid var(--amber);
      background: rgba(255, 200, 87, .055);
      padding: 15px 17px;
      border-radius: 0 12px 12px 0;
      color: #d8caa6;
      font-size: 13px;
    }
    .disclosure strong { color: var(--amber); }
    footer { padding: 58px 0 70px; color: var(--muted); font-size: 12px; border-top: 1px solid rgba(255, 255, 255, .055); margin-top: 38px; }
    .footer-inner { display: flex; justify-content: space-between; gap: 20px; flex-wrap: wrap; }

    @media (max-width: 980px) {
      .hero { grid-template-columns: 1fr; }
      .progress-panel { min-height: 270px; }
      .kpi-grid, .phase-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .two-col { grid-template-columns: 1fr; }
      nav { display: none; }
    }
    @media (max-width: 580px) {
      .shell { width: min(100% - 20px, 1240px); }
      .hero { padding-top: 48px; }
      .kpi-grid, .phase-list { grid-template-columns: 1fr; }
      .section-head { align-items: start; flex-direction: column; }
      .horizon-item { grid-template-columns: 118px 1fr; }
      .horizon-value { grid-column: 2; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="shell topbar-inner">
      <a class="brand" href="#overview"><span class="brand-mark">F1</span><span>Strategy Optimizer</span></a>
      <nav>
        <a href="#roadmap">Roadmap</a>
        <a href="#model">Model</a>
        <a href="#simulation">Simulation</a>
        <a href="#optimizer">Optimizer</a>
        <a href="#evidence">Evidence</a>
      </nav>
    </div>
  </header>

  <main class="shell">
    <section class="hero" id="overview">
      <div>
        <span class="eyebrow"><span class="dot"></span> Verified development evidence</span>
        <h1>Not a mock-up.<br>Actual model evidence.</h1>
        <p class="hero-copy">A read-only view of the trained predictor, deterministic race-strategy replays and audited pit-now versus stay-out decisions completed through Phase 8.</p>
        <div class="hero-meta">
          <span><strong id="hero-phases"></strong> phases completed</span>
          <span><strong id="hero-holdout"></strong> protected 2025 rows used</span>
          <span>Generated <strong id="generated-at"></strong></span>
        </div>
      </div>
      <div class="progress-panel">
        <div class="progress-ring" id="progress-ring">
          <div class="progress-value"><strong id="progress-value"></strong><span>overall complete</span></div>
        </div>
      </div>
    </section>

    <section id="evidence">
      <div class="section-head">
        <div><div class="section-kicker">Integrity first</div><h2>Evidence status</h2></div>
        <p class="section-note">The page is generated only after report hashes, schemas, provenance and exact model predictions pass verification.</p>
      </div>
      <div class="integrity-row" id="integrity-row"></div>
    </section>

    <section id="roadmap">
      <div class="section-head">
        <div><div class="section-kicker">Project status</div><h2>Roadmap</h2></div>
        <p class="section-note">Progress is calculated directly from canonical phase weights and documented within-phase milestones.</p>
      </div>
      <div class="phase-list" id="phase-list"></div>
    </section>

    <section id="model">
      <div class="section-head">
        <div><div class="section-kicker">Phase 6</div><h2>Lap-time predictor</h2></div>
        <p class="section-note">Whole-race temporal validation, training-only preprocessing and a protected 2025 holdout.</p>
      </div>
      <div class="grid kpi-grid" id="model-kpis"></div>

      <div class="grid two-col" style="margin-top:16px">
        <article class="card">
          <div class="card-title">
            <div><h3>Winner versus frozen baseline</h3><p>Comparable-row MAE · lower is better</p></div>
            <span class="pill" id="winner-pill"></span>
          </div>
          <div id="model-comparison"></div>
        </article>
        <article class="card">
          <div class="card-title">
            <div><h3>Winning configuration</h3><p>Final model refitted on the complete development population</p></div>
            <span class="pill" id="device-pill"></span>
          </div>
          <div class="table-wrap"><table><tbody id="winner-parameters"></tbody></table></div>
        </article>
      </div>

      <article class="card" style="margin-top:16px">
        <div class="card-title">
          <div><h3>Candidate leaderboard</h3><p>Top candidate/formulation pairs under the frozen selection contract</p></div>
          <span class="pill" id="candidate-count"></span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Candidate</th><th>Family</th><th>Formulation</th><th>Comparable MAE</th><th>Coverage</th><th>Contract</th></tr></thead>
            <tbody id="leaderboard-body"></tbody>
          </table>
        </div>
      </article>

      <div class="grid two-col" style="margin-top:16px">
        <article class="card">
          <div class="card-title">
            <div><h3>Tyre-age behaviour</h3><p>Observed and predicted mean lap-time change</p></div>
            <select class="control" id="compound-select" aria-label="Select tyre compound"></select>
          </div>
          <div class="chart" id="degradation-chart"></div>
          <div class="legend"><span><i class="swatch" style="background:#30d5f2"></i>Observed</span><span><i class="swatch" style="background:#ff3b4f"></i>Predicted</span></div>
        </article>
        <article class="card">
          <div class="card-title"><div><h3>Hardest model events</h3><p>Selected-model lap MAE by event</p></div></div>
          <div class="table-wrap"><table><thead><tr><th>Event</th><th>Rows</th><th>MAE</th></tr></thead><tbody id="model-events"></tbody></table></div>
        </article>
      </div>
    </section>

    <section id="simulation">
      <div class="section-head">
        <div><div class="section-kicker">Phase 7</div><h2>Observed-strategy replay</h2></div>
        <p class="section-note">The stored Phase 6 model advances real race suffixes lap by lap with deterministic tyre, stint and pit-stop transitions.</p>
      </div>
      <div class="grid kpi-grid" id="simulation-kpis"></div>

      <div class="grid two-col" style="margin-top:16px">
        <article class="card">
          <div class="card-title"><div><h3>Remaining-time error by horizon</h3><p>Complete trajectory MAE · lower is better</p></div></div>
          <div class="horizon-grid" id="horizon-chart"></div>
        </article>
        <article class="card">
          <div class="card-title"><div><h3>Hardest replay events</h3><p>Complete remaining-race-time MAE</p></div></div>
          <div class="table-wrap"><table><thead><tr><th>Event</th><th>Replays</th><th>MAE</th><th>Bias</th></tr></thead><tbody id="simulation-events"></tbody></table></div>
        </article>
      </div>

      <article class="card" style="margin-top:16px">
        <div class="card-title">
          <div><h3>Replay explorer</h3><p>Predicted versus observed total lap time across one complete replay</p></div>
          <select class="control" id="replay-select" aria-label="Select race replay"></select>
        </div>
        <div class="chart-meta" id="replay-meta"></div>
        <div class="chart" id="trajectory-chart"></div>
        <div class="legend"><span><i class="swatch" style="background:#30d5f2"></i>Observed</span><span><i class="swatch" style="background:#ff3b4f"></i>Predicted</span><span><i class="swatch" style="height:9px;width:9px;background:#ffc857;border-radius:50%"></i>Pit after lap</span></div>
      </article>

      <div class="disclosure" style="margin-top:16px">
        <strong>Scope boundary:</strong> replay error is descriptive development evidence. It supplies the declared Phase 8 action-time robustness margin, not a calibrated probability or confidence interval.
      </div>
    </section>

    <section id="optimizer">
      <div class="section-head">
        <div><div class="section-kicker">Phase 8</div><h2>Pit-decision optimizer</h2></div>
        <p class="section-note">Paired historical pit windows compare PIT_NOW with a one-lap STAY_OUT deferral across a 3×3 tyre-age and pit-loss sensitivity grid.</p>
      </div>
      <div class="grid kpi-grid" id="optimizer-kpis"></div>

      <div class="grid two-col" style="margin-top:16px">
        <article class="card">
          <div class="card-title"><div><h3>Stable recommendation distribution</h3><p>Conservative interval after sensitivity and replay-error margin</p></div></div>
          <div class="horizon-grid" id="optimizer-distribution"></div>
        </article>
        <article class="card">
          <div class="card-title"><div><h3>Historical action diagnostic</h3><p>Observed alignment is descriptive, never decision accuracy</p></div></div>
          <div class="table-wrap"><table><tbody id="optimizer-diagnostic"></tbody></table></div>
        </article>
      </div>

      <article class="card" style="margin-top:16px">
        <div class="card-title"><div><h3>Event-level optimizer evidence</h3><p>Development-only decision counts and stable outcomes</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>Event</th><th>Decisions</th><th>Pit now</th><th>Stay out</th><th>No clear advantage</th><th>Observed alignment</th></tr></thead><tbody id="optimizer-events"></tbody></table></div>
      </article>

      <div class="disclosure" style="margin-top:16px">
        <strong>Interpretation:</strong> an observed historical action is not optimal-strategy ground truth. Recommendations are reported only when every declared sensitivity case and the widened action-time interval agree; otherwise the result is NO_CLEAR_ADVANTAGE.
      </div>
    </section>
  </main>

  <footer>
    <div class="shell footer-inner">
      <span>F1 Race Strategy Optimizer · read-only development viewer</span>
      <span id="footer-runs"></span>
    </div>
  </footer>

  <script>
    const DATA = __VIEWER_DATA__;
    const $ = (id) => document.getElementById(id);
    const fmtInt = (value) => new Intl.NumberFormat("en-US").format(value);
    const fmtSec = (value, digits = 3) => `${Number(value).toFixed(digits)} s`;
    const pct = (value, digits = 2) => `${Number(value).toFixed(digits)}%`;
    const horizonLabel = (value) => ({
      SHORT_1_TO_10_LAPS: "Short · 1–10 laps",
      MEDIUM_11_TO_25_LAPS: "Medium · 11–25 laps",
      LONG_26_PLUS_LAPS: "Long · 26+ laps"
    })[value] || value.replaceAll("_", " ");
    const formulationLabel = (value) => value.replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (m) => m.toUpperCase());

    function node(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    }

    function svgNode(tag, attributes = {}) {
      const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
      return element;
    }

    function renderOverview() {
      const project = DATA.project;
      $("progress-value").textContent = `${project.progress_percent}%`;
      $("progress-ring").style.setProperty("--progress", project.progress_percent);
      $("hero-phases").textContent = `${project.completed_phases}/${project.total_phases}`;
      $("hero-holdout").textContent = DATA.integrity.protected_2025_rows;
      $("generated-at").textContent = new Date(DATA.generated_at).toLocaleString();
      $("footer-runs").textContent = `${DATA.model.run_id} · ${DATA.simulation.run_id} · ${DATA.optimizer.run_id}`;
    }

    function renderIntegrity() {
      const labels = [
        ["Model evaluation report", DATA.integrity.model_report],
        ["Fitted model + prediction fingerprint", DATA.integrity.model_artifact],
        ["Simulation report", DATA.integrity.simulation_report],
        ["Optimizer report", DATA.integrity.optimizer_report],
        ["Protected 2025 rows", String(DATA.integrity.protected_2025_rows)]
      ];
      const root = $("integrity-row");
      labels.forEach(([label, value]) => {
        const badge = node("span", "integrity-badge");
        badge.append(node("span", "dot"), document.createTextNode(`${label}: ${value}`));
        root.append(badge);
      });
    }

    function renderPhases() {
      const root = $("phase-list");
      DATA.project.phases.forEach((phase) => {
        const card = node("article", `phase ${phase.status_class}`);
        card.append(node("div", "phase-no", `Phase ${phase.number}`));
        card.append(node("h3", "", phase.name));
        card.append(node("p", "", phase.result));
        const bottom = node("div", "phase-bottom");
        bottom.append(node("span", "phase-status", phase.status));
        bottom.append(node("span", "phase-weight", `${phase.weight_percent}% of project`));
        card.append(bottom);
        root.append(card);
      });
    }

    function kpi(label, value, foot, className = "") {
      const card = node("article", "card");
      card.append(node("div", "kpi-label", label));
      card.append(node("div", `kpi-value ${className}`, value));
      card.append(node("div", "kpi-foot", foot));
      return card;
    }

    function renderModel() {
      const model = DATA.model;
      const winner = model.winner;
      const kpis = $("model-kpis");
      kpis.append(
        kpi("Winning model", winner.candidate_id, `${winner.family} · ${formulationLabel(winner.formulation)}`, "accent"),
        kpi("Comparable MAE", fmtSec(winner.mae_seconds), "Held-out whole-race folds"),
        kpi("Baseline improvement", pct(winner.relative_improvement_percent), `Baseline ${fmtSec(winner.baseline_mae_seconds)}`, "positive"),
        kpi("Training targets", fmtInt(model.primary_targets), `${model.training_sessions}/${model.development_sessions} sessions contributed`)
      );
      $("winner-pill").textContent = winner.candidate_id;
      $("device-pill").textContent = model.execution_device.toUpperCase();
      $("candidate-count").textContent = `${model.candidate_parameter_sets} candidates · ${model.candidate_formulation_runs} formulation runs`;

      const comparison = $("model-comparison");
      const max = Math.max(winner.baseline_mae_seconds, winner.mae_seconds);
      [["Frozen baseline", winner.baseline_mae_seconds, "baseline-bar"], ["Selected XGBoost", winner.mae_seconds, "winner-bar"]].forEach(([label, value, cls]) => {
        const row = node("div", "compare-row");
        const head = node("div", "compare-head");
        head.append(node("span", "", label), node("span", "", fmtSec(value, 6)));
        const track = node("div", "track");
        const bar = node("div", cls);
        bar.style.width = `${value / max * 100}%`;
        track.append(bar);
        row.append(head, track);
        comparison.append(row);
      });
      comparison.append(node("div", "gain", `${pct(winner.relative_improvement_percent)} less error than the frozen comparable baseline`));

      const parameterBody = $("winner-parameters");
      const identity = [
        ["Formulation", formulationLabel(winner.formulation)],
        ["Coverage", pct(winner.coverage_rate * 100, 4)],
        ["All-row MAE", fmtSec(winner.all_row_mae_seconds, 6)],
        ["Without driver/team MAE", fmtSec(winner.ablated_mae_seconds, 6)]
      ];
      Object.entries(winner.parameters).forEach(([key, value]) => identity.push([key.replaceAll("_", " "), String(value)]));
      identity.forEach(([key, value]) => {
        const row = node("tr");
        row.append(node("td", "kpi-label", key), node("td", "", value));
        parameterBody.append(row);
      });

      const leaderboard = $("leaderboard-body");
      model.leaderboard.forEach((entry) => {
        const row = node("tr", entry.selected ? "winner-row" : "");
        const status = node("td");
        status.append(node("span", `status-dot ${entry.meets_selection_contract ? "pass" : "fail"}`), document.createTextNode(entry.meets_selection_contract ? "Pass" : "No"));
        row.append(
          node("td", "", entry.selected ? `${entry.candidate_id} ★` : entry.candidate_id),
          node("td", "", entry.model_family),
          node("td", "", formulationLabel(entry.formulation)),
          node("td", "", fmtSec(entry.full_common_mean_absolute_error_seconds, 6)),
          node("td", "", pct(entry.coverage_rate * 100, 2)),
          status
        );
        leaderboard.append(row);
      });

      const eventBody = $("model-events");
      model.event_slices.forEach((event) => {
        const row = node("tr");
        row.append(node("td", "", event.event_name), node("td", "", fmtInt(event.rows)), node("td", "", fmtSec(event.mean_absolute_error_seconds)));
        eventBody.append(row);
      });

      const compounds = [...new Set(model.degradation.map((item) => item.compound))];
      const select = $("compound-select");
      compounds.forEach((compound) => {
        const option = node("option", "", compound);
        option.value = compound;
        select.append(option);
      });
      select.addEventListener("change", () => renderDegradation(select.value));
      if (compounds.length) renderDegradation(compounds[0]);
    }

    function renderDegradation(compound) {
      const points = DATA.model.degradation.filter((item) => item.compound === compound);
      drawLineChart($("degradation-chart"), points, {
        x: (item) => item.mean_tyre_age_laps,
        xLabel: (value) => `${Math.round(value)} laps`,
        yLabel: (value) => `${value.toFixed(2)}s`,
        includeZero: true,
        series: [
          {name: "Observed", color: "#30d5f2", value: (item) => item.mean_observed_lap_time_delta_seconds},
          {name: "Predicted", color: "#ff3b4f", value: (item) => item.mean_predicted_lap_time_delta_seconds}
        ]
      });
    }

    function renderSimulation() {
      const simulation = DATA.simulation;
      const kpis = $("simulation-kpis");
      kpis.append(
        kpi("Observed replays", fmtInt(simulation.replays), `${simulation.replay_sessions}/${simulation.audited_sessions} races contributed`, "accent"),
        kpi("Aligned laps", fmtInt(simulation.trajectory_laps), "Complete deterministic transitions"),
        kpi("Pooled lap MAE", fmtSec(simulation.lap_mae_seconds), "Recursive replay error"),
        kpi("Remaining-time MAE", fmtSec(simulation.remaining_mae_seconds), "Complete replay trajectories")
      );

      const horizons = simulation.horizon_metrics;
      const maximum = Math.max(...horizons.map((item) => item.mean_absolute_error_seconds), 1);
      const horizonRoot = $("horizon-chart");
      horizons.forEach((item) => {
        const row = node("div", "horizon-item");
        row.append(node("span", "", horizonLabel(item.value)));
        const track = node("div", "horizon-track");
        const bar = node("div");
        bar.style.width = `${item.mean_absolute_error_seconds / maximum * 100}%`;
        track.append(bar);
        row.append(track, node("span", "horizon-value", fmtSec(item.mean_absolute_error_seconds)));
        horizonRoot.append(row);
      });

      const eventBody = $("simulation-events");
      simulation.event_metrics.slice(0, 12).forEach((event) => {
        const row = node("tr");
        row.append(
          node("td", "", event.value),
          node("td", "", fmtInt(event.replays)),
          node("td", "", fmtSec(event.mean_absolute_error_seconds)),
          node("td", "", `${event.mean_signed_error_seconds >= 0 ? "+" : ""}${Number(event.mean_signed_error_seconds).toFixed(3)} s`)
        );
        eventBody.append(row);
      });

      const select = $("replay-select");
      simulation.replay_options.forEach((replay) => {
        const option = node("option", "", `${replay.season} ${replay.event_name} · ${replay.driver} · ${replay.remaining_laps} laps`);
        option.value = replay.replay_id;
        select.append(option);
      });
      select.addEventListener("change", () => renderTrajectory(select.value));
      const preferred = [...simulation.replay_options].sort((a, b) => b.remaining_laps - a.remaining_laps)[0];
      if (preferred) {
        select.value = preferred.replay_id;
        renderTrajectory(preferred.replay_id);
      }
    }

    function renderTrajectory(replayId) {
      const replay = DATA.simulation.replay_options.find((item) => item.replay_id === replayId);
      const points = DATA.simulation.trajectories[replayId] || [];
      const meta = $("replay-meta");
      meta.replaceChildren();
      if (!replay) return;
      [["Event", `${replay.season} ${replay.event_name}`], ["Driver", `${replay.driver} · ${replay.team}`], ["Horizon", horizonLabel(replay.horizon)], ["Remaining-time error", fmtSec(replay.absolute_remaining_time_error_seconds)]].forEach(([label, value]) => {
        const item = node("span");
        item.append(node("strong", "", `${label}: `), document.createTextNode(value));
        meta.append(item);
      });
      drawLineChart($("trajectory-chart"), points, {
        x: (item) => item.lap_number,
        xLabel: (value) => `Lap ${Math.round(value)}`,
        yLabel: (value) => `${value.toFixed(1)}s`,
        includeZero: false,
        pit: (item) => item.pit_stop_after_lap,
        series: [
          {name: "Observed", color: "#30d5f2", value: (item) => item.observed_total_lap_time_seconds},
          {name: "Predicted", color: "#ff3b4f", value: (item) => item.predicted_total_lap_time_seconds}
        ]
      });
    }

    function renderOptimizer() {
      const optimizer = DATA.optimizer;
      const alignment = optimizer.observed_action_alignment_rate;
      $("optimizer-kpis").append(
        kpi("Historical decisions", fmtInt(optimizer.decisions), `${optimizer.decision_sessions}/${optimizer.audited_sessions} races contributed`, "accent"),
        kpi("Sensitivity cases", fmtInt(optimizer.sensitivity_cases), `${optimizer.cases_per_decision} cases per decision`),
        kpi("Stable recommendations", fmtInt(optimizer.stable_pit_now + optimizer.stable_stay_out), `${optimizer.no_clear_advantage} no-clear-advantage outcomes`),
        kpi("Action-time margin", fmtSec(optimizer.action_time_margin_seconds), "Phase 7 remaining-time MAE per action")
      );

      const outcomes = [
        ["PIT_NOW", optimizer.stable_pit_now],
        ["STAY_OUT", optimizer.stable_stay_out],
        ["NO_CLEAR_ADVANTAGE", optimizer.no_clear_advantage]
      ];
      const maximum = Math.max(...outcomes.map((item) => item[1]), 1);
      const distribution = $("optimizer-distribution");
      outcomes.forEach(([label, value]) => {
        const row = node("div", "horizon-item");
        row.append(node("span", "", label.replaceAll("_", " ")));
        const track = node("div", "horizon-track");
        const bar = node("div");
        bar.style.width = `${value / maximum * 100}%`;
        track.append(bar);
        row.append(track, node("span", "horizon-value", fmtInt(value)));
        distribution.append(row);
      });

      const diagnostic = [
        ["Observed PIT_NOW", fmtInt(optimizer.observed_pit_now)],
        ["Observed STAY_OUT", fmtInt(optimizer.observed_stay_out)],
        ["Comparable stable actions", fmtInt(optimizer.comparable_observed_actions)],
        ["Aligned observed actions", fmtInt(optimizer.aligned_observed_actions)],
        ["Descriptive alignment rate", alignment === null ? "n/a" : pct(alignment * 100)]
      ];
      const diagnosticBody = $("optimizer-diagnostic");
      diagnostic.forEach(([label, value]) => {
        const row = node("tr");
        row.append(node("td", "kpi-label", label), node("td", "", value));
        diagnosticBody.append(row);
      });

      const eventBody = $("optimizer-events");
      optimizer.event_summaries.forEach((event) => {
        const row = node("tr");
        row.append(
          node("td", "", event.value),
          node("td", "", fmtInt(event.decisions)),
          node("td", "", fmtInt(event.stable_pit_now)),
          node("td", "", fmtInt(event.stable_stay_out)),
          node("td", "", fmtInt(event.no_clear_advantage)),
          node("td", "", event.observed_action_alignment_rate === null ? "n/a" : pct(event.observed_action_alignment_rate * 100))
        );
        eventBody.append(row);
      });
    }

    function drawLineChart(root, points, options) {
      root.replaceChildren();
      if (!points.length) {
        root.append(node("div", "chart-empty", "No evidence available for this selection."));
        return;
      }
      const width = 900, height = 340;
      const margin = {top: 22, right: 24, bottom: 48, left: 68};
      const chartWidth = width - margin.left - margin.right;
      const chartHeight = height - margin.top - margin.bottom;
      const xValues = points.map(options.x);
      const yValues = options.series.flatMap((series) => points.map(series.value));
      let xMin = Math.min(...xValues), xMax = Math.max(...xValues);
      let yMin = Math.min(...yValues), yMax = Math.max(...yValues);
      if (options.includeZero) { yMin = Math.min(0, yMin); yMax = Math.max(0, yMax); }
      if (xMin === xMax) { xMin -= 1; xMax += 1; }
      if (yMin === yMax) { yMin -= 1; yMax += 1; }
      const yPad = (yMax - yMin) * .12;
      yMin -= yPad; yMax += yPad;
      const sx = (value) => margin.left + (value - xMin) / (xMax - xMin) * chartWidth;
      const sy = (value) => margin.top + (yMax - value) / (yMax - yMin) * chartHeight;
      const svg = svgNode("svg", {viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Evidence line chart"});

      for (let i = 0; i <= 4; i++) {
        const value = yMin + (yMax - yMin) * i / 4;
        const y = sy(value);
        svg.append(svgNode("line", {x1: margin.left, x2: width - margin.right, y1: y, y2: y, stroke: "#243043", "stroke-width": 1}));
        const label = svgNode("text", {x: margin.left - 10, y: y + 4, fill: "#8e9aac", "font-size": 11, "text-anchor": "end"});
        label.textContent = options.yLabel(value);
        svg.append(label);
      }
      const xTicks = Math.min(5, points.length - 1);
      for (let i = 0; i <= xTicks; i++) {
        const value = xMin + (xMax - xMin) * (xTicks ? i / xTicks : 0);
        const label = svgNode("text", {x: sx(value), y: height - 17, fill: "#8e9aac", "font-size": 11, "text-anchor": "middle"});
        label.textContent = options.xLabel(value);
        svg.append(label);
      }

      if (options.pit) {
        points.filter(options.pit).forEach((point) => {
          const x = sx(options.x(point));
          svg.append(svgNode("line", {x1: x, x2: x, y1: margin.top, y2: height - margin.bottom, stroke: "#ffc857", "stroke-width": 1.5, "stroke-dasharray": "5 5", opacity: .8}));
          svg.append(svgNode("circle", {cx: x, cy: margin.top + 5, r: 4, fill: "#ffc857"}));
        });
      }

      options.series.forEach((series) => {
        const path = points.map((point, index) => `${index ? "L" : "M"}${sx(options.x(point)).toFixed(2)},${sy(series.value(point)).toFixed(2)}`).join(" ");
        svg.append(svgNode("path", {d: path, fill: "none", stroke: series.color, "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round"}));
        points.forEach((point) => {
          const circle = svgNode("circle", {cx: sx(options.x(point)), cy: sy(series.value(point)), r: 3.5, fill: series.color, stroke: "#0d121b", "stroke-width": 1.5});
          const title = svgNode("title");
          title.textContent = `${series.name} · ${options.xLabel(options.x(point))}: ${options.yLabel(series.value(point))}`;
          circle.append(title);
          svg.append(circle);
        });
      });
      root.append(svg);
    }

    renderOverview();
    renderIntegrity();
    renderPhases();
    renderModel();
    renderSimulation();
    renderOptimizer();
  </script>
</body>
</html>
'''
