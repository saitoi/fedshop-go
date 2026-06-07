package engine

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestExecutorQueriesServiceBlocksAndJoinsResults(t *testing.T) {
	var requests []string
	client := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		requests = append(requests, r.URL.Query().Get("query"))
		body := "product,review\np1,r1\n"
		if len(requests) == 1 {
			body = "product,label\np1,A\np2,B\n"
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"text/csv"}},
			Body:       io.NopCloser(strings.NewReader(body)),
		}, nil
	})}

	query := Query{
		Prefixes: map[string]string{"rdfs": "http://www.w3.org/2000/01/rdf-schema#"},
		Select:   []string{"product", "label", "review"},
		ServiceBlocks: []ServiceBlock{
			{Endpoint: "http://shop.example/sparql", Triples: []string{"?product rdfs:label ?label ."}},
			{Endpoint: "http://reviews.example/sparql", Triples: []string{"?review <http://example/reviewFor> ?product ."}},
		},
	}

	executor := NewExecutor(client)
	result, err := executor.Execute(context.Background(), query)
	if err != nil {
		t.Fatalf("Execute returned error: %v", err)
	}

	if got, want := len(result.Bindings), 1; got != want {
		t.Fatalf("binding count = %d, want %d: bindings=%#v requests=%#v", got, want, result.Bindings, requests)
	}
	if got, want := result.Bindings[0]["review"], "r1"; got != want {
		t.Fatalf("review = %q, want %q", got, want)
	}
	if got, want := result.HTTPRequests, 2; got != want {
		t.Fatalf("HTTPRequests = %d, want %d", got, want)
	}
	if len(requests) != 2 {
		t.Fatalf("server saw %d requests, want 2", len(requests))
	}
}

func TestReadCSVBindingsTrimsHeaders(t *testing.T) {
	rows, err := readCSVBindings(strings.NewReader("product,label\np1,A\n"))
	if err != nil {
		t.Fatalf("readCSVBindings returned error: %v", err)
	}
	if got, want := rows[0]["product"], "p1"; got != want {
		t.Fatalf("product = %q, want %q in %#v", got, want, rows)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}
