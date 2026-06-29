package app

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/metadata"
)

// SummaryOptions configures offline endpoint-summary construction.
type SummaryOptions struct {
	Config         string
	Output         string
	MaxConcurrency int
}

// RunSummary builds a measured predicate catalog through public endpoints.
func RunSummary(ctx context.Context, options SummaryOptions, querier metadata.Querier) error {
	if options.Config == "" {
		return fmt.Errorf("--config is required")
	}
	if options.Output == "" {
		return fmt.Errorf("--output is required")
	}
	content, err := os.ReadFile(options.Config)
	if err != nil {
		return fmt.Errorf("read endpoint config: %w", err)
	}
	endpoints, err := federation.ParseEndpointConfig(string(content))
	if err != nil {
		return err
	}
	catalog, stats, err := metadata.Build(ctx, endpoints, querier, options.MaxConcurrency)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(options.Output), 0o755); err != nil {
		return fmt.Errorf("create summary directory: %w", err)
	}
	return metadata.Write(options.Output, catalog, stats)
}
