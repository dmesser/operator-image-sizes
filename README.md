# Operator Related Image Sizes Explorer

Analyzes and visualizes the total size of related images shipped with each operator in a Red Hat File-Based Catalog (FBC). Helps identify operators with the largest image footprint across architectures.

## Quick start

### 1. Build the analyzer

```bash
go build -o fbc-size-analyzer .
```

### 2. Analyze a catalog

```bash
./fbc-size-analyzer \
  -a ~/.opm-docker/config.json \
  -d ALL -f json \
  ~/path/to/redhat-operator-index-v4.21.json > sizes.json
```

Key flags:
- `-a` — path to a Docker auth config for private registries
- `-d ALL` — include per-image detail for every package (use a package name instead of `ALL` to scope)
- `-f json` — JSON output (default is a CLI table)
- `-c` — concurrency (default 25)

### 3. Generate the HTML report

```bash
python3 generate-report.py sizes.json index.html
```

This produces a single self-contained HTML file with no external dependencies. Open it locally or push to publish via GitHub Pages.

### 4. Publish

Commit and push `index.html` to the `main` branch. The included GitHub Actions workflow deploys it to GitHub Pages automatically.

## Features

- **Summary table** of all operators sorted by total related image size
- **Drill-down** into any operator to see size growth over releases (line + stacked bar charts)
- **Per-version detail** with architecture breakdown, top-10 largest images chart, and full image table
- **Sortable columns** — semver-aware version sorting, byte-correct size sorting
- **Light / dark theme** — respects browser preference with a manual toggle
- **Fully self-contained** — single HTML file, no CDN or external assets

## How it works

The Go binary (`main.go`) reads an FBC JSON file, extracts every `olm.bundle` entry's `spec.relatedImages`, fetches each image's manifest from the registry to compute compressed layer sizes per architecture, and outputs the results as JSON.

`generate-report.py` reads that JSON, compacts it with string interning for repository names, inlines Chart.js, and emits a single HTML file.
