package artifact

import (
	"encoding/csv"
	"os"
	"path/filepath"
	"testing"

	"github.com/pedrosaito/fedshop-go/internal/executor"
	"github.com/pedrosaito/fedshop-go/internal/federation"
	"github.com/pedrosaito/fedshop-go/internal/sparql"
)

func TestWriteRunArtifacts(t *testing.T) {
	t.Parallel()
	query, err := sparql.Parse(`SELECT ?s ?label WHERE { ?s <http://example/p> ?label }`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	dir := t.TempDir()
	paths := Paths{Results: filepath.Join(dir, "results.csv"), Sources: filepath.Join(dir, "sources.csv"), Plan: filepath.Join(dir, "plan.txt"), Stats: filepath.Join(dir, "stats.json")}
	selection := federation.Selection{0: {{ID: "endpoint_one"}}}
	rows := []executor.Binding{{"s": executor.IRI("http://s"), "label": executor.PlainLiteral("Phone")}}
	stats := RunStats{Engine: "fedshop-go", Rows: 1, Selector: "ask"}
	if err := WriteRun(paths, query, rows, selection, stats); err != nil {
		t.Fatalf("WriteRun() error = %v", err)
	}
	file, err := os.Open(paths.Results)
	if err != nil {
		t.Fatalf("open results: %v", err)
	}
	defer file.Close()
	records, err := csv.NewReader(file).ReadAll()
	if err != nil {
		t.Fatalf("read results: %v", err)
	}
	if len(records) != 2 || records[0][0] != "s" || records[1][1] != "Phone" {
		t.Fatalf("records = %#v", records)
	}
	for _, path := range []string{paths.Sources, paths.Plan, paths.Stats} {
		info, statErr := os.Stat(path)
		if statErr != nil || info.Size() == 0 {
			t.Fatalf("artifact %s is missing or empty", path)
		}
	}
}
