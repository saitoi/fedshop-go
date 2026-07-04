package executor

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// substituteConstants replaces ?var tokens in a SPARQL filter expression with
// their literal values for variables present in constants. Non-constant variables
// are left unchanged. The result is suitable for injection as a SPARQL FILTER.
func substituteConstants(filter string, constants map[string]Value) string {
	if len(constants) == 0 {
		return filter
	}
	tokens := expressionTokens(filter)
	var parts []string
	for _, tok := range tokens {
		if strings.HasPrefix(tok, "?") {
			if val, ok := constants[tok[1:]]; ok {
				parts = append(parts, renderSPARQLLiteral(val))
				continue
			}
		}
		parts = append(parts, tok)
	}
	return strings.Join(parts, " ")
}

// renderSPARQLLiteral serialises a Value as a SPARQL term suitable for embedding
// in a query string (IRI or typed/plain/language-tagged literal).
func renderSPARQLLiteral(val Value) string {
	if val.Kind == "uri" {
		return "<" + val.Lexical + ">"
	}
	quoted := strconv.Quote(val.Lexical)
	if val.Language != "" {
		return quoted + "@" + val.Language
	}
	if val.Datatype != "" {
		return quoted + "^^<" + val.Datatype + ">"
	}
	return quoted
}

type scalar struct {
	value any
	bound bool
}

// partialPassSentinel is placed in scalar.value in partial-evaluation mode when a
// variable is unbound and not in the scalar sets. Comparisons involving this value
// always return true (optimistic pass-through), ensuring the filter is only pruned
// when it is DEFINITIVELY false regardless of the unknown variable's value.
const partialPassSentinel = "\x00__partial_pass__\x00"

func evalFilter(input string, binding Binding) (bool, error) {
	parser := expressionParser{tokens: expressionTokens(input), binding: binding}
	value, err := parser.parseOr()
	if err != nil {
		return false, err
	}
	return effectiveBoolean(value), nil
}

// evalFilterWithScalars evaluates a filter where some variables are provided as
// scalar sets (multiple possible values) rather than single bindings. The filter
// passes if ANY assignment of scalar values to those variables satisfies it.
func evalFilterWithScalars(input string, binding Binding, scalarSets map[string][]Value) (bool, error) {
	if len(scalarSets) == 0 {
		return evalFilter(input, binding)
	}
	scalarVars := uniqueScalarVars(input, binding, scalarSets)
	if len(scalarVars) == 0 {
		return evalFilter(input, binding)
	}
	tokens := expressionTokens(input)
	extras := make(map[string]Value, len(scalarVars))
	return tryScalarCombinations(tokens, binding, extras, scalarSets, scalarVars, 0)
}

// uniqueScalarVars returns the deduplicated list of variables that appear in the
// filter expression, are absent from the binding, and are present in scalarSets.
func uniqueScalarVars(input string, binding Binding, scalarSets map[string][]Value) []string {
	seen := map[string]bool{}
	var result []string
	for _, v := range regexpVars(input) {
		if seen[v] {
			continue
		}
		seen[v] = true
		if val, inRow := binding[v]; inRow && val.Bound {
			continue
		}
		if _, inScalar := scalarSets[v]; inScalar {
			result = append(result, v)
		}
	}
	return result
}

// evalFilterPartialPrune evaluates a filter in "optimistic" mode: variables that are
// neither bound in the row nor present in scalarSets are treated as "unknown" and
// all comparisons involving them return true (pass-through). The filter returns false
// ONLY when it is DEFINITIVELY false for all combinations of scalar variable values,
// regardless of the unknown variables. Used for early pruning during filter-group
// execution, before all group variables have been fetched.
func evalFilterPartialPrune(input string, binding Binding, scalarSets map[string][]Value) (bool, error) {
	seen := map[string]bool{}
	var scalarVars []string
	var hasUnknown bool
	unknownSet := map[string]bool{}
	for _, v := range regexpVars(input) {
		if seen[v] {
			continue
		}
		seen[v] = true
		if val, inRow := binding[v]; inRow && val.Bound {
			continue
		}
		if _, inScalar := scalarSets[v]; inScalar {
			scalarVars = append(scalarVars, v)
			continue
		}
		hasUnknown = true
		unknownSet[v] = true
	}
	if !hasUnknown && len(scalarVars) == 0 {
		return evalFilter(input, binding)
	}
	if !hasUnknown && len(scalarVars) > 0 {
		return evalFilterWithScalars(input, binding, scalarSets)
	}
	tokens := expressionTokens(input)
	// Exclude scalar vars that only co-occur with unknown variables in the filter.
	// Such scalars are effectively irrelevant — comparisons with unknown vars always
	// pass through — so iterating over their values is wasted work.
	scalarVars = excludeIrrelevantScalarVars(tokens, binding, unknownSet, scalarVars)
	extras := make(map[string]Value, len(scalarVars))
	return tryScalarCombinationsPartial(tokens, binding, extras, scalarSets, scalarVars, 0)
}

// excludeIrrelevantScalarVars removes scalar vars from the list whose EVERY
// occurrence in the filter expression is in a comparison clause that contains
// ONLY unknown variables (no bound variables). Such scalars are irrelevant in
// partial evaluation because their clause always passes through regardless of value.
func excludeIrrelevantScalarVars(tokens []string, binding Binding, unknownSet map[string]bool, scalarVars []string) []string {
	if len(unknownSet) == 0 || len(scalarVars) == 0 {
		return scalarVars
	}
	// Split the token list into AND-clauses (respecting paren depth).
	var clauses [][]string
	current := []string{}
	depth := 0
	for _, tok := range tokens {
		switch tok {
		case "(":
			depth++
			current = append(current, tok)
		case ")":
			depth--
			current = append(current, tok)
		case "&&":
			if depth == 0 {
				clauses = append(clauses, current)
				current = []string{}
			} else {
				current = append(current, tok)
			}
		default:
			current = append(current, tok)
		}
	}
	clauses = append(clauses, current)

	// For each scalar var, check if it appears in at least one clause that also
	// contains a bound variable (not unknown and not scalar).
	relevant := make(map[string]bool, len(scalarVars))
	for _, sv := range scalarVars {
		svTok := "?" + sv
		for _, clause := range clauses {
			hasSv := false
			for _, tok := range clause {
				if tok == svTok {
					hasSv = true
					break
				}
			}
			if !hasSv {
				continue
			}
			// Clause contains this scalar var. Check if it also contains a bound var.
			for _, tok := range clause {
				if !strings.HasPrefix(tok, "?") {
					continue
				}
				v := tok[1:]
				if v == sv {
					continue
				}
				if unknownSet[v] {
					continue
				}
				// v is not sv and not unknown → must be bound or another scalar.
				if val, ok := binding[v]; ok && val.Bound {
					relevant[sv] = true
					break
				}
			}
			if relevant[sv] {
				break
			}
		}
	}

	result := scalarVars[:0]
	for _, sv := range scalarVars {
		if relevant[sv] {
			result = append(result, sv)
		}
	}
	return result
}

// tryScalarCombinationsPartial is like tryScalarCombinations but uses partial
// (optimistic) expression evaluation: unknowns return partialPassSentinel which
// makes comparisons return true.
func tryScalarCombinationsPartial(tokens []string, binding Binding, extras map[string]Value, scalarSets map[string][]Value, vars []string, idx int) (bool, error) {
	if idx == len(vars) {
		parser := expressionParser{tokens: tokens, binding: binding, extras: extras, partial: true}
		val, err := parser.parseOr()
		if err != nil {
			return false, err
		}
		return effectiveBoolean(val), nil
	}
	v := vars[idx]
	for _, val := range scalarSets[v] {
		extras[v] = val
		ok, err := tryScalarCombinationsPartial(tokens, binding, extras, scalarSets, vars, idx+1)
		if err != nil {
			return false, err
		}
		if ok {
			return true, nil
		}
	}
	return false, nil
}

// tryScalarCombinations iterates over all combinations of scalar variable values,
// returning true as soon as any combination satisfies the filter.
func tryScalarCombinations(tokens []string, binding Binding, extras map[string]Value, scalarSets map[string][]Value, vars []string, idx int) (bool, error) {
	if idx == len(vars) {
		parser := expressionParser{tokens: tokens, binding: binding, extras: extras}
		val, err := parser.parseOr()
		if err != nil {
			return false, err
		}
		return effectiveBoolean(val), nil
	}
	v := vars[idx]
	for _, val := range scalarSets[v] {
		extras[v] = val
		ok, err := tryScalarCombinations(tokens, binding, extras, scalarSets, vars, idx+1)
		if err != nil {
			return false, err
		}
		if ok {
			return true, nil
		}
	}
	return false, nil
}

type expressionParser struct {
	tokens  []string
	pos     int
	binding Binding
	extras  map[string]Value // scalar variable overrides for evalFilterWithScalars
	partial bool             // if true, unbound vars not in extras → partialPassSentinel
}

func (p *expressionParser) parseOr() (scalar, error) {
	left, err := p.parseAnd()
	if err != nil {
		return scalar{}, err
	}
	for p.accept("||") {
		right, e := p.parseAnd()
		if e != nil {
			return scalar{}, e
		}
		left = scalar{value: effectiveBoolean(left) || effectiveBoolean(right), bound: true}
	}
	return left, nil
}
func (p *expressionParser) parseAnd() (scalar, error) {
	left, err := p.parseCompare()
	if err != nil {
		return scalar{}, err
	}
	for p.accept("&&") {
		right, e := p.parseCompare()
		if e != nil {
			return scalar{}, e
		}
		left = scalar{value: effectiveBoolean(left) && effectiveBoolean(right), bound: true}
	}
	return left, nil
}
func (p *expressionParser) parseCompare() (scalar, error) {
	left, err := p.parseAdd()
	if err != nil {
		return scalar{}, err
	}
	if p.pos < len(p.tokens) && contains([]string{"=", "!=", "<", ">", "<=", ">="}, p.tokens[p.pos]) {
		op := p.tokens[p.pos]
		p.pos++
		right, e := p.parseAdd()
		if e != nil {
			return scalar{}, e
		}
		return scalar{value: compareScalars(left, right, op), bound: true}, nil
	}
	return left, nil
}
func (p *expressionParser) parseAdd() (scalar, error) {
	left, err := p.parseUnary()
	if err != nil {
		return scalar{}, err
	}
	for p.pos < len(p.tokens) && (p.tokens[p.pos] == "+" || p.tokens[p.pos] == "-") {
		op := p.tokens[p.pos]
		p.pos++
		right, e := p.parseUnary()
		if e != nil {
			return scalar{}, e
		}
		if isPartialPass(left) || isPartialPass(right) {
			left = scalar{value: partialPassSentinel, bound: true}
			continue
		}
		lf, lok := number(left.value)
		rf, rok := number(right.value)
		if !left.bound || !right.bound || !lok || !rok {
			left = scalar{}
		} else if op == "+" {
			left = scalar{value: lf + rf, bound: true}
		} else {
			left = scalar{value: lf - rf, bound: true}
		}
	}
	return left, nil
}
func (p *expressionParser) parseUnary() (scalar, error) {
	if p.accept("!") {
		value, err := p.parseUnary()
		return scalar{value: !effectiveBoolean(value), bound: true}, err
	}
	if p.accept("(") {
		value, err := p.parseOr()
		if !p.accept(")") {
			return scalar{}, fmt.Errorf("expression: expected )")
		}
		return value, err
	}
	if p.pos >= len(p.tokens) {
		return scalar{}, fmt.Errorf("expression: unexpected end")
	}
	token := p.tokens[p.pos]
	p.pos++
	if strings.HasPrefix(token, "?") {
		varName := token[1:]
		if p.extras != nil {
			if val, ok := p.extras[varName]; ok {
				return scalar{value: val, bound: true}, nil
			}
		}
		value, ok := p.binding[varName]
		if !ok || !value.Bound {
			if p.partial {
				return scalar{value: partialPassSentinel, bound: true}, nil
			}
			return scalar{}, nil
		}
		return scalar{value: value, bound: true}, nil
	}
	if p.pos < len(p.tokens) && p.tokens[p.pos] == "(" {
		return p.call(token)
	}
	if strings.HasPrefix(token, `"`) {
		return scalar{value: strings.Trim(strings.Split(token, "^^")[0], `"`), bound: true}, nil
	}
	if strings.HasPrefix(token, "<") && strings.HasSuffix(token, ">") {
		return scalar{value: token[1 : len(token)-1], bound: true}, nil
	}
	if value, err := strconv.ParseFloat(token, 64); err == nil {
		return scalar{value: value, bound: true}, nil
	}
	if strings.EqualFold(token, "true") || strings.EqualFold(token, "false") {
		return scalar{value: strings.EqualFold(token, "true"), bound: true}, nil
	}
	return scalar{value: token, bound: true}, nil
}
func (p *expressionParser) call(name string) (scalar, error) {
	p.pos++
	var args []scalar
	if !p.accept(")") {
		for {
			arg, err := p.parseOr()
			if err != nil {
				return scalar{}, err
			}
			args = append(args, arg)
			if p.accept(")") {
				break
			}
			if !p.accept(",") {
				return scalar{}, fmt.Errorf("expression %s: expected comma", name)
			}
		}
	}
	switch strings.ToLower(name) {
	case "bound":
		return scalar{value: len(args) == 1 && args[0].bound, bound: true}, nil
	case "str", "xsd:double":
		if len(args) != 1 || !args[0].bound {
			return scalar{}, nil
		}
		return scalar{value: lexical(args[0].value), bound: true}, nil
	case "lang":
		if len(args) != 1 || !args[0].bound {
			return scalar{}, nil
		}
		if v, ok := args[0].value.(Value); ok {
			return scalar{value: v.Language, bound: true}, nil
		}
		return scalar{value: "", bound: true}, nil
	case "langmatches":
		if len(args) != 2 {
			return scalar{}, nil
		}
		lang := strings.ToLower(lexical(args[0].value))
		pattern := strings.ToLower(lexical(args[1].value))
		return scalar{value: pattern == "*" && lang != "" || lang == pattern || strings.HasPrefix(lang, pattern+"-"), bound: true}, nil
	case "regex":
		if len(args) < 2 {
			return scalar{}, nil
		}
		flags := ""
		if len(args) > 2 {
			flags = lexical(args[2].value)
		}
		pattern := lexical(args[1].value)
		if strings.Contains(strings.ToLower(flags), "i") {
			pattern = "(?i)" + pattern
		}
		re, err := regexp.Compile(pattern)
		if err != nil {
			return scalar{}, err
		}
		return scalar{value: re.MatchString(lexical(args[0].value)), bound: true}, nil
	default:
		return scalar{}, fmt.Errorf("expression: unsupported function %s", name)
	}
}
func (p *expressionParser) accept(token string) bool {
	if p.pos < len(p.tokens) && strings.EqualFold(p.tokens[p.pos], token) {
		p.pos++
		return true
	}
	return false
}

func isPartialPass(s scalar) bool {
	if !s.bound {
		return false
	}
	if sv, ok := s.value.(string); ok && sv == partialPassSentinel {
		return true
	}
	if v, ok := s.value.(Value); ok && v.Kind == "" && v.Lexical == partialPassSentinel {
		return true
	}
	return false
}

func compareScalars(left, right scalar, op string) bool {
	if !left.bound || !right.bound {
		return false
	}
	// In partial evaluation mode, if either side is the pass sentinel, pass-through.
	if isPartialPass(left) || isPartialPass(right) {
		return true
	}
	lv, rv := scalarValue(left.value), scalarValue(right.value)
	lf, lok := number(lv)
	rf, rok := number(rv)
	if lok != rok {
		// One operand is numeric, the other is not — type mismatch in SPARQL semantics.
		// Comparing an integer to a date literal (for example) is a type error → false.
		return false
	}
	if lok && rok {
		switch op {
		case "=":
			return lf == rf
		case "!=":
			return lf != rf
		case "<":
			return lf < rf
		case ">":
			return lf > rf
		case "<=":
			return lf <= rf
		case ">=":
			return lf >= rf
		}
	}
	ls, rs := fmt.Sprint(lv), fmt.Sprint(rv)
	switch op {
	case "=":
		return ls == rs
	case "!=":
		return ls != rs
	case "<":
		return ls < rs
	case ">":
		return ls > rs
	case "<=":
		return ls <= rs
	case ">=":
		return ls >= rs
	}
	return false
}
func scalarValue(value any) any {
	if v, ok := value.(Value); ok {
		return v.Lexical
	}
	return value
}
func lexical(value any) string { return fmt.Sprint(scalarValue(value)) }
func number(value any) (float64, bool) {
	switch v := scalarValue(value).(type) {
	case float64:
		return v, true
	case int:
		return float64(v), true
	case string:
		f, e := strconv.ParseFloat(v, 64)
		return f, e == nil
	}
	return 0, false
}
func effectiveBoolean(value scalar) bool {
	if !value.bound {
		return false
	}
	// Partial-evaluation pass-through: unknown variables always evaluate to true.
	if isPartialPass(value) {
		return true
	}
	switch v := scalarValue(value.value).(type) {
	case bool:
		return v
	case string:
		return v != ""
	case float64:
		return v != 0
	}
	return false
}
func contains(values []string, target string) bool {
	for _, v := range values {
		if v == target {
			return true
		}
	}
	return false
}

func expressionTokens(input string) []string {
	var result []string
	for i := 0; i < len(input); {
		if unicode.IsSpace(rune(input[i])) {
			i++
			continue
		}
		if i+1 < len(input) && contains([]string{"&&", "||", "!=", "<=", ">="}, input[i:i+2]) {
			result = append(result, input[i:i+2])
			i += 2
			continue
		}
		if input[i] == '<' && i+1 < len(input) && !unicode.IsSpace(rune(input[i+1])) && input[i+1] != '=' {
			start := i
			i++
			for i < len(input) && input[i] != '>' {
				i++
			}
			if i < len(input) {
				i++
			}
			result = append(result, input[start:i])
			continue
		}
		if strings.ContainsRune("()!,+-<>=", rune(input[i])) {
			result = append(result, string(input[i]))
			i++
			continue
		}
		start := i
		if input[i] == '"' {
			i++
			for i < len(input) {
				if input[i] == '"' && input[i-1] != '\\' {
					i++
					break
				}
				i++
			}
			if i+2 < len(input) && input[i:i+3] == "^^<" {
				i += 3
				for i < len(input) && input[i] != '>' {
					i++
				}
				if i < len(input) {
					i++
				}
			} else if i < len(input) && input[i] == '@' {
				i++
				for i < len(input) && (unicode.IsLetter(rune(input[i])) || input[i] == '-') {
					i++
				}
			}
		} else {
			for i < len(input) && !unicode.IsSpace(rune(input[i])) && !strings.ContainsRune("()!,+-<>=&|", rune(input[i])) {
				i++
			}
		}
		result = append(result, input[start:i])
	}
	return result
}
