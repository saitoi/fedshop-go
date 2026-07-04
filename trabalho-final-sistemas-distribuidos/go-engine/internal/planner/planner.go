// Package planner orders source-assigned triple patterns.
package planner

import (
	"math"
	"sort"

	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/metadata"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

// SourceCountOrder returns triple IDs ordered by increasing selected-source count.
func SourceCountOrder(query sparql.Query, selection federation.Selection) []int {
	triples := query.Triples()
	sort.SliceStable(triples, func(i, j int) bool { return len(selection[triples[i].ID]) < len(selection[triples[j].ID]) })
	result := make([]int, len(triples))
	for i, triple := range triples {
		result[i] = triple.ID
	}
	return result
}

// CostOrder uses predicate cardinalities, with connectedness as a tie breaker.
func CostOrder(query sparql.Query, selection federation.Selection, catalog metadata.Catalog) []int {
	triples := query.Triples()
	chosen := map[string]bool{}
	result := make([]int, 0, len(triples))
	for len(result) < len(triples) {
		best := -1
		bestCost := int64(math.MaxInt64)
		bestConnected := false
		for i, triple := range triples {
			already := false
			for _, id := range result {
				if id == triple.ID {
					already = true
					break
				}
			}
			if already {
				continue
			}
			cost := estimate(triple, selection, catalog)
			connected := false
			for _, variable := range triple.Variables() {
				if chosen[variable] {
					connected = true
				}
			}
			if best < 0 || cost < bestCost || cost == bestCost && connected && !bestConnected {
				best = i
				bestCost = cost
				bestConnected = connected
			}
		}
		result = append(result, triples[best].ID)
		for _, variable := range triples[best].Variables() {
			chosen[variable] = true
		}
	}
	return result
}

func estimate(triple sparql.TriplePattern, selection federation.Selection, catalog metadata.Catalog) int64 {
	if triple.Predicate.Kind != sparql.TermIRI {
		return int64(len(selection[triple.ID])) * math.MaxInt32
	}
	var total int64
	for _, endpoint := range selection[triple.ID] {
		count := catalog.Endpoints[endpoint.ID].Predicates[triple.Predicate.Value]
		if count == 0 {
			count = math.MaxInt32
		}
		if total > math.MaxInt64-count {
			return math.MaxInt64
		}
		total += count
	}
	return total
}
