package engine

import (
	"context"
	"encoding/csv"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// Executor queries SERVICE endpoints and joins their bindings locally.
type Executor struct {
	client *http.Client
}

// NewExecutor creates an Executor. If client is nil, http.DefaultClient is used.
func NewExecutor(client *http.Client) *Executor {
	if client == nil {
		client = http.DefaultClient
	}
	return &Executor{client: client}
}

// Execute runs each SERVICE block as SELECT * WHERE { ... } and naturally joins the results.
func (e *Executor) Execute(ctx context.Context, query Query) (Result, error) {
	var result Result
	var joined []Binding

	for _, block := range query.ServiceBlocks {
		rows, err := e.queryService(ctx, query.Prefixes, block)
		if err != nil {
			return Result{}, err
		}
		result.HTTPRequests++
		joined = JoinBindings(joined, rows)
		if len(joined) == 0 {
			break
		}
	}

	if query.Distinct {
		joined = distinctBindings(joined)
	}
	if query.Limit > 0 && len(joined) > query.Limit {
		joined = joined[:query.Limit]
	}
	result.Bindings = joined
	return result, nil
}

func (e *Executor) queryService(ctx context.Context, prefixes map[string]string, block ServiceBlock) ([]Binding, error) {
	serviceQuery := buildServiceQuery(prefixes, block.Triples)
	reqURL, err := url.Parse(block.Endpoint)
	if err != nil {
		return nil, fmt.Errorf("parse endpoint %q: %w", block.Endpoint, err)
	}
	values := reqURL.Query()
	values.Set("query", serviceQuery)
	reqURL.RawQuery = values.Encode()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Accept", "text/csv")

	resp, err := e.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("query %s: %w", block.Endpoint, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("query %s: status %d: %s", block.Endpoint, resp.StatusCode, strings.TrimSpace(string(body)))
	}

	rows, err := readCSVBindings(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read csv from %s: %w", block.Endpoint, err)
	}
	return rows, nil
}

func buildServiceQuery(prefixes map[string]string, triples []string) string {
	var b strings.Builder
	for name, iri := range prefixes {
		fmt.Fprintf(&b, "PREFIX %s: <%s>\n", name, iri)
	}
	b.WriteString("SELECT * WHERE {\n")
	for _, triple := range triples {
		b.WriteString("  ")
		b.WriteString(triple)
		b.WriteByte('\n')
	}
	b.WriteString("}")
	return b.String()
}

func readCSVBindings(r io.Reader) ([]Binding, error) {
	reader := csv.NewReader(r)
	header, err := reader.Read()
	if err != nil {
		if err == io.EOF {
			return nil, nil
		}
		return nil, err
	}
	for i, name := range header {
		header[i] = strings.TrimPrefix(strings.TrimSpace(name), "?")
	}

	var rows []Binding
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		row := make(Binding, len(header))
		for i, name := range header {
			if i < len(record) {
				row[name] = record[i]
			}
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func distinctBindings(rows []Binding) []Binding {
	seen := map[string]bool{}
	out := make([]Binding, 0, len(rows))
	for _, row := range rows {
		key := bindingKey(row)
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, row)
	}
	return out
}

func bindingKey(row Binding) string {
	keys := allVars([]Binding{row})
	parts := make([]string, 0, len(keys))
	for _, key := range keys {
		parts = append(parts, key+"="+row[key])
	}
	return strings.Join(parts, "\x00")
}
