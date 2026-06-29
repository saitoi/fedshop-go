// Package endpoint provides the HTTP SPARQL protocol boundary.
package endpoint

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

// Client executes SPARQL protocol requests.
type Client struct {
	httpClient *http.Client
	timeout    time.Duration
	retries    int
	backoff    time.Duration
	requests   atomic.Int64
	bytes      atomic.Int64
}

// Option configures endpoint request behavior.
type Option func(*Client)

// WithRetries sets the number of retries after the initial request.
func WithRetries(retries int) Option {
	return func(client *Client) {
		if retries > 0 {
			client.retries = retries
		}
	}
}

// WithRetryBackoff sets the initial delay between request attempts.
func WithRetryBackoff(backoff time.Duration) Option {
	return func(client *Client) { client.backoff = backoff }
}

// NewClient constructs a SPARQL HTTP client.
func NewClient(httpClient *http.Client, timeout time.Duration, options ...Option) *Client {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	client := &Client{httpClient: httpClient, timeout: timeout, backoff: 100 * time.Millisecond}
	for _, option := range options {
		option(client)
	}
	return client
}

// NewHTTPClient constructs an HTTP client with an optional explicit proxy.
func NewHTTPClient(proxyURL string) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if proxyURL != "" {
		parsed, err := url.Parse(proxyURL)
		if err != nil {
			return nil, fmt.Errorf("parse HTTP proxy: %w", err)
		}
		transport.Proxy = http.ProxyURL(parsed)
	}
	return &http.Client{Transport: transport}, nil
}

// Requests returns the number of completed request attempts.
func (c *Client) Requests() int64 { return c.requests.Load() }

// Bytes returns response-body bytes read.
func (c *Client) Bytes() int64 { return c.bytes.Load() }

// Ask implements federation.ASKClient.
func (c *Client) Ask(ctx context.Context, endpoint federation.Endpoint, triple sparql.TriplePattern) (bool, error) {
	query := "ASK WHERE { " + triple.Key() + " . }"
	body, err := c.do(ctx, endpoint.URL, query)
	if err != nil {
		return false, err
	}
	var response struct {
		Boolean bool `json:"boolean"`
	}
	if err := json.Unmarshal(body, &response); err != nil {
		return false, fmt.Errorf("decode ASK response: %w", err)
	}
	return response.Boolean, nil
}

// Select implements executor.Client.
func (c *Client) Select(ctx context.Context, endpoint federation.Endpoint, triples []sparql.TriplePattern, inputs []executor.Binding) ([]executor.Binding, error) {
	query := buildSelect(triples, inputs)
	return c.Query(ctx, endpoint, query)
}

// Query executes an arbitrary SELECT query for metadata construction.
func (c *Client) Query(ctx context.Context, endpoint federation.Endpoint, query string) ([]executor.Binding, error) {
	body, err := c.do(ctx, endpoint.URL, query)
	if err != nil {
		return nil, err
	}
	var response struct {
		Results struct {
			Bindings []map[string]struct {
				Type     string `json:"type"`
				Value    string `json:"value"`
				Datatype string `json:"datatype"`
				Language string `json:"xml:lang"`
			} `json:"bindings"`
		} `json:"results"`
	}
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("decode SELECT response: %w", err)
	}
	rows := make([]executor.Binding, 0, len(response.Results.Bindings))
	for _, raw := range response.Results.Bindings {
		row := executor.Binding{}
		for name, value := range raw {
			if value.Type == "uri" {
				row[name] = executor.IRI(value.Value)
			} else {
				row[name] = executor.Literal(canonicalNumericLexical(value.Value, value.Datatype), value.Datatype, value.Language)
			}
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func canonicalNumericLexical(value, datatype string) string {
	switch datatype {
	case "http://www.w3.org/2001/XMLSchema#decimal",
		"http://www.w3.org/2001/XMLSchema#double",
		"http://www.w3.org/2001/XMLSchema#float":
		number, err := strconv.ParseFloat(value, 64)
		if err == nil {
			return strconv.FormatFloat(number, 'f', -1, 64)
		}
	}
	return value
}

func (c *Client) do(ctx context.Context, endpointURL, query string) ([]byte, error) {
	if c.timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, c.timeout)
		defer cancel()
	}
	form := url.Values{"query": {query}}.Encode()
	var lastErr error
	for attempt := 0; attempt <= c.retries; attempt++ {
		if attempt > 0 && c.backoff > 0 {
			delay := c.backoff << (attempt - 1)
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return nil, fmt.Errorf("retry SPARQL request: %w", ctx.Err())
			case <-timer.C:
			}
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpointURL, strings.NewReader(form))
		if err != nil {
			return nil, fmt.Errorf("create SPARQL request: %w", err)
		}
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req.Header.Set("Accept", "application/sparql-results+json")
		c.requests.Add(1)
		response, err := c.httpClient.Do(req)
		if err != nil {
			if ctx.Err() != nil {
				return nil, fmt.Errorf("execute SPARQL request: %w", ctx.Err())
			}
			lastErr = fmt.Errorf("execute SPARQL request: %w", err)
			continue
		}
		body, readErr := io.ReadAll(io.LimitReader(response.Body, 2<<30))
		closeErr := response.Body.Close()
		if readErr != nil {
			lastErr = fmt.Errorf("read SPARQL response: %w", readErr)
			continue
		}
		if closeErr != nil {
			lastErr = fmt.Errorf("close SPARQL response: %w", closeErr)
			continue
		}
		c.bytes.Add(int64(len(body)))
		if response.StatusCode >= 200 && response.StatusCode < 300 {
			return body, nil
		}
		lastErr = fmt.Errorf("SPARQL endpoint returned %s: %s", response.Status, strings.TrimSpace(string(body)))
		if response.StatusCode != http.StatusBadGateway && response.StatusCode != http.StatusServiceUnavailable && response.StatusCode != http.StatusGatewayTimeout {
			return nil, lastErr
		}
	}
	return nil, lastErr
}

func buildSelect(triples []sparql.TriplePattern, inputs []executor.Binding) string {
	var builder strings.Builder
	builder.WriteString("SELECT * WHERE { ")
	if len(inputs) > 0 {
		// Only send variables that appear in these triple patterns; other bound
		// variables will be reintroduced by the join after the endpoint returns.
		// This avoids inflating VALUES clauses with irrelevant bindings.
		tripleVarSet := map[string]bool{}
		for _, tp := range triples {
			for _, v := range tp.Variables() {
				tripleVarSet[v] = true
			}
		}
		// Among those, keep only variables that are actually bound in inputs.
		boundVarSet := map[string]bool{}
		for _, row := range inputs {
			for variable, value := range row {
				if value.Bound && tripleVarSet[variable] {
					boundVarSet[variable] = true
				}
			}
		}
		vars := make([]string, 0, len(boundVarSet))
		for variable := range boundVarSet {
			vars = append(vars, variable)
		}
		sort.Strings(vars)
		// Deduplicate rows by the relevant variable subset to avoid redundant requests.
		type rowKey = string
		seen := map[rowKey]bool{}
		var deduped []executor.Binding
		for _, row := range inputs {
			key := rowKeyFor(row, vars)
			if !seen[key] {
				seen[key] = true
				deduped = append(deduped, row)
			}
		}
		if len(vars) > 0 {
			builder.WriteString("VALUES (")
			for _, variable := range vars {
				builder.WriteString(" ?" + variable)
			}
			builder.WriteString(" ) {")
			for _, row := range deduped {
				builder.WriteString(" (")
				for _, variable := range vars {
					builder.WriteByte(' ')
					builder.WriteString(renderValue(row[variable]))
				}
				builder.WriteString(" )")
			}
			builder.WriteString(" } ")
		}
	}
	for _, triple := range triples {
		builder.WriteString(triple.Key())
		builder.WriteString(" . ")
	}
	builder.WriteString("}")
	return builder.String()
}

func rowKeyFor(row executor.Binding, vars []string) string {
	var b strings.Builder
	for _, v := range vars {
		b.WriteString(v)
		b.WriteByte('=')
		val := row[v]
		b.WriteString(val.Kind)
		b.WriteByte(':')
		b.WriteString(val.Lexical)
		b.WriteByte('\x00')
	}
	return b.String()
}

func renderValue(value executor.Value) string {
	if !value.Bound {
		return "UNDEF"
	}
	if value.Kind == "uri" {
		return "<" + value.Lexical + ">"
	}
	quoted := strconvQuote(value.Lexical)
	if value.Language != "" {
		return quoted + "@" + value.Language
	}
	if value.Datatype != "" {
		return quoted + "^^<" + value.Datatype + ">"
	}
	return quoted
}
func strconvQuote(value string) string { return strconv.Quote(value) }
