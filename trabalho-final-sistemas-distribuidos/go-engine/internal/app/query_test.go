package app

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

type fakeProtocol struct{}

func (fakeProtocol) Ask(context.Context, federation.Endpoint, sparql.TriplePattern) (bool, error) {
	return true, nil
}
func (fakeProtocol) Select(_ context.Context, _ federation.Endpoint, _ []sparql.TriplePattern, _ []executor.Binding, _ ...string) ([]executor.Binding, error) {
	return []executor.Binding{{"s": executor.IRI("http://example/s")}}, nil
}
func (fakeProtocol) Requests() int64 { return 1 }
func (fakeProtocol) Bytes() int64    { return 20 }

func TestRunQueryWritesArtifacts(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	queryPath := filepath.Join(dir, "query.sparql")
	configPath := filepath.Join(dir, "config.ttl")
	if err := os.WriteFile(queryPath, []byte(`SELECT ?s WHERE { ?s <http://example/p> ?o }`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, []byte(`<http://member/> a sd:Service ; sd:endpoint "http://endpoint" .`), 0o644); err != nil {
		t.Fatal(err)
	}
	options := QueryOptions{
		Config: configPath, Query: queryPath, Selector: "broadcast", Join: "hash", Planner: "source-count",
		OutResult: filepath.Join(dir, "results.csv"), OutSources: filepath.Join(dir, "sources.csv"), OutPlan: filepath.Join(dir, "plan.txt"), OutStats: filepath.Join(dir, "stats.json"),
	}
	if err := RunQuery(context.Background(), options, fakeProtocol{}); err != nil {
		t.Fatalf("RunQuery() error = %v", err)
	}
	result, err := os.ReadFile(options.OutResult)
	if err != nil {
		t.Fatal(err)
	}
	if string(result) != "s\nhttp://example/s\n" {
		t.Fatalf("results = %q", result)
	}
}
