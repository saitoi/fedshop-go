// Package app orchestrates fedshop-go commands.
package app

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/artifact"
	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/metadata"
	"github.com/pedrosaito/fedshop-go/internal/planner"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
	"github.com/pedrosaito/fedshop-go/internal/trace"
)

// Protocol is the endpoint behavior required by query execution.
type Protocol interface {
	federation.ASKClient
	executor.Client
	Requests() int64
	Bytes() int64
}

// QueryOptions configures one query command.
type QueryOptions struct {
	Config          string
	Query           string
	OutResult       string
	OutSources      string
	OutPlan         string
	OutStats        string
	Selector        string
	Summary         string
	Cache           bool
	Join            string
	Planner         string
	FailurePolicy   string
	MaxConcurrency  int
	BindBatchSize   int
	ExclusiveGroups      bool
	PostBindMaxInputRows int
	NoExec               bool
	TracePath            string
}

// RunQuery parses, selects, executes, and emits one benchmark run.
func RunQuery(ctx context.Context, options QueryOptions, protocol Protocol) (err error) {
	started := time.Now()
	var tracer *trace.Tracer
	if options.TracePath != "" {
		tracer = trace.New()
		defer func() {
			message := ""
			if err != nil {
				message = err.Error()
			}
			if writeErr := tracer.Write(options.TracePath, message); writeErr != nil && err == nil {
				err = writeErr
			}
		}()
		if traced, ok := protocol.(interface {
			SetTrace(func() float64, func(string, float64, map[string]any))
		}); ok {
			traced.SetTrace(tracer.Now, tracer.Emit)
		}
	}
	if err := validateQueryOptions(options); err != nil {
		return err
	}
	queryInput, err := os.ReadFile(options.Query)
	if err != nil {
		return fmt.Errorf("read query: %w", err)
	}
	parseStarted := time.Now()
	query, err := sparql.Parse(string(queryInput))
	if err != nil {
		return err
	}
	parseSeconds := time.Since(parseStarted).Seconds()
	configInput, err := os.ReadFile(options.Config)
	if err != nil {
		return fmt.Errorf("read endpoint config: %w", err)
	}
	endpoints, err := federation.ParseEndpointConfig(string(configInput))
	if err != nil {
		return err
	}
	if tracer != nil {
		triples := query.Triples()
		tpInfo := make([]map[string]any, 0, len(triples))
		for _, tp := range triples {
			tpInfo = append(tpInfo, map[string]any{
				"id": fmt.Sprintf("tp%d", tp.ID), "sparql": tp.Key(), "vars": tp.Variables(), "context": "bgp",
			})
		}
		endpointInfo := make([]map[string]any, 0, len(endpoints))
		for _, ep := range endpoints {
			endpointInfo = append(endpointInfo, map[string]any{"id": ep.ID, "url": ep.URL, "graph_iri": ep.GraphIRI})
		}
		limit := any(nil)
		if query.Limit >= 0 {
			limit = query.Limit
		}
		tracer.Emit("run_start", -1, map[string]any{
			"query": string(queryInput), "triples": tpInfo, "endpoints": endpointInfo,
			"select": query.Select, "distinct": query.Distinct, "limit": limit,
		})
	}
	var selector federation.Selector
	var catalog metadata.Catalog
	switch options.Selector {
	case "broadcast":
		selector = federation.BroadcastSelector{}
	case "ask":
		selector = federation.NewASKSelector(protocol, options.MaxConcurrency, options.Cache)
	case "summary":
		loadedCatalog, readErr := metadata.Read(options.Summary)
		if readErr != nil {
			return readErr
		}
		catalog = loadedCatalog
		selector = metadata.Selector{Catalog: catalog}
	default:
		return fmt.Errorf("selector %q is not available", options.Selector)
	}
	selectionStarted := time.Now()
	var selectionT0 float64
	if tracer != nil {
		selectionT0 = tracer.Now()
		tracer.Emit("phase", -1, map[string]any{"name": "source_selection"})
	}
	selection, selectionStats, err := selector.Select(ctx, query, endpoints)
	if err != nil {
		return err
	}
	selectionSeconds := time.Since(selectionStarted).Seconds()
	if tracer != nil {
		sources := map[string][]string{}
		for tpID, eps := range selection {
			ids := make([]string, 0, len(eps))
			for _, ep := range eps {
				ids = append(ids, ep.ID)
			}
			sources[fmt.Sprintf("tp%d", tpID)] = ids
		}
		for _, tp := range query.Triples() {
			if _, ok := sources[fmt.Sprintf("tp%d", tp.ID)]; !ok {
				sources[fmt.Sprintf("tp%d", tp.ID)] = []string{}
			}
		}
		tracer.Emit("source_selection_done", selectionT0, map[string]any{
			"sources": sources, "ask_count": selectionStats.ASKRequests,
		})
	}
	planningStarted := time.Now()
	var order []int
	if options.Planner == "cost" {
		if catalog.Version == 0 {
			return fmt.Errorf("--planner cost requires --selector summary and --summary")
		}
		order = planner.CostOrder(query, selection, catalog)
	}
	// For "source-count" and any other planner, leave order nil so the executor
	// uses per-branch greedy ordering (fewest sources + connectivity tie-break).
	planningSeconds := time.Since(planningStarted).Seconds()
	var rows []executor.Binding
	executionStats := executor.Stats{}
	executionSeconds := 0.0
	if !options.NoExec {
		executionStarted := time.Now()
		var executionT0 float64
		execOptions := executor.Options{Join: options.Join, BindBatchSize: options.BindBatchSize, FailurePolicy: options.FailurePolicy, TripleOrder: order, ExclusiveGroups: options.ExclusiveGroups, MaxConcurrency: options.MaxConcurrency, PostBindMaxInputRows: options.PostBindMaxInputRows}
		if tracer != nil {
			executionT0 = tracer.Now()
			tracer.Emit("phase", -1, map[string]any{"name": "execution"})
			execOptions.Trace = tracer.Emit
		}
		rows, executionStats, err = executor.New(protocol, execOptions).Execute(ctx, query, selection)
		executionSeconds = time.Since(executionStarted).Seconds()
		if err != nil {
			return err
		}
		if tracer != nil {
			columns := query.Select
			tracer.Emit("run_complete", executionT0, map[string]any{
				"rows": len(rows), "sample": executor.SampleRows(rows, 20), "columns": columns,
				"http_requests": int(protocol.Requests()), "total_seconds": time.Since(started).Seconds(),
			})
		}
	}
	stats := artifact.RunStats{Engine: "fedshop-go", Rows: len(rows), Selector: options.Selector, Join: options.Join, Planner: options.Planner, ASK: selectionStats.ASKRequests, CacheHits: selectionStats.CacheHits, HTTPRequests: int(protocol.Requests()), DataTransfer: protocol.Bytes(), ParseSeconds: parseSeconds, SourceSelectionSeconds: selectionSeconds, PlanningSeconds: planningSeconds, ExecutionSeconds: executionSeconds, TotalSeconds: time.Since(started).Seconds(), Partial: executionStats.Partial, FailedEndpoints: executionStats.FailedEndpoints, TripleOrder: order}
	return artifact.WriteRun(artifact.Paths{Results: options.OutResult, Sources: options.OutSources, Plan: options.OutPlan, Stats: options.OutStats}, query, rows, selection, stats)
}

func validateQueryOptions(options QueryOptions) error {
	required := map[string]string{"--config": options.Config, "--query": options.Query, "--out-result": options.OutResult, "--out-source-selection": options.OutSources, "--query-plan": options.OutPlan, "--stats": options.OutStats}
	for flag, value := range required {
		if value == "" {
			return fmt.Errorf("%s is required", flag)
		}
	}
	if options.Selector == "" {
		return fmt.Errorf("--selector is required")
	}
	if options.Join != "hash" && options.Join != "bind" {
		return fmt.Errorf("--join must be hash or bind")
	}
	if options.FailurePolicy != "" && options.FailurePolicy != "strict" && options.FailurePolicy != "partial" {
		return fmt.Errorf("--failure-policy must be strict or partial")
	}
	return nil
}
