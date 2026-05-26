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

    def get_repo_id(name):
        if name not in repo_idx:
            repo_idx[name] = len(repo_table)
            repo_table.append(name)
        return repo_idx[name]

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
                row = [get_repo_id(img["repository"]), img["total_size"]]
                for a in arches:
                    arch_data = img_arches.get(a)
                    row.append(arch_data["size"] if isinstance(arch_data, dict) else 0)
                cv["im"].append(row)
            cp["vs"].append(cv)
        compact.append(cp)

    return {"repos": repo_table, "pkgs": compact, "meta": {
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
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operator Related Image Sizes Explorer</title>
<style>
:root {
  --bg: #ffffff; --bg-elevated: #f8f9fa; --bg-card: #ffffff;
  --text-primary: #1a1a2e; --text-secondary: #4a4a6a; --text-tertiary: #8888a8;
  --accent: #2563eb; --accent-hover: #1d4ed8;
  --border: #e2e8f0; --border-light: #f1f5f9;
  --stat-bg: #f1f5f9;
  --danger: #dc2626; --info: #2563eb; --success: #16a34a; --warning: #d97706;
  --table-stripe: #f8fafc; --table-hover: #f1f5f9;
  --chart-1: #3b82f6; --chart-2: #ef4444; --chart-3: #22c55e;
  --chart-4: #f59e0b; --chart-5: #8b5cf6; --chart-6: #06b6d4;
  --chart-7: #ec4899; --chart-8: #14b8a6;
  --chart-grid: rgba(0,0,0,0.06); --chart-text: #64748b;
  --scrollbar-thumb: #cbd5e1; --scrollbar-track: #f1f5f9;
}
[data-theme="dark"] {
  --bg: #0f1117; --bg-elevated: #1a1b26; --bg-card: #1a1b26;
  --text-primary: #e2e8f0; --text-secondary: #94a3b8; --text-tertiary: #64748b;
  --accent: #60a5fa; --accent-hover: #93bbfd;
  --border: #2d2d3f; --border-light: #23233a;
  --stat-bg: #1e1e30;
  --danger: #f87171; --info: #60a5fa; --success: #4ade80; --warning: #fbbf24;
  --table-stripe: #16162a; --table-hover: #1e1e35;
  --chart-grid: rgba(255,255,255,0.08); --chart-text: #94a3b8;
  --scrollbar-thumb: #3d3d5c; --scrollbar-track: #1a1b26;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1117; --bg-elevated: #1a1b26; --bg-card: #1a1b26;
    --text-primary: #e2e8f0; --text-secondary: #94a3b8; --text-tertiary: #64748b;
    --accent: #60a5fa; --accent-hover: #93bbfd;
    --border: #2d2d3f; --border-light: #23233a;
    --stat-bg: #1e1e30;
    --danger: #f87171; --info: #60a5fa; --success: #4ade80; --warning: #fbbf24;
    --table-stripe: #16162a; --table-hover: #1e1e35;
    --chart-grid: rgba(255,255,255,0.08); --chart-text: #94a3b8;
    --scrollbar-thumb: #3d3d5c; --scrollbar-track: #1a1b26;
  }
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
  background: var(--bg); color: var(--text-primary);
  line-height: 1.5; -webkit-font-smoothing: antialiased;
}
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--scrollbar-track); }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 4px; }
.app { max-width: 1400px; margin: 0 auto; padding: 24px 32px; }
.top-bar {
  display: flex; align-items: center; gap: 12px; margin-bottom: 24px;
  padding-bottom: 16px; border-bottom: 1px solid var(--border);
}
.top-bar h1 { font-size: 20px; font-weight: 700; flex: 1; }
.top-bar .meta { color: var(--text-tertiary); font-size: 13px; white-space: nowrap; }
.gh-link {
  display: inline-flex; align-items: center; color: var(--text-secondary);
  transition: color 0.15s;
}
.gh-link:hover { color: var(--text-primary); }
.gh-link svg { width: 22px; height: 22px; fill: currentColor; }
.theme-btn {
  background: none; border: 1px solid var(--border); border-radius: 6px;
  color: var(--text-secondary); cursor: pointer; padding: 4px 8px;
  font-size: 16px; line-height: 1; transition: all 0.15s;
}
.theme-btn:hover { border-color: var(--accent); color: var(--accent); }
.stats-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin-bottom: 20px;
}
.stat-card {
  background: var(--stat-bg); border-radius: 8px; padding: 14px 16px;
  border: 1px solid var(--border-light);
}
.stat-value { font-size: 22px; font-weight: 700; line-height: 1.2; }
.stat-value.danger { color: var(--danger); }
.stat-value.info { color: var(--info); }
.stat-label { font-size: 12px; color: var(--text-tertiary); margin-top: 2px; }
.search-row { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.search-input {
  padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-elevated); color: var(--text-primary); font-size: 14px;
  width: 300px; outline: none; transition: border-color 0.15s;
}
.search-input:focus { border-color: var(--accent); }
.search-input::placeholder { color: var(--text-tertiary); }
.section-title { font-size: 16px; font-weight: 600; margin: 20px 0 6px; }
.section-sub { font-size: 12px; color: var(--text-tertiary); margin-bottom: 10px; }
.table-wrap {
  border: 1px solid var(--border); border-radius: 8px; overflow: auto;
  max-height: 600px; margin-bottom: 20px;
}
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead { position: sticky; top: 0; z-index: 1; }
th {
  background: var(--bg-elevated); padding: 8px 12px; text-align: left;
  font-weight: 600; font-size: 12px; color: var(--text-secondary);
  border-bottom: 1px solid var(--border); white-space: nowrap;
  cursor: pointer; user-select: none; transition: color 0.15s;
}
th:hover { color: var(--accent); }
th.sorted { color: var(--accent); }
th .arrow { font-size: 10px; margin-left: 4px; }
th.r, td.r { text-align: right; }
td {
  padding: 6px 12px; border-bottom: 1px solid var(--border-light);
  white-space: nowrap;
}
tr:nth-child(even) td { background: var(--table-stripe); }
tr:hover td { background: var(--table-hover); }
.link {
  color: var(--accent); cursor: pointer; font-weight: 600;
  text-decoration: none; transition: color 0.15s;
}
.link:hover { color: var(--accent-hover); text-decoration: underline; }
.btn-back {
  display: inline-flex; align-items: center; gap: 4px; background: none;
  border: 1px solid var(--border); border-radius: 6px; color: var(--text-secondary);
  cursor: pointer; padding: 5px 12px; font-size: 13px; transition: all 0.15s;
  margin-bottom: 16px;
}
.btn-back:hover { border-color: var(--accent); color: var(--accent); }
.chart-wrap {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; margin-bottom: 20px; position: relative;
}
.chart-row { display: flex; gap: 16px; margin-bottom: 20px; }
.chart-row > div { flex: 1; }
</style>
</head>
<body>
<div class="app" id="app"></div>

<script>
%%CHARTJS%%
</script>

<script>
const RAW = %%DATA%%;
const REPO_URL = "%%REPO_URL%%";

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

function cmpSemver(a, b) {
  const re = /(\d+)/g;
  const pa = a.match(re) || [], pb = b.match(re) || [];
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const na = parseInt(pa[i] || '0', 10), nb = parseInt(pb[i] || '0', 10);
    if (na !== nb) return na - nb;
  }
  return a.localeCompare(b);
}

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (k === 'className') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object')
      Object.assign(e.style, v);
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    if (typeof c === 'string' || typeof c === 'number') e.appendChild(document.createTextNode(c));
    else if (Array.isArray(c)) c.forEach(x => x && e.appendChild(x));
    else e.appendChild(c);
  }
  return e;
}

const CHART_COLORS = ['#3b82f6','#ef4444','#22c55e','#f59e0b','#8b5cf6','#06b6d4','#ec4899','#14b8a6'];
let activeCharts = [];

function destroyCharts() {
  activeCharts.forEach(c => c.destroy());
  activeCharts = [];
}

function isDark() {
  const t = document.documentElement.getAttribute('data-theme');
  if (t === 'dark') return true;
  if (t === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function chartDefaults() {
  const dark = isDark();
  return {
    color: dark ? '#94a3b8' : '#64748b',
    borderColor: dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)',
  };
}

function makeLineChart(canvas, categories, seriesData, opts = {}) {
  const cd = chartDefaults();
  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: categories,
      datasets: seriesData.map((s, i) => ({
        label: s.name,
        data: s.data,
        borderColor: CHART_COLORS[i % CHART_COLORS.length],
        backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + '22',
        fill: opts.fill || false,
        tension: 0.3,
        pointRadius: categories.length > 20 ? 2 : 4,
        pointHoverRadius: 6,
        borderWidth: 2,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: seriesData.length > 1, labels: { color: cd.color, font: { size: 12 } } },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: { ticks: { color: cd.color, font: { size: 11 }, maxRotation: 45 }, grid: { color: cd.borderColor } },
        y: {
          ticks: { color: cd.color, font: { size: 11 },
            callback: v => v + (opts.suffix || '') },
          grid: { color: cd.borderColor },
        },
      },
    },
  });
  activeCharts.push(chart);
  return chart;
}

function makeBarChart(canvas, categories, seriesData, opts = {}) {
  const cd = chartDefaults();
  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: categories,
      datasets: seriesData.map((s, i) => ({
        label: s.name,
        data: s.data,
        backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + (opts.stacked ? 'cc' : 'aa'),
        borderColor: CHART_COLORS[i % CHART_COLORS.length],
        borderWidth: 1,
        borderRadius: 3,
      })),
    },
    options: {
      indexAxis: opts.horizontal ? 'y' : 'x',
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 600, easing: 'easeOutQuart' },
      plugins: {
        legend: { display: seriesData.length > 1, labels: { color: cd.color, font: { size: 12 } } },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          stacked: opts.stacked || false,
          ticks: { color: cd.color, font: { size: 11 }, maxRotation: 45,
            callback: opts.horizontal ? (v => v + (opts.suffix || '')) : undefined },
          grid: { color: cd.borderColor },
        },
        y: {
          stacked: opts.stacked || false,
          ticks: { color: cd.color, font: { size: 11 },
            callback: opts.horizontal ? undefined : (v => v + (opts.suffix || '')) },
          grid: { color: cd.borderColor },
        },
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
};

function navigate(view, pkgName, verIdx) {
  state.view = view;
  state.pkgName = pkgName;
  state.verIdx = verIdx;
  render();
}

function toggleSort(key, col) {
  const s = state[key];
  if (s.col === col) s.dir = s.dir === 'asc' ? 'desc' : 'asc';
  else { s.col = col; s.dir = 'desc'; }
  render();
}

function sortHeader(label, sortKey, col, align) {
  const s = state[sortKey];
  const active = s.col === col;
  const arrow = active ? (s.dir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
  const th = el('th', {
    className: (active ? 'sorted' : '') + (align === 'right' ? ' r' : ''),
    onClick: () => toggleSort(sortKey, col),
  }, label + arrow);
  return th;
}

// --- Views ---
function renderSummary() {
  destroyCharts();
  const app = document.getElementById('app');
  app.innerHTML = '';

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
  const biggest = RAW.pkgs.reduce((max, p) => p.lt > max.lt ? p : max, RAW.pkgs[0]);

  app.appendChild(el('div', { className: 'stats-grid' },
    statCard(RAW.pkgs.length, 'Operators'),
    statCard(fmtSize(totalLatest), 'Total latest (all arch)'),
    statCard(fmtSize(biggest.lt), 'Largest: ' + biggest.n, 'danger'),
    statCard(totalImages, 'Total images (latest)'),
  ));

  const searchInput = el('input', {
    className: 'search-input', type: 'search',
    placeholder: 'Filter operators...', value: state.search,
    onInput: (e) => { state.search = e.target.value; render(); },
  });
  app.appendChild(el('div', { className: 'search-row' }, searchInput));

  const thead = el('tr', null,
    el('th', { className: 'r' }, '#'),
    sortHeader('Operator', 'sumSort', 'name', 'left'),
    sortHeader('Versions', 'sumSort', 'vc', 'right'),
    sortHeader('Avg total (all arch)', 'sumSort', 'avg', 'right'),
    sortHeader('Latest total (all arch)', 'sumSort', 'latest', 'right'),
    sortHeader('Images (latest)', 'sumSort', 'imgs', 'right'),
  );

  const tbody = el('tbody');
  list.forEach((p, i) => {
    const link = el('a', { className: 'link', onClick: () => navigate('package', p.n) }, p.n);
    tbody.appendChild(el('tr', null,
      el('td', { className: 'r' }, (i + 1).toString()),
      el('td', null, link),
      el('td', { className: 'r' }, p.vc.toString()),
      el('td', { className: 'r' }, fmtSize(p.avg)),
      el('td', { className: 'r' }, fmtSize(p.lt)),
      el('td', { className: 'r' }, p.li.toString()),
    ));
  });

  app.appendChild(el('div', { className: 'table-wrap' },
    el('table', null, el('thead', null, thead), tbody)
  ));
}

function renderPackage() {
  destroyCharts();
  const app = document.getElementById('app');
  app.innerHTML = '';

  const pkg = RAW.pkgs.find(p => p.n === state.pkgName);
  if (!pkg) { navigate('summary'); return; }
  const versions = pkg.vs;

  app.appendChild(el('button', { className: 'btn-back', onClick: () => navigate('summary') },
    '\u2190 Back to list'));
  app.appendChild(el('h1', { style: { fontSize: '20px', fontWeight: 700, marginBottom: '16px' } }, pkg.n));

  app.appendChild(el('div', { className: 'stats-grid' },
    statCard(pkg.vc, 'Versions'),
    statCard(fmtSize(pkg.avg), 'Avg total size'),
    statCard(fmtSize(pkg.lt), 'Latest: ' + pkg.lv, 'info'),
    statCard(pkg.li, 'Images (latest)'),
  ));

  // Line chart: total over releases
  const chartVsRaw = [...versions].reverse();
  let chartVs = chartVsRaw;
  if (chartVs.length > 30) {
    const step = Math.ceil(chartVs.length / 30);
    chartVs = chartVs.filter((_, i) => i % step === 0 || i === chartVs.length - 1);
  }

  app.appendChild(el('div', { className: 'section-title' }, 'Total size over releases (all architectures combined)'));
  app.appendChild(el('div', { className: 'section-sub' }, 'Source: fbc-size-analyzer, compressed layer sizes'));
  const lineWrap = el('div', { className: 'chart-wrap' }, el('canvas', { id: 'lineChart', style: { height: '280px' } }));
  app.appendChild(lineWrap);
  requestAnimationFrame(() => {
    const c = document.getElementById('lineChart');
    if (c) makeLineChart(c, chartVs.map(v => v.v),
      [{ name: 'Total all-arch (GB)', data: chartVs.map(v => +(v.ts / 1073741824).toFixed(1)) }],
      { fill: true, suffix: ' GB' });
  });

  // Stacked bar: per-arch
  const allArchs = [...new Set(versions.flatMap(v => v.ar))].sort();
  if (allArchs.length > 1) {
    app.appendChild(el('div', { className: 'section-title' }, 'Per-architecture breakdown over releases'));
    app.appendChild(el('div', { className: 'section-sub' }, 'Stacked bar: each color is one architecture'));
    const barWrap = el('div', { className: 'chart-wrap' }, el('canvas', { id: 'stackedBar', style: { height: '280px' } }));
    app.appendChild(barWrap);
    requestAnimationFrame(() => {
      const c = document.getElementById('stackedBar');
      if (c) makeBarChart(c, chartVs.map(v => v.v),
        allArchs.map(arch => ({
          name: arch,
          data: chartVs.map(v => {
            const idx = v.ar.indexOf(arch);
            return idx >= 0 ? +(v.as[idx] / 1073741824).toFixed(1) : 0;
          }),
        })),
        { stacked: true, suffix: ' GB' });
    });
  }

  // Versions table
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

  app.appendChild(el('div', { className: 'section-title' }, 'All versions'));
  const thead = el('tr', null,
    sortHeader('Version', 'pkgSort', 'ver', 'left'),
    sortHeader('Images', 'pkgSort', 'ic', 'right'),
    ...allArchs.map(a => sortHeader(a, 'pkgSort', 'arch:' + a, 'right')),
    sortHeader('Total', 'pkgSort', 'total', 'right'),
  );
  const tbody = el('tbody');
  indexed.forEach(({ v, oi }) => {
    const link = el('a', { className: 'link', onClick: () => navigate('version', pkg.n, oi) }, v.v);
    tbody.appendChild(el('tr', null,
      el('td', null, link),
      el('td', { className: 'r' }, v.ic.toString()),
      ...allArchs.map(arch => {
        const idx = v.ar.indexOf(arch);
        return el('td', { className: 'r' }, fmtSize(idx >= 0 ? v.as[idx] : 0));
      }),
      el('td', { className: 'r', style: { fontWeight: 600 } }, fmtSize(v.ts)),
    ));
  });
  app.appendChild(el('div', { className: 'table-wrap', style: { maxHeight: '500px' } },
    el('table', null, el('thead', null, thead), tbody)
  ));
}

function renderVersion() {
  destroyCharts();
  const app = document.getElementById('app');
  app.innerHTML = '';

  const pkg = RAW.pkgs.find(p => p.n === state.pkgName);
  if (!pkg) { navigate('summary'); return; }
  const ver = pkg.vs[state.verIdx];
  if (!ver) { navigate('package', pkg.n); return; }
  const arches = ver.ar;

  const images = ver.im.map(row => ({
    repo: RAW.repos[row[0]], total: row[1],
    perArch: arches.map((_, ai) => row[2 + ai] || 0),
  }));

  const archTotals = arches.map((_, ai) => images.reduce((s, img) => s + img.perArch[ai], 0));

  app.appendChild(el('button', { className: 'btn-back', onClick: () => navigate('package', pkg.n) },
    '\u2190 Back to ' + pkg.n));
  app.appendChild(el('h1', { style: { fontSize: '20px', fontWeight: 700, marginBottom: '16px' } },
    pkg.n + ' ' + ver.v));

  const statCols = [statCard(ver.ic, 'Images')];
  arches.forEach((a, i) => statCols.push(statCard(fmtSize(archTotals[i]), a)));
  statCols.push(statCard(fmtSize(ver.ts), 'Total (all arch)', 'info'));
  app.appendChild(el('div', { className: 'stats-grid' }, ...statCols));

  if (arches.length > 1) {
    const chartRow = el('div', { className: 'chart-row' });
    const leftWrap = el('div', null,
      el('div', { className: 'section-title' }, 'Architecture comparison'),
      el('div', { className: 'section-sub' }, 'Total compressed size per architecture'),
      el('div', { className: 'chart-wrap' }, el('canvas', { id: 'archBar', style: { height: '220px' } })),
    );
    const rightWrap = el('div', null,
      el('div', { className: 'section-title' }, 'Top 10 largest images'),
      el('div', { className: 'section-sub' }, 'By total size across all architectures'),
      el('div', { className: 'chart-wrap' }, el('canvas', { id: 'topBar', style: { height: '300px' } })),
    );
    chartRow.appendChild(leftWrap);
    chartRow.appendChild(rightWrap);
    app.appendChild(chartRow);

    requestAnimationFrame(() => {
      const ac = document.getElementById('archBar');
      if (ac) makeBarChart(ac, arches,
        [{ name: 'Compressed size (GB)', data: archTotals.map(s => +(s / 1073741824).toFixed(1)) }],
        { suffix: ' GB' });
      const tc = document.getElementById('topBar');
      if (tc) makeBarChart(tc,
        images.slice(0, 10).map(img => img.repo.split('/').pop()),
        [{ name: 'Total size (GB)', data: images.slice(0, 10).map(img => +(img.total / 1073741824).toFixed(2)) }],
        { horizontal: true, suffix: ' GB' });
    });
  } else {
    app.appendChild(el('div', { className: 'section-title' }, 'Top 10 largest images'));
    app.appendChild(el('div', { className: 'section-sub' }, 'By total size across all architectures'));
    const topWrap = el('div', { className: 'chart-wrap' }, el('canvas', { id: 'topBar', style: { height: '300px' } }));
    app.appendChild(topWrap);
    requestAnimationFrame(() => {
      const tc = document.getElementById('topBar');
      if (tc) makeBarChart(tc,
        images.slice(0, 10).map(img => img.repo.split('/').pop()),
        [{ name: 'Total size (GB)', data: images.slice(0, 10).map(img => +(img.total / 1073741824).toFixed(2)) }],
        { horizontal: true, suffix: ' GB' });
    });
  }

  // Images table
  const sorted = images.map((img, i) => ({ img, i }));
  const sm = state.imgSort.dir === 'asc' ? 1 : -1;
  const sc = state.imgSort.col;
  if (sc === 'repo') sorted.sort((a, b) => sm * a.img.repo.localeCompare(b.img.repo));
  else if (sc === 'total') sorted.sort((a, b) => sm * (a.img.total - b.img.total));
  else if (sc.startsWith('arch:')) {
    const ai = arches.indexOf(sc.slice(5));
    if (ai >= 0) sorted.sort((a, b) => sm * (a.img.perArch[ai] - b.img.perArch[ai]));
  }

  app.appendChild(el('div', { className: 'section-title' }, 'All images (' + ver.ic + ')'));
  const thead = el('tr', null,
    el('th', { className: 'r' }, '#'),
    sortHeader('Repository', 'imgSort', 'repo', 'left'),
    ...arches.map(a => sortHeader(a, 'imgSort', 'arch:' + a, 'right')),
    sortHeader('Total', 'imgSort', 'total', 'right'),
  );
  const tbody = el('tbody');
  sorted.forEach(({ img }, i) => {
    tbody.appendChild(el('tr', null,
      el('td', { className: 'r' }, (i + 1).toString()),
      el('td', { style: { maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis' } }, img.repo),
      ...img.perArch.map(s => el('td', { className: 'r' }, fmtSize(s))),
      el('td', { className: 'r', style: { fontWeight: 600 } }, fmtSize(img.total)),
    ));
  });
  app.appendChild(el('div', { className: 'table-wrap' },
    el('table', null, el('thead', null, thead), tbody)
  ));
}

function statCard(value, label, tone) {
  const valDiv = el('div', { className: 'stat-value' + (tone ? ' ' + tone : '') }, String(value));
  const labDiv = el('div', { className: 'stat-label' }, label);
  return el('div', { className: 'stat-card' }, valDiv, labDiv);
}

// --- Theme ---
function getEffectiveTheme() {
  const t = document.documentElement.getAttribute('data-theme');
  if (t) return t;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function cycleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  let next;
  if (!current) next = getEffectiveTheme() === 'dark' ? 'light' : 'dark';
  else if (current === 'dark') next = 'light';
  else { document.documentElement.removeAttribute('data-theme'); updateThemeBtn(); render(); return; }
  document.documentElement.setAttribute('data-theme', next);
  updateThemeBtn();
  render();
}

function updateThemeBtn() {
  const btn = document.getElementById('themeBtn');
  if (!btn) return;
  const t = getEffectiveTheme();
  btn.textContent = t === 'dark' ? '\u2600\uFE0F' : '\uD83C\uDF19';
  btn.title = t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
}

// --- Render dispatcher ---
function render() {
  const app = document.getElementById('app');

  // Top bar (rebuild each time for simplicity)
  const topBar = el('div', { className: 'top-bar' },
    el('h1', null, 'Operator Related Image Sizes Explorer'),
    el('span', { className: 'meta' }, 'Red Hat operator catalog v4.21'),
    REPO_URL ? el('a', { className: 'gh-link', href: REPO_URL, target: '_blank', title: 'View on GitHub' },
      ghSvg()) : null,
    el('button', { className: 'theme-btn', id: 'themeBtn', onClick: cycleTheme }),
  );

  if (state.view === 'summary') renderSummary();
  else if (state.view === 'package') renderPackage();
  else if (state.view === 'version') renderVersion();

  app.prepend(topBar);
  updateThemeBtn();
}

function ghSvg() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('width', '22');
  svg.setAttribute('height', '22');
  svg.setAttribute('fill', 'currentColor');
  svg.innerHTML = '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>';
  return svg;
}

// Boot
render();
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
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
