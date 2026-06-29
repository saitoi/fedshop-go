package endpoint

import (
	"context"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }

func TestClientASKAndSelect(t *testing.T) {
	t.Parallel()
	var requests []string
	httpClient := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		body, _ := io.ReadAll(r.Body)
		requests = append(requests, string(body))
		payload := `{"head":{"vars":["s","label"]},"results":{"bindings":[{"s":{"type":"uri","value":"http://s"},"label":{"type":"literal","xml:lang":"en","value":"Phone"}}]}}`
		if strings.Contains(string(body), "ASK") {
			payload = `{"boolean":true}`
		}
		return &http.Response{StatusCode: http.StatusOK, Status: "200 OK", Body: io.NopCloser(strings.NewReader(payload)), Header: make(http.Header)}, nil
	})}

	query, err := sparql.Parse(`SELECT ?s WHERE { ?s <http://example/p> ?o }`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	client := NewClient(httpClient, time.Second)
	ep := federation.Endpoint{ID: "test", URL: "http://endpoint"}
	has, err := client.Ask(context.Background(), ep, query.Triples()[0])
	if err != nil || !has {
		t.Fatalf("Ask() = %v, %v", has, err)
	}
	rows, err := client.Select(context.Background(), ep, query.Triples(), nil)
	if err != nil {
		t.Fatalf("Select() error = %v", err)
	}
	if len(rows) != 1 || rows[0]["s"] != executor.IRI("http://s") || rows[0]["label"].Language != "en" {
		t.Fatalf("rows = %#v", rows)
	}
	rawRows, err := client.Query(context.Background(), ep, "SELECT ?s ?label WHERE { ?s ?p ?label }")
	if err != nil || len(rawRows) != 1 {
		t.Fatalf("Query() = %#v, %v", rawRows, err)
	}
	if len(requests) != 3 || !strings.Contains(requests[0], "query=ASK") || !strings.Contains(requests[1], "SELECT") {
		t.Fatalf("requests = %#v", requests)
	}
}

func TestClientHonorsContextCancellation(t *testing.T) {
	t.Parallel()
	httpClient := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		<-r.Context().Done()
		return nil, r.Context().Err()
	})}
	client := NewClient(httpClient, time.Minute)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := client.Ask(ctx, federation.Endpoint{URL: "http://endpoint"}, sparql.TriplePattern{})
	if err == nil {
		t.Fatal("Ask() error = nil, want cancellation")
	}
}

func TestClientCanonicalizesFloatingPointLiteralLexicalForm(t *testing.T) {
	t.Parallel()
	httpClient := &http.Client{Transport: roundTripFunc(func(_ *http.Request) (*http.Response, error) {
		payload := `{"results":{"bindings":[{"price":{"type":"literal","datatype":"http://www.w3.org/2001/XMLSchema#decimal","value":"2787.7100000000000364"}}]}}`
		return &http.Response{
			StatusCode: http.StatusOK,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(payload)),
			Header:     make(http.Header),
		}, nil
	})}
	client := NewClient(httpClient, time.Second)

	rows, err := client.Query(context.Background(), federation.Endpoint{URL: "http://endpoint"}, "SELECT ?price WHERE {}")
	if err != nil {
		t.Fatal(err)
	}
	if got := rows[0]["price"].Lexical; got != "2787.71" {
		t.Fatalf("price lexical = %q, want 2787.71", got)
	}
}

func TestClientRetriesTransientTransportErrors(t *testing.T) {
	t.Parallel()
	attempts := 0
	httpClient := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		attempts++
		if attempts < 3 {
			return nil, io.ErrUnexpectedEOF
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(`{"boolean":true}`)),
			Header:     make(http.Header),
		}, nil
	})}
	client := NewClient(httpClient, time.Second, WithRetries(2), WithRetryBackoff(0))

	has, err := client.Ask(context.Background(), federation.Endpoint{URL: "http://endpoint"}, sparql.TriplePattern{})
	if err != nil || !has {
		t.Fatalf("Ask() = %v, %v", has, err)
	}
	if attempts != 3 {
		t.Fatalf("attempts = %d, want 3", attempts)
	}
}

func TestClientDoesNotRetryClientErrors(t *testing.T) {
	t.Parallel()
	attempts := 0
	httpClient := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		attempts++
		return &http.Response{
			StatusCode: http.StatusBadRequest,
			Status:     "400 Bad Request",
			Body:       io.NopCloser(strings.NewReader("bad query")),
			Header:     make(http.Header),
		}, nil
	})}
	client := NewClient(httpClient, time.Second, WithRetries(3), WithRetryBackoff(0))

	_, err := client.Ask(context.Background(), federation.Endpoint{URL: "http://endpoint"}, sparql.TriplePattern{})
	if err == nil || !strings.Contains(err.Error(), "400 Bad Request") {
		t.Fatalf("Ask() error = %v", err)
	}
	if attempts != 1 {
		t.Fatalf("attempts = %d, want 1", attempts)
	}
}

func TestNewHTTPClientUsesExplicitProxy(t *testing.T) {
	t.Parallel()
	httpClient, err := NewHTTPClient("http://localhost:5555")
	if err != nil {
		t.Fatalf("NewHTTPClient() error = %v", err)
	}
	transport, ok := httpClient.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport = %T", httpClient.Transport)
	}
	proxy, err := transport.Proxy(&http.Request{URL: mustURL(t, "http://localhost:8890/sparql")})
	if err != nil {
		t.Fatalf("Proxy() error = %v", err)
	}
	if proxy.String() != "http://localhost:5555" {
		t.Fatalf("proxy = %s", proxy)
	}
}

func mustURL(t *testing.T, value string) *url.URL {
	t.Helper()
	parsed, err := url.Parse(value)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}
