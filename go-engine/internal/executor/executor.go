// Package executor evaluates source-assigned FedShop query algebra.
package executor

import (
	"context"
	"fmt"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

var debugExec = os.Getenv("DEBUG_EXEC") == "1"

// Client executes triple-pattern groups at an endpoint.
// The optional filters variadic allows callers to inject SPARQL FILTER expressions
// that the endpoint should evaluate alongside the triple patterns (push-down).
type Client interface {
	Select(context.Context, federation.Endpoint, []sparql.TriplePattern, []Binding, ...string) ([]Binding, error)
}

// Options controls physical execution.
type Options struct {
	Join                   string
	BindBatchSize          int
	FailurePolicy          string
	TripleOrder            []int
	ExclusiveGroups        bool
	MaxConcurrency         int
	PostBindMaxInputRows   int // 0 = unlimited; skip post-bind group when input rows exceed this
}

// Stats describes physical execution work.
type Stats struct {
	HTTPRequests    int      `json:"http_requests"`
	Partial         bool     `json:"partial"`
	FailedEndpoints []string `json:"failed_endpoints,omitempty"`
}

// Executor evaluates query algebra.
type Executor struct {
	client  Client
	options Options
}

// New constructs an executor.
func New(client Client, options Options) *Executor {
	if options.FailurePolicy == "" {
		options.FailurePolicy = "strict"
	}
	return &Executor{client: client, options: options}
}

// Execute evaluates a query using the supplied source assignment.
func (e *Executor) Execute(ctx context.Context, query sparql.Query, selection federation.Selection) ([]Binding, Stats, error) {
	// Build the set of variables that appear in SELECT or ORDER BY output. These must
	// not be treated as scalar-only even when they appear in only one triple pattern.
	outputVars := map[string]bool{}
	for _, v := range query.Select {
		outputVars[v] = true
	}
	for _, cond := range query.OrderBy {
		for _, v := range regexpVars(cond.Expression) {
			outputVars[v] = true
		}
	}
	rows, stats, err := e.executeGroup(ctx, query.Where, selection, nil, outputVars)
	if err != nil {
		return nil, stats, err
	}
	projected := make([]Binding, 0, len(rows))
	for _, row := range rows {
		out := Binding{}
		vars := query.Select
		if len(vars) == 0 {
			for key := range row {
				vars = append(vars, key)
			}
			sort.Strings(vars)
		}
		for _, key := range vars {
			if value, ok := row[key]; ok && value.Bound {
				out[key] = value
			} else {
				out[key] = Value{}
			}
		}
		projected = append(projected, out)
	}
	if query.Distinct {
		projected = distinct(projected, query.Select)
	}
	if len(query.OrderBy) > 0 {
		sort.SliceStable(projected, func(i, j int) bool {
			for _, condition := range query.OrderBy {
				iv := orderValue(condition.Expression, projected[i])
				jv := orderValue(condition.Expression, projected[j])
				if iv == jv {
					continue
				}
				if condition.Ascending {
					return iv < jv
				}
				return iv > jv
			}
			return false
		})
	}
	start := query.Offset
	if start > len(projected) {
		start = len(projected)
	}
	end := len(projected)
	if query.Limit >= 0 && start+query.Limit < end {
		end = start + query.Limit
	}
	return projected[start:end], stats, nil
}

// executeGroup evaluates one WHERE group. outputVars is the set of variables that
// must appear in the final result (SELECT + ORDER BY) and must not be treated as
// scalar-only; pass nil for recursive calls (UNION/OPTIONAL sub-groups).
func (e *Executor) executeGroup(ctx context.Context, group *sparql.Group, selection federation.Selection, inputs []Binding, outputVars map[string]bool) ([]Binding, Stats, error) {
	rows := cloneBindings(inputs)
	if len(rows) == 0 {
		rows = []Binding{{}}
	}
	stats := Stats{}
	triples := append([]sparql.TriplePattern(nil), group.Triples...)
	if len(e.options.TripleOrder) > 0 {
		rank := map[int]int{}
		for index, id := range e.options.TripleOrder {
			rank[id] = index
		}
		sort.SliceStable(triples, func(i, j int) bool { return rank[triples[i].ID] < rank[triples[j].ID] })
	} else {
		triples = greedyOrderTriples(triples, selection, inputs)
	}
	// Among equal-source-count groups, defer SELECT-only output patterns until after
	// filter-variable producers so eager filter pruning fires as early as possible.
	if len(group.Filters) > 0 {
		triples = reorderForEagerFilter(triples, selection, group.Filters)
	}

	// Scalar-set optimization: patterns whose only new variables appear solely in
	// filter expressions are executed in-line but their results are collected as value
	// sets rather than joined into rows. This avoids cross-product blowup when several
	// independent properties of the same subject are used only for filter comparison.
	var scalarSets map[string][]Value
	var varCount map[string]int
	var filterOnlyVars map[string]bool
	if len(group.Filters) > 0 {
		varCount = map[string]int{}
		for _, tp := range triples {
			for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
				if term.Kind == sparql.TermVariable {
					varCount[term.Value]++
				}
			}
		}
		filterOnlyVars = computeFilterOnlyVars(triples, group.Filters, group.Optionals, outputVars)
		scalarSets = map[string][]Value{}
	}

	pendingFilters := append([]string(nil), group.Filters...)
	startAt := 0
	if endpoint, ok := exclusiveEndpoint(triples, selection); ok && e.options.Join != "bind" && e.options.ExclusiveGroups {
		remote, err := e.client.Select(ctx, endpoint, triples, nil)
		stats.HTTPRequests++
		if err != nil {
			if e.options.FailurePolicy == "partial" {
				stats.Partial = true
				stats.FailedEndpoints = append(stats.FailedEndpoints, endpoint.ID)
				rows = nil
			} else {
				return nil, stats, fmt.Errorf("select exclusive group %s: %w", endpoint.ID, err)
			}
		} else {
			rows = remote
		}
		startAt = len(triples)
	}
	remaining := triples[startAt:]
	for i := 0; i < len(remaining); i++ {
		triple := remaining[i]

		// Filter-group optimization: if the next consecutive triples all introduce only
		// filter-only variables on the same bound subject, fetch them together and apply
		// available filters before joining back to rows. This avoids the multiplicative
		// cross-product explosion when several independent properties of the same subject
		// feed only the FILTER clause.
		if filterOnlyVars != nil && len(pendingFilters) > 0 {
			if groupLen := detectFilterGroup(remaining[i:], filterOnlyVars, varCount, rows); groupLen >= 2 {
				var s Stats
				var err error
				rows, pendingFilters, s, err = e.executeFilterGroup(
					ctx, remaining[i:i+groupLen], selection, rows, scalarSets, pendingFilters)
				stats = addStats(stats, s)
				if err != nil {
					return nil, stats, err
				}
				if len(rows) == 0 {
					return nil, stats, nil
				}
				if debugExec {
					fmt.Fprintf(os.Stderr, "[exec] filter-group(tp%d..tp%d) → %d rows\n",
						remaining[i].ID, remaining[i+groupLen-1].ID, len(rows))
				}
				i += groupLen - 1 // skip grouped triples (loop will i++)
				continue
			}
		}

		sources := selection[triple.ID]
		if len(sources) == 0 {
			return nil, stats, nil
		}
		// If the triple's subject is uniformly bound to an IRI that maps to exactly one
		// endpoint, restrict sources to that endpoint. This avoids cross-product explosion
		// when the same local product/resource is replicated across many endpoints with
		// different property values (e.g., BSBM product textual properties).
		sources = pruneSourcesBySubjectLocality(triple, sources, rows)

		// Compute filters that can be pushed into the endpoint query for this triple.
		// A filter is pushable when (after substituting constant-valued variables) its
		// only remaining unbound variables are introduced by this specific triple.
		var pushFilters []string
		if len(pendingFilters) > 0 {
			if constants := extractConstantVars(rows); len(constants) > 0 {
				pushFilters = derivePushableFilters(pendingFilters, rows, triple, constants)
			}
		}
		t0 := time.Now()
		union, s, err := e.fetchTriple(ctx, triple, sources, rows, pushFilters...)
		if debugExec {
			fmt.Fprintf(os.Stderr, "[exec] tp%d %s %s %s (srcs=%d, inputs=%d) → %d results in %v\n",
				triple.ID, triple.Subject.Value, triple.Predicate.Value, triple.Object.Value,
				len(sources), len(rows), len(union), time.Since(t0))
		}
		stats = addStats(stats, s)
		if err != nil {
			return nil, stats, err
		}
		union = distinct(union, nil)

		// If this triple introduces only filter-only variables, collect them as a
		// scalar set instead of joining — avoids cross-product with existing rows.
		if filterOnlyVars != nil && isScalarTriple(triple, filterOnlyVars, varCount, rows) {
			if debugExec {
				fmt.Fprintf(os.Stderr, "[exec] tp%d → SCALAR collect\n", triple.ID)
			}
			seen := map[string]bool{}
			for _, binding := range union {
				for _, term := range []sparql.Term{triple.Subject, triple.Predicate, triple.Object} {
					if term.Kind != sparql.TermVariable {
						continue
					}
					v := term.Value
					if !filterOnlyVars[v] {
						continue
					}
					if val, ok := binding[v]; ok && val.Bound {
						key := val.Kind + ":" + val.Lexical
						if !seen[v+"\x00"+key] {
							seen[v+"\x00"+key] = true
							scalarSets[v] = append(scalarSets[v], val)
						}
					}
				}
			}
			// No join: rows unchanged. Apply eligible filters using scalar sets.
			if len(pendingFilters) > 0 {
				pendingFilters, rows = applyEligibleFiltersScalar(pendingFilters, rows, scalarSets)
				if len(rows) == 0 {
					return nil, stats, nil
				}
			}
			continue
		}

		t1 := time.Now()
		if debugExec && len(union) > 0 && len(rows) > 0 {
			shared := joinVars(rows[0], union[0])
			uniqueLeft := map[string]bool{}
			for _, r := range rows {
				uniqueLeft[bindingProjectionKey(r, shared)] = true
			}
			uniqueRight := map[string]bool{}
			for _, r := range union {
				uniqueRight[bindingProjectionKey(r, shared)] = true
			}
			fmt.Fprintf(os.Stderr, "[exec] tp%d join key=%v left=%d(unique=%d) right=%d(unique=%d)\n",
				triple.ID, shared, len(rows), len(uniqueLeft), len(union), len(uniqueRight))
		}
		rows = join(rows, union)
		if debugExec {
			fmt.Fprintf(os.Stderr, "[exec] tp%d join → %d rows in %v\n", triple.ID, len(rows), time.Since(t1))
		}
		if len(rows) == 0 {
			return nil, stats, nil
		}
		// Eager filter: apply any pending filter whose variables are all now bound.
		if len(pendingFilters) > 0 {
			pendingFilters, rows = applyEligibleFiltersScalar(pendingFilters, rows, scalarSets)
			if len(rows) == 0 {
				return nil, stats, nil
			}
		}
		// Post-bind exclusive group: if all remaining triples (after this one) can be
		// routed exclusively to one endpoint given the current bindings, execute them
		// as a single SPARQL query. This avoids cross-product explosion when many
		// single-subject properties are joined in memory.
		rest := remaining[i+1:]
		maxRows := e.options.PostBindMaxInputRows
		if len(rest) > 0 && e.options.ExclusiveGroups && (maxRows == 0 || len(rows) <= maxRows) {
			if ep, ok := postBindExclusiveEndpoint(rest, selection, rows); ok {
				remote, err := e.client.Select(ctx, ep, rest, rows)
				stats.HTTPRequests++
				if err != nil {
					if e.options.FailurePolicy == "partial" {
						stats.Partial = true
						stats.FailedEndpoints = append(stats.FailedEndpoints, ep.ID)
					} else {
						return nil, stats, fmt.Errorf("select post-bind group %s: %w", ep.ID, err)
					}
				} else {
					remote = distinct(remote, nil)
					rows = join(rows, remote)
				}
				for _, f := range pendingFilters {
					kept := rows[:0]
					for _, row := range rows {
						ok, ferr := evalFilterWithScalars(f, row, scalarSets)
						if ferr != nil {
							return nil, stats, fmt.Errorf("filter %q: %w", f, ferr)
						}
						if ok {
							kept = append(kept, row)
						}
					}
					rows = kept
				}
				pendingFilters = nil
				break
			}
		}
		// Per-endpoint compound: generalises postBind to rows spread across multiple
		// endpoints. When every row maps exclusively to ONE endpoint (via the first
		// remaining triple's subject locality) and all remaining triples are served by
		// that same endpoint, send a single compound SPARQL query per endpoint group
		// instead of N-triples × M-endpoints individual requests.
		if len(rest) > 1 && e.options.ExclusiveGroups {
			var compoundFilters []string
			if len(pendingFilters) > 0 {
				if constants := extractConstantVars(rows); len(constants) > 0 {
					compoundFilters = derivePushableFiltersCompound(pendingFilters, rows, rest, constants)
				}
			}
			if groups := perEndpointCompound(rest, selection, rows); groups != nil {
				var merged []Binding
				for _, g := range groups {
					remote, err := e.client.Select(ctx, g.endpoint, rest, g.rows, compoundFilters...)
					stats.HTTPRequests++
					if err != nil {
						if e.options.FailurePolicy == "partial" {
							stats.Partial = true
							stats.FailedEndpoints = append(stats.FailedEndpoints, g.endpoint.ID)
							continue
						}
						return nil, stats, fmt.Errorf("select per-endpoint group %s: %w", g.endpoint.ID, err)
					}
					merged = append(merged, join(g.rows, remote)...)
				}
				rows = distinct(merged, nil)
				for _, f := range pendingFilters {
					kept := rows[:0]
					for _, row := range rows {
						ok, ferr := evalFilterWithScalars(f, row, scalarSets)
						if ferr != nil {
							return nil, stats, fmt.Errorf("filter %q: %w", f, ferr)
						}
						if ok {
							kept = append(kept, row)
						}
					}
					rows = kept
				}
				pendingFilters = nil
				if debugExec {
					fmt.Fprintf(os.Stderr, "[exec] per-endpoint-compound %d groups → %d rows\n", len(groups), len(rows))
				}
				break
			}
		}
	}
	for _, pair := range group.Unions {
		left, ls, err := e.executeGroup(ctx, pair[0], selection, rows, nil)
		stats = addStats(stats, ls)
		if err != nil {
			return nil, stats, err
		}
		right, rs, err := e.executeGroup(ctx, pair[1], selection, rows, nil)
		stats = addStats(stats, rs)
		if err != nil {
			return nil, stats, err
		}
		rows = append(left, right...)
	}
	for _, optional := range group.Optionals {
		optInputs := uniqueInputsForOptional(optional, rows)
		right, os, err := e.executeGroup(ctx, optional, selection, optInputs, nil)
		stats = addStats(stats, os)
		if err != nil {
			return nil, stats, err
		}
		rows = leftJoin(rows, right)
	}
	// Apply any filters not yet applied eagerly (e.g. those referencing OPTIONAL variables).
	for _, filter := range pendingFilters {
		kept := rows[:0]
		for _, row := range rows {
			ok, err := evalFilterWithScalars(filter, row, scalarSets)
			if err != nil {
				return nil, stats, fmt.Errorf("filter %q: %w", filter, err)
			}
			if ok {
				kept = append(kept, row)
			}
		}
		rows = kept
	}
	return rows, stats, nil
}

// detectFilterGroup checks whether the leading triples in a slice form a
// "filter group": ≥2 consecutive patterns with the same bound subject variable
// where every new (unbound) variable they introduce is filter-only. When such a
// group exists, executeFilterGroup can process them together to avoid the
// multiplicative join explosion.
func detectFilterGroup(triples []sparql.TriplePattern, filterOnlyVars map[string]bool, varCount map[string]int, rows []Binding) int {
	if len(triples) < 2 || len(rows) == 0 || filterOnlyVars == nil {
		return 0
	}
	first := triples[0]
	if first.Subject.Kind != sparql.TermVariable {
		return 0
	}
	subjVar := first.Subject.Value
	sample := rows[0]
	if val, ok := sample[subjVar]; !ok || !val.Bound {
		return 0
	}
	count := 0
	for _, tp := range triples {
		if tp.Subject.Kind != sparql.TermVariable || tp.Subject.Value != subjVar {
			break
		}
		allFilterOnly := true
		for _, term := range []sparql.Term{tp.Predicate, tp.Object} {
			if term.Kind != sparql.TermVariable {
				continue
			}
			v := term.Value
			// If the var is already bound in the rows it's a join constraint, not new.
			if val, ok := sample[v]; ok && val.Bound {
				continue
			}
			if !filterOnlyVars[v] {
				allFilterOnly = false
				break
			}
		}
		if !allFilterOnly {
			break
		}
		// Scalar triples (uniform join variable) belong to the scalar-set optimization,
		// not the filter group — break here to let the scalar path handle them.
		if isScalarTriple(tp, filterOnlyVars, varCount, rows) {
			break
		}
		count++
	}
	return count
}

// executeFilterGroup processes a group of filter-only triples (same bound subject)
// without joining their results together. Each triple is fetched independently:
// a lp "passes" a triple when it has at least one result satisfying the partial filter
// (unknown group vars treated as pass-through). Only lps that pass ALL triples enter
// the passSet, and the original rows are pruned to that set.
//
// This avoids the multiplicative cross-product: instead of join(tp9_results, tp10_results)
// → 175K rows → 39M filter evaluations, we evaluate 10K + 10K rows independently.
// Correctness holds when each scalar variable's filter clauses are independent (no
// cross-var terms), which evalFilterPartialPrune's excludeIrrelevantScalarVars handles
// by skipping scalar vars whose clauses only involve unknown variables.
func (e *Executor) executeFilterGroup(
	ctx context.Context,
	groupTriples []sparql.TriplePattern,
	selection federation.Selection,
	rows []Binding,
	scalarSets map[string][]Value,
	pendingFilters []string,
) ([]Binding, []string, Stats, error) {
	stats := Stats{}
	if len(groupTriples) == 0 || len(rows) == 0 {
		return rows, pendingFilters, stats, nil
	}
	subjVar := groupTriples[0].Subject.Value

	// Determine which variables the group introduces.
	groupVars := map[string]bool{}
	for _, tp := range groupTriples {
		for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
			if term.Kind == sparql.TermVariable {
				groupVars[term.Value] = true
			}
		}
	}

	// Dedup rows by subject and build a representative-row index for filter context.
	// The representative row provides variables (like ?product) needed by the filter
	// but not present in the group triple results.
	lpIndex := map[string]Binding{}
	seenSubj := map[string]bool{}
	var deduped []Binding
	for _, row := range rows {
		val := row[subjVar]
		k := val.Kind + ":" + val.Lexical
		if !seenSubj[k] {
			seenSubj[k] = true
			lpIndex[k] = row
			deduped = append(deduped, row)
		}
	}

	// Identify filters that can be fully evaluated once all groupVars are bound.
	sample := deduped[0]
	consumableSet := map[int]bool{}
	for fi, f := range pendingFilters {
		allCovered := true
		for _, v := range regexpVars(f) {
			if groupVars[v] {
				continue
			}
			if _, ok := scalarSets[v]; ok {
				continue
			}
			if val, ok2 := sample[v]; ok2 && val.Bound {
				continue
			}
			allCovered = false
			break
		}
		if allCovered {
			consumableSet[fi] = true
		}
	}
	if len(consumableSet) == 0 {
		return rows, pendingFilters, stats, nil
	}

	// Process each group triple independently — no cross-product join.
	// currentInputs starts as all unique subjects; after each triple, we restrict
	// to only those lps that had at least one result passing the partial filter.
	// evalFilterPartialPrune with excludeIrrelevantScalarVars ensures that scalar
	// vars whose clauses only involve unknown variables are skipped, so each triple
	// is evaluated against only the scalar vars relevant to its own bound variables.
	currentInputs := deduped
	for tpIdx, tp := range groupTriples {
		union, s, err := e.fetchTriple(ctx, tp, selection[tp.ID], currentInputs)
		stats = addStats(stats, s)
		if err != nil {
			return nil, pendingFilters, stats, err
		}
		union = distinct(union, nil)
		if debugExec {
			fmt.Fprintf(os.Stderr, "[exec] filter-group tp%d: fetched %d results for %d inputs\n", tp.ID, len(union), len(currentInputs))
		}

		// Which lps have at least one result passing the partial filter?
		passedThisTriple := make(map[string]bool)
		var sampleFail string
		for _, result := range union {
			lp := result[subjVar]
			k := lp.Kind + ":" + lp.Lexical
			if passedThisTriple[k] {
				continue
			}
			repRow := lpIndex[k]
			fullBinding := merge(repRow, result)
			for fi := range consumableSet {
				ok, err2 := evalFilterPartialPrune(pendingFilters[fi], fullBinding, scalarSets)
				if ok {
					passedThisTriple[k] = true
					break
				}
				if debugExec && sampleFail == "" && err2 != nil {
					sampleFail = err2.Error()
				}
			}
		}
		if debugExec {
			fmt.Fprintf(os.Stderr, "[exec] filter-group tp%d: %d/%d lps passed partial filter (tpIdx=%d, sampleFail=%q)\n",
				tp.ID, len(passedThisTriple), len(currentInputs), tpIdx, sampleFail)
			if len(passedThisTriple) == 0 && len(union) > 0 {
				// Print sample evaluation for diagnosis
				result := union[0]
				lp := result[subjVar]
				repRow := lpIndex[lp.Kind+":"+lp.Lexical]
				fullBinding := merge(repRow, result)
				for fi := range consumableSet {
					ok, err2 := evalFilterPartialPrune(pendingFilters[fi], fullBinding, scalarSets)
					fmt.Fprintf(os.Stderr, "[exec]   filter-group sample result=%v ok=%v err=%v\n", result, ok, err2)
					fmt.Fprintf(os.Stderr, "[exec]   repRow keys: %v\n", bindingKeys(repRow))
					fmt.Fprintf(os.Stderr, "[exec]   scalarSets keys: %v\n", scalarSetKeys(scalarSets))
				}
			}
		}

		if len(passedThisTriple) == 0 {
			return rows[:0], removeConsumed(pendingFilters, consumableSet), stats, nil
		}

		// Restrict inputs for the next triple to only lps that passed this one.
		var nextInputs []Binding
		for _, row := range currentInputs {
			lp := row[subjVar]
			if passedThisTriple[lp.Kind+":"+lp.Lexical] {
				nextInputs = append(nextInputs, row)
			}
		}
		currentInputs = nextInputs
	}

	// currentInputs now holds lps that passed all group triples' partial filters.
	passSet := make(map[string]bool, len(currentInputs))
	for _, row := range currentInputs {
		lp := row[subjVar]
		passSet[lp.Kind+":"+lp.Lexical] = true
	}

	kept := rows[:0]
	for _, row := range rows {
		lp := row[subjVar]
		if passSet[lp.Kind+":"+lp.Lexical] {
			kept = append(kept, row)
		}
	}

	return kept, removeConsumed(pendingFilters, consumableSet), stats, nil
}

func removeConsumed(filters []string, consumed map[int]bool) []string {
	out := filters[:0]
	for fi, f := range filters {
		if !consumed[fi] {
			out = append(out, f)
		}
	}
	return out
}

// fetchTriple executes one triple pattern across its selected endpoints, using
// concurrent goroutines bounded by MaxConcurrency. pushFilters are SPARQL FILTER
// expressions to inject into each endpoint query for push-down pruning.
func (e *Executor) fetchTriple(ctx context.Context, triple sparql.TriplePattern, sources []federation.Endpoint, rows []Binding, pushFilters ...string) ([]Binding, Stats, error) {
	stats := Stats{}
	batchSize := e.options.BindBatchSize
	if batchSize < 1 {
		batchSize = 1
	}
	concurrency := e.options.MaxConcurrency
	if concurrency < 1 {
		concurrency = 1
	}

	bindInputs := []Binding(nil)
	if e.options.Join == "bind" && !(len(rows) == 1 && len(rows[0]) == 0) {
		bindInputs = rows
	}

	// Build per-endpoint task list.
	type task struct {
		endpoint federation.Endpoint
		inputs   []Binding
	}
	var tasks []task
	if len(bindInputs) > 0 {
		local, broadcast := localityPartition(bindInputs, triple, sources)
		// Deduplicate each endpoint's input slice on the triple's variables so
		// that repeated bindings (e.g. after a high-cardinality join on an
		// unrelated variable) don't inflate the number of batches sent.
		tripleVars := triple.Variables()
		dedup := func(rows []Binding) []Binding {
			if len(rows) == 0 {
				return rows
			}
			seen := map[string]bool{}
			var out []Binding
			for _, row := range rows {
				k := bindingProjectionKey(row, tripleVars)
				if !seen[k] {
					seen[k] = true
					out = append(out, row)
				}
			}
			return out
		}
		for _, ep := range sources {
			inp := dedup(append(append([]Binding(nil), local[ep.ID]...), broadcast...))
			if len(inp) > 0 {
				tasks = append(tasks, task{ep, inp})
			}
		}
	} else {
		for _, ep := range sources {
			tasks = append(tasks, task{ep, nil})
		}
	}

	if len(tasks) == 0 {
		return nil, stats, nil
	}

	type result struct {
		bindings     []Binding
		httpRequests int
		endpoint     string
		err          error
	}
	results := make([]result, len(tasks))
	sem := make(chan struct{}, concurrency)
	var wg sync.WaitGroup

	for i, t := range tasks {
		wg.Add(1)
		go func(idx int, t task) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			var collected []Binding
			requests := 0
			inp := t.inputs
			if len(inp) == 0 {
				// Unconstrained fetch (hash join or first triple)
				remote, err := e.client.Select(ctx, t.endpoint, []sparql.TriplePattern{triple}, nil, pushFilters...)
				requests++
				if err != nil {
					results[idx] = result{nil, requests, t.endpoint.ID, err}
					return
				}
				collected = remote
			} else {
				for offset := 0; offset < len(inp); offset += batchSize {
					end := offset + batchSize
					if end > len(inp) {
						end = len(inp)
					}
					remote, err := e.client.Select(ctx, t.endpoint, []sparql.TriplePattern{triple}, inp[offset:end], pushFilters...)
					requests++
					if err != nil {
						results[idx] = result{nil, requests, t.endpoint.ID, err}
						return
					}
					collected = append(collected, remote...)
				}
			}
			results[idx] = result{collected, requests, t.endpoint.ID, nil}
		}(i, t)
	}
	wg.Wait()

	var union []Binding
	for _, r := range results {
		stats.HTTPRequests += r.httpRequests
		if r.err != nil {
			if e.options.FailurePolicy == "partial" {
				stats.Partial = true
				stats.FailedEndpoints = append(stats.FailedEndpoints, r.endpoint)
				continue
			}
			return nil, stats, fmt.Errorf("select %s: %w", r.endpoint, r.err)
		}
		union = append(union, r.bindings...)
	}
	return union, stats, nil
}

// reorderForEagerFilter reorders triples within equal-source-count groups so that
// patterns producing SELECT-only output variables are deferred to run after all
// filter-variable producers. This allows eager filter pruning to fire before
// executing expensive label/comment fetches.
func reorderForEagerFilter(triples []sparql.TriplePattern, selection federation.Selection, filters []string) []sparql.TriplePattern {
	// Build the set of variables referenced in any filter expression.
	filterVarSet := map[string]bool{}
	for _, f := range filters {
		for _, v := range regexpVars(f) {
			filterVarSet[v] = true
		}
	}

	// Count how many triples each variable appears in.
	varCount := map[string]int{}
	for _, tp := range triples {
		for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
			if term.Kind == sparql.TermVariable {
				varCount[term.Value]++
			}
		}
	}

	// isSelectOnly: a pattern produces only "SELECT-only" output when every unique
	// variable it introduces (appears in exactly 1 triple) is absent from all filters.
	// Patterns with join variables (count > 1) or filter variables are not select-only.
	isSelectOnly := func(tp sparql.TriplePattern) bool {
		hasUniqueVar := false
		for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
			if term.Kind != sparql.TermVariable {
				continue
			}
			if filterVarSet[term.Value] {
				return false
			}
			if varCount[term.Value] == 1 {
				hasUniqueVar = true
			}
		}
		return hasUniqueVar
	}

	// Process each group of equal-source-count triples separately so that we never
	// move a high-source-count pattern before a low-source-count one.
	result := make([]sparql.TriplePattern, 0, len(triples))
	i := 0
	for i < len(triples) {
		sc := len(selection[triples[i].ID])
		j := i + 1
		for j < len(triples) && len(selection[triples[j].ID]) == sc {
			j++
		}
		group := triples[i:j]

		// Only reorder within this group if it contains at least one filter provider.
		hasFilterProvider := false
		for _, tp := range group {
			for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
				if term.Kind == sparql.TermVariable && filterVarSet[term.Value] {
					hasFilterProvider = true
					break
				}
			}
			if hasFilterProvider {
				break
			}
		}

		if !hasFilterProvider {
			result = append(result, group...)
		} else {
			var nonDeferred, deferred []sparql.TriplePattern
			for _, tp := range group {
				if isSelectOnly(tp) {
					deferred = append(deferred, tp)
				} else {
					nonDeferred = append(nonDeferred, tp)
				}
			}
			result = append(result, nonDeferred...)
			result = append(result, deferred...)
		}
		i = j
	}
	return result
}

// applyEligibleFilters applies each pending filter whose variables are all bound
// in the current rows, removing matched rows. Returns remaining pending filters
// and the pruned row set.
func applyEligibleFilters(pending []string, rows []Binding) ([]string, []Binding) {
	if len(rows) == 0 {
		return pending, rows
	}
	sample := rows[0]
	remaining := pending[:0]
	for _, filter := range pending {
		vars := regexpVars(filter)
		allBound := true
		for _, v := range vars {
			val, ok := sample[v]
			if !ok || !val.Bound {
				allBound = false
				break
			}
		}
		if !allBound {
			remaining = append(remaining, filter)
			continue
		}
		// All variables bound: apply filter now.
		kept := rows[:0]
		for _, row := range rows {
			ok, err := evalFilter(filter, row)
			if err == nil && ok {
				kept = append(kept, row)
			}
		}
		rows = kept
	}
	return remaining, rows
}

func cloneBindings(rows []Binding) []Binding {
	result := make([]Binding, len(rows))
	for index, row := range rows {
		result[index] = row.Clone()
	}
	return result
}

// localityPartition splits bindings into per-endpoint local groups and a broadcast slice.
// A binding is routed to a specific endpoint when the triple pattern's subject or object
// variable is bound to an IRI that starts with that endpoint's GraphIRI. Bindings whose
// bound IRIs match no endpoint, or match multiple, are placed in broadcast and sent to all.
func localityPartition(inputs []Binding, triple sparql.TriplePattern, endpoints []federation.Endpoint) (local map[string][]Binding, broadcast []Binding) {
	local = make(map[string][]Binding, len(endpoints))
	for _, binding := range inputs {
		id := patternEndpointID(binding, triple, endpoints)
		if id != "" {
			local[id] = append(local[id], binding)
		} else {
			broadcast = append(broadcast, binding)
		}
	}
	return local, broadcast
}

// subjectEndpointID is like patternEndpointID but checks only the subject variable.
// Used in post-bind exclusive-group detection to avoid routing "?review reviewFor ?product"
// to the product's endpoint when the review entity lives elsewhere.
func subjectEndpointID(binding Binding, triple sparql.TriplePattern, endpoints []federation.Endpoint) string {
	term := triple.Subject
	if term.Kind != sparql.TermVariable {
		return ""
	}
	value, ok := binding[term.Value]
	if !ok || !value.Bound || value.Kind != "uri" {
		return ""
	}
	for _, ep := range endpoints {
		if ep.GraphIRI != "" && strings.HasPrefix(value.Lexical, ep.GraphIRI) {
			return ep.ID
		}
	}
	return ""
}

// patternEndpointID returns the single endpoint ID whose GraphIRI is a prefix of
// the triple's subject or object variable value in this binding. Returns "" when
// no endpoint matches or when multiple endpoints match (ambiguous → broadcast).
func patternEndpointID(binding Binding, triple sparql.TriplePattern, endpoints []federation.Endpoint) string {
	matched := ""
	for _, term := range []sparql.Term{triple.Subject, triple.Object} {
		if term.Kind != sparql.TermVariable {
			continue
		}
		value, ok := binding[term.Value]
		if !ok || !value.Bound || value.Kind != "uri" {
			continue
		}
		for _, ep := range endpoints {
			if ep.GraphIRI == "" {
				continue
			}
			if strings.HasPrefix(value.Lexical, ep.GraphIRI) {
				if matched == "" {
					matched = ep.ID
				} else if matched != ep.ID {
					return "" // Ambiguous: IRI prefixes from different endpoints
				}
			}
		}
	}
	return matched
}

// postBindExclusiveEndpoint checks whether all triples route exclusively to one
// endpoint given the current bound rows. Returns that endpoint if so.
// Only fires when every binding in every row routes to the SAME endpoint.
// Only subject variables are used for locality routing here (not object variables)
// to avoid incorrectly routing patterns like "?review reviewFor ?product" to the
// product's endpoint when the review is in a different endpoint's namespace.
func postBindExclusiveEndpoint(triples []sparql.TriplePattern, selection federation.Selection, rows []Binding) (federation.Endpoint, bool) {
	if len(triples) == 0 || len(rows) == 0 {
		return federation.Endpoint{}, false
	}
	var target *federation.Endpoint
	for _, triple := range triples {
		sources := selection[triple.ID]
		if len(sources) == 0 {
			return federation.Endpoint{}, false
		}
		for _, row := range rows {
			id := subjectEndpointID(row, triple, sources)
			if id == "" {
				return federation.Endpoint{}, false // no subject locality — cannot consolidate
			}
			if target == nil {
				for i := range sources {
					if sources[i].ID == id {
						ep := sources[i]
						target = &ep
						break
					}
				}
			} else if target.ID != id {
				return federation.Endpoint{}, false // different endpoints for different rows
			}
		}
	}
	if target == nil {
		return federation.Endpoint{}, false
	}
	return *target, true
}

func exclusiveEndpoint(triples []sparql.TriplePattern, selection federation.Selection) (federation.Endpoint, bool) {
	if len(triples) < 2 {
		return federation.Endpoint{}, false
	}
	sources := selection[triples[0].ID]
	if len(sources) != 1 {
		return federation.Endpoint{}, false
	}
	endpoint := sources[0]
	for _, triple := range triples[1:] {
		current := selection[triple.ID]
		if len(current) != 1 || current[0].ID != endpoint.ID {
			return federation.Endpoint{}, false
		}
	}
	return endpoint, true
}

// joinVars returns the variables that appear in both a and b (the hash join key).
func joinVars(a, b Binding) []string {
	var shared []string
	for k := range a {
		if _, ok := b[k]; ok {
			shared = append(shared, k)
		}
	}
	sort.Strings(shared)
	return shared
}

func join(left, right []Binding) []Binding {
	if len(left) == 0 || len(right) == 0 {
		return nil
	}
	// Use hash join when there are shared variables (avoids O(n×m) cross-product).
	// Build the hash table on the smaller side for better cache locality.
	probe, build := left, right
	if len(right) > len(left) {
		probe, build = right, left
	}
	shared := joinVars(probe[0], build[0])
	if len(shared) == 0 {
		// No shared variables → cross product; fall back to nested loop.
		var result []Binding
		for _, l := range left {
			for _, r := range right {
				result = append(result, merge(l, r))
			}
		}
		return result
	}
	hash := make(map[string][]Binding, len(build))
	for _, row := range build {
		key := bindingProjectionKey(row, shared)
		hash[key] = append(hash[key], row)
	}
	var result []Binding
	for _, row := range probe {
		key := bindingProjectionKey(row, shared)
		for _, candidate := range hash[key] {
			if compatible(row, candidate) {
				result = append(result, merge(row, candidate))
			}
		}
	}
	return result
}

func leftJoin(left, right []Binding) []Binding {
	if len(left) == 0 {
		return nil
	}
	if len(right) == 0 {
		return cloneBindings(left)
	}
	shared := joinVars(left[0], right[0])
	if len(shared) == 0 {
		// No shared variables → every left row matches every right row.
		var result []Binding
		for _, l := range left {
			for _, r := range right {
				result = append(result, merge(l, r))
			}
		}
		return result
	}
	hash := make(map[string][]Binding, len(right))
	for _, row := range right {
		key := bindingProjectionKey(row, shared)
		hash[key] = append(hash[key], row)
	}
	var result []Binding
	for _, l := range left {
		key := bindingProjectionKey(l, shared)
		matched := false
		for _, r := range hash[key] {
			if compatible(l, r) {
				result = append(result, merge(l, r))
				matched = true
			}
		}
		if !matched {
			result = append(result, l.Clone())
		}
	}
	return result
}
func distinct(rows []Binding, variables []string) []Binding {
	seen := map[string]bool{}
	var result []Binding
	for _, row := range rows {
		var parts []string
		vars := variables
		if len(vars) == 0 {
			for key := range row {
				vars = append(vars, key)
			}
			sort.Strings(vars)
		}
		for _, key := range vars {
			v := row[key]
			parts = append(parts, key+"="+v.Kind+":"+v.Lexical+":"+v.Datatype+":"+v.Language)
		}
		key := strings.Join(parts, "\x00")
		if !seen[key] {
			seen[key] = true
			result = append(result, row)
		}
	}
	return result
}
func orderValue(expression string, row Binding) string {
	vars := regexpVars(expression)
	if len(vars) == 0 {
		return expression
	}
	value := row[vars[len(vars)-1]]
	if number, ok := number(value); ok {
		return fmt.Sprintf("%024.9f", number)
	}
	return value.Lexical
}
func regexpVars(input string) []string {
	var result []string
	for i := 0; i < len(input); i++ {
		if input[i] == '?' {
			j := i + 1
			for j < len(input) && ((input[j] >= 'a' && input[j] <= 'z') || (input[j] >= 'A' && input[j] <= 'Z') || (input[j] >= '0' && input[j] <= '9') || input[j] == '_') {
				j++
			}
			result = append(result, input[i+1:j])
			i = j - 1
		}
	}
	return result
}
// bindingProjectionKey returns a canonical string key for the subset of a
// binding projected onto the given variables. Used to deduplicate bind-join
// inputs on the variables that actually appear in the next triple pattern.
func bindingProjectionKey(row Binding, vars []string) string {
	var b strings.Builder
	for _, v := range vars {
		val := row[v]
		b.WriteString(v)
		b.WriteByte('=')
		b.WriteString(val.Kind)
		b.WriteByte(':')
		b.WriteString(val.Lexical)
		b.WriteByte('\x00')
	}
	return b.String()
}

func addStats(left, right Stats) Stats {
	left.HTTPRequests += right.HTTPRequests
	left.Partial = left.Partial || right.Partial
	left.FailedEndpoints = append(left.FailedEndpoints, right.FailedEndpoints...)
	return left
}

// computeFilterOnlyVars returns the set of variables that appear in filters but
// in exactly one triple pattern (across triples + optionals) and are not in the
// output (SELECT/ORDER BY). These are "filter-only" variables: they don't join with
// other patterns and aren't projected, so patterns that introduce only filter-only
// variables can be executed as scalar-set collectors rather than joined.
func computeFilterOnlyVars(triples []sparql.TriplePattern, filters []string, optionals []*sparql.Group, outputVars map[string]bool) map[string]bool {
	varCount := map[string]int{}
	countTripleVars := func(tps []sparql.TriplePattern) {
		for _, tp := range tps {
			for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
				if term.Kind == sparql.TermVariable {
					varCount[term.Value]++
				}
			}
		}
	}
	countTripleVars(triples)
	var countGroupVars func(g *sparql.Group)
	countGroupVars = func(g *sparql.Group) {
		countTripleVars(g.Triples)
		for _, pair := range g.Unions {
			countGroupVars(pair[0])
			countGroupVars(pair[1])
		}
		for _, opt := range g.Optionals {
			countGroupVars(opt)
		}
	}
	for _, opt := range optionals {
		countGroupVars(opt)
	}
	filterVars := map[string]bool{}
	for _, f := range filters {
		for _, v := range regexpVars(f) {
			filterVars[v] = true
		}
	}
	result := map[string]bool{}
	for v, count := range varCount {
		if count == 1 && filterVars[v] && !outputVars[v] {
			result[v] = true
		}
	}
	return result
}

// isScalarTriple returns true when this triple can be executed as a scalar-set
// collector rather than joined. Two conditions must both hold:
// 1. Every unique variable (count == 1 across the group) is filter-only (not in SELECT
//    or other triple patterns) — so it contributes only a set of filter-comparison values.
// 2. Every join variable (count > 1) is bound to the SAME value across all current rows
//    — so fetching the triple with those bindings produces a single coherent value set
//    rather than per-row values that need to be tracked individually.
//
// Condition 2 prevents treating patterns like "?localProduct prop1 ?simProp1" as scalar
// when ?localProduct varies across rows (the simProp1 values would differ per-row and
// must be joined, not collected globally).
func isScalarTriple(tp sparql.TriplePattern, filterOnlyVars map[string]bool, varCount map[string]int, rows []Binding) bool {
	hasUniqueVar := false
	for _, term := range []sparql.Term{tp.Subject, tp.Predicate, tp.Object} {
		if term.Kind != sparql.TermVariable {
			continue
		}
		v := term.Value
		if varCount[v] == 1 {
			if !filterOnlyVars[v] {
				return false
			}
			hasUniqueVar = true
		} else {
			// Join variable: must be the same value in every row; otherwise per-row
			// variation means results must be joined rather than collected globally.
			if !uniformValue(rows, v) {
				return false
			}
		}
	}
	return hasUniqueVar
}

// uniformValue returns true when every row in rows has the same bound value for v.
func uniformValue(rows []Binding, v string) bool {
	if len(rows) <= 1 {
		return true
	}
	first, ok := rows[0][v]
	if !ok || !first.Bound {
		return true // all unbound is uniform
	}
	for _, row := range rows[1:] {
		val, ok := row[v]
		if !ok || !val.Bound || val.Kind != first.Kind || val.Lexical != first.Lexical {
			return false
		}
	}
	return true
}

// allVarsBoundOrScalar checks whether all variables in a filter expression are
// either bound in the sample row or available in the scalar sets.
func allVarsBoundOrScalar(filter string, sample Binding, scalarSets map[string][]Value) bool {
	for _, v := range regexpVars(filter) {
		if _, inScalar := scalarSets[v]; inScalar {
			continue
		}
		val, ok := sample[v]
		if !ok || !val.Bound {
			return false
		}
	}
	return true
}

// applyEligibleFiltersScalar is like applyEligibleFilters but also treats scalar-set
// variables as bound when deciding filter eligibility.
func applyEligibleFiltersScalar(pending []string, rows []Binding, scalarSets map[string][]Value) ([]string, []Binding) {
	if len(rows) == 0 {
		return pending, rows
	}
	sample := rows[0]
	remaining := pending[:0]
	for _, filter := range pending {
		if !allVarsBoundOrScalar(filter, sample, scalarSets) {
			remaining = append(remaining, filter)
			continue
		}
		kept := rows[:0]
		for _, row := range rows {
			ok, err := evalFilterWithScalars(filter, row, scalarSets)
			if err == nil && ok {
				kept = append(kept, row)
			}
		}
		rows = kept
	}
	return remaining, rows
}

// collectGroupVars recursively collects all variable names in a Group.
func collectGroupVars(g *sparql.Group, vars map[string]bool) {
	for _, tp := range g.Triples {
		for _, v := range tp.Variables() {
			vars[v] = true
		}
	}
	for _, pair := range g.Unions {
		collectGroupVars(pair[0], vars)
		collectGroupVars(pair[1], vars)
	}
	for _, opt := range g.Optionals {
		collectGroupVars(opt, vars)
	}
}

// uniqueInputsForOptional returns deduplicated rows projected onto variables
// shared between the current row set and the optional group. Reduces HTTP
// fetch work inside executeGroup when many rows share identical binding values.
func uniqueInputsForOptional(optional *sparql.Group, rows []Binding) []Binding {
	if len(rows) == 0 {
		return rows
	}
	optVars := map[string]bool{}
	collectGroupVars(optional, optVars)
	var sharedVars []string
	for v := range rows[0] {
		if optVars[v] {
			sharedVars = append(sharedVars, v)
		}
	}
	if len(sharedVars) == 0 {
		return []Binding{{}}
	}
	sort.Strings(sharedVars)
	seen := map[string]bool{}
	var unique []Binding
	for _, row := range rows {
		b := Binding{}
		key := ""
		for _, v := range sharedVars {
			val := row[v]
			b[v] = val
			key += v + "\x00" + val.Kind + "\x00" + val.Lexical + "\x01"
		}
		if !seen[key] {
			seen[key] = true
			unique = append(unique, b)
		}
	}
	return unique
}

// greedyOrderTriples orders triple patterns to minimise cartesian products.
// At each step it prefers patterns that share at least one variable with
// already-processed patterns (connected), breaking ties by source count.
// Unconnected patterns are chosen by source count when no connected option
// exists. This is a strict improvement over sorting purely by source count
// because it prevents cross-product blowup when unrelated sameAs-like
// patterns are processed before their joining siblings.
func greedyOrderTriples(triples []sparql.TriplePattern, selection federation.Selection, inputs []Binding) []sparql.TriplePattern {
	if len(triples) <= 1 {
		return triples
	}
	// Seed the bound-variable set from the caller's input bindings.
	bound := map[string]bool{}
	if len(inputs) > 0 {
		for v, val := range inputs[0] {
			if val.Bound {
				bound[v] = true
			}
		}
	}
	remaining := append([]sparql.TriplePattern(nil), triples...)
	result := make([]sparql.TriplePattern, 0, len(triples))
	for len(remaining) > 0 {
		best := -1
		bestSrcs := 0
		bestConnected := false
		bestNewVars := 0
		for i, tp := range remaining {
			srcs := len(selection[tp.ID])
			connected := false
			newVars := 0
			for _, v := range tp.Variables() {
				if bound[v] {
					connected = true
				} else {
					newVars++
				}
			}
			choose := false
			switch {
			case best < 0:
				choose = true
			case connected && !bestConnected:
				choose = true
			case connected == bestConnected && srcs < bestSrcs:
				choose = true
			case connected == bestConnected && srcs == bestSrcs && newVars < bestNewVars:
				// Prefer patterns with fewer new unbound variables: patterns that constrain
				// an already-resolved variable are processed eagerly (e.g. a sameAs lookup
				// whose output is already bound acts as an in-memory filter, immediately
				// reducing the intermediate result size).
				choose = true
			}
			if choose {
				best = i
				bestSrcs = srcs
				bestConnected = connected
				bestNewVars = newVars
			}
		}
		chosen := remaining[best]
		result = append(result, chosen)
		for _, v := range chosen.Variables() {
			bound[v] = true
		}
		remaining[best] = remaining[len(remaining)-1]
		remaining = remaining[:len(remaining)-1]
	}
	return result
}

func bindingKeys(b Binding) []string {
	keys := make([]string, 0, len(b))
	for k := range b {
		keys = append(keys, k)
	}
	return keys
}

func scalarSetKeys(ss map[string][]Value) []string {
	keys := make([]string, 0, len(ss))
	for k := range ss {
		keys = append(keys, k)
	}
	return keys
}

// endpointGroup pairs a target endpoint with the input rows whose subject locality
// maps exclusively to that endpoint.
type endpointGroup struct {
	endpoint federation.Endpoint
	rows     []Binding
}

// collectLocalSubjectGroup returns the triples in rest that share the same subject
// variable (subjVar) as the current triple and can be served by ep. Returns the
// matching triples and the count to skip in the outer loop. Only CONTIGUOUS triples
// starting from the front of rest that have subjVar as subject are collected; the first
// triple with a different subject stops the scan. This lets the caller send all
// same-subject triples as one compound BGP to ep.
func collectLocalSubjectGroup(subjVar string, ep federation.Endpoint, rest []sparql.TriplePattern, selection federation.Selection) ([]sparql.TriplePattern, int) {
	var group []sparql.TriplePattern
	for _, tp := range rest {
		if tp.Subject.Kind != sparql.TermVariable || tp.Subject.Value != subjVar {
			break
		}
		servable := false
		for _, src := range selection[tp.ID] {
			if src.ID == ep.ID {
				servable = true
				break
			}
		}
		if !servable {
			break
		}
		group = append(group, tp)
	}
	return group, len(group)
}

// pruneSourcesBySubjectLocality narrows sources to a single endpoint when the triple's
// subject variable is uniformly bound to an IRI whose prefix maps to exactly one endpoint.
// This prevents cross-product explosion when a local resource (e.g., a specific vendor
// product) is replicated across many endpoints with independently generated property values:
// without pruning, fetching N independent properties each from M endpoints creates an
// N^M cross-product in the intermediate result.
func pruneSourcesBySubjectLocality(triple sparql.TriplePattern, sources []federation.Endpoint, rows []Binding) []federation.Endpoint {
	if len(rows) == 0 || len(sources) <= 1 || triple.Subject.Kind != sparql.TermVariable {
		return sources
	}
	subjVar := triple.Subject.Value
	if !uniformValue(rows, subjVar) {
		return sources
	}
	val := rows[0][subjVar]
	if !val.Bound || val.Kind != "uri" {
		return sources
	}
	for _, ep := range sources {
		if ep.GraphIRI != "" && strings.HasPrefix(val.Lexical, ep.GraphIRI) {
			return []federation.Endpoint{ep}
		}
	}
	return sources
}

// perEndpointCompound partitions rows by exclusive endpoint and verifies that all
// triples in rest can be served by each endpoint group. Returns nil when any row
// lacks clear subject locality, when only one group would be formed (handled by
// postBindExclusiveEndpoint), or when a triple is missing from an endpoint's selection.
func perEndpointCompound(rest []sparql.TriplePattern, selection federation.Selection, rows []Binding) []endpointGroup {
	if len(rest) < 2 || len(rows) == 0 {
		return nil
	}
	first := rest[0]
	sources := selection[first.ID]
	if len(sources) == 0 {
		return nil
	}
	epIndex := make(map[string]federation.Endpoint, len(sources))
	for _, ep := range sources {
		epIndex[ep.ID] = ep
	}
	groupMap := make(map[string][]Binding, len(sources))
	for _, row := range rows {
		id := subjectEndpointID(row, first, sources)
		if id == "" {
			return nil
		}
		groupMap[id] = append(groupMap[id], row)
	}
	if len(groupMap) <= 1 {
		// Single group: postBindExclusiveEndpoint already handles this case.
		return nil
	}
	result := make([]endpointGroup, 0, len(groupMap))
	for epID, groupRows := range groupMap {
		ep, ok := epIndex[epID]
		if !ok {
			return nil
		}
		for _, tp := range rest {
			found := false
			for _, src := range selection[tp.ID] {
				if src.ID == epID {
					found = true
					break
				}
			}
			if !found {
				return nil
			}
		}
		result = append(result, endpointGroup{endpoint: ep, rows: groupRows})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].endpoint.ID < result[j].endpoint.ID })
	return result
}

// extractConstantVars returns variables that have the same bound value in every row.
// These can be substituted as literal constants in filter expressions for push-down.
func extractConstantVars(rows []Binding) map[string]Value {
	if len(rows) == 0 {
		return nil
	}
	result := map[string]Value{}
	for v, val := range rows[0] {
		if !val.Bound {
			continue
		}
		if uniformValue(rows, v) {
			result[v] = val
		}
	}
	return result
}

// derivePushableFilters returns filter strings (with constants substituted) that
// can be safely pushed to the endpoint for the given single triple. A filter is
// pushable when, after constant substitution, every remaining unbound variable is
// a NEW variable introduced by triple (not already bound in rows).
func derivePushableFilters(pending []string, rows []Binding, triple sparql.TriplePattern, constants map[string]Value) []string {
	if len(pending) == 0 || len(constants) == 0 {
		return nil
	}
	boundVars := map[string]bool{}
	if len(rows) > 0 {
		for v, val := range rows[0] {
			if val.Bound {
				boundVars[v] = true
			}
		}
	}
	tripleNewVars := map[string]bool{}
	for _, v := range triple.Variables() {
		if !boundVars[v] {
			tripleNewVars[v] = true
		}
	}
	if len(tripleNewVars) == 0 {
		return nil
	}
	var pushable []string
	for _, f := range pending {
		simplified := substituteConstants(f, constants)
		fvars := regexpVars(simplified)
		allCovered, hasNew := true, false
		for _, v := range fvars {
			if tripleNewVars[v] {
				hasNew = true
			} else if !boundVars[v] {
				allCovered = false
				break
			}
		}
		if allCovered && hasNew {
			pushable = append(pushable, simplified)
		}
	}
	return pushable
}

// derivePushableFiltersCompound returns filter strings (with constants substituted)
// that can be pushed into a compound query covering all triples in rest.
// A filter is pushable when all its remaining unbound variables (after substitution)
// appear in rest's triple patterns or are already bound in rows.
func derivePushableFiltersCompound(pending []string, rows []Binding, rest []sparql.TriplePattern, constants map[string]Value) []string {
	if len(pending) == 0 || len(constants) == 0 {
		return nil
	}
	boundVars := map[string]bool{}
	if len(rows) > 0 {
		for v, val := range rows[0] {
			if val.Bound {
				boundVars[v] = true
			}
		}
	}
	restVars := map[string]bool{}
	for _, tp := range rest {
		for _, v := range tp.Variables() {
			restVars[v] = true
		}
	}
	var pushable []string
	for _, f := range pending {
		simplified := substituteConstants(f, constants)
		fvars := regexpVars(simplified)
		allCovered := true
		for _, v := range fvars {
			if !boundVars[v] && !restVars[v] {
				allCovered = false
				break
			}
		}
		if allCovered {
			pushable = append(pushable, simplified)
		}
	}
	return pushable
}
