package engine

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var (
	prefixRE = regexp.MustCompile(`(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):\s*<([^>]+)>`)
	selectRE = regexp.MustCompile(`(?is)\bSELECT\s+(DISTINCT\s+)?(.+?)\s+\bWHERE\b`)
	limitRE  = regexp.MustCompile(`(?is)\bLIMIT\s+(\d+)`)
	varRE    = regexp.MustCompile(`\?([A-Za-z_][\w-]*)`)
)

// ParseQuery parses a deliberately small SPARQL subset: prefixes, SELECT,
// LIMIT, and SERVICE <endpoint> { basic graph pattern } blocks.
func ParseQuery(input string) (Query, error) {
	query := Query{
		Prefixes: make(map[string]string),
		Limit:    -1,
	}

	for _, match := range prefixRE.FindAllStringSubmatch(input, -1) {
		query.Prefixes[match[1]] = match[2]
	}

	selectMatch := selectRE.FindStringSubmatch(input)
	if selectMatch == nil {
		return Query{}, fmt.Errorf("parse select clause: unsupported query")
	}
	query.Distinct = strings.TrimSpace(selectMatch[1]) != ""
	query.Select = parseSelectVars(selectMatch[2])

	if limitMatch := limitRE.FindStringSubmatch(input); limitMatch != nil {
		limit, err := strconv.Atoi(limitMatch[1])
		if err != nil {
			return Query{}, fmt.Errorf("parse limit: %w", err)
		}
		query.Limit = limit
	}

	blocks, err := parseServiceBlocks(input)
	if err != nil {
		return Query{}, err
	}
	if len(blocks) == 0 {
		return Query{}, fmt.Errorf("parse service blocks: only SERVICE queries are supported")
	}
	query.ServiceBlocks = blocks

	return query, nil
}

func parseSelectVars(clause string) []string {
	if strings.TrimSpace(clause) == "*" {
		return nil
	}
	matches := varRE.FindAllStringSubmatch(clause, -1)
	vars := make([]string, 0, len(matches))
	seen := make(map[string]bool, len(matches))
	for _, match := range matches {
		if !seen[match[1]] {
			vars = append(vars, match[1])
			seen[match[1]] = true
		}
	}
	return vars
}

func parseServiceBlocks(input string) ([]ServiceBlock, error) {
	var blocks []ServiceBlock
	lower := strings.ToLower(input)
	offset := 0
	for {
		idx := strings.Index(lower[offset:], "service")
		if idx == -1 {
			break
		}
		pos := offset + idx + len("service")
		pos = skipSpace(input, pos)
		if pos >= len(input) || input[pos] != '<' {
			offset = pos
			continue
		}
		endEndpoint := strings.IndexByte(input[pos:], '>')
		if endEndpoint == -1 {
			return nil, fmt.Errorf("parse service endpoint: missing closing >")
		}
		endpoint := input[pos+1 : pos+endEndpoint]
		pos = skipSpace(input, pos+endEndpoint+1)
		if pos >= len(input) || input[pos] != '{' {
			return nil, fmt.Errorf("parse service block %s: missing opening brace", endpoint)
		}
		closeBrace, err := matchingBrace(input, pos)
		if err != nil {
			return nil, fmt.Errorf("parse service block %s: %w", endpoint, err)
		}
		body := input[pos+1 : closeBrace]
		blocks = append(blocks, ServiceBlock{
			Endpoint: endpoint,
			Triples:  splitTripleLines(body),
		})
		offset = closeBrace + 1
	}
	return blocks, nil
}

func skipSpace(s string, pos int) int {
	for pos < len(s) && (s[pos] == ' ' || s[pos] == '\n' || s[pos] == '\r' || s[pos] == '\t') {
		pos++
	}
	return pos
}

func matchingBrace(s string, open int) (int, error) {
	depth := 0
	for i := open; i < len(s); i++ {
		switch s[i] {
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return i, nil
			}
		}
	}
	return 0, fmt.Errorf("missing closing brace")
}

func splitTripleLines(body string) []string {
	var triples []string
	for _, line := range strings.Split(body, "\n") {
		line = stripComment(line)
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		triples = append(triples, line)
	}
	return triples
}

func stripComment(line string) string {
	if idx := strings.IndexByte(line, '#'); idx >= 0 {
		return line[:idx]
	}
	return line
}
