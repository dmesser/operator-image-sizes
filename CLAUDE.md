# CLAUDE.md -- Agent orientation for optional-operators-size-tracker

## What this project does

Analyzes every operator in a Red Hat **File-Based Catalog (FBC)** to measure the
total compressed container image size each operator version pulls in via its
`relatedImages` metadata. Produces an interactive, self-contained HTML report
with drill-down from operator summary to per-version architecture breakdowns.

## Domain concepts

### OLM (Operator Lifecycle Manager)

OLM manages the lifecycle of Kubernetes operators on OpenShift. Operators are
packaged as **bundles** and listed in a **catalog** so that OLM can discover,
install, and upgrade them.

### File-Based Catalog (FBC)

An FBC is a JSON file containing a stream of concatenated JSON objects (one per
line, *not* a JSON array). Each object has a `schema` field:

- `olm.package` -- declares a package (operator name, default channel).
- `olm.channel` -- maps a channel name to an upgrade graph of bundle versions.
- `olm.bundle` -- the installable unit. Contains `name`, `package`, and most
  importantly `relatedImages`: the list of container images OLM must mirror and
  make available when installing that bundle.

### Related images

Each `olm.bundle` entry carries a `relatedImages` array:

```json
{
  "name": "operator_image",
  "image": "registry.redhat.io/foo/bar@sha256:abc123..."
}
```

- `name` -- a human-readable label (may be empty in older bundles).
- `image` -- the full pull spec, always pinned by digest (`@sha256:...`).

Images are typically multi-architecture manifest lists. The analyzer resolves
each manifest list and sums compressed layer sizes per architecture.

### Bundle naming and version extraction

Bundle names follow the pattern `<package>.<version>`, e.g.
`amq-broker-operator.v7.12.7-opr-1`. Automated respins append a timestamp
suffix: `v7.12.7-opr-1-0.1780501200.p`. The analyzer extracts the semver-style
version by stripping the package prefix and groups respins so only the latest
bundle per extracted version is reported.

## Repository structure

```
.
├── main.go               # Go analyzer -- registry inspection, caching, output
├── go.mod / go.sum        # Go module (requires Go 1.22+)
├── generate-report.py     # Python script -- compacts JSON, emits HTML report
├── index.html             # Generated self-contained HTML report (committed)
├── .github/workflows/
│   └── pages.yml          # Deploys index.html to GitHub Pages on push to main
├── .gitignore
├── README.md
└── CLAUDE.md              # This file
```

### Files not in git (generated at runtime)

| File | Purpose |
|------|---------|
| `fbc-size-analyzer` | Compiled Go binary |
| `sizes.json` | Full JSON output from the analyzer |
| `.fbc-size-cache.json` | Disk cache of image-digest-to-size mappings |
| `.chartjs-cache.js` | Locally cached copy of Chart.js |

## main.go -- the analyzer

Single-file Go program (~1200 lines). Key components:

### Data flow

1. **Parse FBC** -- reads concatenated JSON objects, collects all `olm.bundle`
   entries grouped by package name.
2. **Deduplicate bundles** -- groups bundles by extracted version, keeps only the
   latest (highest lexicographic bundle name) per version.
3. **Deduplicate images** -- within each bundle, tracks seen image digests to
   avoid counting the same image twice.
4. **Fetch manifests** -- resolves each unique image digest against the registry
   using the Docker Registry HTTP API v2. Handles manifest lists
   (multi-arch) by fetching sub-manifests per architecture. Supports
   token-based auth with refresh, exponential backoff, and retry on 429/5xx.
5. **Cache** -- stores `digest -> {arch: size}` mappings in
   `.fbc-size-cache.json`. Cache hits skip network calls entirely.
6. **Output** -- CLI table (default, uses `go-pretty`) or JSON (`-f json`).

### Key types

| Type | Role |
|------|------|
| `fbcEntry` | Parsed FBC JSON object (`schema`, `package`, `name`, `relatedImages`) |
| `relatedImage` | `{name, image}` from a bundle's `relatedImages` array |
| `imageResult` | Per-image output: name, pull spec, repo, per-arch sizes, total |
| `bundleResult` | Per-version rollup: image list, arch totals, total size |
| `packageResult` | Per-operator rollup: all versions, average total size |
| `jsonOutput` | Top-level JSON envelope: catalog path, timestamp, packages |

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `-a` | (none) | Path to Docker auth config JSON |
| `-d` | (none) | Package names for detail output, or `ALL` |
| `-f` | `table` | Output format: `table` or `json` |
| `-c` | `25` | Concurrency (parallel registry requests) |
| `-cache` | `.fbc-size-cache.json` | Cache file path |
| `-no-cache` | `false` | Disable disk cache |

## sizes.json -- analyzer output schema

The JSON output from `fbc-size-analyzer -f json` is the primary data file.
Agents answering questions about operator image sizes should read this file.

### Top-level structure

```json
{
  "catalog": "/path/to/redhat-operator-index-v4.22.json",
  "analyzed_at": "2026-07-20T18:05:44Z",
  "package_count": 145,
  "packages": [ ... ]
}
```

- `catalog` -- filesystem path to the FBC file that was analyzed.
- `analyzed_at` -- UTC timestamp of the analysis run.
- `package_count` -- number of operator packages.
- `packages` -- array of package objects, sorted by `avg_total_size` descending.

### Package object

```json
{
  "name": "advanced-cluster-management",
  "version_count": 4,
  "avg_total_size": 5284019200,
  "avg_total_size_human": "4.9 GB",
  "latest_version": "v2.17.0",
  "latest_total_size": 5074083840,
  "latest_total_size_human": "4.7 GB",
  "latest_image_count": 51,
  "versions": [ ... ]
}
```

- `avg_total_size` -- mean of `total_size` across all versions (bytes, all
  architectures summed). This is the primary sort key.
- `latest_*` fields -- summary of the highest version.
- `versions` -- present only when the package was included in the `-d` detail
  flag. Omitted for summary-only packages (when `-d ALL` was not used).

### Version object

```json
{
  "bundle_name": "advanced-cluster-management.v2.17.0",
  "version": "v2.17.0",
  "image_count": 51,
  "total_size": 5074083840,
  "total_size_human": "4.7 GB",
  "architectures": {
    "amd64": { "size": 2580000000, "size_human": "2.4 GB" },
    "arm64": { "size": 1200000000, "size_human": "1.1 GB" },
    "ppc64le": { "size": 800000000, "size_human": "745.1 MB" },
    "s390x": { "size": 494083840, "size_human": "471.2 MB" }
  },
  "images": [ ... ]
}
```

- `bundle_name` -- the FBC bundle entry name (includes respin suffix for
  automated rebuilds, e.g. `operator.v1.2.3-opr-1-0.1780501200.p`).
- `version` -- extracted semver-style version (respins collapsed).
- `architectures` -- per-architecture totals (sum of all image sizes for that
  architecture). Keys are bare architecture names (e.g. `arm64`, not
  `arm64/v8`).
- `images` -- array of image objects for this version, one per unique image
  digest.

### Image object

```json
{
  "name": "endpoint_monitoring_operator",
  "image": "registry.redhat.io/rhacm2/endpoint-monitoring-rhel9-operator@sha256:abc...",
  "repository": "rhacm2/endpoint-monitoring-rhel9-operator",
  "total_size": 128057344,
  "total_size_human": "122.1 MB",
  "architectures": {
    "amd64": { "size": 64028672, "size_human": "61.1 MB" },
    "arm64": { "size": 64028672, "size_human": "61.1 MB" }
  }
}
```

- `name` -- the `relatedImage.name` from the FBC bundle (e.g.
  `endpoint_monitoring_operator`). May be empty for older bundles.
- `image` -- full pull spec with digest (e.g.
  `registry.redhat.io/repo/image@sha256:...`).
- `repository` -- registry-relative repository path (e.g.
  `rhacm2/endpoint-monitoring-rhel9-operator`).
- `total_size` -- sum of all per-architecture compressed layer sizes (bytes).
- `architectures` -- map of architecture name to `{size, size_human}`. Only
  architectures present in the image's manifest list appear here.
- `error` -- (optional) present when the registry could not be reached or
  returned an error. When set, `total_size` is 0 and `architectures` is empty.

### Querying tips for agents

- To find an operator: filter `packages` by `name`.
- To compare versions: iterate `versions` array (sorted by bundle name).
- To get single-architecture sizes: access `architectures.<arch>.size` at the
  image or version level.
- All `size` values are compressed layer sizes in bytes.
- The `_human` fields are pre-formatted strings (e.g. `"4.7 GB"`) suitable for
  display.
- Image deduplication is already applied: each image digest appears at most once
  per version.

## generate-report.py -- the report builder

Python 3 script (no pip dependencies). Reads `sizes.json`, compacts the data
using string interning for repository names and image references, fetches
Chart.js (cached locally), and emits a single self-contained `index.html`.

### Compact data format

The compacted JSON uses short keys and integer indices into string tables to
minimize file size:

- `repos[]` -- interned repository name table (e.g. `"rhoai/odh-foo-rhel9"`)
- `refs[]` -- interned image reference table (full pull specs)
- `pkgs[]` -- array of package objects with:
  - `n` (name), `vc` (version count), `avg` (average total size)
  - `vs[]` -- versions, each with `v` (version), `ic` (image count),
    `ts` (total size), `ar` (architecture names), `as` (arch sizes),
    `im[]` (image rows)
- Image row format: `[repoIdx, totalSize, refIdx, name, arch1Size, ...]`

### HTML report features

- Three views: Summary (all operators) -> Package (version history with charts)
  -> Version (per-image table with arch breakdown)
- Chart.js line and bar charts with GB units
- Sortable tables (semver-aware, byte-value-aware)
- Light/dark theme with browser-default detection
- Image name display with copy-to-clipboard for pull specs
- Optional full image URL column (hidden by default)
- `REPO_URL` env var injects a GitHub link into the header

## Workflow: updating the report

```bash
# 1. Build (if source changed)
go build -o fbc-size-analyzer .

# 2. Run analysis (cache accelerates repeat runs)
./fbc-size-analyzer \
  -a ~/.opm-docker/config.json \
  -d ALL -f json \
  ~/path/to/redhat-operator-index-v4.XX.json > sizes.json

# 3. Generate HTML
python3 generate-report.py sizes.json

# 4. Publish
git add index.html && git commit -m "Update report" && git push
```

The GitHub Actions workflow (`.github/workflows/pages.yml`) deploys `index.html`
to GitHub Pages on any push to `main` that touches that file.

## Development notes

- The cache (`.fbc-size-cache.json`) persists across runs. It does not need to be
  cleared when changing dedup logic or output format -- it only maps image digests
  to per-architecture byte sizes, which are immutable for a given digest.
- The FBC input file can be obtained using `opm` (Operator Package Manager) or by
  extracting it from a published catalog image (e.g. via `oc image extract`).
- Registry auth is read from a Docker-format `config.json` (same format as
  `~/.docker/config.json`). The `auths` map keys are matched against image
  registry hostnames.
- The analyzer handles both base64-encoded credentials (`auth` field) and
  username/password pairs in the auth config.
