package sparql

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseFedShopTemplates(t *testing.T) {
	t.Parallel()
	queries, err := filepath.Glob(filepath.Join("..", "..", "..", "fedshop-py", "queries", "q*.sparql"))
	if err != nil {
		t.Fatalf("glob templates: %v", err)
	}
	if len(queries) != 12 {
		t.Fatalf("got %d query templates, want 12", len(queries))
	}
	for _, path := range queries {
		path := path
		t.Run(filepath.Base(path), func(t *testing.T) {
			t.Parallel()
			input, readErr := os.ReadFile(path)
			if readErr != nil {
				t.Fatalf("read query: %v", readErr)
			}
			query, parseErr := Parse(string(input))
			if parseErr != nil {
				t.Fatalf("Parse() error = %v", parseErr)
			}
			if len(query.Select) == 0 {
				t.Fatal("Parse() returned no projected variables")
			}
			if len(query.Triples()) == 0 {
				t.Fatal("Parse() returned no triple patterns")
			}
		})
	}
}

func TestParseBuildsNestedAlgebra(t *testing.T) {
	t.Parallel()
	query, err := Parse(`
PREFIX ex: <http://example/>
SELECT DISTINCT ?s ?label WHERE {
  ?s ex:p ?o .
  OPTIONAL { ?s ex:label ?label . FILTER(BOUND(?label)) }
  { ?s ex:a ?x } UNION { ?s ex:b ?x }
  FILTER(?o > 2)
}
ORDER BY DESC(?label)
OFFSET 5
LIMIT 10`)
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if !query.Distinct || query.Offset != 5 || query.Limit != 10 {
		t.Fatalf("query modifiers = distinct:%v offset:%d limit:%d", query.Distinct, query.Offset, query.Limit)
	}
	if got := len(query.Where.Optionals); got != 1 {
		t.Fatalf("optionals = %d, want 1", got)
	}
	if got := len(query.Where.Unions); got != 1 {
		t.Fatalf("unions = %d, want 1", got)
	}
	if got := len(query.Where.Filters); got != 1 {
		t.Fatalf("top-level filters = %d, want 1", got)
	}
	if got := len(query.OrderBy); got != 1 || query.OrderBy[0].Ascending {
		t.Fatalf("order by = %#v, want one descending condition", query.OrderBy)
	}
}

func TestParseRejectsUnsupportedGraph(t *testing.T) {
	t.Parallel()
	_, err := Parse(`SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } }`)
	if err == nil {
		t.Fatal("Parse() error = nil, want unsupported GRAPH error")
	}
}

func TestParseRejectsOverflowingLimit(t *testing.T) {
	t.Parallel()
	_, err := Parse(`SELECT ?s WHERE { ?s ?p ?o } LIMIT 999999999999999999999999999999`)
	if err == nil {
		t.Fatal("Parse() error = nil, want overflowing LIMIT error")
	}
}
