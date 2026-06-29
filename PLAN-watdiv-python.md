# Plan: WatDiv Python Rewrite

Replace the C++ WatDiv binary with a pure-Python implementation so `fedshop-py`
can run `generate products` / `generate sources` without a compiled binary or
system dict files.

## Scope

Only the `-d <model> <scale_factor>` mode (dataset generation → `.nq` output).
The `-q` (query instantiation) and `-s` (statistics) modes are not used by
fedshop-py and will not be ported.

## Files to create / modify

| Action | Path |
|--------|------|
| New    | `fedshop-py/src/fedshop/watdiv.py` — ~250-line core |
| Modify | `fedshop-py/src/fedshop/generate.py` — replace `subprocess` call with `watdiv.run()` |
| Add    | `fedshop-py/src/fedshop/data/firstnames` — bundled from `reference-repos/query-engines/watdiv/files/firstnames` |
| Add    | `fedshop-py/src/fedshop/data/lastnames`  — bundled from `reference-repos/query-engines/watdiv/files/lastnames` |
| Modify | `fedshop-py/pyproject.toml` — add `package-data` entry for `data/` |

## Implementation outline (`watdiv.py`)

### 1. Dictionary (replaces `dictionary.cpp`)
```
_WORDS  = sorted(Path("/usr/share/dict/words").read_text().split())
_FIRST  = sorted((data_dir / "firstnames").read_text().split())
_LAST   = sorted((data_dir / "lastnames").read_text().split())
```
Bundle `firstnames` / `lastnames` inside the package under `src/fedshop/data/`
so no system install is needed.

### 2. Random generators (replaces Boost random)
```python
import random, numpy as np
rng = random.Random()                         # seeded once at import

def _uniform() -> float: return rng.random()
def _normal()  -> float: return max(0.0, min(1.0, rng.gauss(0.5, 0.5/3)))
def _zipfian(n: int) -> float: ...           # CDF-bisect, cached per n
def _generate_random(dist, n=0) -> float: ...
```

### 3. Literal generator (replaces `model::generate_literal`)
Six literal types: INTEGER, FLOAT, STRING, NAME, COUNTRY, DATE.
```python
COUNTRIES      = ["US","UK","JP","CN","DE","FR","ES","RU","KR","AT"]
COUNTRY_WEIGHTS = [40,  10,  10,  10,   5,   5,   5,   5,   5,   5]
LANGTAGS       = ["en","ja","zh","de","fr","es","ru","kr","at"]
LANG_WEIGHTS   = [50,  10,  10,   5,   5,   5,   5,   5,   5]

def generate_literal(lit_type, dist, var_len, rmin, rmax) -> str: ...
```
Date arithmetic via `datetime.date`; no Boost.

### 4. Template parser (replaces `model::parse`)
Line-by-line, strip comments (`//`), dispatch on first token:
- `#namespace key=value` → namespace dict
- `<type> prefix N` / `</type>` → push/pop ResourceDef
- `<pgroup> prob [@restriction]` / `</pgroup>` → push/pop PGroupDef
- `#predicate label type [min max [dist]]` → PredicateDef
- `#association[1] subj pred obj card_l card_r dist_l dist_r` → AssocDef
  - plain `#association` → CHOSEN constraint
  - `#association1`      → CHOSEN_OR_PREVIOUSLY_EXISTED constraint

### 5. Resource generation (replaces `resource_m_t::generate_one`)
```python
def generate_one(res: ResourceDef, ns: dict, id: int, gen_log: set, out: IO):
    subject = f"<{ns['__provenance']}{res.type_suffix}{id}>"
    global_subject = f"<{ns_replace(res.type_prefix)}{id}>"
    emit(subject, RDF_TYPE, f"<{ns_replace(res.type_prefix)}>", provenance)
    emit(subject, OWL_SAME_AS, global_subject, provenance)
    for pgroup in res.pgroups:
        if rng.random() <= pgroup.probability:
            for pred in pgroup.predicates:
                emit(subject, pred.uri(ns), pred.generate(), provenance)
```

### 6. Association generation (replaces `association_m_t::generate`)
This is the most complex part. Four constraint modes; only CHOSEN and
CHOSEN_OR_PREVIOUSLY_EXISTED appear in the BSBM templates, but implement all
four for correctness:
```python
for i in range(left_count):
    left_id = pick_left(i, dist_l, left_count, left_cover)
    cond = eval_constraint(constraint, left_id, gen_log, ...)
    if cond:
        for j in range(sample_right_size(card_r, dist_r)):
            right_id = pick_unique_right(dist_r, right_count, used_rights)
            ensure_generated(left_id, right_id, ...)
            emit(subject, predicate, object, provenance)
```

### 7. Top-level `run(model_text: str, scale_factor: int, output: IO)`
```python
def run(model_text: str, scale_factor: int, output: IO) -> None:
    ns, resources, associations = parse_template(model_text)
    ns = apply_scale(ns, resources, scale_factor)
    gen_log: set[str] = set()
    for assoc in associations:
        assoc.generate(ns, resources, gen_log, output)
    for res in resources:
        res.process_type_restrictions(ns, gen_log, output)
```

### 8. Integration in `generate.py`
Replace:
```python
proc = subprocess.run(f"{gen.generator.exec} -d {model_file} {scale_factor}", ...)
```
With:
```python
from .watdiv import run as watdiv_run
watdiv_run(model_text, scale_factor, output_file.open("w"))
```
Config key `generation.generator.exec` becomes optional / ignored when the
Python fallback is active. Keep the subprocess path as a fallback if the binary
exists, for parity testing.

## Day-by-day breakdown

**Day 1** — dictionary, literal generators, distribution functions, template
parser. Unit-test literal output shapes and distribution ranges.

**Day 2** — resource generation, association generation (all 4 constraint
modes), NQ output, top-level `run()`. Integration into `generate.py`.

**Day 3** — end-to-end test: run `fedshop generate products` and
`fedshop generate sources`, diff entity counts and predicate coverage against
the existing `.nq` files in `benchmark/generation/` (exact byte match is
impossible — output is random — but structural checks: entity count,
predicate presence, NQ syntax).

## Testing strategy

1. Parse one existing `.nq` file and verify entity count matches config params.
2. Unit tests for each literal type (valid range, correct XSD annotation).
3. Unit test for Zipfian: histogram should be heavily skewed to low indices.
4. Smoke: `generate sources --section vendor --id 0` completes without error and
   produces a non-empty `.nq` file with the right subject prefix.

## Known risks

- **Association constraint semantics**: `resource_gen_log` interaction in
  PREVIOUSLY_EXISTED mode is subtle. The BSBM templates only use CHOSEN and
  CHOSEN_OR_PREVIOUSLY_EXISTED (`#association` vs `#association1`), so the
  other two modes can be stubbed with a `NotImplementedError` initially.
- **Randomness reproducibility**: output will differ from C++ WatDiv byte-for-
  byte. Downstream tests that assume fixed `.nq` content will need to check
  structure, not exact content.
- **Scale performance**: Python will be slower than C++ for large scale factors,
  but the small config (`n_batch=2`, 20 endpoints) is trivial in size.
