package main

import (
	"context"
	"encoding/csv"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"example-implementation/internal/engine"
)

const version = "0.1.0"

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	fs := flag.NewFlagSet("fedshop-rsa-go", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	queryFile := fs.String("query", "", "SPARQL query file containing SERVICE blocks")
	outResult := fs.String("out-result", "results.csv", "CSV result output path")
	outSource := fs.String("out-source-selection", "source_selection.csv", "source-selection CSV output path")
	outPlan := fs.String("query-plan", "query_plan.txt", "query plan output path")
	stats := fs.String("stats", "stats.csv", "stats CSV output path")
	timeout := fs.Duration("timeout", 120*time.Second, "query timeout")
	noexec := fs.Bool("noexec", false, "write plan/source outputs without querying endpoints")
	showVersion := fs.Bool("version", false, "print version and exit")

	if err := fs.Parse(args); err != nil {
		return err
	}
	if *showVersion {
		fmt.Println(version)
		return nil
	}
	if *queryFile == "" {
		return fmt.Errorf("--query is required")
	}

	queryBytes, err := os.ReadFile(*queryFile)
	if err != nil {
		return fmt.Errorf("read query: %w", err)
	}
	query, err := engine.ParseQuery(string(queryBytes))
	if err != nil {
		return err
	}

	if err := writeTextFile(*outPlan, engine.PlanText(query)); err != nil {
		return err
	}
	if err := writeFile(*outSource, func(file *os.File) error {
		return engine.WriteSourceSelectionCSV(file, query)
	}); err != nil {
		return err
	}

	start := time.Now()
	result := engine.Result{}
	if !*noexec {
		ctx, cancel := context.WithTimeout(context.Background(), *timeout)
		defer cancel()

		executor := engine.NewExecutor(http.DefaultClient)
		result, err = executor.Execute(ctx, query)
		if err != nil {
			return err
		}
		if err := writeFile(*outResult, func(file *os.File) error {
			return engine.WriteResultCSV(file, result.Bindings, query.Select)
		}); err != nil {
			return err
		}
	} else if err := touch(*outResult); err != nil {
		return err
	}

	return writeStats(*stats, filepath.Base(*queryFile), time.Since(start), result.HTTPRequests)
}

func writeFile(path string, write func(*os.File) error) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil && filepath.Dir(path) != "." {
		return fmt.Errorf("create parent dir for %s: %w", path, err)
	}
	file, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create %s: %w", path, err)
	}
	defer file.Close()
	if err := write(file); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	return nil
}

func writeTextFile(path, text string) error {
	return writeFile(path, func(file *os.File) error {
		_, err := file.WriteString(text)
		return err
	})
}

func touch(path string) error {
	return writeFile(path, func(*os.File) error { return nil })
}

func writeStats(path, queryName string, elapsed time.Duration, httpRequests int) error {
	return writeFile(path, func(file *os.File) error {
		writer := csv.NewWriter(file)
		if err := writer.Write([]string{"query", "engine", "instance", "batch", "attempt", "exec_time", "ask", "source_selection_time", "planning_time", "http_req", "data_transfer"}); err != nil {
			return err
		}
		if err := writer.Write([]string{
			queryName,
			"fedshop-rsa-go",
			"",
			"",
			"",
			fmt.Sprintf("%.3f", float64(elapsed.Microseconds())/1000.0),
			"0",
			"0",
			"0",
			fmt.Sprintf("%d", httpRequests),
			"0",
		}); err != nil {
			return err
		}
		writer.Flush()
		return writer.Error()
	})
}
