package engine

import "sort"

// JoinBindings performs a natural join over shared variable names.
func JoinBindings(left, right []Binding) []Binding {
	if len(left) == 0 {
		return cloneBindings(right)
	}
	if len(right) == 0 {
		return nil
	}

	joined := make([]Binding, 0)
	for _, l := range left {
		for _, r := range right {
			if compatible(l, r) {
				joined = append(joined, merge(l, r))
			}
		}
	}
	return joined
}

// ProjectBindings converts bindings to ordered CSV-style records.
func ProjectBindings(rows []Binding, vars []string) ([]string, [][]string) {
	if len(vars) == 0 {
		vars = allVars(rows)
	}
	records := make([][]string, 0, len(rows))
	for _, row := range rows {
		record := make([]string, len(vars))
		for i, name := range vars {
			record[i] = row[name]
		}
		records = append(records, record)
	}
	return vars, records
}

func compatible(left, right Binding) bool {
	for key, leftValue := range left {
		if rightValue, ok := right[key]; ok && rightValue != leftValue {
			return false
		}
	}
	return true
}

func merge(left, right Binding) Binding {
	out := make(Binding, len(left)+len(right))
	for key, value := range left {
		out[key] = value
	}
	for key, value := range right {
		out[key] = value
	}
	return out
}

func cloneBindings(rows []Binding) []Binding {
	out := make([]Binding, 0, len(rows))
	for _, row := range rows {
		clone := make(Binding, len(row))
		for key, value := range row {
			clone[key] = value
		}
		out = append(out, clone)
	}
	return out
}

func allVars(rows []Binding) []string {
	seen := map[string]bool{}
	for _, row := range rows {
		for key := range row {
			seen[key] = true
		}
	}
	var vars []string
	for key := range seen {
		vars = append(vars, key)
	}
	sort.Strings(vars)
	return vars
}
