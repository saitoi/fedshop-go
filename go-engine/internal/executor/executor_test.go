package executor

import (
	"context"
	"testing"

	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

type fakeClient struct {
	rows map[string][]Binding
}

func (c fakeClient) Select(_ context.Context, endpoint federation.Endpoint, triples []sparql.TriplePattern, _ []Binding) ([]Binding, error) {
	return cloneRows(c.rows[endpoint.ID+":"+triples[0].Key()]), nil
}

type bindRecordingClient struct{ calls []int }

func (c *bindRecordingClient) Select(_ context.Context, _ federation.Endpoint, triples []sparql.TriplePattern, inputs []Binding) ([]Binding, error) {
	c.calls = append(c.calls, len(inputs))
	if len(triples) > 1 {
		return []Binding{{"s": IRI("http://s"), "o": IRI("http://o")}}, nil
	}
	if triples[0].Predicate.Value == "http://example/first" {
		return []Binding{{"s": IRI("http://s"), "x": IRI("http://x")}}, nil
	}
	return []Binding{{"x": IRI("http://x"), "o": IRI("http://o")}}, nil
}

type groupInputClient struct{ calls map[string][]int }

func (c *groupInputClient) Select(_ context.Context, _ federation.Endpoint, triples []sparql.TriplePattern, inputs []Binding) ([]Binding, error) {
	predicate := triples[0].Predicate.Value
	c.calls[predicate] = append(c.calls[predicate], len(inputs))
	switch predicate {
	case "http://example/base":
		return []Binding{{"s": IRI("http://s1")}, {"s": IRI("http://s2")}}, nil
	case "http://example/label":
		return []Binding{{"s": IRI("http://s1"), "label": PlainLiteral("one")}}, nil
	case "http://example/left":
		return []Binding{{"s": IRI("http://s1"), "value": PlainLiteral("left")}}, nil
	case "http://example/right":
		return []Binding{{"s": IRI("http://s1"), "value": PlainLiteral("right")}}, nil
	default:
		return nil, nil
	}
}

func TestExecuteJoinsFiltersProjectsAndSlices(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT DISTINCT ?s ?price WHERE {
  ?s <http://example/product> ?p .
  ?p <http://example/price> ?price .
  FILTER(?price < 20)
} ORDER BY DESC(?price) OFFSET 1 LIMIT 1`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	triples := query.Triples()
	one := federation.Endpoint{ID: "one"}
	two := federation.Endpoint{ID: "two"}
	client := fakeClient{rows: map[string][]Binding{
		"one:" + triples[0].Key(): {
			{"s": IRI("http://s1"), "p": IRI("http://p1")},
			{"s": IRI("http://s2"), "p": IRI("http://p2")},
			{"s": IRI("http://s3"), "p": IRI("http://p3")},
		},
		"two:" + triples[1].Key(): {
			{"p": IRI("http://p1"), "price": Literal("10", "http://www.w3.org/2001/XMLSchema#integer", "")},
			{"p": IRI("http://p2"), "price": Literal("15", "http://www.w3.org/2001/XMLSchema#integer", "")},
			{"p": IRI("http://p3"), "price": Literal("25", "http://www.w3.org/2001/XMLSchema#integer", "")},
		},
	}}
	selection := federation.Selection{triples[0].ID: {one}, triples[1].ID: {two}}
	rows, stats, err := New(client, Options{Join: "hash"}).Execute(context.Background(), query, selection)
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if stats.HTTPRequests != 2 {
		t.Fatalf("HTTP requests = %d, want 2", stats.HTTPRequests)
	}
	if len(rows) != 1 || rows[0]["s"].Lexical != "http://s1" {
		t.Fatalf("rows = %#v, want s1 after descending order and offset", rows)
	}
}

func TestExecuteOptionalPreservesUnmatchedRows(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?label WHERE { ?s <http://example/p> ?o . OPTIONAL { ?s <http://example/label> ?label } }`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	triples := query.Triples()
	ep := federation.Endpoint{ID: "one"}
	client := fakeClient{rows: map[string][]Binding{
		"one:" + triples[0].Key(): {{"s": IRI("http://s1")}, {"s": IRI("http://s2")}},
		"one:" + triples[1].Key(): {{"s": IRI("http://s1"), "label": PlainLiteral("one")}},
	}}
	selection := federation.Selection{triples[0].ID: {ep}, triples[1].ID: {ep}}
	rows, _, err := New(client, Options{}).Execute(context.Background(), query, selection)
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if len(rows) != 2 || rows[1]["label"].Bound {
		t.Fatalf("rows = %#v, want unmatched optional row", rows)
	}
}

func TestBindJoinPassesIncomingBindingsToOptional(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?label WHERE {
  ?s <http://example/base> ?o .
  OPTIONAL { ?s <http://example/label> ?label }
}`)
	if err != nil {
		t.Fatal(err)
	}
	triples := query.Triples()
	ep := federation.Endpoint{ID: "one"}
	client := &groupInputClient{calls: map[string][]int{}}
	_, _, err = New(client, Options{Join: "bind", BindBatchSize: 10}).Execute(
		context.Background(), query, federation.Selection{triples[0].ID: {ep}, triples[1].ID: {ep}},
	)
	if err != nil {
		t.Fatal(err)
	}
	if got := client.calls["http://example/label"]; len(got) != 1 || got[0] != 2 {
		t.Fatalf("optional input sizes = %#v, want [2]", got)
	}
}

func TestBindJoinPassesIncomingBindingsToUnionArms(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?value WHERE {
  ?s <http://example/base> ?o .
  { ?s <http://example/left> ?value } UNION { ?s <http://example/right> ?value }
}`)
	if err != nil {
		t.Fatal(err)
	}
	triples := query.Triples()
	ep := federation.Endpoint{ID: "one"}
	selection := federation.Selection{}
	for _, triple := range triples {
		selection[triple.ID] = []federation.Endpoint{ep}
	}
	client := &groupInputClient{calls: map[string][]int{}}
	_, _, err = New(client, Options{Join: "bind", BindBatchSize: 10}).Execute(context.Background(), query, selection)
	if err != nil {
		t.Fatal(err)
	}
	for _, predicate := range []string{"http://example/left", "http://example/right"} {
		if got := client.calls[predicate]; len(got) != 1 || got[0] != 2 {
			t.Fatalf("%s input sizes = %#v, want [2]", predicate, got)
		}
	}
}

func TestBindJoinSendsIntermediateBindings(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?o WHERE { ?s <http://example/first> ?x . ?x <http://example/second> ?o }`)
	if err != nil {
		t.Fatal(err)
	}
	triples := query.Triples()
	ep1 := federation.Endpoint{ID: "one"}
	ep2 := federation.Endpoint{ID: "two"}
	client := &bindRecordingClient{}
	_, _, err = New(client, Options{Join: "bind", BindBatchSize: 10}).Execute(context.Background(), query, federation.Selection{triples[0].ID: {ep1}, triples[1].ID: {ep2}})
	if err != nil {
		t.Fatal(err)
	}
	if len(client.calls) != 2 || client.calls[0] != 0 || client.calls[1] != 1 {
		t.Fatalf("input sizes = %#v, want [0 1]", client.calls)
	}
}

func TestExclusiveGroupUsesOneRequest(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?o WHERE { ?s <http://example/first> ?x . ?x <http://example/second> ?o }`)
	if err != nil {
		t.Fatal(err)
	}
	triples := query.Triples()
	ep := federation.Endpoint{ID: "one"}
	client := &bindRecordingClient{}
	rows, stats, err := New(client, Options{Join: "hash", ExclusiveGroups: true}).Execute(context.Background(), query, federation.Selection{triples[0].ID: {ep}, triples[1].ID: {ep}})
	if err != nil {
		t.Fatal(err)
	}
	if stats.HTTPRequests != 1 || len(client.calls) != 1 || len(rows) != 1 {
		t.Fatalf("requests=%d calls=%#v rows=%#v", stats.HTTPRequests, client.calls, rows)
	}
}

func TestExclusiveGroupsCanBeDisabledForAblation(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?o WHERE { ?s <http://example/first> ?x . ?x <http://example/second> ?o }`)
	if err != nil {
		t.Fatal(err)
	}
	triples := query.Triples()
	ep := federation.Endpoint{ID: "one"}
	client := &bindRecordingClient{}
	_, stats, err := New(client, Options{Join: "hash"}).Execute(context.Background(), query, federation.Selection{triples[0].ID: {ep}, triples[1].ID: {ep}})
	if err != nil {
		t.Fatal(err)
	}
	if stats.HTTPRequests != 2 {
		t.Fatalf("requests = %d, want 2", stats.HTTPRequests)
	}
}

func TestExecuteDeduplicatesReplicatedBindingsAcrossEndpoints(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/type> <http://example/Product> }`)
	if err != nil {
		t.Fatal(err)
	}
	triple := query.Triples()[0]
	one := federation.Endpoint{ID: "one"}
	two := federation.Endpoint{ID: "two"}
	row := Binding{"s": IRI("http://example/product/1")}
	client := fakeClient{rows: map[string][]Binding{
		"one:" + triple.Key(): {row},
		"two:" + triple.Key(): {row},
	}}

	rows, _, err := New(client, Options{Join: "hash"}).Execute(
		context.Background(),
		query,
		federation.Selection{triple.ID: {one, two}},
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 {
		t.Fatalf("rows = %#v, want one binding for replicated triple", rows)
	}
}

func TestLocalityRoutingReducesEndpointFanOut(t *testing.T) {
	t.Parallel()
	// Two endpoints with distinct graph IRI prefixes; the bound subject IRI belongs
	// to vendor0, so only vendor0 should be queried for subsequent triple patterns.
	query, err := sparql.Parse(`SELECT ?s ?label WHERE {
  ?s <http://example/sameAs> <http://global/Product1> .
  ?s <http://example/label> ?label
}`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	triples := query.Triples()
	v0 := federation.Endpoint{ID: "vendor0", GraphIRI: "http://www.vendor0.fr/", URL: "http://endpoint/v0"}
	v1 := federation.Endpoint{ID: "vendor1", GraphIRI: "http://www.vendor1.fr/", URL: "http://endpoint/v1"}
	type call struct {
		endpoint string
		pred     string
		inputs   int
	}
	var calls []call
	client := &callRecordingClient{fn: func(ep federation.Endpoint, tps []sparql.TriplePattern, inputs []Binding) ([]Binding, error) {
		pred := tps[0].Predicate.Value
		calls = append(calls, call{ep.ID, pred, len(inputs)})
		if pred == "http://example/sameAs" && ep.ID == "vendor0" && len(inputs) == 0 {
			return []Binding{{"s": IRI("http://www.vendor0.fr/Product1")}}, nil
		}
		if pred == "http://example/label" && ep.ID == "vendor0" {
			return []Binding{{"s": IRI("http://www.vendor0.fr/Product1"), "label": PlainLiteral("Widget")}}, nil
		}
		return nil, nil
	}}
	selection := federation.Selection{triples[0].ID: {v0, v1}, triples[1].ID: {v0, v1}}
	rows, _, err := New(client, Options{Join: "bind", BindBatchSize: 10}).Execute(context.Background(), query, selection)
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if len(rows) != 1 || rows[0]["label"].Lexical != "Widget" {
		t.Fatalf("rows = %#v, calls = %#v", rows, calls)
	}
	// tp1 (bind join with vendor0-local ?s IRI): only vendor0 should be queried
	for _, c := range calls {
		if c.pred == "http://example/label" && c.endpoint != "vendor0" {
			t.Fatalf("locality routing sent label query to %s, want vendor0 only; calls=%#v", c.endpoint, calls)
		}
	}
	labelCallCount := 0
	for _, c := range calls {
		if c.pred == "http://example/label" {
			labelCallCount++
		}
	}
	if labelCallCount != 1 {
		t.Fatalf("expected 1 label call (to vendor0), got %d; calls=%#v", labelCallCount, calls)
	}
}

// TestScalarSetOptimizationAvoidsJoinExplosion verifies the q05-style scalar
// optimization: patterns whose only new variables appear solely in the FILTER
// (not in SELECT or other triple patterns) are executed as scalar-set collectors
// rather than joined, preventing cross-product blowup.
func TestScalarSetOptimizationAvoidsJoinExplosion(t *testing.T) {
	t.Parallel()
	// Simulates q05 structure:
	//   ?anchor sameAs <Ref>.            → tp0 (1 result)
	//   ?anchor <p:prop1> ?filterVar1.   → tp1 (scalar: filterVar1 only in FILTER)
	//   ?anchor <p:prop2> ?filterVar2.   → tp2 (scalar: filterVar2 only in FILTER)
	//   ?other  <p:prop1> ?simVar1.      → tp3 (join var: simVar1 also in FILTER)
	//   FILTER(?simVar1 > ?filterVar1 - 10 && ?simVar1 < ?filterVar1 + 10)
	// Without scalar optimization: rows after tp1×tp2 = 2×3 = 6; with optimization = 2.
	query, err := sparql.Parse(`
SELECT ?other WHERE {
  ?anchor <http://example/sameAs> <http://example/Ref>.
  ?anchor <http://example/p1> ?filterVar1.
  ?other  <http://example/p1> ?simVar1.
  FILTER(?simVar1 > ?filterVar1 - 10 && ?simVar1 < ?filterVar1 + 10)
}`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	triples := query.Triples()
	ep := federation.Endpoint{ID: "one"}
	var joinSizes []int
	client := &callRecordingClient{fn: func(endpoint federation.Endpoint, tps []sparql.TriplePattern, inputs []Binding) ([]Binding, error) {
		joinSizes = append(joinSizes, len(inputs))
		pred := tps[0].Predicate.Value
		switch pred {
		case "http://example/sameAs":
			return []Binding{{"anchor": IRI("http://example/LocalRef")}}, nil
		case "http://example/p1":
			if tps[0].Subject.Value == "anchor" {
				// scalar pattern: two filterVar1 values
				return []Binding{{"anchor": IRI("http://example/LocalRef"), "filterVar1": Literal("100", "", "")},
					{"anchor": IRI("http://example/LocalRef"), "filterVar1": Literal("200", "", "")}}, nil
			}
			// simVar1 for ?other
			return []Binding{
				{"other": IRI("http://example/O1"), "simVar1": Literal("105", "", "")}, // matches filterVar1=100
				{"other": IRI("http://example/O2"), "simVar1": Literal("300", "", "")}, // no match
			}, nil
		}
		return nil, nil
	}}
	sel := federation.Selection{}
	for _, tp := range triples {
		sel[tp.ID] = []federation.Endpoint{ep}
	}
	rows, _, err := New(client, Options{Join: "bind", BindBatchSize: 10}).Execute(context.Background(), query, sel)
	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if len(rows) != 1 || rows[0]["other"].Lexical != "http://example/O1" {
		t.Fatalf("rows = %#v, want only O1 (105 is within 10 of 100)", rows)
	}
}

type callRecordingClient struct {
	fn func(federation.Endpoint, []sparql.TriplePattern, []Binding) ([]Binding, error)
}

func (c *callRecordingClient) Select(_ context.Context, ep federation.Endpoint, tps []sparql.TriplePattern, inputs []Binding) ([]Binding, error) {
	return c.fn(ep, tps, inputs)
}

func cloneRows(rows []Binding) []Binding {
	result := make([]Binding, len(rows))
	for i, row := range rows {
		result[i] = row.Clone()
	}
	return result
}
