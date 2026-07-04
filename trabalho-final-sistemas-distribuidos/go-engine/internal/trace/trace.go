// Package trace records a structured event timeline for visualization.
//
// The schema matches the fedshop-py webapp tracer (tracer.py): an ordered list
// of events, each with seq, type, t0, t1 (seconds since run start) plus
// type-specific fields. All methods are safe on a nil *Tracer (no-ops) so
// instrumentation call sites need no guards, and Emit is safe for concurrent
// use because endpoint requests run in parallel.
package trace

import (
	"encoding/json"
	"os"
	"sync"
	"time"
)

// Tracer accumulates events for one query run.
type Tracer struct {
	mu      sync.Mutex
	started time.Time
	events  []map[string]any
}

// New starts a tracer clocked from now.
func New() *Tracer {
	return &Tracer{started: time.Now()}
}

// Now returns seconds elapsed since the tracer started.
func (t *Tracer) Now() float64 {
	if t == nil {
		return 0
	}
	return time.Since(t.started).Seconds()
}

// Emit appends one event. Pass t0 < 0 to use the current time; t1 is always
// the current time.
func (t *Tracer) Emit(eventType string, t0 float64, fields map[string]any) {
	if t == nil {
		return
	}
	t1 := t.Now()
	if t0 < 0 {
		t0 = t1
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	event := map[string]any{"seq": len(t.events), "type": eventType, "t0": t0, "t1": t1}
	for key, value := range fields {
		event[key] = value
	}
	t.events = append(t.events, event)
}

// Write serializes {"events": [...], "error": ...} to path.
func (t *Tracer) Write(path, errorMessage string) error {
	if t == nil || path == "" {
		return nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	payload := map[string]any{"events": t.events}
	if errorMessage != "" {
		payload["error"] = errorMessage
	} else {
		payload["error"] = nil
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}
