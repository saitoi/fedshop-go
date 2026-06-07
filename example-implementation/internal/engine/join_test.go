package engine

import "testing"

func TestJoinBindingsMatchesSharedVariables(t *testing.T) {
	left := []Binding{
		{"product": "p1", "label": "A"},
		{"product": "p2", "label": "B"},
	}
	right := []Binding{
		{"product": "p1", "review": "r1"},
		{"product": "p3", "review": "r3"},
	}

	got := JoinBindings(left, right)
	if len(got) != 1 {
		t.Fatalf("len(join) = %d, want 1: %#v", len(got), got)
	}
	if got[0]["product"] != "p1" || got[0]["label"] != "A" || got[0]["review"] != "r1" {
		t.Fatalf("joined binding = %#v", got[0])
	}
}

func TestProjectBindingsPreservesColumnOrder(t *testing.T) {
	rows := []Binding{
		{"product": "p1", "label": "A", "review": "r1"},
	}

	header, records := ProjectBindings(rows, []string{"label", "product"})
	if got, want := len(records), 1; got != want {
		t.Fatalf("record count = %d, want %d", got, want)
	}
	if got, want := header[0], "label"; got != want {
		t.Fatalf("header[0] = %q, want %q", got, want)
	}
	if got, want := records[0][0], "A"; got != want {
		t.Fatalf("records[0][0] = %q, want %q", got, want)
	}
	if got, want := records[0][1], "p1"; got != want {
		t.Fatalf("records[0][1] = %q, want %q", got, want)
	}
}
