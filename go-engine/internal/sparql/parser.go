// Package sparql parses the SPARQL SELECT subset exercised by FedShop.
package sparql

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// TermKind identifies a SPARQL term.
type TermKind uint8

const (
	TermVariable TermKind = iota
	TermIRI
	TermLiteral
	TermBare
)

// Term is one RDF term in a triple pattern.
type Term struct {
	Kind  TermKind
	Value string
}

// TriplePattern is a basic graph pattern statement.
type TriplePattern struct {
	ID                         int
	Subject, Predicate, Object Term
}

// Key returns the FedShop composition-compatible triple representation.
func (t TriplePattern) Key() string {
	return strings.Join([]string{t.Subject.SPARQL(), t.Predicate.SPARQL(), t.Object.SPARQL()}, " ")
}

// Variables returns the unique variables in statement order.
func (t TriplePattern) Variables() []string {
	seen := map[string]bool{}
	var result []string
	for _, term := range []Term{t.Subject, t.Predicate, t.Object} {
		if term.Kind == TermVariable && !seen[term.Value] {
			seen[term.Value] = true
			result = append(result, term.Value)
		}
	}
	return result
}

// SPARQL renders a term without losing its RDF lexical representation.
func (t Term) SPARQL() string {
	switch t.Kind {
	case TermVariable:
		return "?" + t.Value
	case TermIRI:
		return "<" + t.Value + ">"
	default:
		return t.Value
	}
}

// Group is a graph-pattern group.
type Group struct {
	Triples   []TriplePattern
	Filters   []string
	Optionals []*Group
	Unions    [][2]*Group
}

// OrderCondition is one ORDER BY expression.
type OrderCondition struct {
	Expression string
	Ascending  bool
}

// Query is the FedShop-supported SELECT algebra.
type Query struct {
	Prefixes map[string]string
	Select   []string
	Distinct bool
	Where    *Group
	OrderBy  []OrderCondition
	Offset   int
	Limit    int
}

// Triples returns every triple in stable source order.
func (q Query) Triples() []TriplePattern {
	var result []TriplePattern
	var visit func(*Group)
	visit = func(group *Group) {
		result = append(result, group.Triples...)
		for _, pair := range group.Unions {
			visit(pair[0])
			visit(pair[1])
		}
		for _, optional := range group.Optionals {
			visit(optional)
		}
	}
	visit(q.Where)
	return result
}

var (
	prefixPattern   = regexp.MustCompile(`(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>`)
	selectPattern   = regexp.MustCompile(`(?is)\bSELECT\s+(DISTINCT\s+)?(.+?)\s+(?:WHERE\s*)?\{`)
	variablePattern = regexp.MustCompile(`\?([A-Za-z_][\w-]*)`)
	limitPattern    = regexp.MustCompile(`(?is)\bLIMIT\s+(\d+)`)
	offsetPattern   = regexp.MustCompile(`(?is)\bOFFSET\s+(\d+)`)
	orderPattern    = regexp.MustCompile(`(?is)\bORDER\s+BY\s+(.+?)(?:\bLIMIT\b|\bOFFSET\b|$)`)
)

// Parse parses the SELECT subset used by all FedShop query templates.
func Parse(input string) (Query, error) {
	clean := stripComments(input)
	if regexp.MustCompile(`(?i)\b(GRAPH|SERVICE|BIND|VALUES|MINUS|GROUP\s+BY|HAVING)\b`).MatchString(clean) {
		return Query{}, fmt.Errorf("parse query: unsupported graph-pattern feature")
	}
	prefixes := map[string]string{}
	for _, match := range prefixPattern.FindAllStringSubmatch(clean, -1) {
		prefixes[match[1]] = match[2]
	}
	selectMatch := selectPattern.FindStringSubmatchIndex(clean)
	if selectMatch == nil {
		return Query{}, fmt.Errorf("parse query: expected SELECT and graph pattern")
	}
	selectMatchText := selectPattern.FindStringSubmatch(clean)
	selected := unique(variablePattern.FindAllStringSubmatch(selectMatchText[2], -1))
	if strings.TrimSpace(selectMatchText[2]) == "*" {
		selected = nil
	}
	open := strings.Index(clean[selectMatch[0]:selectMatch[1]], "{") + selectMatch[0]
	close, err := matching(clean, open, '{', '}')
	if err != nil {
		return Query{}, err
	}
	group, err := parseGroup(clean[open+1:close], prefixes)
	if err != nil {
		return Query{}, err
	}
	assignTripleIDs(group)
	query := Query{Prefixes: prefixes, Select: selected, Distinct: strings.TrimSpace(selectMatchText[1]) != "", Where: group, Limit: -1}
	if match := limitPattern.FindStringSubmatch(clean[close+1:]); match != nil {
		query.Limit, err = strconv.Atoi(match[1])
		if err != nil {
			return Query{}, fmt.Errorf("parse LIMIT: %w", err)
		}
	}
	if match := offsetPattern.FindStringSubmatch(clean[close+1:]); match != nil {
		query.Offset, err = strconv.Atoi(match[1])
		if err != nil {
			return Query{}, fmt.Errorf("parse OFFSET: %w", err)
		}
	}
	if match := orderPattern.FindStringSubmatch(clean[close+1:]); match != nil {
		query.OrderBy = parseOrder(match[1])
	}
	return query, nil
}

func unique(matches [][]string) []string {
	seen := map[string]bool{}
	var result []string
	for _, match := range matches {
		if !seen[match[1]] {
			seen[match[1]] = true
			result = append(result, match[1])
		}
	}
	return result
}

func parseOrder(input string) []OrderCondition {
	var result []OrderCondition
	for len(strings.TrimSpace(input)) > 0 {
		input = strings.TrimSpace(input)
		ascending := true
		expr := ""
		upper := strings.ToUpper(input)
		if strings.HasPrefix(upper, "DESC(") || strings.HasPrefix(upper, "ASC(") {
			ascending = strings.HasPrefix(upper, "ASC(")
			open := strings.Index(input, "(")
			close, err := matching(input, open, '(', ')')
			if err != nil {
				return result
			}
			expr, input = strings.TrimSpace(input[open+1:close]), input[close+1:]
		} else if strings.HasPrefix(input, "?") {
			end := 1
			for end < len(input) && (unicode.IsLetter(rune(input[end])) || unicode.IsDigit(rune(input[end])) || input[end] == '_') {
				end++
			}
			expr, input = input[:end], input[end:]
		} else {
			// FedShop q10 uses xsd:double(str(?price)); retain it as one expression.
			end := len(input)
			expr, input = strings.TrimSpace(input[:end]), ""
		}
		result = append(result, OrderCondition{Expression: expr, Ascending: ascending})
	}
	return result
}

func assignTripleIDs(group *Group) {
	next := 0
	var visit func(*Group)
	visit = func(g *Group) {
		for i := range g.Triples {
			g.Triples[i].ID = next
			next++
		}
		for _, union := range g.Unions {
			visit(union[0])
			visit(union[1])
		}
		for _, optional := range g.Optionals {
			visit(optional)
		}
	}
	visit(group)
}

func parseGroup(body string, prefixes map[string]string) (*Group, error) {
	group := &Group{}
	for pos := 0; pos < len(body); {
		pos = skipSpace(body, pos)
		if pos >= len(body) {
			break
		}
		if hasKeyword(body, pos, "OPTIONAL") {
			pos = skipSpace(body, pos+len("OPTIONAL"))
			if pos >= len(body) || body[pos] != '{' {
				return nil, fmt.Errorf("parse OPTIONAL: expected {")
			}
			close, err := matching(body, pos, '{', '}')
			if err != nil {
				return nil, err
			}
			child, err := parseGroup(body[pos+1:close], prefixes)
			if err != nil {
				return nil, err
			}
			group.Optionals = append(group.Optionals, child)
			pos = close + 1
			continue
		}
		if hasKeyword(body, pos, "FILTER") {
			pos = skipSpace(body, pos+len("FILTER"))
			if pos >= len(body) {
				return nil, fmt.Errorf("parse FILTER: expected expression")
			}
			exprStart, open := pos, pos
			if body[open] != '(' {
				open = strings.IndexByte(body[pos:], '(')
				if open < 0 {
					return nil, fmt.Errorf("parse FILTER: expected expression")
				}
				open += pos
			}
			close, err := matching(body, open, '(', ')')
			if err != nil {
				return nil, err
			}
			if open == pos {
				group.Filters = append(group.Filters, strings.TrimSpace(body[pos+1:close]))
			} else {
				group.Filters = append(group.Filters, strings.TrimSpace(body[exprStart:close+1]))
			}
			pos = close + 1
			continue
		}
		if body[pos] == '{' {
			close, err := matching(body, pos, '{', '}')
			if err != nil {
				return nil, err
			}
			left, err := parseGroup(body[pos+1:close], prefixes)
			if err != nil {
				return nil, err
			}
			next := skipSpace(body, close+1)
			if !hasKeyword(body, next, "UNION") {
				return nil, fmt.Errorf("parse subgroup: only UNION groups are supported")
			}
			next = skipSpace(body, next+len("UNION"))
			if next >= len(body) || body[next] != '{' {
				return nil, fmt.Errorf("parse UNION: expected second group")
			}
			rightClose, err := matching(body, next, '{', '}')
			if err != nil {
				return nil, err
			}
			right, err := parseGroup(body[next+1:rightClose], prefixes)
			if err != nil {
				return nil, err
			}
			group.Unions = append(group.Unions, [2]*Group{left, right})
			pos = rightClose + 1
			continue
		}
		statementEnd := findStatementEnd(body, pos)
		triples, err := parseStatement(body[pos:statementEnd], prefixes)
		if err != nil {
			return nil, err
		}
		group.Triples = append(group.Triples, triples...)
		pos = statementEnd
		if pos < len(body) && body[pos] == '.' {
			pos++
		}
	}
	return group, nil
}

func parseStatement(input string, prefixes map[string]string) ([]TriplePattern, error) {
	tokens := tokenize(strings.TrimSpace(input))
	if len(tokens) < 3 {
		return nil, fmt.Errorf("parse triple near %q: expected subject predicate object", strings.TrimSpace(input))
	}
	subject, err := parseTerm(tokens[0], prefixes)
	if err != nil {
		return nil, err
	}
	var result []TriplePattern
	var predicate Term
	for i := 1; i < len(tokens); {
		if tokens[i] == ";" {
			i++
			continue
		}
		if tokens[i] == "," {
			i++
			if i >= len(tokens) {
				return nil, fmt.Errorf("parse comma object")
			}
			object, termErr := parseTerm(tokens[i], prefixes)
			if termErr != nil {
				return nil, termErr
			}
			result = append(result, TriplePattern{Subject: subject, Predicate: predicate, Object: object})
			i++
			continue
		}
		if i+1 >= len(tokens) {
			return nil, fmt.Errorf("parse triple: missing object")
		}
		predicate, err = parseTerm(tokens[i], prefixes)
		if err != nil {
			return nil, err
		}
		object, termErr := parseTerm(tokens[i+1], prefixes)
		if termErr != nil {
			return nil, termErr
		}
		result = append(result, TriplePattern{Subject: subject, Predicate: predicate, Object: object})
		i += 2
	}
	return result, nil
}

func parseTerm(token string, prefixes map[string]string) (Term, error) {
	if strings.HasPrefix(token, "?") {
		return Term{Kind: TermVariable, Value: token[1:]}, nil
	}
	if strings.HasPrefix(token, "<") && strings.HasSuffix(token, ">") {
		return Term{Kind: TermIRI, Value: token[1 : len(token)-1]}, nil
	}
	if token == "a" {
		return Term{Kind: TermIRI, Value: "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"}, nil
	}
	if strings.HasPrefix(token, `"`) {
		return Term{Kind: TermLiteral, Value: token}, nil
	}
	if colon := strings.IndexByte(token, ':'); colon >= 0 {
		if base, ok := prefixes[token[:colon]]; ok {
			return Term{Kind: TermIRI, Value: base + token[colon+1:]}, nil
		}
	}
	return Term{Kind: TermBare, Value: token}, nil
}

func tokenize(input string) []string {
	var tokens []string
	for i := 0; i < len(input); {
		if unicode.IsSpace(rune(input[i])) {
			i++
			continue
		}
		start := i
		switch input[i] {
		case '<':
			i++
			for i < len(input) && input[i] != '>' {
				i++
			}
			if i < len(input) {
				i++
			}
		case '"':
			i++
			escaped := false
			for i < len(input) {
				if !escaped && input[i] == '"' {
					i++
					break
				}
				escaped = !escaped && input[i] == '\\'
				if input[i] != '\\' {
					escaped = false
				}
				i++
			}
			for i < len(input) && !unicode.IsSpace(rune(input[i])) && input[i] != ';' && input[i] != ',' {
				i++
			}
		case ';', ',':
			i++
		default:
			for i < len(input) && !unicode.IsSpace(rune(input[i])) && input[i] != ';' && input[i] != ',' {
				i++
			}
		}
		tokens = append(tokens, input[start:i])
	}
	return tokens
}

func findStatementEnd(input string, start int) int {
	inIRI, inString, escaped := false, false, false
	for i := start; i < len(input); i++ {
		ch := input[i]
		if escaped {
			escaped = false
			continue
		}
		if inString && ch == '\\' {
			escaped = true
			continue
		}
		if !inString && ch == '<' && i+1 < len(input) && !unicode.IsSpace(rune(input[i+1])) && input[i+1] != '=' {
			inIRI = true
		} else if inIRI && ch == '>' {
			inIRI = false
		} else if !inIRI && ch == '"' {
			inString = !inString
		}
		if !inIRI && !inString && (ch == '.' || ch == '{' || ch == '}') {
			return i
		}
	}
	return len(input)
}

func matching(input string, open int, left, right byte) (int, error) {
	depth, inIRI, inString, escaped := 0, false, false, false
	for i := open; i < len(input); i++ {
		ch := input[i]
		if escaped {
			escaped = false
			continue
		}
		if inString && ch == '\\' {
			escaped = true
			continue
		}
		if !inString && ch == '<' && i+1 < len(input) && !unicode.IsSpace(rune(input[i+1])) && input[i+1] != '=' {
			inIRI = true
		} else if inIRI && ch == '>' {
			inIRI = false
		} else if !inIRI && ch == '"' {
			inString = !inString
		}
		if inIRI || inString {
			continue
		}
		if ch == left {
			depth++
		} else if ch == right {
			depth--
			if depth == 0 {
				return i, nil
			}
		}
	}
	return 0, fmt.Errorf("parse query: missing %q", right)
}

func stripComments(input string) string {
	var result strings.Builder
	for _, line := range strings.Split(input, "\n") {
		inIRI, inString, escaped := false, false, false
		for _, ch := range line {
			if escaped {
				result.WriteRune(ch)
				escaped = false
				continue
			}
			if inString && ch == '\\' {
				result.WriteRune(ch)
				escaped = true
				continue
			}
			if !inString && ch == '<' {
				inIRI = true
			} else if inIRI && ch == '>' {
				inIRI = false
			} else if !inIRI && ch == '"' {
				inString = !inString
			}
			if ch == '#' && !inIRI && !inString {
				break
			}
			result.WriteRune(ch)
		}
		result.WriteByte('\n')
	}
	return result.String()
}

func skipSpace(input string, pos int) int {
	for pos < len(input) && unicode.IsSpace(rune(input[pos])) {
		pos++
	}
	return pos
}
func hasKeyword(input string, pos int, keyword string) bool {
	if pos < 0 || pos+len(keyword) > len(input) || !strings.EqualFold(input[pos:pos+len(keyword)], keyword) {
		return false
	}
	return pos+len(keyword) == len(input) || !(unicode.IsLetter(rune(input[pos+len(keyword)])) || unicode.IsDigit(rune(input[pos+len(keyword)])) || input[pos+len(keyword)] == '_')
}
