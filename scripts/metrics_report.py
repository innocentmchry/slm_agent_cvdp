#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0

"""
Build a standalone HTML report of the agent metrics recorded in one benchmark run.

The agent writes rundir/agent_metrics.json for every problem it works on (see
main_agent/SLM_agent/utils/metrics.py). This script collects those files from a
run directory (the -p prefix given to run_benchmark.py), joins them with the
pass/fail results in raw_result.json and writes a single self-contained HTML page.

Usage:
    python scripts/metrics_report.py gpt-4o-mini
    python scripts/metrics_report.py gpt-4o-mini -o report.html
    python scripts/metrics_report.py my_run --price-input 0.15 --price-cached 0.075 --price-output 0.60
"""

import argparse
import json
import sys
from pathlib import Path

METRICS_FILE = "agent_metrics.json"
METRICS_GLOB = f"*/harness/*/rundir/{METRICS_FILE}"

# USD per 1M tokens: (input, cached input, output). Matched by model name prefix,
# longest prefix first. Override with the --price-* options.
PRICES = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"WARNING: could not read {path}: {e}", file=sys.stderr)
        return None


def problem_id(run_dir, metrics_path):
    """<run_dir>/<name>/harness/<n>/rundir/agent_metrics.json -> <name>_<nnnn>"""
    parts = metrics_path.relative_to(run_dir).parts
    name, number = parts[0], parts[2]
    return f"{name}_{int(number):04d}" if number.isdigit() else f"{name}_{number}"


def price_for(model, override):
    if override is not None:
        return override
    for prefix in sorted(PRICES, key=len, reverse=True):
        if model and model.startswith(prefix):
            return PRICES[prefix]
    return None


def call_cost(call, default_model, override):
    """Cost of one call in USD, or None when tokens or prices are unknown."""
    if call.get("input_tokens") is None or call.get("output_tokens") is None:
        return None
    price = price_for(call.get("response_model") or default_model, override)
    if price is None:
        return None
    cached = call.get("cached_input_tokens") or 0
    fresh = call["input_tokens"] - cached
    return (fresh * price[0] + cached * price[1] + call["output_tokens"] * price[2]) / 1e6


def harness_passed(result):
    tests = result.get("tests") or []
    if not tests:
        return False
    return result.get("errors", 0) == 0 and all(test.get("result") == 0 for test in tests)


def build_rows(run_dir, price_override):
    raw_result = load_json(run_dir / "raw_result.json") if (run_dir / "raw_result.json").exists() else None
    results = raw_result or {}

    metrics = {}
    for path in sorted(run_dir.glob(METRICS_GLOB)):
        data = load_json(path)
        if data is not None:
            metrics[problem_id(run_dir, path)] = data

    rows = []
    for pid in sorted(set(results) | set(metrics)):
        result = results.get(pid)
        data = metrics.get(pid)
        row = {
            "id": pid,
            "category": result.get("category") if result else None,
            "difficulty": result.get("difficulty") if result else None,
            "passed": harness_passed(result) if result else None,
            "agent_status": result.get("agent_status") if result else None,
            "agent_time_s": result.get("agent_execution") if result else None,
            "has_metrics": data is not None,
        }
        if data is not None:
            totals = data.get("totals") or {}
            calls = data.get("calls") or []
            costs = [call_cost(call, data.get("model"), price_override) for call in calls]
            for call, cost in zip(calls, costs):
                call["cost"] = cost
            known_costs = [cost for cost in costs if cost is not None]
            # GPU readings exist only for local models served by scripts/slm_server.py
            energies = [call["gpu_energy_j"] for call in calls if call.get("gpu_energy_j") is not None]
            peaks = [call["gpu_peak_memory_mb"] for call in calls if call.get("gpu_peak_memory_mb") is not None]
            row.update({
                "model": data.get("model"),
                "agent_success": data.get("agent_success"),
                "finished": data.get("finished_at") is not None,
                "iterations": totals.get("iterations"),
                "llm_calls": totals.get("llm_calls"),
                "failed_llm_calls": totals.get("failed_llm_calls"),
                "input_tokens": totals.get("input_tokens"),
                "output_tokens": totals.get("output_tokens"),
                "total_tokens": totals.get("total_tokens"),
                "cached_input_tokens": totals.get("cached_input_tokens"),
                "llm_latency_ms": totals.get("llm_latency_ms"),
                "test_time_ms": totals.get("test_time_ms"),
                "cost": sum(known_costs) if known_costs else None,
                "gpu_energy_j": sum(energies) if energies else None,
                "gpu_peak_memory_mb": max(peaks) if peaks else None,
                "truncated": any(call.get("finish_reason") in ("length", "max_tokens") for call in calls),
                "calls": calls,
                "iteration_log": data.get("iterations") or [],
            })
        rows.append(row)
    return rows, raw_result is not None


def build_payload(run_dir, price_override):
    rows, has_results = build_rows(run_dir, price_override)
    report = load_json(run_dir / "report.json") if (run_dir / "report.json").exists() else None
    metadata = (report or {}).get("metadata") or {}
    models = sorted({row["model"] for row in rows if row.get("model")})
    priced = sorted({model for model in models if price_for(model, price_override)})
    prices = {model: price_for(model, price_override) for model in priced}
    return {
        "run_dir": str(run_dir),
        "models": models,
        "agent": metadata.get("model_agent"),
        "dataset": metadata.get("dataset_path"),
        "timestamp": metadata.get("timestamp"),
        "has_results": has_results,
        "prices": prices,
        "rows": rows,
    }


def render(payload):
    # "</" must not appear inside the inline <script> block
    data = json.dumps(payload).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", data)


def main():
    parser = argparse.ArgumentParser(description="Build an HTML report of agent metrics for one benchmark run.")
    parser.add_argument("run_dir", help="Run directory (the -p prefix given to run_benchmark.py)")
    parser.add_argument("-o", "--output", help="Output HTML file (default: <run_dir>/metrics_report.html)")
    parser.add_argument("--price-input", type=float, help="USD per 1M input tokens (overrides the built-in price table)")
    parser.add_argument("--price-cached", type=float, help="USD per 1M cached input tokens (default: same as --price-input)")
    parser.add_argument("--price-output", type=float, help="USD per 1M output tokens")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        parser.error(f"{run_dir} is not a directory")

    price_override = None
    if args.price_input is not None or args.price_output is not None:
        if args.price_input is None or args.price_output is None:
            parser.error("--price-input and --price-output must be given together")
        cached = args.price_cached if args.price_cached is not None else args.price_input
        price_override = (args.price_input, cached, args.price_output)

    payload = build_payload(run_dir, price_override)
    rows = payload["rows"]
    with_metrics = sum(1 for row in rows if row["has_metrics"])

    if not rows:
        print(f"No results or {METRICS_FILE} files found in {run_dir}", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else run_dir / "metrics_report.html"
    output.write_text(render(payload), encoding="utf-8")

    print(f"Problems: {len(rows)} ({with_metrics} with recorded metrics)")
    if not payload["has_results"]:
        print("raw_result.json not found: pass/fail, category and difficulty are not shown")
    if with_metrics and not payload["prices"]:
        print("No price known for this model: cost is not shown (use --price-input/--price-output)")
    print(f"Report written to {output}")
    return 0


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CVDP run metrics</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --wash: rgba(11,11,11,0.04);
  --series-1: #2a78d6; --good: #0ca30c; --critical: #d03b3b; --warning: #fab219;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --wash: rgba(255,255,255,0.05);
    --series-1: #3987e5;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1400px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 0 0 12px; }
.sub { color: var(--ink-2); margin: 0 0 16px; overflow-wrap: anywhere; }
.note { color: var(--ink-2); border-left: 3px solid var(--warning); padding: 4px 12px; margin: 0 0 16px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 16px; align-items: center; }
.filters input, .filters select { font: inherit; color: var(--ink); background: var(--surface);
  border: 1px solid var(--axis); border-radius: 6px; padding: 6px 8px; }
.filters input { min-width: 220px; }
.filters .count { color: var(--ink-2); margin-left: 4px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 12px; }
.tile .label { color: var(--ink-2); font-size: 13px; }
.tile .value { font-size: 28px; font-weight: 600; line-height: 1.2; margin: 2px 0; }
.tile .detail { color: var(--muted); font-size: 12px; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; margin-bottom: 12px; }
.bar-row { display: grid; grid-template-columns: 96px 1fr; align-items: center; gap: 8px; padding: 5px 0; }
.bar-row .name { color: var(--ink-2); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { display: flex; align-items: center; gap: 2px; min-width: 0; border-left: 1px solid var(--axis); }
.bar { height: 16px; min-width: 2px; background: var(--series-1); border-radius: 0 4px 4px 0; flex: none; }
.bar.seg { border-radius: 0; }
.bar.seg.last { border-radius: 0 4px 4px 0; }
.bar.good { background: var(--good); }
.bar.critical { background: var(--critical); }
.bar:hover, .bar:focus { filter: brightness(1.15); outline: none; }
.bar-label { color: var(--ink-2); font-size: 12px; white-space: nowrap; margin-left: 6px; font-variant-numeric: tabular-nums; }
.legend { display: flex; gap: 16px; color: var(--ink-2); font-size: 12px; margin-bottom: 8px; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; }
.empty { color: var(--muted); padding: 12px 0; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink-2); font-weight: 600; position: sticky; top: 0; background: var(--surface); }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--ink); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.problem { cursor: pointer; }
tr.problem:hover { background: var(--wash); }
tr.detail > td { background: var(--wash); padding: 12px 16px; white-space: normal; }
tr.detail table { width: auto; }
tr.detail th { position: static; background: transparent; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--muted); }
.dot.good { background: var(--good); }
.dot.critical { background: var(--critical); }
.dot.warning { background: var(--warning); }
.muted { color: var(--muted); }
section { margin-bottom: 12px; }
#tooltip { position: fixed; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.18); display: none; z-index: 10; }
#tooltip strong { display: block; font-size: 13px; }
#tooltip span { color: var(--ink-2); }
</style>
</head>
<body>
<main>
  <h1>CVDP run metrics</h1>
  <p class="sub" id="sub"></p>
  <div id="notes"></div>

  <div class="filters">
    <input id="f-search" type="search" placeholder="Search problem ID" aria-label="Search problem ID">
    <select id="f-category" aria-label="Category"></select>
    <select id="f-difficulty" aria-label="Difficulty"></select>
    <select id="f-result" aria-label="Result">
      <option value="">All results</option><option value="pass">Passed</option>
      <option value="fail">Failed</option><option value="unknown">Not evaluated</option>
    </select>
    <span class="count" id="f-count"></span>
  </div>

  <div class="tiles" id="tiles"></div>

  <div class="charts">
    <div class="card"><h2>Pass rate by category</h2><div id="chart-category"></div></div>
    <div class="card"><h2>Problems by iterations used</h2>
      <div class="legend"><span><span class="swatch" style="background:var(--good)"></span>Passed</span>
        <span><span class="swatch" style="background:var(--critical)"></span>Failed</span></div>
      <div id="chart-iterations"></div></div>
  </div>

  <section class="card"><h2>Category &times; difficulty</h2><div class="table-wrap" id="breakdown"></div></section>
  <section class="card"><h2>Problems</h2>
    <p class="sub">Click a row for its per-iteration detail. Tokens, latency and cost are summed over all LLM calls for the problem.</p>
    <div class="table-wrap" id="problems"></div></section>
</main>
<div id="tooltip"></div>

<script>
const DATA = __DATA__;
const ROWS = DATA.rows;
const DIFF_ORDER = ['easy', 'medium', 'hard'];

// ---- helpers
function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'text') node.textContent = v;
    else if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children || []) node.append(child);
  return node;
}
const has = v => v !== null && v !== undefined;
const fmtInt = v => has(v) ? Math.round(v).toLocaleString() : '–';
function fmtCompact(v) {
  if (!has(v)) return '–';
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (v >= 1e4) return (v / 1e3).toFixed(1) + 'K';
  return Math.round(v).toLocaleString();
}
const fmtSec = ms => has(ms) ? (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + ' s' : '–';
const fmtCost = v => has(v) ? '$' + (v >= 1 ? v.toFixed(2) : v.toFixed(4)) : '–';
const fmtEnergy = j => !has(j) ? '–' : j >= 3.6e6 ? (j / 3.6e6).toFixed(2) + ' kWh' : (j / 3600).toFixed(j < 36000 ? 2 : 1) + ' Wh';
const fmtMem = mb => has(mb) ? (mb / 1024).toFixed(1) + ' GB' : '–';
const HAS_GPU = ROWS.some(r => has(r.gpu_energy_j) || has(r.gpu_peak_memory_mb));
const fmtPct = v => has(v) ? (v * 100).toFixed(1) + '%' : '–';
const fmtNum = (v, d) => has(v) ? v.toFixed(d) : '–';
const plural = (n, word) => n + ' ' + word + (n === 1 ? '' : 's');
const sum = (rows, key) => rows.reduce((a, r) => a + (has(r[key]) ? r[key] : 0), 0);
function avg(rows, key) {
  const vals = rows.filter(r => has(r[key])).map(r => r[key]);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}
function passRate(rows) {
  const evaluated = rows.filter(r => r.passed !== null);
  return evaluated.length ? evaluated.filter(r => r.passed).length / evaluated.length : null;
}
function diffRank(d) { const i = DIFF_ORDER.indexOf(d); return i < 0 ? DIFF_ORDER.length : i; }
function status(kind, label) {
  return el('span', {}, [el('span', {class: 'dot ' + kind}), label]);
}
function passCell(passed) {
  if (passed === true) return status('good', '✓ Pass');
  if (passed === false) return status('critical', '✗ Fail');
  return el('span', {class: 'muted', text: '–'});
}
function boolCell(v) {
  if (v === true) return status('good', 'yes');
  if (v === false) return status('critical', 'no');
  return el('span', {class: 'muted', text: '–'});
}

// ---- tooltip
const tooltip = document.getElementById('tooltip');
function showTip(target, value, label) {
  tooltip.replaceChildren(el('strong', {text: value}), el('span', {text: label}));
  tooltip.style.display = 'block';
  const r = target.getBoundingClientRect();
  const t = tooltip.getBoundingClientRect();
  tooltip.style.left = Math.max(8, Math.min(window.innerWidth - t.width - 8, r.left + r.width / 2 - t.width / 2)) + 'px';
  tooltip.style.top = Math.max(8, r.top - t.height - 8) + 'px';
}
function withTip(node, value, label) {
  node.tabIndex = 0;
  node.setAttribute('aria-label', label + ': ' + value);
  for (const ev of ['pointerenter', 'focus']) node.addEventListener(ev, () => showTip(node, value, label));
  for (const ev of ['pointerleave', 'blur']) node.addEventListener(ev, () => { tooltip.style.display = 'none'; });
  return node;
}

// ---- header
(function header() {
  const parts = [DATA.run_dir];
  if (DATA.models.length) parts.push('model ' + DATA.models.join(', '));
  if (DATA.agent) parts.push('agent ' + DATA.agent);
  if (DATA.dataset) parts.push(DATA.dataset);
  if (DATA.timestamp) parts.push(DATA.timestamp);
  document.getElementById('sub').textContent = parts.join(' · ');

  const notes = document.getElementById('notes');
  const missing = ROWS.filter(r => !r.has_metrics).length;
  const unfinished = ROWS.filter(r => r.has_metrics && !r.finished).length;
  if (!DATA.has_results)
    notes.append(el('p', {class: 'note', text: 'raw_result.json was not found in this run directory, so pass/fail, category and difficulty are unknown.'}));
  if (missing)
    notes.append(el('p', {class: 'note', text: missing + ' of ' + plural(ROWS.length, 'problem') + ' had no agent_metrics.json recorded; token, latency and cost figures leave them out.'}));
  if (unfinished)
    notes.append(el('p', {class: 'note', text: 'The agent run did not finish (killed or timed out) for ' + plural(unfinished, 'problem') + ', so those figures are partial.'}));
  const priced = Object.entries(DATA.prices);
  if (priced.length)
    notes.append(el('p', {class: 'sub', text: 'Cost uses USD per 1M tokens (input / cached input / output): ' +
      priced.map(([m, p]) => m + ' ' + p.join(' / ')).join('; ') + '.'}));
  else if (ROWS.some(r => r.has_metrics))
    notes.append(el('p', {class: 'note', text: 'No price is known for this model, so cost is not shown. Re-run the report with --price-input and --price-output.'}));
})();

// ---- filters
const fSearch = document.getElementById('f-search');
const fCategory = document.getElementById('f-category');
const fDifficulty = document.getElementById('f-difficulty');
const fResult = document.getElementById('f-result');
function fillSelect(select, allLabel, values) {
  select.append(el('option', {value: '', text: allLabel}));
  for (const v of values) select.append(el('option', {value: v, text: v}));
}
fillSelect(fCategory, 'All categories', [...new Set(ROWS.map(r => r.category).filter(has))].sort());
fillSelect(fDifficulty, 'All difficulties',
  [...new Set(ROWS.map(r => r.difficulty).filter(has))].sort((a, b) => diffRank(a) - diffRank(b)));
for (const node of [fSearch, fCategory, fDifficulty, fResult]) node.addEventListener('input', renderAll);

function filteredRows() {
  const q = fSearch.value.trim().toLowerCase();
  return ROWS.filter(r => {
    if (q && !r.id.toLowerCase().includes(q)) return false;
    if (fCategory.value && r.category !== fCategory.value) return false;
    if (fDifficulty.value && r.difficulty !== fDifficulty.value) return false;
    if (fResult.value === 'pass' && r.passed !== true) return false;
    if (fResult.value === 'fail' && r.passed !== false) return false;
    if (fResult.value === 'unknown' && r.passed !== null) return false;
    return true;
  });
}

// ---- tiles
function tile(label, value, detail) {
  return el('div', {class: 'card tile'}, [
    el('div', {class: 'label', text: label}), el('div', {class: 'value', text: value}),
    el('div', {class: 'detail', text: detail || ''})]);
}
function renderTiles(rows) {
  const evaluated = rows.filter(r => r.passed !== null);
  const passed = evaluated.filter(r => r.passed).length;
  const m = rows.filter(r => r.has_metrics);
  const cost = m.some(r => has(r.cost)) ? sum(m, 'cost') : null;
  const failedCalls = sum(m, 'failed_llm_calls');
  const truncated = m.filter(r => r.truncated).length;
  document.getElementById('tiles').replaceChildren(
    tile('Pass rate', fmtPct(passRate(rows)), evaluated.length ? passed + ' of ' + evaluated.length + ' problems' : 'not evaluated'),
    tile('Total tokens', fmtCompact(m.length ? sum(m, 'total_tokens') : null),
      fmtCompact(sum(m, 'input_tokens')) + ' in · ' + fmtCompact(sum(m, 'output_tokens')) + ' out'),
    tile('Total cost', fmtCost(cost), has(cost) ? fmtCost(avg(m, 'cost')) + ' avg per problem' : ''),
    tile('Avg LLM latency', fmtSec(avg(m, 'llm_latency_ms')), 'per problem, all calls summed'),
    tile('Avg iterations', fmtNum(avg(m, 'iterations'), 2), 'per problem'),
    tile('LLM calls', fmtInt(m.length ? sum(m, 'llm_calls') : null),
      failedCalls + ' failed · output limit hit in ' + plural(truncated, 'problem')));
  const g = m.filter(r => has(r.gpu_energy_j));
  if (g.length) {
    const solved = g.filter(r => r.passed).length;
    const peaks = m.filter(r => has(r.gpu_peak_memory_mb)).map(r => r.gpu_peak_memory_mb);
    document.getElementById('tiles').append(
      tile('GPU energy', fmtEnergy(sum(g, 'gpu_energy_j')),
        fmtEnergy(avg(g, 'gpu_energy_j')) + ' avg per problem' +
        (solved ? ' · ' + fmtEnergy(sum(g, 'gpu_energy_j') / solved) + ' per passed problem' : '')),
      tile('Peak GPU memory', fmtMem(peaks.length ? Math.max(...peaks) : null), 'during generation, model process only'));
  }
}

// ---- charts
function barRow(name, segments, label) {
  const track = el('div', {class: 'bar-track'});
  segments.forEach((s, i) => {
    if (s.width <= 0) return;
    const bar = el('div', {class: 'bar ' + (s.cls || '') + (segments.length > 1 ? ' seg' : '') +
      (i === segments.length - 1 || segments.slice(i + 1).every(x => x.width <= 0) ? ' last' : '')});
    bar.style.width = 'calc((100% - 150px) * ' + s.width + ')';
    track.append(withTip(bar, s.tipValue, s.tipLabel));
  });
  track.append(el('span', {class: 'bar-label', text: label}));
  return el('div', {class: 'bar-row'}, [el('div', {class: 'name', text: name, title: name}), track]);
}
function renderCategoryChart(rows) {
  const box = document.getElementById('chart-category');
  const cats = [...new Set(rows.filter(r => r.passed !== null).map(r => r.category || 'unknown'))].sort();
  if (!cats.length) { box.replaceChildren(el('div', {class: 'empty', text: 'No evaluated problems in this selection.'})); return; }
  box.replaceChildren(...cats.map(c => {
    const group = rows.filter(r => r.passed !== null && (r.category || 'unknown') === c);
    const passed = group.filter(r => r.passed).length;
    const rate = passed / group.length;
    return barRow(c, [{width: rate, tipValue: fmtPct(rate), tipLabel: c + ' · ' + passed + ' of ' + group.length + ' passed'}],
      fmtPct(rate) + '  (' + passed + '/' + group.length + ')');
  }));
}
function renderIterationChart(rows) {
  const box = document.getElementById('chart-iterations');
  const m = rows.filter(r => has(r.iterations));
  if (!m.length) { box.replaceChildren(el('div', {class: 'empty', text: 'No recorded metrics in this selection.'})); return; }
  const counts = [...new Set(m.map(r => r.iterations))].sort((a, b) => a - b);
  const max = Math.max(...counts.map(n => m.filter(r => r.iterations === n).length));
  box.replaceChildren(...counts.map(n => {
    const group = m.filter(r => r.iterations === n);
    const passed = group.filter(r => r.passed === true).length;
    const failed = group.filter(r => r.passed === false).length;
    const name = plural(n, 'iteration');
    const unknown = group.length - passed - failed;
    return barRow(name, [
      {width: passed / max, cls: 'good', tipValue: String(passed), tipLabel: name + ' · passed'},
      {width: failed / max, cls: 'critical', tipValue: String(failed), tipLabel: name + ' · failed'},
    ], passed + ' passed · ' + failed + ' failed' + (unknown ? ' · ' + unknown + ' not evaluated' : ''));
  }));
}

// ---- tables
function table(columns, rows, opts) {
  opts = opts || {};
  const head = el('tr', {}, columns.map(c => {
    const th = el('th', {class: (c.num ? 'num ' : '') + (opts.onSort ? 'sortable' : ''),
      text: c.label + (opts.sortKey === c.key ? (opts.sortAsc ? ' ▲' : ' ▼') : '')});
    if (opts.onSort) th.addEventListener('click', () => opts.onSort(c.key));
    return th;
  }));
  const body = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {class: opts.rowClass || ''}, columns.map(c => {
      const v = c.render ? c.render(r) : r[c.key];
      return el('td', {class: c.num ? 'num' : ''}, [v instanceof Node ? v : (has(v) ? String(v) : '–')]);
    }));
    body.append(tr);
    if (opts.onRow) opts.onRow(r, tr, body, columns.length);
  }
  return el('table', {}, [el('thead', {}, [head]), body]);
}

function renderBreakdown(rows) {
  const groups = new Map();
  for (const r of rows) {
    const key = (r.category || 'unknown') + '|' + (r.difficulty || 'unknown');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  const lines = [...groups.entries()].map(([key, g]) => {
    const [category, difficulty] = key.split('|');
    const evaluated = g.filter(r => r.passed !== null);
    return {category, difficulty, problems: g.length, passed: evaluated.filter(r => r.passed).length,
      rate: passRate(g), input: avg(g, 'input_tokens'), output: avg(g, 'output_tokens'),
      latency: avg(g, 'llm_latency_ms'), cost: avg(g, 'cost'), iterations: avg(g, 'iterations'),
      energy: avg(g.filter(r => has(r.gpu_energy_j)), 'gpu_energy_j')};
  }).sort((a, b) => a.category.localeCompare(b.category) || diffRank(a.difficulty) - diffRank(b.difficulty));
  document.getElementById('breakdown').replaceChildren(table([
    {key: 'category', label: 'Category'}, {key: 'difficulty', label: 'Difficulty'},
    {key: 'problems', label: 'Problems', num: true}, {key: 'passed', label: 'Passed', num: true},
    {key: 'rate', label: 'Pass rate', num: true, render: r => fmtPct(r.rate)},
    {key: 'input', label: 'Avg input tokens', num: true, render: r => fmtInt(r.input)},
    {key: 'output', label: 'Avg output tokens', num: true, render: r => fmtInt(r.output)},
    {key: 'latency', label: 'Avg LLM latency', num: true, render: r => fmtSec(r.latency)},
    {key: 'cost', label: 'Avg cost', num: true, render: r => fmtCost(r.cost)},
    {key: 'iterations', label: 'Avg iterations', num: true, render: r => fmtNum(r.iterations, 2)},
    ...(HAS_GPU ? [{key: 'energy', label: 'Avg GPU energy', num: true, render: r => fmtEnergy(r.energy)}] : []),
  ], lines));
}

const PROBLEM_COLUMNS = [
  {key: 'id', label: 'Problem ID'}, {key: 'category', label: 'Category'}, {key: 'difficulty', label: 'Difficulty'},
  {key: 'passed', label: 'Result', render: r => passCell(r.passed)},
  {key: 'agent_success', label: 'Agent self-test', render: r => boolCell(r.agent_success)},
  {key: 'iterations', label: 'Iterations', num: true, render: r => fmtInt(r.iterations)},
  {key: 'input_tokens', label: 'Input tokens', num: true, render: r => fmtInt(r.input_tokens)},
  {key: 'output_tokens', label: 'Output tokens', num: true, render: r => fmtInt(r.output_tokens)},
  {key: 'total_tokens', label: 'Total tokens', num: true, render: r => fmtInt(r.total_tokens)},
  {key: 'cached_input_tokens', label: 'Cached input', num: true, render: r => fmtInt(r.cached_input_tokens)},
  {key: 'llm_latency_ms', label: 'LLM latency', num: true, render: r => fmtSec(r.llm_latency_ms)},
  {key: 'test_time_ms', label: 'Agent test time', num: true, render: r => fmtSec(r.test_time_ms)},
  {key: 'agent_time_s', label: 'Agent wall time', num: true, render: r => has(r.agent_time_s) ? fmtSec(r.agent_time_s * 1000) : '–'},
  {key: 'cost', label: 'Cost', num: true, render: r => fmtCost(r.cost)},
  ...(HAS_GPU ? [
    {key: 'gpu_energy_j', label: 'GPU energy', num: true, render: r => fmtEnergy(r.gpu_energy_j)},
    {key: 'gpu_peak_memory_mb', label: 'Peak GPU memory', num: true, render: r => fmtMem(r.gpu_peak_memory_mb)},
  ] : []),
];
const sortState = {key: 'id', asc: true};
const expanded = new Set();

function detailTable(r) {
  if (!r.has_metrics) return el('div', {class: 'muted', text: 'No agent_metrics.json was recorded for this problem.'});
  const lines = r.iteration_log.map(it => Object.assign({}, r.calls.find(c => c.iteration === it.iteration) || {}, it));
  return table([
    {key: 'iteration', label: '#', num: true}, {key: 'prompt_type', label: 'Prompt'},
    {key: 'input_tokens', label: 'Input tokens', num: true, render: c => fmtInt(c.input_tokens)},
    {key: 'output_tokens', label: 'Output tokens', num: true, render: c => fmtInt(c.output_tokens)},
    {key: 'cached_input_tokens', label: 'Cached input', num: true, render: c => fmtInt(c.cached_input_tokens)},
    {key: 'latency_ms', label: 'LLM latency', num: true, render: c => fmtSec(c.latency_ms)},
    {key: 'cost', label: 'Cost', num: true, render: c => fmtCost(c.cost)},
    ...(HAS_GPU ? [
      {key: 'gpu_energy_j', label: 'GPU energy', num: true, render: c => fmtEnergy(c.gpu_energy_j)},
      {key: 'gpu_avg_power_w', label: 'GPU power', num: true, render: c => has(c.gpu_avg_power_w) ? fmtNum(c.gpu_avg_power_w, 0) + ' W' : '–'},
      {key: 'gpu_avg_util_pct', label: 'GPU util', num: true, render: c => has(c.gpu_avg_util_pct) ? fmtNum(c.gpu_avg_util_pct, 0) + '%' : '–'},
    ] : []),
    {key: 'finish_reason', label: 'Finish reason'},
    {key: 'structure_valid', label: 'Structure valid', render: c => boolCell(c.structure_valid)},
    {key: 'compilation_success', label: 'Compiled', render: c => boolCell(c.compilation_success)},
    {key: 'test_success', label: 'Tests passed', render: c => boolCell(c.test_success)},
    {key: 'test_time_ms', label: 'Test time', num: true, render: c => fmtSec(c.test_time_ms)},
    {key: 'response_model', label: 'Model'}, {key: 'error', label: 'Error'},
  ], lines);
}
function renderProblems(rows) {
  const {key, asc} = sortState;
  const sorted = rows.slice().sort((a, b) => {
    const av = a[key], bv = b[key];
    if (!has(av) && !has(bv)) return 0;
    if (!has(av)) return 1;            // unknown values always last
    if (!has(bv)) return -1;
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return asc ? cmp : -cmp;
  });
  document.getElementById('problems').replaceChildren(table(PROBLEM_COLUMNS, sorted, {
    rowClass: 'problem', sortKey: key, sortAsc: asc,
    onSort: k => { sortState.asc = sortState.key === k ? !sortState.asc : true; sortState.key = k; renderProblems(filteredRows()); },
    onRow: (r, tr, body, span) => {
      tr.addEventListener('click', () => { expanded.has(r.id) ? expanded.delete(r.id) : expanded.add(r.id); renderProblems(filteredRows()); });
      if (expanded.has(r.id))
        body.append(el('tr', {class: 'detail'}, [el('td', {colspan: span}, [el('div', {class: 'table-wrap'}, [detailTable(r)])])]));
    },
  }));
}

function renderAll() {
  const rows = filteredRows();
  document.getElementById('f-count').textContent = rows.length + ' of ' + plural(ROWS.length, 'problem');
  renderTiles(rows);
  renderCategoryChart(rows);
  renderIterationChart(rows);
  renderBreakdown(rows);
  renderProblems(rows);
}
renderAll();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
