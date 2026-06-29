package executor

// Value is an RDF binding value as returned by a SPARQL endpoint.
type Value struct {
	Kind     string `json:"kind"`
	Lexical  string `json:"lexical"`
	Datatype string `json:"datatype,omitempty"`
	Language string `json:"language,omitempty"`
	Bound    bool   `json:"bound"`
}

// IRI constructs a bound IRI value.
func IRI(value string) Value { return Value{Kind: "uri", Lexical: value, Bound: true} }

// Literal constructs a bound RDF literal.
func Literal(value, datatype, language string) Value {
	return Value{Kind: "literal", Lexical: value, Datatype: datatype, Language: language, Bound: true}
}

// PlainLiteral constructs a bound untyped literal.
func PlainLiteral(value string) Value { return Literal(value, "", "") }

// Binding maps variable names without the leading question mark to RDF values.
type Binding map[string]Value

// Clone returns an independent shallow copy of a binding.
func (b Binding) Clone() Binding {
	result := make(Binding, len(b))
	for key, value := range b {
		result[key] = value
	}
	return result
}

func compatible(left, right Binding) bool {
	for key, lvalue := range left {
		if rvalue, ok := right[key]; ok && lvalue.Bound && rvalue.Bound && lvalue != rvalue {
			return false
		}
	}
	return true
}

func merge(left, right Binding) Binding {
	result := left.Clone()
	for key, value := range right {
		if value.Bound {
			result[key] = value
		}
	}
	return result
}
