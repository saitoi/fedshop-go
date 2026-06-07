// Package engine implements a minimal RSA-style federated SPARQL executor.
package engine

// Binding maps SPARQL variable names without "?" to lexical values.
type Binding map[string]string

// Query is the subset of SPARQL supported by this example implementation.
type Query struct {
	Prefixes      map[string]string
	Select        []string
	Distinct      bool
	Limit         int
	ServiceBlocks []ServiceBlock
}

// ServiceBlock is one SERVICE endpoint and the basic graph pattern delegated to it.
type ServiceBlock struct {
	Endpoint string
	Triples  []string
}

// Result contains query bindings and lightweight execution counters.
type Result struct {
	Bindings     []Binding
	HTTPRequests int
}
