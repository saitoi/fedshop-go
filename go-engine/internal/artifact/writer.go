// Package artifact writes deterministic FedShop benchmark artifacts.
package artifact

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

// Paths identifies one benchmark run's raw artifacts.
type Paths struct {
	Results string
	Sources string
	Plan    string
	Stats   string
}

// RunStats is the engine-owned metrics record consumed by the Python adapter.
type RunStats struct {
	Engine                 string    `json:"engine"`
	Rows                   int       `json:"rows"`
	Selector               string    `json:"selector"`
	Join                   string    `json:"join"`
	Planner                string    `json:"planner"`
	ASK                    int       `json:"ask"`
	CacheHits              int       `json:"cache_hits"`
	HTTPRequests           int       `json:"http_requests"`
	DataTransfer           int64     `json:"data_transfer"`
	ParseSeconds           float64   `json:"parse_seconds"`
	SourceSelectionSeconds float64   `json:"source_selection_seconds"`
	PlanningSeconds        float64   `json:"planning_seconds"`
	ExecutionSeconds       float64   `json:"execution_seconds"`
	TotalSeconds           float64   `json:"total_seconds"`
	Partial                bool      `json:"partial"`
	FailedEndpoints        []string  `json:"failed_endpoints,omitempty"`
	TripleOrder            []int     `json:"triple_order,omitempty"`
	GeneratedAt            time.Time `json:"generated_at"`
}

// WriteRun atomically writes the result, source, plan, and stats artifacts.
func WriteRun(paths Paths, query sparql.Query, rows []executor.Binding, selection federation.Selection, stats RunStats) error {
	for _, path := range []string{paths.Results, paths.Sources, paths.Plan, paths.Stats} {
		if path == "" {
			return fmt.Errorf("write artifacts: empty output path")
		}
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return fmt.Errorf("create artifact directory: %w", err)
		}
	}
	if err := writeResults(paths.Results, query.Select, rows); err != nil {
		return err
	}
	if err := writeSources(paths.Sources, query, selection); err != nil {
		return err
	}
	if err := writePlan(paths.Plan, query, selection, stats); err != nil {
		return err
	}
	if stats.GeneratedAt.IsZero() {
		stats.GeneratedAt = time.Now().UTC()
	}
	encoded, err := json.MarshalIndent(stats, "", "  ")
	if err != nil {
		return fmt.Errorf("encode stats: %w", err)
	}
	encoded = append(encoded, '\n')
	if err := os.WriteFile(paths.Stats, encoded, 0o644); err != nil {
		return fmt.Errorf("write stats: %w", err)
	}
	return nil
}

func writeResults(path string, variables []string, rows []executor.Binding) error {
	file, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create results: %w", err)
	}
	writer := csv.NewWriter(file)
	if err := writer.Write(variables); err != nil {
		file.Close()
		return fmt.Errorf("write results header: %w", err)
	}
	for _, row := range rows {
		record := make([]string, len(variables))
		for i, variable := range variables {
			record[i] = row[variable].Lexical
		}
		if err := writer.Write(record); err != nil {
			file.Close()
			return fmt.Errorf("write result row: %w", err)
		}
	}
	writer.Flush()
	if err := writer.Error(); err != nil {
		file.Close()
		return fmt.Errorf("flush results: %w", err)
	}
	if err := file.Close(); err != nil {
		return fmt.Errorf("close results: %w", err)
	}
	return nil
}
func writeSources(path string, query sparql.Query, selection federation.Selection) error {
	file, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create sources: %w", err)
	}
	writer := csv.NewWriter(file)
	if err := writer.Write([]string{"triple", "source_selection"}); err != nil {
		file.Close()
		return err
	}
	for _, triple := range query.Triples() {
		ids := make([]string, 0, len(selection[triple.ID]))
		for _, endpoint := range selection[triple.ID] {
			ids = append(ids, endpoint.ID)
		}
		encoded, err := json.Marshal(ids)
		if err != nil {
			file.Close()
			return fmt.Errorf("encode selected sources: %w", err)
		}
		if err := writer.Write([]string{triple.Key(), string(encoded)}); err != nil {
			file.Close()
			return err
		}
	}
	writer.Flush()
	if err := writer.Error(); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}
func writePlan(path string, query sparql.Query, selection federation.Selection, stats RunStats) error {
	var lines []string
	lines = append(lines, "fedshop-go plan", "selector="+stats.Selector, "planner="+stats.Planner, "join="+stats.Join, fmt.Sprintf("triple_order=%v", stats.TripleOrder), "")
	for _, triple := range query.Triples() {
		sources := selection[triple.ID]
		ids := make([]string, 0, len(sources))
		for _, source := range sources {
			ids = append(ids, source.ID)
		}
		sort.Strings(ids)
		kind := "EmptyStatementPattern"
		if len(ids) == 1 {
			kind = "ExclusiveStatement"
		} else if len(ids) > 1 {
			kind = "StatementSourcePattern"
		}
		lines = append(lines, fmt.Sprintf("tp%d: %s: %s", triple.ID, kind, triple.Key()), "  sources: "+strings.Join(ids, ", "))
	}
	return os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o644)
}
