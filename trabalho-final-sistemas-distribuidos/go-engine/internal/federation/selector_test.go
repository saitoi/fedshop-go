package federation

import (
	"context"
	"sync"
	"testing"

	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

type recordingClient struct {
	mu      sync.Mutex
	answers map[string]bool
	asks    []string
}

func (c *recordingClient) Ask(_ context.Context, endpoint Endpoint, triple sparql.TriplePattern) (bool, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	key := endpoint.ID + ":" + triple.Key()
	c.asks = append(c.asks, key)
	return c.answers[key], nil
}

func TestParseEndpointConfig(t *testing.T) {
	t.Parallel()
	config := `
@prefix sd: <http://www.w3.org/ns/sparql-service-description#> .
<http://www.vendor0.fr/> a sd:Service ; sd:endpoint "http://proxy/vendor0" .
<http://www.ratingsite0.fr/> a sd:Service ; sd:endpoint "http://proxy/rating0" .`
	endpoints, err := ParseEndpointConfig(config)
	if err != nil {
		t.Fatalf("ParseEndpointConfig() error = %v", err)
	}
	if len(endpoints) != 2 || endpoints[0].ID != "http_www.vendor0.fr" || endpoints[1].URL != "http://proxy/rating0" {
		t.Fatalf("endpoints = %#v", endpoints)
	}
}

func TestASKSelectorCachesWithinQuery(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/p> ?o . ?s <http://example/p> ?o . }`)
	if err != nil {
		t.Fatalf("parse query: %v", err)
	}
	endpoints := []Endpoint{{ID: "one", URL: "http://one"}, {ID: "two", URL: "http://two"}}
	client := &recordingClient{answers: map[string]bool{
		"one:" + query.Triples()[0].Key(): true,
	}}
	selector := NewASKSelector(client, 2, true)
	selection, stats, err := selector.Select(context.Background(), query, endpoints)
	if err != nil {
		t.Fatalf("Select() error = %v", err)
	}
	if stats.ASKRequests != 2 {
		t.Fatalf("ASK requests = %d, want 2", stats.ASKRequests)
	}
	if len(selection[query.Triples()[0].ID]) != 1 || selection[query.Triples()[0].ID][0].ID != "one" {
		t.Fatalf("selection = %#v", selection)
	}
}

func TestASKSelectorCanDisableCacheForAblation(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/p> ?o . ?s <http://example/p> ?o . }`)
	if err != nil {
		t.Fatal(err)
	}
	endpoint := Endpoint{ID: "one"}
	client := &recordingClient{answers: map[string]bool{"one:" + query.Triples()[0].Key(): true}}
	_, stats, err := NewASKSelector(client, 1, false).Select(context.Background(), query, []Endpoint{endpoint})
	if err != nil {
		t.Fatal(err)
	}
	if stats.ASKRequests != 2 {
		t.Fatalf("ASK requests = %d, want 2 with cache disabled", stats.ASKRequests)
	}
}

func TestBroadcastSelectorAssignsEveryEndpoint(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/p> ?o }`)
	if err != nil {
		t.Fatalf("parse query: %v", err)
	}
	endpoints := []Endpoint{{ID: "one"}, {ID: "two"}}
	selection, _, err := (BroadcastSelector{}).Select(context.Background(), query, endpoints)
	if err != nil {
		t.Fatalf("Select() error = %v", err)
	}
	if got := len(selection[0]); got != 2 {
		t.Fatalf("selected endpoints = %d, want 2", got)
	}
}
