package sparql

import "testing"

func FuzzParseDoesNotPanic(f *testing.F) {
	f.Add(`SELECT ?s WHERE { ?s <http://example/p> ?o }`)
	f.Add(`PREFIX ex: <http://example/> SELECT ?s { OPTIONAL { ?s ex:p ?o } }`)
	f.Add(`SELECT WHERE {`)
	f.Fuzz(func(t *testing.T, input string) { _, _ = Parse(input) })
}
