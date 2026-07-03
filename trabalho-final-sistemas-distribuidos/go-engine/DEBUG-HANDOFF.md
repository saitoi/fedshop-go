# Go Engine Debug Handoff

## Status Summary (2026-06-22)

Binary in use: `/tmp/fedshop-go-hashjoin` (built from current `go-engine/` source)

---

## Completed

### q02 — accepted as expected timeout
- Post-bind exclusive group fires correctly (sends remaining 12 patterns as one query to vendor0)
- Virtuoso itself takes >300s to return 1M-row result → accepted as timeout, same as FedX

### Hash join optimization (just merged)
- `join()` in `executor/executor.go` was O(n×m) nested loop; replaced with O(n+m) hash join
- `leftJoin()` similarly updated
- All 59 tests pass, build clean
- Root cause for slow q05: `join(208080, 5500)` = 1.14B comparisons with old code

### Prior session optimizations (already in code)
- `buildSelect` in `endpoint/client.go`: filters VALUES clause to only triple-relevant variables and deduplicates rows
- Pre-batch dedup in `executor/fetchTriple`: deduplicates input by triple variables before batching
- Post-bind exclusive group: after locality lock-in, sends all remaining patterns as one SPARQL to one endpoint
- `reorderForEagerFilter`: defers SELECT-only patterns (e.g. `rdfs:label`) until after filter-variable producers
- Response body limit raised to 2 GB

---

## q05 — Still Failing (timeout ~4+ min even with hash join)

### Root cause
Product8746 has:
- 72 features (tp1)
- 17 distinct origProperty1 values × 17 origProperty2 = 289 combos (tp2, tp3)

These are independent properties joined only on `localProductXYZ`, creating 72 × 289 = **20,808 rows** before the cross-endpoint search begins.

Then tp5 (similar features from 10 vendors) returns ~714 rows → `join(20808, 714)` = **208K rows**.
Then tp6 (products with those features) returns ~5500 rows → `join(208K, 5500)` = **1.5M rows**.

Even with O(n+m) hash join, creating 1.5M `Binding` maps (each a `map[string]Value`) is expensive and exceeds 90–120s.

### What was tried (in this session)
| Attempt | Outcome |
|---|---|
| `--timeout 60s` old binary | Killed at 60s, no result |
| `--timeout 300s` old binary | Killed externally at 5 min, no result |
| `--timeout 90s` hash join binary | Killed by outer `timeout 120` at 4:05 |

Virtuoso memory stays stable (~600 MB) — **no OOM risk** with current code.

### What remains for q05

**Option A (simplest correctness fix)**: Recognize that `origProperty1` and `origProperty2` are semantically independent of the feature path. Instead of joining them into rows, compute:
- `orig1_values` = `{605, 621, 645, ...}` (17 floats)
- `orig2_values` = `{1033, ...}` (17 floats)

Then for each candidate `(sim1, sim2)` from the similar-product path: check `∃ o1 ∈ orig1_values: |sim1 - o1| < 20` and `∃ o2 ∈ orig2_values: |sim2 - o2| < 70` as scalar range checks (binary search). This avoids the 20808 cross-product entirely.

Requires: detect that tp2/tp3 feed only the FILTER (not joins) and evaluate them as scalar sets.

**Option B (quick test)**: Just run with `--timeout 600s` and outer `timeout 600` to see if hash join completes eventually. If it finishes in 3–5 min, it might be acceptable for the benchmark's `exec_time` limit.

**Option C**: Accept q05 as timeout (similar to FedX behavior on q02).

---

## How to Resume

```bash
cd /Users/pedrosaito/fedshop-new-engine/go-engine

# Kill any stale processes first
pkill -f fedshop-go 2>/dev/null || true

# Build latest binary
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go build -o /tmp/fedshop-go-latest ./cmd/fedshop-go

# Quick test q05 with generous timeout
CONFIG="$PWD/target/config/config_batch0.ttl"
QUERY="../fedshop-py/benchmark/generation/q05/instance_0/injected.sparql"
time /tmp/fedshop-go-latest query --config "$CONFIG" --query "$QUERY" \
  --out-result /tmp/q05.csv --out-source-selection /tmp/q05_sel.csv \
  --query-plan /tmp/q05_plan.txt --stats /tmp/q05_stats.json \
  --join bind --exclusive-groups --timeout 600s

# Run tests to verify no regressions
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go test ./...
```

---

## Other Queries (batch0, instance_0)

| Query | Status | Notes |
|---|---|---|
| q02 | timeout | Expected; FedX also fails; 1M-row result |
| q05 | timeout | Root cause above; hash join helps but still too slow |
| q06, q07, q12 | MATCH reference | Verified correct |
| q11 | 5 rows (correct) | Minor float formatting diff (`2787.71` vs `2787.710...`) |
| q08, q09 | Not re-tested this session | Were working in prior session |
| q01, q03, q04, q10 | Not re-tested this session | |
