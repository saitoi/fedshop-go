package planner

import (
	"testing"

	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/metadata"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

func TestCostOrderPrefersLowerEstimatedCardinalityAndConnectedPatterns(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/common> ?x . ?x <http://example/rare> ?o . ?z <http://example/tiny> ?v }`)
	if err != nil {
		t.Fatal(err)
	}
	ep := federation.Endpoint{ID: "one"}
	selection := federation.Selection{0: {ep}, 1: {ep}, 2: {ep}}
	catalog := metadata.Catalog{Endpoints: map[string]metadata.EndpointSummary{"one": {Predicates: map[string]int64{"http://example/common": 1000, "http://example/rare": 10, "http://example/tiny": 1}}}}
	order := CostOrder(query, selection, catalog)
	if len(order) != 3 || order[0] != 2 || order[1] != 1 || order[2] != 0 {
		t.Fatalf("order = %#v, want [2 1 0]", order)
	}
}

func TestSourceCountOrderIsStable(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/a> ?x . ?x <http://example/b> ?o }`)
	if err != nil {
		t.Fatal(err)
	}
	ep := federation.Endpoint{ID: "one"}
	order := SourceCountOrder(query, federation.Selection{0: {ep, ep}, 1: {ep}})
	if len(order) != 2 || order[0] != 1 {
		t.Fatalf("order = %#v", order)
	}
}
