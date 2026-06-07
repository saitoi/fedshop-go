package engine

import (
	"encoding/csv"
	"fmt"
	"io"
	"strings"
)

// WriteResultCSV writes projected bindings in SPARQL CSV format.
func WriteResultCSV(w io.Writer, rows []Binding, vars []string) error {
	header, records := ProjectBindings(rows, vars)
	writer := csv.NewWriter(w)
	if err := writer.Write(header); err != nil {
		return fmt.Errorf("write header: %w", err)
	}
	if err := writer.WriteAll(records); err != nil {
		return fmt.Errorf("write records: %w", err)
	}
	return writer.Error()
}

// WriteSourceSelectionCSV writes a simple FedShop-like source-selection table.
func WriteSourceSelectionCSV(w io.Writer, query Query) error {
	var header []string
	var row []string
	tp := 1
	for _, block := range query.ServiceBlocks {
		for range block.Triples {
			header = append(header, fmt.Sprintf("tp%d", tp))
			row = append(row, block.Endpoint)
			tp++
		}
	}
	writer := csv.NewWriter(w)
	if err := writer.Write(header); err != nil {
		return fmt.Errorf("write source header: %w", err)
	}
	if err := writer.Write(row); err != nil {
		return fmt.Errorf("write source row: %w", err)
	}
	writer.Flush()
	return writer.Error()
}

// PlanText returns a readable execution plan.
func PlanText(query Query) string {
	var b strings.Builder
	for i, block := range query.ServiceBlocks {
		fmt.Fprintf(&b, "SERVICE %d %s\n", i+1, block.Endpoint)
		for _, triple := range block.Triples {
			fmt.Fprintf(&b, "  %s\n", triple)
		}
	}
	return b.String()
}
