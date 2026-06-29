// Package cli implements the non-interactive fedshop-go command line.
package cli

import (
	"context"
	"flag"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/pedrosaito/fedshop-go/internal/app"
	"github.com/pedrosaito/fedshop-go/internal/endpoint"
)

// Version is replaced by release builds when desired.
const Version = "dev"

// Run executes a command with a background context.
func Run(args []string, stdout, stderr io.Writer) int {
	return RunContext(context.Background(), args, stdout, stderr)
}

// RunContext executes a command and returns a process exit code.
func RunContext(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 || args[0] == "--help" || args[0] == "-h" {
		writeHelp(stdout)
		return 0
	}
	switch args[0] {
	case "version":
		fmt.Fprintf(stdout, "fedshop-go %s\n", Version)
		return 0
	case "completion":
		if len(args) != 2 {
			return usageError(stderr, "completion requires bash, zsh, or fish")
		}
		return writeCompletion(args[1], stdout, stderr)
	case "query":
		return runQuery(ctx, args[1:], stderr)
	case "summarize":
		return runSummary(ctx, args[1:], stderr)
	default:
		return usageError(stderr, "unknown command "+strconv.Quote(args[0]))
	}
}

func runQuery(ctx context.Context, args []string, stderr io.Writer) int {
	set := flag.NewFlagSet("query", flag.ContinueOnError)
	set.SetOutput(stderr)
	var options app.QueryOptions
	var timeout time.Duration
	var cache string
	var httpProxy string
	var retryCount int
	set.StringVar(&options.Config, "config", "", "Turtle endpoint config")
	set.StringVar(&options.Query, "query", "", "SPARQL SELECT query")
	set.StringVar(&options.OutResult, "out-result", "", "result CSV")
	set.StringVar(&options.OutSources, "out-source-selection", "", "source-selection CSV")
	set.StringVar(&options.OutPlan, "query-plan", "", "query plan")
	set.StringVar(&options.OutStats, "stats", "", "JSON engine stats")
	set.DurationVar(&timeout, "timeout", 60*time.Second, "query and per-request timeout")
	set.StringVar(&options.Selector, "selector", "ask", "broadcast, ask, or summary")
	set.StringVar(&options.Summary, "summary", "", "metadata catalog for summary selector")
	set.StringVar(&cache, "cache", "memory", "off or memory")
	set.StringVar(&options.Join, "join", "hash", "hash or bind")
	set.StringVar(&options.Planner, "planner", "source-count", "source-count or cost")
	set.StringVar(&options.FailurePolicy, "failure-policy", "strict", "strict or partial")
	set.StringVar(&httpProxy, "http-proxy", "", "explicit HTTP proxy URL")
	set.IntVar(&retryCount, "retry-count", 2, "retries for transient endpoint failures")
	set.IntVar(&options.MaxConcurrency, "max-concurrency", 16, "maximum concurrent endpoint requests")
	set.IntVar(&options.BindBatchSize, "bind-batch-size", 20, "VALUES rows per bound request")
	set.BoolVar(&options.ExclusiveGroups, "exclusive-groups", false, "combine patterns assigned to one endpoint")
	set.IntVar(&options.PostBindMaxInputRows, "post-bind-max-input-rows", 0, "skip post-bind exclusive group when input rows exceed this (0=unlimited)")
	set.BoolVar(&options.NoExec, "noexec", false, "plan without executing SELECT requests")
	if err := set.Parse(args); err != nil {
		return 2
	}
	if options.Config == "" {
		return usageError(stderr, "--config is required")
	}
	if options.Query == "" {
		return usageError(stderr, "--query is required")
	}
	if options.OutResult == "" {
		return usageError(stderr, "--out-result is required")
	}
	if options.OutSources == "" {
		return usageError(stderr, "--out-source-selection is required")
	}
	if options.OutPlan == "" {
		return usageError(stderr, "--query-plan is required")
	}
	if options.OutStats == "" {
		return usageError(stderr, "--stats is required")
	}
	if cache != "off" && cache != "memory" {
		return usageError(stderr, "--cache must be off or memory")
	}
	options.Cache = cache == "memory"
	if retryCount < 0 {
		return usageError(stderr, "--retry-count must be non-negative")
	}
	httpClient, err := endpoint.NewHTTPClient(httpProxy)
	if err != nil {
		return usageError(stderr, err.Error())
	}
	queryCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	client := endpoint.NewClient(httpClient, timeout, endpoint.WithRetries(retryCount))
	if err := app.RunQuery(queryCtx, options, client); err != nil {
		fmt.Fprintf(stderr, "fedshop-go query: %v\n", err)
		return 1
	}
	return 0
}

func runSummary(ctx context.Context, args []string, stderr io.Writer) int {
	set := flag.NewFlagSet("summarize", flag.ContinueOnError)
	set.SetOutput(stderr)
	var options app.SummaryOptions
	var timeout time.Duration
	set.StringVar(&options.Config, "config", "", "Turtle endpoint config")
	set.StringVar(&options.Output, "output", "", "versioned summary JSON")
	set.IntVar(&options.MaxConcurrency, "max-concurrency", 8, "maximum concurrent endpoints")
	set.DurationVar(&timeout, "timeout", 60*time.Second, "summary request timeout")
	if err := set.Parse(args); err != nil {
		return 2
	}
	if options.Config == "" {
		return usageError(stderr, "--config is required")
	}
	if options.Output == "" {
		return usageError(stderr, "--output is required")
	}
	summaryCtx, cancel := context.WithTimeout(ctx, timeout*time.Duration(options.MaxConcurrency+1))
	defer cancel()
	client := endpoint.NewClient(&http.Client{}, timeout)
	if err := app.RunSummary(summaryCtx, options, client); err != nil {
		fmt.Fprintf(stderr, "fedshop-go summarize: %v\n", err)
		return 1
	}
	return 0
}

func writeHelp(output io.Writer) {
	fmt.Fprint(output, `fedshop-go - federated SPARQL engine for FedShop

Usage:
  fedshop-go query [flags]
  fedshop-go summarize [flags]
  fedshop-go completion bash|zsh|fish
  fedshop-go version
`)
}
func usageError(stderr io.Writer, message string) int {
	fmt.Fprintln(stderr, "fedshop-go:", message)
	return 2
}
func writeCompletion(shell string, stdout, stderr io.Writer) int {
	if shell != "bash" && shell != "zsh" && shell != "fish" {
		return usageError(stderr, "unsupported shell "+shell)
	}
	commands := "query summarize completion version"
	switch shell {
	case "bash":
		fmt.Fprintf(stdout, "complete -W %q fedshop-go\n", commands)
	case "zsh":
		fmt.Fprintf(stdout, "#compdef fedshop-go\n_arguments '1:command:(%s)'\n", strings.ReplaceAll(commands, " ", " "))
	case "fish":
		for _, command := range strings.Fields(commands) {
			fmt.Fprintf(stdout, "complete -c fedshop-go -f -a %s\n", command)
		}
	}
	return 0
}
