#!/usr/bin/env python3
"""Generate a self-contained HTML report from fbc-size-analyzer JSON output."""

import sys
import json
import os
import urllib.request

CHARTJS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
CHARTJS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chartjs-cache.js")


def compact_data(data):
    repo_table = []
    repo_idx = {}
    ref_table = []
    ref_idx = {}

    def get_repo_id(name):
        if name not in repo_idx:
            repo_idx[name] = len(repo_table)
            repo_table.append(name)
        return repo_idx[name]

    def get_ref_id(ref):
        if ref not in ref_idx:
            ref_idx[ref] = len(ref_table)
            ref_table.append(ref)
        return ref_idx[ref]

    compact = []
    for p in sorted(data["packages"], key=lambda x: -x["avg_total_size"]):
        cp = {
            "n": p["name"],
            "vc": p["version_count"],
            "avg": p["avg_total_size"],
            "lv": p.get("latest_version", ""),
            "lt": p.get("latest_total_size", 0),
            "li": p.get("latest_image_count", 0),
            "vs": [],
        }
        for v in p.get("versions", []):
            arches = sorted(v["architectures"].keys())
            sorted_imgs = sorted(v.get("images", []), key=lambda x: -x["total_size"])
            cv = {
                "v": v["version"],
                "ic": v["image_count"],
                "ts": v["total_size"],
                "ar": arches,
                "as": [v["architectures"][a]["size"] for a in arches],
                "im": [],
            }
            for img in sorted_imgs:
                img_arches = img.get("architectures", {})
                img_name = img.get("name", "")
                img_ref = img.get("image", "")
                # row: [repoId, totalSize, refId, name, arch1size, arch2size, ...]
                row = [get_repo_id(img["repository"]), img["total_size"],
                       get_ref_id(img_ref), img_name]
                for a in arches:
                    arch_data = img_arches.get(a)
                    row.append(arch_data["size"] if isinstance(arch_data, dict) else 0)
                cv["im"].append(row)
            cp["vs"].append(cv)
        compact.append(cp)

    return {"repos": repo_table, "refs": ref_table, "pkgs": compact, "meta": {
        "package_count": data.get("package_count", len(data["packages"])),
    }}


def get_chartjs():
    if os.path.exists(CHARTJS_CACHE):
        with open(CHARTJS_CACHE) as f:
            return f.read()
    print(f"Downloading Chart.js from {CHARTJS_URL}...")
    req = urllib.request.Request(CHARTJS_URL, headers={"User-Agent": "generate-report/1.0"})
    with urllib.request.urlopen(req) as resp:
        src = resp.read().decode("utf-8")
    with open(CHARTJS_CACHE, "w") as f:
        f.write(src)
    return src


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Operator Related Image Sizes Explorer</title>
<style>
:root, [data-theme="light"] {
  --bg: #ffffff;
  --fg: #1a1a2e;
  --card-bg: #f8f9fa;
  --card-bg-alt: #eef0f3;
  --border: #d1d5db;
  --accent: #2563eb;
  --accent-fg: #ffffff;
  --muted: #6b7280;
  --table-stripe: #f3f4f6;
  --summary-hover: #e5e7eb;
  --tab-inactive-bg: #f3f4f6;
  --tab-inactive-fg: #374151;
  --input-bg: #ffffff;
  --shadow: rgba(0,0,0,0.06);
  --danger: #b91c1c;
  --info: #1d4ed8;
  --chart-grid: rgba(0,0,0,0.06);
  --chart-text: #6b7280;
}
[data-theme="dark"] {
  --bg: #1a1a2e;
  --fg: #e8e8f0;
  --card-bg: #252540;
  --card-bg-alt: #2d2d4a;
  --border: #3d3d5c;
  --accent: #60a5fa;
  --accent-fg: #1a1a2e;
  --muted: #9ca3af;
  --table-stripe: #2a2a45;
  --summary-hover: #353555;
  --tab-inactive-bg: #2d2d4a;
  --tab-inactive-fg: #c8c8d8;
  --input-bg: #252540;
  --shadow: rgba(0,0,0,0.3);
  --danger: #fca5a5;
  --info: #93c5fd;
  --chart-grid: rgba(255,255,255,0.08);
  --chart-text: #9ca3af;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg); color: var(--fg);
  line-height: 1.5; font-size: 14px;
  transition: background 0.2s, color 0.2s;
}
.container { max-width: 1100px; margin: 0 auto; padding: 1rem 1.25rem 3rem; }
header {
  display: flex; flex-wrap: wrap; align-items: flex-start;
  justify-content: space-between; gap: 1rem; margin-bottom: 1.25rem;
}
header h1 { margin: 0 0 0.25rem; font-size: 1.5rem; font-weight: 700; }
header .meta { color: var(--muted); font-size: 0.85rem; }
.header-actions { display: flex; align-items: center; gap: 0.75rem; }
.gh-link {
  color: var(--fg); display: flex; opacity: 0.7; transition: opacity 0.15s;
  text-decoration: none;
}
.gh-link:hover { opacity: 1; }
.theme-switcher {
  display: flex; gap: 0; border: 1px solid var(--border);
  border-radius: 6px; overflow: hidden; flex-shrink: 0;
}
.theme-switcher button {
  padding: 0.35rem 0.65rem; border: none; background: var(--tab-inactive-bg);
  color: var(--tab-inactive-fg); cursor: pointer; font-size: 0.75rem; font-family: inherit;
}
.theme-switcher button.active { background: var(--accent); color: var(--accent-fg); }
.theme-switcher button:not(:last-child) { border-right: 1px solid var(--border); }
.stat-strip {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem; margin-bottom: 1.25rem;
}
.stat-box {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.85rem 1rem; text-align: center;
}
.stat-box .num {
  font-size: 1.75rem; font-weight: 700; font-variant-numeric: tabular-nums;
  font-family: ui-monospace, 'Cascadia Code', monospace;
}
.stat-box .num.danger { color: var(--danger); }
.stat-box .num.info { color: var(--info); }
.stat-box .lbl { font-size: 0.75rem; color: var(--muted); margin-top: 0.15rem; }
.filter-row {
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 0.75rem; margin-bottom: 0.75rem;
}
.filter-row input {
  flex: 1; min-width: 180px; padding: 0.45rem 0.65rem;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--input-bg); color: var(--fg);
  font-size: 0.85rem; font-family: inherit;
}
.filter-row input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.section-title { font-size: 0.95rem; font-weight: 600; margin: 1.25rem 0 0.35rem; }
.section-sub { font-size: 0.78rem; color: var(--muted); margin-bottom: 0.5rem; }
.table-scroll { overflow-x: auto; }
.table-wrap {
  border: 1px solid var(--border); border-radius: 8px;
  overflow: auto; margin-bottom: 0.75rem; background: var(--card-bg);
}
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
thead { position: sticky; top: 0; z-index: 1; }
th {
  background: var(--card-bg); padding: 0.4rem 0.55rem; text-align: left;
  font-weight: 600; font-size: 0.75rem; color: var(--muted);
  border-bottom: 1px solid var(--border); white-space: nowrap;
  cursor: pointer; user-select: none; transition: color 0.15s;
}
th:hover { color: var(--accent); }
th.sorted { color: var(--accent); }
th.num, td.num { text-align: right; font-family: ui-monospace, 'Cascadia Code', monospace; font-variant-numeric: tabular-nums; }
td { padding: 0.4rem 0.55rem; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
tbody tr:nth-child(even) { background: var(--table-stripe); }
tbody tr:hover { background: var(--summary-hover); }
.link {
  color: var(--accent); cursor: pointer; font-weight: 600;
  text-decoration: none; transition: color 0.15s;
}
.link:hover { text-decoration: underline; }
.btn-back {
  display: inline-flex; align-items: center; gap: 0.3rem; background: none;
  border: 1px solid var(--border); border-radius: 6px; color: var(--muted);
  cursor: pointer; padding: 0.35rem 0.75rem; font-size: 0.82rem;
  font-family: inherit; transition: all 0.15s; margin-bottom: 0.75rem;
}
.btn-back:hover { border-color: var(--accent); color: var(--accent); }
.chart-card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem; margin-bottom: 0.75rem;
}
.chart-row { display: flex; gap: 0.75rem; margin-bottom: 0.75rem; }
.chart-row > div { flex: 1; }
@media (max-width: 700px) {
  header h1 { font-size: 1.2rem; }
  .stat-box .num { font-size: 1.4rem; }
  th, td { padding: 0.3rem 0.35rem; font-size: 0.75rem; }
  .chart-row { flex-direction: column; }
}
.img-name-cell { display: inline-flex; align-items: center; gap: 0.35rem; max-width: 100%; }
.img-name-cell .name-text {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  cursor: default;
}
.btn-copy {
  background: none; border: 1px solid var(--border); border-radius: 4px;
  color: var(--fg); cursor: pointer; padding: 1px 5px; font-size: 0.7rem;
  line-height: 1.2; opacity: 0.6; flex-shrink: 0;
}
.btn-copy:hover { opacity: 1; background: var(--accent); color: var(--accent-fg); }
.btn-copy.copied { opacity: 1; background: #22c55e; color: #fff; border-color: #22c55e; }
.toggle-row {
  display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;
  font-size: 0.8rem; color: var(--muted-fg);
}
.toggle-row label { cursor: pointer; user-select: none; display: flex; align-items: center; gap: 0.35rem; }
.col-imgurl { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.75rem; }
</style>
</head>
<body>
<div class="container" id="root">
  <header>
    <div>
      <h1>Operator Related Image Sizes Explorer</h1>
      <div class="meta" id="header-meta"></div>
    </div>
    <div class="header-actions">
      <a class="gh-link" id="gh-link" href="#" title="View source on GitHub" style="display:none">
        <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>
      </a>
      <div class="theme-switcher" id="theme-switcher">
        <button data-theme="system" class="active">System</button>
        <button data-theme="light">Light</button>
        <button data-theme="dark">Dark</button>
      </div>
    </div>
  </header>
  <div id="app"></div>
</div>

<script>
%%CHARTJS%%
</script>

<script>
const RAW = %%DATA%%;
const REPO_URL = "%%REPO_URL%%";

// --- Boot ---
if (REPO_URL) {
  const ghLink = document.getElementById('gh-link');
  ghLink.href = REPO_URL;
  ghLink.style.display = 'flex';
}
document.getElementById('header-meta').textContent =
  'Red Hat operator catalog v4.21 \u00b7 ' + RAW.pkgs.length + ' operators';

// --- Theme ---
function applyTheme(mode) {
  localStorage.setItem('img-report-theme', mode);
  document.querySelectorAll('#theme-switcher button').forEach(b =>
    b.classList.toggle('active', b.dataset.theme === mode));
  if (mode === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', mode);
  render();
}
function initTheme() {
  const saved = localStorage.getItem('img-report-theme') || 'system';
  applyTheme(saved);
  document.getElementById('theme-switcher').addEventListener('click', e => {
    const btn = e.target.closest('button[data-theme]');
    if (btn) applyTheme(btn.dataset.theme);
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem('img-report-theme') || 'system') === 'system') render();
  });
}

// --- Utilities ---
function fmtSize(b) {
  if (b <= 0) return '0 B';
  const units = ['B','KB','MB','GB','TB'];
  let v = b;
  for (const u of units) {
    if (v < 1024) return (u === 'B' || u === 'KB') ? Math.round(v)+' '+u : v.toFixed(1)+' '+u;
    v /= 1024;
  }
  return v.toFixed(1)+' PB';
}
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
function cmpSemver(a, b) {
  const re = /(\d+)/g;
  const pa = a.match(re) || [], pb = b.match(re) || [];
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const na = parseInt(pa[i] || '0', 10), nb = parseInt(pb[i] || '0', 10);
    if (na !== nb) return na - nb;
  }
  return a.localeCompare(b);
}

const CHART_COLORS = ['#3b82f6','#ef4444','#22c55e','#f59e0b','#8b5cf6','#06b6d4','#ec4899','#14b8a6'];
let activeCharts = [];
function destroyCharts() { activeCharts.forEach(c => c.destroy()); activeCharts = []; }

function isDark() {
  const t = document.documentElement.getAttribute('data-theme');
  if (t === 'dark') return true;
  if (t === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function chartOpts(cd) {
  return { color: isDark() ? '#9ca3af' : '#6b7280', border: isDark() ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)' };
}

function makeLineChart(canvas, categories, seriesData, opts = {}) {
  const cd = chartOpts();
  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: categories,
      datasets: seriesData.map((s, i) => ({
        label: s.name, data: s.data,
        borderColor: CHART_COLORS[i % CHART_COLORS.length],
        backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + '22',
        fill: opts.fill || false, tension: 0.3,
        pointRadius: categories.length > 20 ? 2 : 4, pointHoverRadius: 6, borderWidth: 2,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: { legend: { display: seriesData.length > 1, labels: { color: cd.color, font: { size: 11 } } },
        tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { color: cd.color, font: { size: 10 }, maxRotation: 45 }, grid: { color: cd.border } },
        y: { ticks: { color: cd.color, font: { size: 10 }, callback: v => v + (opts.suffix || '') }, grid: { color: cd.border } },
      },
    },
  });
  activeCharts.push(chart);
  return chart;
}

function makeBarChart(canvas, categories, seriesData, opts = {}) {
  const cd = chartOpts();
  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: categories,
      datasets: seriesData.map((s, i) => ({
        label: s.name, data: s.data,
        backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + (opts.stacked ? 'cc' : 'aa'),
        borderColor: CHART_COLORS[i % CHART_COLORS.length], borderWidth: 1, borderRadius: 3,
      })),
    },
    options: {
      indexAxis: opts.horizontal ? 'y' : 'x',
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: { legend: { display: seriesData.length > 1, labels: { color: cd.color, font: { size: 11 } } },
        tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { stacked: opts.stacked || false,
          ticks: { color: cd.color, font: { size: 10 }, maxRotation: 45,
            callback: opts.horizontal ? (v => v + (opts.suffix || '')) : undefined },
          grid: { color: cd.border } },
        y: { stacked: opts.stacked || false,
          ticks: { color: cd.color, font: { size: 10 },
            callback: opts.horizontal ? undefined : (v => v + (opts.suffix || '')) },
          grid: { color: cd.border } },
      },
    },
  });
  activeCharts.push(chart);
  return chart;
}

// --- State ---
let state = { view: 'summary', pkgName: null, verIdx: null, search: '',
  sumSort: { col: 'avg', dir: 'desc' },
  pkgSort: { col: 'ver', dir: 'desc' },
  imgSort: { col: 'total', dir: 'desc' },
  showImgUrl: false,
};

function navigate(view, pkgName, verIdx) {
  state.view = view; state.pkgName = pkgName; state.verIdx = verIdx;
  render();
}

function toggleSort(key, col) {
  const s = state[key];
  if (s.col === col) s.dir = s.dir === 'asc' ? 'desc' : 'asc';
  else { s.col = col; s.dir = 'desc'; }
  render();
}

function sortTh(label, sortKey, col, isNum) {
  const s = state[sortKey];
  const active = s.col === col;
  const arrow = active ? (s.dir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
  return `<th class="${active ? 'sorted' : ''}${isNum ? ' num' : ''}" onclick="toggleSort('${sortKey}','${col}')">${esc(label)}${arrow}</th>`;
}

// --- Render helpers ---
function statBox(val, lbl, tone) {
  return `<div class="stat-box"><div class="num${tone ? ' '+tone : ''}">${esc(String(val))}</div><div class="lbl">${esc(lbl)}</div></div>`;
}

// --- Views ---
function renderSummary() {
  destroyCharts();
  let list = [...RAW.pkgs];
  if (state.search) {
    const q = state.search.toLowerCase();
    list = list.filter(p => p.n.toLowerCase().includes(q));
  }
  const m = state.sumSort.dir === 'asc' ? 1 : -1;
  const sc = state.sumSort.col;
  if (sc === 'name') list.sort((a, b) => m * a.n.localeCompare(b.n));
  else if (sc === 'vc') list.sort((a, b) => m * (a.vc - b.vc));
  else if (sc === 'latest') list.sort((a, b) => m * (a.lt - b.lt));
  else if (sc === 'imgs') list.sort((a, b) => m * (a.li - b.li));
  else list.sort((a, b) => m * (a.avg - b.avg));

  const totalLatest = RAW.pkgs.reduce((s, p) => s + p.lt, 0);
  const totalImages = RAW.pkgs.reduce((s, p) => s + p.li, 0);
  const biggest = RAW.pkgs.reduce((mx, p) => p.lt > mx.lt ? p : mx, RAW.pkgs[0]);

  let html = `<div class="stat-strip">
    ${statBox(RAW.pkgs.length, 'Operators')}
    ${statBox(fmtSize(totalLatest), 'Total latest (all arch)')}
    ${statBox(fmtSize(biggest.lt), 'Largest: ' + biggest.n, 'danger')}
    ${statBox(totalImages, 'Total images (latest)')}
  </div>
  <div class="filter-row">
    <input type="text" id="pkg-filter" placeholder="Filter operators\u2026" value="${esc(state.search)}" autocomplete="off">
    <span style="color:var(--muted);font-size:0.82rem">${list.length} of ${RAW.pkgs.length} operators</span>
  </div>
  <div class="table-wrap" style="max-height:600px">
    <table><thead><tr>
      <th class="num">#</th>
      ${sortTh('Operator', 'sumSort', 'name', false)}
      ${sortTh('Versions', 'sumSort', 'vc', true)}
      ${sortTh('Avg total (all arch)', 'sumSort', 'avg', true)}
      ${sortTh('Latest total (all arch)', 'sumSort', 'latest', true)}
      ${sortTh('Images (latest)', 'sumSort', 'imgs', true)}
    </tr></thead><tbody>`;

  list.forEach((p, i) => {
    html += `<tr>
      <td class="num">${i + 1}</td>
      <td><a class="link" onclick="navigate('package','${esc(p.n)}')">${esc(p.n)}</a></td>
      <td class="num">${p.vc}</td><td class="num">${fmtSize(p.avg)}</td>
      <td class="num">${fmtSize(p.lt)}</td><td class="num">${p.li}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  document.getElementById('app').innerHTML = html;

  document.getElementById('pkg-filter').addEventListener('input', e => {
    state.search = e.target.value; render();
  });
}

function renderPackage() {
  destroyCharts();
  const pkg = RAW.pkgs.find(p => p.n === state.pkgName);
  if (!pkg) { navigate('summary'); return; }
  const versions = pkg.vs;
  const allArchs = [...new Set(versions.flatMap(v => v.ar))].sort();

  const chartVsRaw = [...versions].reverse();
  let chartVs = chartVsRaw;
  if (chartVs.length > 30) {
    const step = Math.ceil(chartVs.length / 30);
    chartVs = chartVs.filter((_, i) => i % step === 0 || i === chartVs.length - 1);
  }

  const indexed = versions.map((v, oi) => ({ v, oi }));
  const sm = state.pkgSort.dir === 'asc' ? 1 : -1;
  const sc = state.pkgSort.col;
  if (sc === 'ver') indexed.sort((a, b) => sm * cmpSemver(a.v.v, b.v.v));
  else if (sc === 'ic') indexed.sort((a, b) => sm * (a.v.ic - b.v.ic));
  else if (sc === 'total') indexed.sort((a, b) => sm * (a.v.ts - b.v.ts));
  else if (sc.startsWith('arch:')) {
    const arch = sc.slice(5);
    indexed.sort((a, b) => {
      const ai = a.v.ar.indexOf(arch), bi = b.v.ar.indexOf(arch);
      return sm * ((ai >= 0 ? a.v.as[ai] : 0) - (bi >= 0 ? b.v.as[bi] : 0));
    });
  }

  let html = `<button class="btn-back" onclick="navigate('summary')">\u2190 Back to list</button>
  <h2 style="font-size:1.3rem;font-weight:700;margin:0 0 0.75rem">${esc(pkg.n)}</h2>
  <div class="stat-strip">
    ${statBox(pkg.vc, 'Versions')}
    ${statBox(fmtSize(pkg.avg), 'Avg total size')}
    ${statBox(fmtSize(pkg.lt), 'Latest: ' + pkg.lv, 'info')}
    ${statBox(pkg.li, 'Images (latest)')}
  </div>
  <div class="section-title">Total size over releases (all architectures combined)</div>
  <div class="section-sub">Source: fbc-size-analyzer, compressed layer sizes</div>
  <div class="chart-card"><canvas id="lineChart" style="height:280px"></canvas></div>`;

  if (allArchs.length > 1) {
    html += `<div class="section-title">Per-architecture breakdown over releases</div>
    <div class="section-sub">Stacked bar: each color is one architecture</div>
    <div class="chart-card"><canvas id="stackedBar" style="height:280px"></canvas></div>`;
  }

  html += `<div class="section-title">All versions</div>
  <div class="table-wrap" style="max-height:500px"><table><thead><tr>
    ${sortTh('Version', 'pkgSort', 'ver', false)}
    ${sortTh('Images', 'pkgSort', 'ic', true)}
    ${allArchs.map(a => sortTh(a, 'pkgSort', 'arch:' + a, true)).join('')}
    ${sortTh('Total', 'pkgSort', 'total', true)}
  </tr></thead><tbody>`;

  indexed.forEach(({ v, oi }) => {
    html += `<tr>
      <td><a class="link" onclick="navigate('version','${esc(pkg.n)}',${oi})">${esc(v.v)}</a></td>
      <td class="num">${v.ic}</td>`;
    allArchs.forEach(arch => {
      const idx = v.ar.indexOf(arch);
      html += `<td class="num">${fmtSize(idx >= 0 ? v.as[idx] : 0)}</td>`;
    });
    html += `<td class="num" style="font-weight:600">${fmtSize(v.ts)}</td></tr>`;
  });
  html += '</tbody></table></div>';
  document.getElementById('app').innerHTML = html;

  requestAnimationFrame(() => {
    const lc = document.getElementById('lineChart');
    if (lc) makeLineChart(lc, chartVs.map(v => v.v),
      [{ name: 'Total all-arch (GB)', data: chartVs.map(v => +(v.ts / 1073741824).toFixed(1)) }],
      { fill: true, suffix: ' GB' });
    const sc = document.getElementById('stackedBar');
    if (sc) makeBarChart(sc, chartVs.map(v => v.v),
      allArchs.map(arch => ({
        name: arch,
        data: chartVs.map(v => { const idx = v.ar.indexOf(arch); return idx >= 0 ? +(v.as[idx] / 1073741824).toFixed(1) : 0; }),
      })),
      { stacked: true, suffix: ' GB' });
  });
}

function copyPullSpec(btn, text) {
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('copied');
    btn.textContent = 'copied';
    setTimeout(() => { btn.classList.remove('copied'); btn.textContent = 'copy'; }, 1500);
  });
}

function toggleImgUrlCol() {
  state.showImgUrl = !state.showImgUrl;
  renderVersion();
}

function renderVersion() {
  destroyCharts();
  const pkg = RAW.pkgs.find(p => p.n === state.pkgName);
  if (!pkg) { navigate('summary'); return; }
  const ver = pkg.vs[state.verIdx];
  if (!ver) { navigate('package', pkg.n); return; }
  const arches = ver.ar;
  // row: [repoId, totalSize, refId, name, arch1size, ...]
  const images = ver.im.map(row => ({
    repo: RAW.repos[row[0]], total: row[1],
    ref: RAW.refs[row[2]], name: row[3] || '',
    perArch: arches.map((_, ai) => row[4 + ai] || 0),
  }));
  const archTotals = arches.map((_, ai) => images.reduce((s, img) => s + img.perArch[ai], 0));
  const showUrl = !!state.showImgUrl;

  const sorted = images.map((img, i) => ({ img, i }));
  const sm = state.imgSort.dir === 'asc' ? 1 : -1;
  const sc = state.imgSort.col;
  if (sc === 'name') sorted.sort((a, b) => sm * (a.img.name || a.img.repo).localeCompare(b.img.name || b.img.repo));
  else if (sc === 'repo') sorted.sort((a, b) => sm * a.img.repo.localeCompare(b.img.repo));
  else if (sc === 'ref') sorted.sort((a, b) => sm * (a.img.ref || '').localeCompare(b.img.ref || ''));
  else if (sc === 'total') sorted.sort((a, b) => sm * (a.img.total - b.img.total));
  else if (sc.startsWith('arch:')) {
    const ai = arches.indexOf(sc.slice(5));
    if (ai >= 0) sorted.sort((a, b) => sm * (a.img.perArch[ai] - b.img.perArch[ai]));
  }

  let html = `<button class="btn-back" onclick="navigate('package','${esc(pkg.n)}')">\u2190 Back to ${esc(pkg.n)}</button>
  <h2 style="font-size:1.3rem;font-weight:700;margin:0 0 0.75rem">${esc(pkg.n)} ${esc(ver.v)}</h2>
  <div class="stat-strip">
    ${statBox(ver.ic, 'Images')}
    ${arches.map((a, i) => statBox(fmtSize(archTotals[i]), a)).join('')}
    ${statBox(fmtSize(ver.ts), 'Total (all arch)', 'info')}
  </div>`;

  if (arches.length > 1) {
    html += `<div class="chart-row">
      <div>
        <div class="section-title">Architecture comparison</div>
        <div class="section-sub">Total compressed size per architecture</div>
        <div class="chart-card"><canvas id="archBar" style="height:220px"></canvas></div>
      </div>
      <div>
        <div class="section-title">Top 10 largest images</div>
        <div class="section-sub">By total size across all architectures</div>
        <div class="chart-card"><canvas id="topBar" style="height:300px"></canvas></div>
      </div>
    </div>`;
  } else {
    html += `<div class="section-title">Top 10 largest images</div>
    <div class="section-sub">By total size across all architectures</div>
    <div class="chart-card"><canvas id="topBar" style="height:300px"></canvas></div>`;
  }

  html += `<div class="section-title">All images (${ver.ic})</div>
  <div class="toggle-row"><label><input type="checkbox" ${showUrl ? 'checked' : ''} onchange="toggleImgUrlCol()"> Show full image URL column</label></div>
  <div class="table-wrap" style="max-height:600px"><table><thead><tr>
    <th class="num">#</th>
    ${sortTh('Image', 'imgSort', 'name', false)}
    ${showUrl ? sortTh('Image URL', 'imgSort', 'ref', false) : ''}
    ${arches.map(a => sortTh(a, 'imgSort', 'arch:' + a, true)).join('')}
    ${sortTh('Total', 'imgSort', 'total', true)}
  </tr></thead><tbody>`;

  sorted.forEach(({ img }, i) => {
    const displayName = img.name || img.repo;
    const hasName = !!img.name;
    let nameCell;
    if (hasName) {
      nameCell = `<td style="max-width:400px"><span class="img-name-cell"><span class="name-text" title="${esc(img.ref)}">${esc(displayName)}</span><button class="btn-copy" onclick="copyPullSpec(this,'${esc(img.ref)}')" title="Copy image pull spec">copy</button></span></td>`;
    } else {
      nameCell = `<td style="max-width:400px;overflow:hidden;text-overflow:ellipsis" title="${esc(img.ref)}">${esc(displayName)}</td>`;
    }
    html += `<tr><td class="num">${i + 1}</td>${nameCell}`;
    if (showUrl) html += `<td class="col-imgurl" title="${esc(img.ref)}">${esc(img.ref)}</td>`;
    img.perArch.forEach(s => { html += `<td class="num">${fmtSize(s)}</td>`; });
    html += `<td class="num" style="font-weight:600">${fmtSize(img.total)}</td></tr>`;
  });
  html += '</tbody></table></div>';
  document.getElementById('app').innerHTML = html;

  requestAnimationFrame(() => {
    const ac = document.getElementById('archBar');
    if (ac) makeBarChart(ac, arches,
      [{ name: 'Compressed size (GB)', data: archTotals.map(s => +(s / 1073741824).toFixed(1)) }],
      { suffix: ' GB' });
    const tc = document.getElementById('topBar');
    if (tc) makeBarChart(tc,
      images.slice(0, 10).map(img => (img.name || img.repo).split('/').pop()),
      [{ name: 'Total size (GB)', data: images.slice(0, 10).map(img => +(img.total / 1073741824).toFixed(2)) }],
      { horizontal: true, suffix: ' GB' });
  });
}

// --- Render dispatcher ---
function render() {
  if (state.view === 'summary') renderSummary();
  else if (state.view === 'package') renderPackage();
  else if (state.view === 'version') renderVersion();
}

initTheme();
render();
</script>
</body>
</html>
"""


def generate_html(compact_data, chartjs_src, repo_url=""):
    html = HTML_TEMPLATE
    html = html.replace("%%CHARTJS%%", chartjs_src)
    html = html.replace("%%DATA%%", json.dumps(compact_data, separators=(",", ":")))
    html = html.replace("%%REPO_URL%%", repo_url)
    return html


def main():
    if len(sys.argv) < 2:
        print("Usage: generate-report.py <sizes.json> [output.html]")
        print("  Generates a self-contained HTML report from fbc-size-analyzer JSON output.")
        sys.exit(1)

    sizes_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "index.html"

    print(f"Reading {sizes_path}...")
    with open(sizes_path) as f:
        data = json.load(f)

    print(f"Compacting data ({data.get('package_count', '?')} packages)...")
    compact = compact_data(data)

    chartjs = get_chartjs()
    print(f"Chart.js: {len(chartjs) // 1024} KB")

    repo_url = os.environ.get("REPO_URL", "")
    html = generate_html(compact, chartjs, repo_url)

    with open(output_path, "w") as f:
        f.write(html)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"Written {output_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
