package executor

import "testing"

func TestFedShopFilterExpressions(t *testing.T) {
	t.Parallel()
	row := Binding{
		"price": Literal("12.5", "http://www.w3.org/2001/XMLSchema#decimal", ""),
		"orig":  Literal("100", "http://www.w3.org/2001/XMLSchema#integer", ""),
		"sim":   Literal("110", "http://www.w3.org/2001/XMLSchema#integer", ""),
		"label": PlainLiteral("Phone XL"),
		"text":  Literal("Great", "", "en-US"),
		"a":     IRI("http://a"), "b": IRI("http://b"),
	}
	tests := []struct {
		name, expression string
		want             bool
	}{
		{"numeric comparison", "?price < 20", true},
		{"arithmetic conjunction", "?sim < (?orig + 20) && ?sim > (?orig - 20)", true},
		{"regex", "regex(?label, \"Phone\")", true},
		{"bound", "BOUND(?label)", true},
		{"not bound", "!BOUND(?missing)", true},
		{"language", "langMatches(lang(?text), \"en\")", true},
		{"not equal", "?a != ?b", true},
		{"typed date", `"2026-01-02"^^<http://www.w3.org/2001/XMLSchema#date> > "2026-01-01"^^<http://www.w3.org/2001/XMLSchema#date>`, true},
		{"IRI constant", `?a = <http://a>`, true},
	}
	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			got, err := evalFilter(tt.expression, row)
			if err != nil {
				t.Fatalf("evalFilter() error = %v", err)
			}
			if got != tt.want {
				t.Fatalf("evalFilter(%q) = %v, want %v", tt.expression, got, tt.want)
			}
		})
	}
}
