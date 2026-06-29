package metadata

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

type fakeQuerier struct{}

func (fakeQuerier) Query(_ context.Context, endpoint federation.Endpoint, _ string) ([]executor.Binding, error) {
	return []executor.Binding{{
		"p":     executor.IRI("http://example/" + endpoint.ID),
		"count": executor.Literal("12", "http://www.w3.org/2001/XMLSchema#integer", ""),
	}}, nil
}

func mustParse(t *testing.T, input string) sparql.Query {
	t.Helper()
	query, err := sparql.Parse(input)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	return query
}
func (fakeQuerier) Requests() int64 { return 2 }
func (fakeQuerier) Bytes() int64    { return 100 }

func TestBuildWriteReadCatalog(t *testing.T) {
	t.Parallel()
	endpoints := []federation.Endpoint{{ID: "one", URL: "http://one"}, {ID: "two", URL: "http://two"}}
	catalog, stats, err := Build(context.Background(), endpoints, fakeQuerier{}, 2)
	if err != nil {
		t.Fatalf("Build() error = %v", err)
	}
	if stats.HTTPRequests != 2 || catalog.Endpoints["one"].Predicates["http://example/one"] != 12 {
		t.Fatalf("catalog = %#v, stats = %#v", catalog, stats)
	}
	path := filepath.Join(t.TempDir(), "summary.json")
	if err := Write(path, catalog, stats); err != nil {
		t.Fatalf("Write() error = %v", err)
	}
	loaded, err := Read(path)
	if err != nil || loaded.Fingerprint != catalog.Fingerprint {
		t.Fatalf("Read() = %#v, %v", loaded, err)
	}
}

func TestSelectorUsesPredicateSummary(t *testing.T) {
	t.Parallel()
	query := mustParse(t, `SELECT ?s WHERE { ?s <http://example/p> ?o }`)
	endpoints := []federation.Endpoint{{ID: "one"}, {ID: "two"}}
	catalog := Catalog{Endpoints: map[string]EndpointSummary{
		"one": {Predicates: map[string]int64{"http://example/p": 3}},
		"two": {Predicates: map[string]int64{}},
	}}
	selection, _, err := (Selector{Catalog: catalog}).Select(context.Background(), query, endpoints)
	if err != nil {
		t.Fatalf("Select() error = %v", err)
	}
	if len(selection[0]) != 1 || selection[0][0].ID != "one" {
		t.Fatalf("selection = %#v", selection)
	}
}
