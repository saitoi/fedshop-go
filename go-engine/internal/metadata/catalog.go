// Package metadata builds and consumes endpoint predicate summaries.
package metadata

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

// EndpointSummary stores predicate cardinalities for one member.
type EndpointSummary struct {
	Predicates map[string]int64 `json:"predicates"`
}

// Catalog is a versioned, federation-fingerprinted summary.
type Catalog struct {
	Version     int                        `json:"version"`
	Fingerprint string                     `json:"fingerprint"`
	GeneratedAt time.Time                  `json:"generated_at"`
	Endpoints   map[string]EndpointSummary `json:"endpoints"`
}

// BuildStats records summary construction cost separately from query cost.
type BuildStats struct {
	BuildSeconds float64 `json:"build_seconds"`
	HTTPRequests int64   `json:"http_requests"`
	DataTransfer int64   `json:"data_transfer"`
}

// Querier executes arbitrary SELECT queries for catalog construction.
type Querier interface {
	Query(context.Context, federation.Endpoint, string) ([]executor.Binding, error)
	Requests() int64
	Bytes() int64
}

const predicateSummaryQuery = `SELECT ?p (COUNT(*) AS ?count) WHERE { ?s ?p ?o } GROUP BY ?p`

// Build queries each endpoint through its public SPARQL interface.
func Build(ctx context.Context, endpoints []federation.Endpoint, querier Querier, concurrency int) (Catalog, BuildStats, error) {
	started := time.Now()
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	if concurrency < 1 {
		concurrency = 1
	}
	catalog := Catalog{Version: 1, Fingerprint: fingerprint(endpoints), GeneratedAt: time.Now().UTC(), Endpoints: map[string]EndpointSummary{}}
	tasks := make(chan federation.Endpoint)
	type result struct {
		endpoint federation.Endpoint
		rows     []executor.Binding
		err      error
	}
	results := make(chan result)
	var workers sync.WaitGroup
	for range concurrency {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for endpoint := range tasks {
				rows, err := querier.Query(ctx, endpoint, predicateSummaryQuery)
				select {
				case results <- result{endpoint: endpoint, rows: rows, err: err}:
				case <-ctx.Done():
					return
				}
			}
		}()
	}
	go func() {
		defer close(tasks)
		for _, endpoint := range endpoints {
			select {
			case tasks <- endpoint:
			case <-ctx.Done():
				return
			}
		}
	}()
	go func() { workers.Wait(); close(results) }()
	for item := range results {
		if item.err != nil {
			cancel()
			return Catalog{}, BuildStats{}, fmt.Errorf("summarize %s: %w", item.endpoint.ID, item.err)
		}
		summary := EndpointSummary{Predicates: map[string]int64{}}
		for _, row := range item.rows {
			predicate := row["p"].Lexical
			count, err := strconv.ParseInt(row["count"].Lexical, 10, 64)
			if err != nil {
				return Catalog{}, BuildStats{}, fmt.Errorf("summarize %s count: %w", item.endpoint.ID, err)
			}
			summary.Predicates[predicate] = count
		}
		catalog.Endpoints[item.endpoint.ID] = summary
	}
	return catalog, BuildStats{BuildSeconds: time.Since(started).Seconds(), HTTPRequests: querier.Requests(), DataTransfer: querier.Bytes()}, nil
}

// Write persists a catalog and its separately measured construction stats.
func Write(path string, catalog Catalog, stats BuildStats) error {
	payload := struct {
		Catalog Catalog    `json:"catalog"`
		Stats   BuildStats `json:"stats"`
	}{catalog, stats}
	encoded, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return fmt.Errorf("encode summary: %w", err)
	}
	if err := os.WriteFile(path, append(encoded, '\n'), 0o644); err != nil {
		return fmt.Errorf("write summary: %w", err)
	}
	return nil
}

// Read loads a summary catalog.
func Read(path string) (Catalog, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return Catalog{}, fmt.Errorf("read summary: %w", err)
	}
	var payload struct {
		Catalog Catalog `json:"catalog"`
	}
	if err := json.Unmarshal(content, &payload); err != nil {
		return Catalog{}, fmt.Errorf("decode summary: %w", err)
	}
	if payload.Catalog.Version != 1 {
		return Catalog{}, fmt.Errorf("unsupported summary version %d", payload.Catalog.Version)
	}
	return payload.Catalog, nil
}

// Selector prunes endpoints using predicate presence and cardinality summaries.
type Selector struct{ Catalog Catalog }

// Select implements federation.Selector.
func (s Selector) Select(_ context.Context, query sparql.Query, endpoints []federation.Endpoint) (federation.Selection, federation.SelectionStats, error) {
	selection := federation.Selection{}
	for _, triple := range query.Triples() {
		for _, endpoint := range endpoints {
			summary, known := s.Catalog.Endpoints[endpoint.ID]
			if triple.Predicate.Kind != sparql.TermIRI || !known {
				selection[triple.ID] = append(selection[triple.ID], endpoint)
				continue
			}
			if summary.Predicates[triple.Predicate.Value] > 0 {
				selection[triple.ID] = append(selection[triple.ID], endpoint)
			}
		}
	}
	return selection, federation.SelectionStats{}, nil
}

func fingerprint(endpoints []federation.Endpoint) string {
	parts := make([]string, 0, len(endpoints))
	for _, endpoint := range endpoints {
		parts = append(parts, endpoint.ID+"\x00"+endpoint.GraphIRI+"\x00"+endpoint.URL)
	}
	sort.Strings(parts)
	sum := sha256.Sum256([]byte(strings.Join(parts, "\n")))
	return hex.EncodeToString(sum[:])
}
