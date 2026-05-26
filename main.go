package main

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/jedib0t/go-pretty/v6/table"
	"github.com/jedib0t/go-pretty/v6/text"
)

// ---------------------------------------------------------------------------
// FBC types
// ---------------------------------------------------------------------------

type relatedImage struct {
	Name  string `json:"name"`
	Image string `json:"image"`
}

type fbcEntry struct {
	Schema        string         `json:"schema"`
	Package       string         `json:"package"`
	Name          string         `json:"name"`
	RelatedImages []relatedImage `json:"relatedImages,omitempty"`
}

// ---------------------------------------------------------------------------
// Registry manifest types
// ---------------------------------------------------------------------------

type manifestPlatform struct {
	Architecture string `json:"architecture"`
	OS           string `json:"os"`
	Variant      string `json:"variant,omitempty"`
}

type manifestDescriptor struct {
	MediaType string           `json:"mediaType"`
	Digest    string           `json:"digest"`
	Size      int64            `json:"size"`
	Platform  manifestPlatform `json:"platform"`
}

type manifestEnvelope struct {
	MediaType string               `json:"mediaType"`
	Manifests []manifestDescriptor `json:"manifests,omitempty"` // index / list
	Layers    []struct {
		Size int64 `json:"size"`
	} `json:"layers,omitempty"` // single manifest
}

// ---------------------------------------------------------------------------
// Analysis data model
// ---------------------------------------------------------------------------

type archSizes = map[string]int64

type imageResult struct {
	Name     string    `json:"name"`
	ImageRef string    `json:"image"`
	Repo     string    `json:"repository"`
	Sizes    archSizes `json:"architectures,omitempty"`
	Total    int64     `json:"total_size"`
	Error    string    `json:"error,omitempty"`
}

type bundleResult struct {
	Package    string
	BundleName string
	Version    string
	ImageCount int
	Images     []imageResult
	ArchTotals archSizes
	TotalSize  int64
}

type packageResult struct {
	Name         string
	Bundles      []bundleResult
	AvgTotalSize float64
}

// ---------------------------------------------------------------------------
// CLI flag helpers
// ---------------------------------------------------------------------------

type stringSlice []string

func (s *stringSlice) String() string { return strings.Join(*s, ",") }
func (s *stringSlice) Set(v string) error {
	for _, part := range strings.Split(v, ",") {
		if t := strings.TrimSpace(part); t != "" {
			*s = append(*s, t)
		}
	}
	return nil
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func parseImageRef(ref string) (registry, repository, refType, refValue string) {
	if idx := strings.LastIndex(ref, "@"); idx >= 0 {
		refType, refValue = "digest", ref[idx+1:]
		ref = ref[:idx]
	} else if slashIdx := strings.LastIndex(ref, "/"); slashIdx >= 0 {
		tail := ref[slashIdx+1:]
		if ci := strings.Index(tail, ":"); ci >= 0 {
			refType, refValue = "tag", tail[ci+1:]
			ref = ref[:slashIdx+1] + tail[:ci]
		} else {
			refType, refValue = "tag", "latest"
		}
	} else {
		refType, refValue = "tag", "latest"
	}

	parts := strings.SplitN(ref, "/", 2)
	if len(parts) == 1 {
		return "registry-1.docker.io", "library/" + parts[0], refType, refValue
	}
	if strings.Contains(parts[0], ".") || strings.Contains(parts[0], ":") {
		return parts[0], parts[1], refType, refValue
	}
	return "registry-1.docker.io", ref, refType, refValue
}

func extractDigest(ref string) string {
	if idx := strings.LastIndex(ref, "@"); idx >= 0 {
		return ref[idx+1:]
	}
	return ""
}

var versionRe = regexp.MustCompile(`v?\d+\.\d+[\d.]*`)

func extractVersion(bundleName, packageName string) string {
	prefix := packageName + "."
	if strings.HasPrefix(bundleName, prefix) {
		return bundleName[len(prefix):]
	}
	if m := versionRe.FindString(bundleName); m != "" {
		return m
	}
	return bundleName
}

func formatSize(b int64) string {
	if b < 0 {
		return "ERR"
	}
	if b == 0 {
		return "0 B"
	}
	v := float64(b)
	for _, u := range []string{"B", "KB", "MB", "GB", "TB"} {
		if v < 1024 {
			switch u {
			case "B", "KB":
				return fmt.Sprintf("%.0f %s", v, u)
			default:
				return fmt.Sprintf("%.1f %s", v, u)
			}
		}
		v /= 1024
	}
	return fmt.Sprintf("%.1f PB", v)
}

var wwwAuthRe = regexp.MustCompile(`(\w+)="([^"]*)"`)

// ---------------------------------------------------------------------------
// Disk cache  (digest → arch → compressed bytes)
// ---------------------------------------------------------------------------

type cacheFile struct {
	Version int                        `json:"version"`
	Entries map[string]map[string]int64 `json:"entries"`
}

type sizeCache struct {
	mu      sync.RWMutex
	entries map[string]map[string]int64
	path    string
	dirty   bool
}

func loadCache(path string) *sizeCache {
	c := &sizeCache{path: path, entries: make(map[string]map[string]int64)}
	data, err := os.ReadFile(path)
	if err != nil {
		return c
	}
	var f cacheFile
	if json.Unmarshal(data, &f) == nil && f.Entries != nil {
		c.entries = f.Entries
	}
	return c
}

func (c *sizeCache) get(digest string) (map[string]int64, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	v, ok := c.entries[digest]
	return v, ok
}

func (c *sizeCache) set(digest string, sizes map[string]int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[digest] = sizes
	c.dirty = true
}

func (c *sizeCache) save() error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if !c.dirty {
		return nil
	}
	data, err := json.Marshal(cacheFile{Version: 1, Entries: c.entries})
	if err != nil {
		return err
	}
	return os.WriteFile(c.path, data, 0644)
}

func (c *sizeCache) len() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.entries)
}

// ---------------------------------------------------------------------------
// Registry client
// ---------------------------------------------------------------------------

const (
	acceptAll    = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
	acceptSingle = "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"
)

var manifestListTypes = map[string]bool{
	"application/vnd.docker.distribution.manifest.list.v2+json": true,
	"application/vnd.oci.image.index.v1+json":                   true,
}

type registryClient struct {
	http        *http.Client
	credentials map[string][2]string // registry → {user, pass}
	tokens      sync.Map             // "registry/repo" → token
	manifests   sync.Map             // cache key → *manifestEnvelope
}

func newRegistryClient(authConfigPath string) *registryClient {
	rc := &registryClient{
		http: &http.Client{
			Timeout: 30 * time.Second,
			Transport: &http.Transport{
				MaxIdleConns:        200,
				MaxIdleConnsPerHost: 50,
				IdleConnTimeout:     90 * time.Second,
			},
		},
		credentials: make(map[string][2]string),
	}
	if authConfigPath != "" {
		rc.loadAuth(authConfigPath)
	}
	return rc
}

func (rc *registryClient) loadAuth(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: cannot read auth config %s: %v\n", path, err)
		return
	}
	var cfg struct {
		Auths map[string]struct {
			Auth string `json:"auth"`
		} `json:"auths"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		fmt.Fprintf(os.Stderr, "warning: cannot parse auth config: %v\n", err)
		return
	}
	for key, v := range cfg.Auths {
		key = strings.TrimRight(key, "/")
		for _, prefix := range []string{"https://", "http://"} {
			key = strings.TrimPrefix(key, prefix)
		}
		decoded, err := base64.StdEncoding.DecodeString(v.Auth)
		if err != nil {
			continue
		}
		parts := strings.SplitN(string(decoded), ":", 2)
		if len(parts) == 2 {
			rc.credentials[key] = [2]string{parts[0], parts[1]}
		}
	}
}

func (rc *registryClient) findCredentials(registry string) (string, string, bool) {
	best, bestLen := [2]string{}, 0
	for key, creds := range rc.credentials {
		if strings.HasPrefix(registry, key) && len(key) > bestLen {
			best, bestLen = creds, len(key)
		}
	}
	if bestLen == 0 {
		host := strings.SplitN(registry, "/", 2)[0]
		if c, ok := rc.credentials[host]; ok {
			return c[0], c[1], true
		}
		return "", "", false
	}
	return best[0], best[1], true
}

func (rc *registryClient) getToken(registry, repository, wwwAuth string) (string, error) {
	cacheKey := registry + "/" + repository
	if tok, ok := rc.tokens.Load(cacheKey); ok {
		return tok.(string), nil
	}

	params := make(map[string]string)
	for _, m := range wwwAuthRe.FindAllStringSubmatch(wwwAuth, -1) {
		params[m[1]] = m[2]
	}
	realm := params["realm"]
	if realm == "" {
		return "", fmt.Errorf("no realm in WWW-Authenticate header")
	}

	req, _ := http.NewRequest("GET", realm, nil)
	q := req.URL.Query()
	q.Set("service", params["service"])
	q.Set("scope", params["scope"])
	req.URL.RawQuery = q.Encode()

	if user, pass, ok := rc.findCredentials(registry); ok {
		req.SetBasicAuth(user, pass)
	}

	resp, err := rc.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("token endpoint returned %d", resp.StatusCode)
	}

	var body struct {
		Token       string `json:"token"`
		AccessToken string `json:"access_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return "", err
	}
	tok := body.Token
	if tok == "" {
		tok = body.AccessToken
	}
	rc.tokens.Store(cacheKey, tok)
	return tok, nil
}

func (rc *registryClient) fetchManifest(registry, repository, reference, accept string) (*manifestEnvelope, string, error) {
	cacheKey := registry + "/" + repository + "@" + reference
	if v, ok := rc.manifests.Load(cacheKey); ok {
		m := v.(*manifestEnvelope)
		return m, m.MediaType, nil
	}

	url := fmt.Sprintf("https://%s/v2/%s/manifests/%s", registry, repository, reference)
	if accept == "" {
		accept = acceptAll
	}

	tokenKey := registry + "/" + repository

	var lastErr error
	for attempt := range 3 {
		req, _ := http.NewRequest("GET", url, nil)
		req.Header.Set("Accept", accept)

		if tok, ok := rc.tokens.Load(tokenKey); ok {
			req.Header.Set("Authorization", "Bearer "+tok.(string))
		}

		resp, err := rc.http.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(time.Duration(1<<attempt) * time.Second)
			continue
		}

		if resp.StatusCode == 401 {
			resp.Body.Close()
			// Clear stale token so we get a fresh one
			rc.tokens.Delete(tokenKey)
			wwwAuth := resp.Header.Get("Www-Authenticate")
			tok, tokenErr := rc.getToken(registry, repository, wwwAuth)
			if tokenErr != nil {
				lastErr = fmt.Errorf("auth failed: %w", tokenErr)
				time.Sleep(time.Duration(1<<attempt) * time.Second)
				continue
			}
			req2, _ := http.NewRequest("GET", url, nil)
			req2.Header.Set("Accept", accept)
			req2.Header.Set("Authorization", "Bearer "+tok)
			resp, err = rc.http.Do(req2)
			if err != nil {
				lastErr = err
				time.Sleep(time.Duration(1<<attempt) * time.Second)
				continue
			}
		}

		if resp.StatusCode == 429 || resp.StatusCode >= 500 {
			resp.Body.Close()
			lastErr = fmt.Errorf("HTTP %d for %s", resp.StatusCode, url)
			wait := 2 * (attempt + 1)
			time.Sleep(time.Duration(wait) * time.Second)
			continue
		}

		if resp.StatusCode != 200 {
			resp.Body.Close()
			return nil, "", fmt.Errorf("HTTP %d", resp.StatusCode)
		}

		ct := resp.Header.Get("Content-Type")
		var m manifestEnvelope
		err = json.NewDecoder(resp.Body).Decode(&m)
		resp.Body.Close()
		if err != nil {
			return nil, "", err
		}
		if m.MediaType == "" {
			m.MediaType = ct
		}

		rc.manifests.Store(cacheKey, &m)
		return &m, m.MediaType, nil
	}
	return nil, "", lastErr
}

func (rc *registryClient) getImageSizes(imageRef string) (archSizes, error) {
	registry, repository, _, refValue := parseImageRef(imageRef)
	m, mt, err := rc.fetchManifest(registry, repository, refValue, "")
	if err != nil {
		return nil, err
	}

	sizes := make(archSizes)

	if manifestListTypes[mt] || len(m.Manifests) > 0 {
		for _, desc := range m.Manifests {
			if desc.Platform.OS != "" && desc.Platform.OS != "linux" {
				continue
			}
			arch := desc.Platform.Architecture
			if arch == "" || arch == "unknown" {
				continue
			}
			key := arch
			if desc.Platform.Variant != "" {
				key += "/" + desc.Platform.Variant
			}
			child, _, err := rc.fetchManifest(registry, repository, desc.Digest, acceptSingle)
			if err != nil {
				sizes[key] = -1
				continue
			}
			var total int64
			for _, l := range child.Layers {
				total += l.Size
			}
			sizes[key] = total
		}
	} else if len(m.Layers) > 0 {
		var total int64
		for _, l := range m.Layers {
			total += l.Size
		}
		sizes["amd64"] = total
	}

	return sizes, nil
}

// ---------------------------------------------------------------------------
// FBC parsing
// ---------------------------------------------------------------------------

func parseFBC(path string) (map[string][]fbcEntry, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	reader := bufio.NewReaderSize(f, 1<<20)

	// Peek at first non-whitespace byte to detect format
	var firstByte byte
	for {
		b, err := reader.ReadByte()
		if err != nil {
			return nil, fmt.Errorf("empty or unreadable file: %w", err)
		}
		if b != ' ' && b != '\t' && b != '\n' && b != '\r' {
			firstByte = b
			_ = reader.UnreadByte()
			break
		}
	}

	var entries []fbcEntry
	if firstByte == '[' {
		if err := json.NewDecoder(reader).Decode(&entries); err != nil {
			return nil, fmt.Errorf("parsing JSON array: %w", err)
		}
	} else {
		dec := json.NewDecoder(reader)
		for {
			var e fbcEntry
			if err := dec.Decode(&e); err != nil {
				if errors.Is(err, io.EOF) {
					break
				}
				return nil, fmt.Errorf("parsing concatenated JSON at offset: %w", err)
			}
			entries = append(entries, e)
		}
	}

	packages := make(map[string][]fbcEntry)
	for i := range entries {
		if entries[i].Schema == "olm.bundle" {
			packages[entries[i].Package] = append(packages[entries[i].Package], entries[i])
		}
	}
	for pkg := range packages {
		sort.Slice(packages[pkg], func(i, j int) bool {
			return packages[pkg][i].Name < packages[pkg][j].Name
		})
	}
	return packages, nil
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

func progressBar(done, total int64, width int) string {
	if total == 0 {
		return strings.Repeat("╌", width)
	}
	filled := int(int64(width) * done / total)
	if filled > width {
		filled = width
	}
	return strings.Repeat("━", filled) + strings.Repeat("╌", width-filled)
}

// ---------------------------------------------------------------------------
// Analysis engine
// ---------------------------------------------------------------------------

type fetchJob struct {
	imageRef string
	digest   string
}

type fetchResult struct {
	imageRef string
	digest   string
	sizes    archSizes
	err      error
	cached   bool
}

func analyze(
	fbcPath, authConfig, cachePath string,
	concurrency int,
	useCache bool,
) []packageResult {
	fmt.Fprintf(os.Stderr, "Loading catalog %s …\n", fbcPath)
	packages, err := parseFBC(fbcPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing FBC: %v\n", err)
		os.Exit(1)
	}

	var totalBundles int
	for _, b := range packages {
		totalBundles += len(b)
	}
	fmt.Fprintf(os.Stderr, "Found %d operator packages with %d bundle versions\n",
		len(packages), totalBundles)

	// Collect unique image references
	uniqueRefs := make(map[string]struct{})
	for _, bundles := range packages {
		for _, b := range bundles {
			for _, img := range b.RelatedImages {
				if img.Image != "" {
					uniqueRefs[img.Image] = struct{}{}
				}
			}
		}
	}
	total := int64(len(uniqueRefs))
	fmt.Fprintf(os.Stderr, "%d unique image references to inspect\n", total)

	// Load disk cache
	var cache *sizeCache
	if useCache {
		cache = loadCache(cachePath)
		fmt.Fprintf(os.Stderr, "Cache: %d entries loaded from %s\n", cache.len(), cachePath)
	} else {
		cache = &sizeCache{entries: make(map[string]map[string]int64)}
	}

	// Set up registry client
	client := newRegistryClient(authConfig)

	// Worker pool
	jobs := make(chan fetchJob, concurrency*2)
	results := make(chan fetchResult, concurrency*2)

	var wg sync.WaitGroup
	for range concurrency {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobs {
				if job.digest != "" {
					if sizes, ok := cache.get(job.digest); ok {
						results <- fetchResult{
							imageRef: job.imageRef, digest: job.digest,
							sizes: sizes, cached: true,
						}
						continue
					}
				}
				sizes, err := client.getImageSizes(job.imageRef)
				if err == nil && job.digest != "" {
					cache.set(job.digest, sizes)
				}
				results <- fetchResult{
					imageRef: job.imageRef, digest: job.digest,
					sizes: sizes, err: err,
				}
			}
		}()
	}

	// Feed jobs
	go func() {
		for ref := range uniqueRefs {
			jobs <- fetchJob{imageRef: ref, digest: extractDigest(ref)}
		}
		close(jobs)
	}()

	// Collect results with progress
	go func() {
		wg.Wait()
		close(results)
	}()

	imageSizes := make(map[string]archSizes)
	imageErrors := make(map[string]string)
	var completed, cacheHits int64
	startTime := time.Now()

	// Progress ticker
	done := make(chan struct{})
	go func() {
		ticker := time.NewTicker(150 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				n := atomic.LoadInt64(&completed)
				hits := atomic.LoadInt64(&cacheHits)
				elapsed := time.Since(startTime).Truncate(time.Second)
				fmt.Fprintf(os.Stderr, "\r  Fetching manifests %s %d/%d (cached: %d) [%s]",
					progressBar(n, total, 35), n, total, hits, elapsed)
			}
		}
	}()

	for r := range results {
		imageSizes[r.imageRef] = r.sizes
		if r.err != nil {
			imageErrors[r.imageRef] = r.err.Error()
		}
		if r.cached {
			atomic.AddInt64(&cacheHits, 1)
		}
		atomic.AddInt64(&completed, 1)
	}
	close(done)

	elapsed := time.Since(startTime).Truncate(time.Second)
	fmt.Fprintf(os.Stderr, "\r  Fetching manifests %s %d/%d (cached: %d) [%s]\n",
		progressBar(total, total, 35), total, total, atomic.LoadInt64(&cacheHits), elapsed)

	if len(imageErrors) > 0 {
		fmt.Fprintf(os.Stderr, "⚠  %d image(s) could not be inspected\n", len(imageErrors))
		// Categorize errors for diagnostics
		categories := make(map[string]int)
		for _, msg := range imageErrors {
			cat := msg
			if strings.Contains(msg, "HTTP 404") {
				cat = "HTTP 404 (not found)"
			} else if strings.Contains(msg, "HTTP 403") {
				cat = "HTTP 403 (forbidden)"
			} else if strings.Contains(msg, "HTTP 5") {
				cat = "HTTP 5xx (server error)"
			} else if strings.Contains(msg, "HTTP 429") {
				cat = "HTTP 429 (rate limited)"
			} else if strings.Contains(msg, "auth failed") {
				cat = "auth failed"
			} else if strings.Contains(msg, "timeout") || strings.Contains(msg, "Timeout") {
				cat = "timeout"
			} else if strings.Contains(msg, "connection") {
				cat = "connection error"
			}
			categories[cat]++
		}
		type errCat struct {
			cat   string
			count int
		}
		var sorted []errCat
		for c, n := range categories {
			sorted = append(sorted, errCat{c, n})
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].count > sorted[j].count })
		for _, e := range sorted {
			fmt.Fprintf(os.Stderr, "   %-35s %d\n", e.cat, e.count)
		}
	}

	// Save cache
	if useCache {
		if err := cache.save(); err != nil {
			fmt.Fprintf(os.Stderr, "warning: failed to save cache: %v\n", err)
		} else {
			fmt.Fprintf(os.Stderr, "Cache: %d entries saved to %s\n", cache.len(), cachePath)
		}
	}

	// Assemble results
	var pkgResults []packageResult
	for pkgName, bundles := range packages {
		pr := packageResult{Name: pkgName}
		for _, b := range bundles {
			br := bundleResult{
				Package:    pkgName,
				BundleName: b.Name,
				Version:    extractVersion(b.Name, pkgName),
				ArchTotals: make(archSizes),
			}
			seen := make(map[string]bool)
			for _, img := range b.RelatedImages {
				if img.Image == "" || seen[img.Image] {
					continue
				}
				seen[img.Image] = true
				sizes := imageSizes[img.Image]
				_, repo, _, _ := parseImageRef(img.Image)
				var total int64
				for _, s := range sizes {
					if s > 0 {
						total += s
					}
				}
				ir := imageResult{
					Name:     img.Name,
					ImageRef: img.Image,
					Repo:     repo,
					Sizes:    sizes,
					Total:    total,
					Error:    imageErrors[img.Image],
				}
				br.Images = append(br.Images, ir)
				for arch, s := range sizes {
					if s > 0 {
						br.ArchTotals[arch] += s
					}
				}
			}
			br.ImageCount = len(br.Images)
			for _, s := range br.ArchTotals {
				br.TotalSize += s
			}
			pr.Bundles = append(pr.Bundles, br)
		}
		if len(pr.Bundles) > 0 {
			var sum int64
			for _, b := range pr.Bundles {
				sum += b.TotalSize
			}
			pr.AvgTotalSize = float64(sum) / float64(len(pr.Bundles))
		}
		pkgResults = append(pkgResults, pr)
	}

	sort.Slice(pkgResults, func(i, j int) bool {
		return pkgResults[i].AvgTotalSize > pkgResults[j].AvgTotalSize
	})
	return pkgResults
}

// ---------------------------------------------------------------------------
// Table output
// ---------------------------------------------------------------------------

func tableStyle() table.Style {
	s := table.StyleLight
	s.Color.Header = text.Colors{text.Bold}
	s.Format.Header = text.FormatDefault
	s.Options.SeparateRows = true
	return s
}

func renderSummaryTable(results []packageResult) {
	t := table.NewWriter()
	t.SetOutputMirror(os.Stdout)
	t.SetStyle(tableStyle())
	t.SetTitle("Operator Related Images — Size Summary (all architectures combined)")

	t.AppendHeader(table.Row{"#", "Package", "Versions",
		"Avg Total Size\n(all arch)", "Latest Total\n(all arch)", "Latest\nImages"})

	t.SetColumnConfigs([]table.ColumnConfig{
		{Number: 1, Align: text.AlignRight, AlignHeader: text.AlignRight},
		{Number: 3, Align: text.AlignRight, AlignHeader: text.AlignRight},
		{Number: 4, Align: text.AlignRight, AlignHeader: text.AlignRight},
		{Number: 5, Align: text.AlignRight, AlignHeader: text.AlignRight},
		{Number: 6, Align: text.AlignRight, AlignHeader: text.AlignRight},
	})

	for i, pkg := range results {
		latest := pkg.Bundles[len(pkg.Bundles)-1]
		t.AppendRow(table.Row{
			i + 1,
			pkg.Name,
			len(pkg.Bundles),
			formatSize(int64(pkg.AvgTotalSize)),
			formatSize(latest.TotalSize),
			latest.ImageCount,
		})
	}
	fmt.Println()
	t.Render()
	fmt.Println()
}

func renderDetailTable(pkg packageResult, topN int) {
	// Collect all architectures
	archSet := make(map[string]bool)
	for _, b := range pkg.Bundles {
		for a := range b.ArchTotals {
			archSet[a] = true
		}
	}
	archList := make([]string, 0, len(archSet))
	for a := range archSet {
		archList = append(archList, a)
	}
	sort.Strings(archList)

	// Per-version table
	t := table.NewWriter()
	t.SetOutputMirror(os.Stdout)
	s := tableStyle()
	s.Title.Align = text.AlignLeft
	t.SetStyle(s)
	t.SetTitle(fmt.Sprintf("  %s — per-version breakdown", pkg.Name))

	header := table.Row{"Version", "Images"}
	colCfgs := []table.ColumnConfig{
		{Number: 2, Align: text.AlignRight, AlignHeader: text.AlignRight},
	}
	for i, a := range archList {
		header = append(header, a)
		colCfgs = append(colCfgs, table.ColumnConfig{
			Number: i + 3, Align: text.AlignRight, AlignHeader: text.AlignRight,
		})
	}
	header = append(header, "Total (all arch)")
	colCfgs = append(colCfgs, table.ColumnConfig{
		Number: len(archList) + 3, Align: text.AlignRight, AlignHeader: text.AlignRight,
	})
	t.AppendHeader(header)
	t.SetColumnConfigs(colCfgs)

	for i := len(pkg.Bundles) - 1; i >= 0; i-- {
		b := pkg.Bundles[i]
		row := table.Row{b.Version, b.ImageCount}
		for _, a := range archList {
			row = append(row, formatSize(b.ArchTotals[a]))
		}
		row = append(row, formatSize(b.TotalSize))
		t.AppendRow(row)
	}
	fmt.Println()
	t.Render()

	// Top images for latest version
	latest := pkg.Bundles[len(pkg.Bundles)-1]
	if len(latest.Images) == 0 {
		return
	}
	sorted := make([]imageResult, len(latest.Images))
	copy(sorted, latest.Images)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Total > sorted[j].Total })

	n := topN
	if n > len(sorted) {
		n = len(sorted)
	}

	it := table.NewWriter()
	it.SetOutputMirror(os.Stdout)
	it.SetStyle(s)
	it.SetTitle(fmt.Sprintf("  Top %d largest images — %s %s", n, pkg.Name, latest.Version))

	iHeader := table.Row{"#", "Repository"}
	iColCfgs := []table.ColumnConfig{
		{Number: 1, Align: text.AlignRight, AlignHeader: text.AlignRight},
	}
	for i, a := range archList {
		iHeader = append(iHeader, a)
		iColCfgs = append(iColCfgs, table.ColumnConfig{
			Number: i + 3, Align: text.AlignRight, AlignHeader: text.AlignRight,
		})
	}
	iHeader = append(iHeader, "Total")
	iColCfgs = append(iColCfgs, table.ColumnConfig{
		Number: len(archList) + 3, Align: text.AlignRight, AlignHeader: text.AlignRight,
	})
	it.AppendHeader(iHeader)
	it.SetColumnConfigs(iColCfgs)

	for i, img := range sorted[:n] {
		row := table.Row{i + 1, img.Repo}
		for _, a := range archList {
			row = append(row, formatSize(img.Sizes[a]))
		}
		row = append(row, formatSize(img.Total))
		it.AppendRow(row)
	}
	fmt.Println()
	it.Render()
	fmt.Println()
}

// ---------------------------------------------------------------------------
// JSON output
// ---------------------------------------------------------------------------

type jsonArchSize struct {
	Size      int64  `json:"size"`
	SizeHuman string `json:"size_human"`
}

type jsonImage struct {
	Name     string                  `json:"name"`
	Image    string                  `json:"image"`
	Repo     string                  `json:"repository"`
	Total    int64                   `json:"total_size"`
	TotalH   string                  `json:"total_size_human"`
	Arches   map[string]jsonArchSize `json:"architectures,omitempty"`
	ErrorMsg string                  `json:"error,omitempty"`
}

type jsonVersion struct {
	BundleName string                  `json:"bundle_name"`
	Version    string                  `json:"version"`
	ImageCount int                     `json:"image_count"`
	TotalSize  int64                   `json:"total_size"`
	TotalSizeH string                  `json:"total_size_human"`
	Arches     map[string]jsonArchSize `json:"architectures"`
	Images     []jsonImage             `json:"images"`
}

type jsonPackage struct {
	Name          string        `json:"name"`
	VersionCount  int           `json:"version_count"`
	AvgTotalSize  int64         `json:"avg_total_size"`
	AvgTotalSizeH string        `json:"avg_total_size_human"`
	LatestVersion string        `json:"latest_version,omitempty"`
	LatestTotal   int64         `json:"latest_total_size,omitempty"`
	LatestTotalH  string        `json:"latest_total_size_human,omitempty"`
	LatestImages  int           `json:"latest_image_count,omitempty"`
	Versions      []jsonVersion `json:"versions,omitempty"`
}

type jsonOutput struct {
	Catalog      string        `json:"catalog"`
	AnalyzedAt   string        `json:"analyzed_at"`
	PackageCount int           `json:"package_count"`
	Packages     []jsonPackage `json:"packages"`
}

func buildJSON(results []packageResult, details []string, catalogPath string) jsonOutput {
	showAll := false
	detailSet := make(map[string]bool)
	for _, d := range details {
		if strings.EqualFold(d, "ALL") {
			showAll = true
		}
		detailSet[d] = true
	}

	out := jsonOutput{
		Catalog:      catalogPath,
		AnalyzedAt:   time.Now().UTC().Format(time.RFC3339),
		PackageCount: len(results),
	}

	for _, pkg := range results {
		jp := jsonPackage{
			Name:          pkg.Name,
			VersionCount:  len(pkg.Bundles),
			AvgTotalSize:  int64(pkg.AvgTotalSize),
			AvgTotalSizeH: formatSize(int64(pkg.AvgTotalSize)),
		}
		if l := pkg.Bundles[len(pkg.Bundles)-1]; true {
			jp.LatestVersion = l.Version
			jp.LatestTotal = l.TotalSize
			jp.LatestTotalH = formatSize(l.TotalSize)
			jp.LatestImages = l.ImageCount
		}

		if showAll || detailSet[pkg.Name] {
			for i := len(pkg.Bundles) - 1; i >= 0; i-- {
				b := pkg.Bundles[i]
				jv := jsonVersion{
					BundleName: b.BundleName,
					Version:    b.Version,
					ImageCount: b.ImageCount,
					TotalSize:  b.TotalSize,
					TotalSizeH: formatSize(b.TotalSize),
					Arches:     make(map[string]jsonArchSize),
				}
				for a, s := range b.ArchTotals {
					jv.Arches[a] = jsonArchSize{Size: s, SizeHuman: formatSize(s)}
				}
				imgs := make([]imageResult, len(b.Images))
				copy(imgs, b.Images)
				sort.Slice(imgs, func(x, y int) bool { return imgs[x].Total > imgs[y].Total })
				for _, img := range imgs {
					ji := jsonImage{
						Name:   img.Name,
						Image:  img.ImageRef,
						Repo:   img.Repo,
						Total:  img.Total,
						TotalH: formatSize(img.Total),
						Arches: make(map[string]jsonArchSize),
					}
					for a, s := range img.Sizes {
						if s > 0 {
							ji.Arches[a] = jsonArchSize{Size: s, SizeHuman: formatSize(s)}
						}
					}
					if img.Error != "" {
						ji.ErrorMsg = img.Error
					}
					jv.Images = append(jv.Images, ji)
				}
				jp.Versions = append(jp.Versions, jv)
			}
		}

		out.Packages = append(out.Packages, jp)
	}
	return out
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

func main() {
	var (
		details     stringSlice
		format      string
		authConfig  string
		concurrency int
		topN        int
		cachePath   string
		noCache     bool
	)

	flag.Var(&details, "d", "Per-version details for named packages (comma-sep, repeatable, or ALL)")
	flag.StringVar(&format, "f", "table", "Output format: table or json")
	flag.StringVar(&authConfig, "a", "", "Docker/OPM auth config.json path")
	flag.IntVar(&concurrency, "c", 25, "Parallel registry workers")
	flag.IntVar(&topN, "t", 5, "Top images per version in table mode")
	flag.StringVar(&cachePath, "cache", ".fbc-size-cache.json", "Disk cache path")
	flag.BoolVar(&noCache, "no-cache", false, "Disable disk cache")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, `FBC Related Images Size Analyzer

Analyzes operator bundles in a File-Based Catalog (FBC) JSON file and reports
the combined compressed size of all related images, broken down by architecture.

Usage:
  %s [flags] <catalog.json>

Flags:
`, os.Args[0])
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, `
Examples:
  %[1]s catalog.json
  %[1]s -a ~/.opm-docker/config.json catalog.json
  %[1]s -a ~/.opm-docker/config.json -d advanced-cluster-management catalog.json
  %[1]s -a ~/.opm-docker/config.json -d ALL catalog.json
  %[1]s -a ~/.opm-docker/config.json -d ALL -f json catalog.json > sizes.json
`, os.Args[0])
	}
	flag.Parse()

	if flag.NArg() != 1 {
		flag.Usage()
		os.Exit(1)
	}
	catalogPath := flag.Arg(0)
	if _, err := os.Stat(catalogPath); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintln(os.Stderr, "╭──────────────────────────────────╮")
	fmt.Fprintln(os.Stderr, "│ FBC Related Images Size Analyzer │")
	fmt.Fprintln(os.Stderr, "╰──────────────────────────────────╯")

	results := analyze(catalogPath, authConfig, cachePath, concurrency, !noCache)

	switch format {
	case "json":
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(buildJSON(results, details, catalogPath))
	default:
		renderSummaryTable(results)
		if len(details) > 0 {
			showAll := false
			for _, d := range details {
				if strings.EqualFold(d, "ALL") {
					showAll = true
				}
			}
			for _, pkg := range results {
				if showAll {
					renderDetailTable(pkg, topN)
					continue
				}
				for _, d := range details {
					if pkg.Name == d {
						renderDetailTable(pkg, topN)
						break
					}
				}
			}
		}
	}
}
