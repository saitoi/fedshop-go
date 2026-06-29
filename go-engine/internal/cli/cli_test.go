package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestHelpListsPublicCommands(t *testing.T) {
	t.Parallel()
	var stdout, stderr bytes.Buffer
	code := Run([]string{"--help"}, &stdout, &stderr)
	if code != 0 {
		t.Fatalf("Run() code = %d, stderr = %s", code, stderr.String())
	}
	for _, command := range []string{"query", "summarize", "completion", "version"} {
		if !strings.Contains(stdout.String(), command) {
			t.Fatalf("help does not contain %q: %s", command, stdout.String())
		}
	}
}

func TestVersionWritesVersion(t *testing.T) {
	t.Parallel()
	var stdout, stderr bytes.Buffer
	if code := Run([]string{"version"}, &stdout, &stderr); code != 0 {
		t.Fatalf("code = %d", code)
	}
	if !strings.Contains(stdout.String(), "fedshop-go") {
		t.Fatalf("version = %q", stdout.String())
	}
}

func TestQueryRejectsMissingRequiredFlags(t *testing.T) {
	t.Parallel()
	var stdout, stderr bytes.Buffer
	if code := Run([]string{"query"}, &stdout, &stderr); code != 2 {
		t.Fatalf("code = %d, want 2", code)
	}
	if !strings.Contains(stderr.String(), "--config") {
		t.Fatalf("stderr = %q", stderr.String())
	}
}

func TestQueryAcceptsProxyAndRetryFlags(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	query := filepath.Join(dir, "query.sparql")
	config := filepath.Join(dir, "config.ttl")
	if err := os.WriteFile(query, []byte(`SELECT ?s WHERE { ?s <http://example/p> ?o }`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(config, []byte(`<http://member/> a sd:Service ; sd:endpoint "http://endpoint" .`), 0o644); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	code := Run([]string{
		"query",
		"--config", config,
		"--query", query,
		"--out-result", filepath.Join(dir, "results.csv"),
		"--out-source-selection", filepath.Join(dir, "sources.csv"),
		"--query-plan", filepath.Join(dir, "plan.txt"),
		"--stats", filepath.Join(dir, "stats.json"),
		"--selector", "broadcast",
		"--noexec",
		"--http-proxy", "http://localhost:5555",
		"--retry-count", "2",
	}, &stdout, &stderr)
	if code != 0 {
		t.Fatalf("Run() code = %d, stderr = %s", code, stderr.String())
	}
}
