package engine

import (
	"strings"
	"testing"
)

func TestParseQueryExtractsPrefixesSelectAndServiceBlocks(t *testing.T) {
	input := strings.TrimSpace(`
PREFIX bsbm: <http://example.com/bsbm/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?product ?label
WHERE {
  SERVICE <http://shop.example/sparql> {
    ?product rdfs:label ?label .
    ?product bsbm:price ?price .
  }
  SERVICE <http://reviews.example/sparql> {
    ?review bsbm:reviewFor ?product .
  }
}
LIMIT 10
`)

	query, err := ParseQuery(input)
	if err != nil {
		t.Fatalf("ParseQuery returned error: %v", err)
	}

	if !query.Distinct {
		t.Fatalf("Distinct = false, want true")
	}
	if got, want := strings.Join(query.Select, ","), "product,label"; got != want {
		t.Fatalf("Select = %q, want %q", got, want)
	}
	if got := len(query.ServiceBlocks); got != 2 {
		t.Fatalf("len(ServiceBlocks) = %d, want 2", got)
	}
	if got, want := query.ServiceBlocks[0].Endpoint, "http://shop.example/sparql"; got != want {
		t.Fatalf("first endpoint = %q, want %q", got, want)
	}
	if got := query.ServiceBlocks[0].Triples; len(got) != 2 {
		t.Fatalf("first block triples = %v, want 2 triples", got)
	}
	if got, want := query.Limit, 10; got != want {
		t.Fatalf("Limit = %d, want %d", got, want)
	}
	if got, want := query.Prefixes["rdfs"], "http://www.w3.org/2000/01/rdf-schema#"; got != want {
		t.Fatalf("rdfs prefix = %q, want %q", got, want)
	}
}

func TestParseQueryRejectsQueriesWithoutServiceBlocks(t *testing.T) {
	_, err := ParseQuery(`SELECT ?s WHERE { ?s ?p ?o . }`)
	if err == nil {
		t.Fatal("ParseQuery returned nil error, want unsupported query error")
	}
}
