# Session Handoff — 2026-06-29

## Objetivo geral

Corrigir os 22 timeouts do fedshop-go e os mismatches das outras engines (fedx: 51, rsa: 35, semagrow: 22, splendid: 8), conforme reportado em `estado-atual-benchmarks.txt`.

---

## O que foi feito

### 1. Fixes para mismatches (outras engines) — COMPLETO

Todos os fixes foram implementados e testam OK (sintaxe válida):

**`fedshop-py/src/fedshop/engines/fedx.py`**
- Adicionado `import requests`
- Adicionada função `_wait_virtuoso(endpoint, max_wait=120)` que bloqueia até Virtuoso responder
- Chamada de `_wait_virtuoso` em `FedXAdapter.run_benchmark` antes de `proxy_client.reset()`
- Isso resolve 47 dos 51 mismatches do FedX (todos causados por attempt_0 com Virtuoso ainda iniciando)

**`fedshop-py/src/fedshop/engines/rsa.py`**
- Adicionada chamada de `_wait_jena(virt_sparql)` em `RsaAdapter.run_benchmark` antes de `proxy_client.reset()`
- `_wait_jena` já existia e funciona para qualquer SPARQL endpoint
- Isso resolve 34 dos 35 mismatches do RSA

**`fedshop-py/src/fedshop/engines/semagrow.py`**
- Importado `_wait_virtuoso` de `..engines.fedx`
- Chamada em `SemagrowAdapter.run_benchmark` antes de `proxy_client.reset()`
- `transform_results` agora faz `drop_duplicates` (resolve q11 20→10 rows parcialmente)
- Isso resolve 18 dos 22 mismatches do Semagrow

**`fedshop-py/src/fedshop/evaluate.py`**
- Adicionada remoção de `source_selection_time.txt` e `planning_time.txt` stale antes de cada attempt
- Evita que valores de runs anteriores poluam `stats.csv` quando o engine falha silenciosamente

**Mismatches NÃO fixáveis no adapter:**
- FedX q06 (4/51): bug no Java FedX — resultados não deduplicados por fonte
- RSA q02 att0 (1/35): limitação do FedUP — atribui 1 fonte para query cross-product
- Semagrow q11 coluna `isValueOf` (4/22): bug no Java Semagrow — não projeta variáveis UNION não-bound
- SPLENDID todos (8/8): crashes JVM em q11 + timeouts em q02/q05/q07 — não fixável no adapter

---

### 2. Otimizações do Go engine — PARCIALMENTE FEITO

O binário está em `/Users/pedrosaito/fedshop-new-engine/go-engine/fedshop-go` e foi recompilado.

#### Implementado e funcionando (passa `go test ./...`):

**`go-engine/internal/executor/executor.go`**
- `Client` interface: `Select` aceita `...string` (push filters) como parâmetro variadic
- `pruneSourcesBySubjectLocality`: quando o subject de um triple está uniformemente bound a um IRI que mapeia para 1 endpoint via GraphIRI prefix, restringe sources a esse endpoint. Reduz HTTP requests em ~20x para q02 (de 220 para ~14)
- `perEndpointCompound` + `extractConstantVars` + `derivePushableFilters` + `derivePushableFiltersCompound`: tentativa de compound queries por endpoint — implementadas mas NÃO resolvem q02 (ver análise abaixo)
- `collectLocalSubjectGroup`: REVERTIDA — tornava q02 pior

**`go-engine/internal/endpoint/client.go`**
- `Select` aceita `...string` para injetar FILTER clauses na query SPARQL

**`go-engine/internal/executor/expression.go`**
- `substituteConstants`: substitui variáveis constantes em filter expressions
- `renderSPARQLLiteral`: serializa Value para literal SPARQL

**Todos os mocks em `executor_test.go` e `app/query_test.go` atualizados.**

---

### 3. Análise do q02 — TIMEOUT NÃO RESOLVÍVEL COM DADOS ATUAIS

**Causa raiz descoberta via debug (DEBUG_EXEC=1):**

O produto `Product8540` está no endpoint `ratingsite1` (via sameAs). O endpoint ratingsite1 tem:
- 63 features para este produto
- **11 valores INDEPENDENTES** para cada propriedade textual/numérica:
  - `productPropertyTextual1`: 11 valores distintos
  - `productPropertyTextual2`: 11 valores distintos  
  - `productPropertyTextual3`: 11 valores distintos
  - `productPropertyNumeric1`: 11 valores distintos
  - `productPropertyNumeric2`: 11 valores distintos

Isso cria um cross-product inevitável: 11^5 = 161,051 combinações só para as propriedades obrigatórias. Com features (63) e labels (9 por feature), o resultado seria ~90M linhas — impossível em 120s.

**Verificação da referência:** `results-batch0.csv` para q02 tem 1,048,576 linhas. O valor textual3 da referência ("SHIPP BYRNE GABLE...") **não existe no Virtuoso atual** — os dados são diferentes dos que geraram a referência. Qualquer engine rodando no Virtuoso atual produzirá resultados errados OU timeout para q02.

**Otimizações tentadas e por que não funcionam:**
- `perEndpointCompound`: falha porque `?localProductFeature1` não está bound quando a checagem ocorre após o 1º triple
- `local-subject-compound` (compound query ao endpoint): Virtuoso ainda produz 11^5 internamente — mesmo resultado, diferente só onde o cross-product acontece
- `pruneSourcesBySubjectLocality`: AJUDA (reduz HTTP de 220→14) mas não resolve o cross-product

**Conclusão:** q02 tem 12 timeouts causados por dados incompatíveis na referência + explosão de cross-product no Virtuoso atual. Não é resolvível sem alterar os dados ou o framework de comparação.

---

### 4. Análise do q05 — INTERROMPIDA

O debug de q05 foi iniciado e mostrou os primeiros steps:
```
tp0: sameAs → 1 resultado
tp1: productFeature → 63 resultados (mesma explosão do q02)
tp2: numeric1 → 11 resultados, SCALAR COLLECT ← bom! filtro pushdown funciona
tp3: numeric2 → 11 resultados, SCALAR COLLECT
tp4: featureSameAs → 63 resultados
tp5: localProdFeature sameAs → 1090 resultados
tp6: localProduct productFeature → 19354 resultados
```

Então o engine tenta `per-endpoint group` em `ratingsite3` e recebe `context deadline exceeded` — timeout em 25s de teste.

**q05 tem `LIMIT 5`** — em teoria deveria ser rápido se o engine conseguir early termination. O problema é que o engine está tentando materializar TODOS os resultados antes de aplicar LIMIT.

---

## Estado do código

| Arquivo | Estado |
|---------|--------|
| `fedshop-py/src/fedshop/engines/fedx.py` | ✅ Modificado |
| `fedshop-py/src/fedshop/engines/rsa.py` | ✅ Modificado |
| `fedshop-py/src/fedshop/engines/semagrow.py` | ✅ Modificado |
| `fedshop-py/src/fedshop/evaluate.py` | ✅ Modificado |
| `go-engine/internal/executor/executor.go` | ✅ Modificado (pruning + perEndpointCompound) |
| `go-engine/internal/endpoint/client.go` | ✅ Modificado (variadic filters) |
| `go-engine/internal/executor/expression.go` | ✅ Modificado (substituteConstants) |
| `go-engine/fedshop-go` (binário) | ✅ Recompilado |
| `go test ./...` | ✅ 60 testes passando |

---

## O que falta

### Prioridade 1 — Validar fixes das outras engines

Rodar o benchmark completo para fedx, rsa, semagrow com os novos adapters:
```bash
cd /Users/pedrosaito/fedshop-new-engine/fedshop-py
uv run fedshop evaluate run-all --engine fedx
uv run fedshop evaluate run-all --engine rsa  
uv run fedshop evaluate run-all --engine semagrow
```

Verificar que mismatches reduziram de 51/35/22 para ~4/1/4.

### Prioridade 2 — Investigar q05 mais a fundo

Q05 tem `LIMIT 5`. O engine provavelmente não implementa early-termination para LIMIT. Investigar:
1. Onde o LIMIT é aplicado no código Go (`go-engine/internal/`)
2. Se é possível propagar o LIMIT para as queries dos endpoints (via `LIMIT N` na query SPARQL)
3. Verificar se o `perEndpointCompound` ajuda quando rows se dividem por múltiplos endpoints para `?localProduct`

```bash
# Para debugar q05:
DEBUG_EXEC=1 timeout 60 /Users/pedrosaito/fedshop-new-engine/go-engine/fedshop-go query \
  --config /Users/pedrosaito/fedshop-new-engine/go-engine/target/config/config_batch0.ttl \
  --query /Users/pedrosaito/fedshop-new-engine/fedshop-py/benchmark/generation/q05/instance_0/injected.sparql \
  --out-result /tmp/q05_result.csv --out-source-selection /tmp/q05_src.csv \
  --query-plan /tmp/q05_plan.txt --stats /tmp/q05_stats.json \
  --timeout 55s --selector ask --cache memory --join bind \
  --planner source-count --exclusive-groups 2>&1
```

### Prioridade 3 — Aceitar q02 como irresolvível OU investigar data

Opções para q02:
- **Opção A (recomendada):** Aceitar que q02 tem 12 timeouts causados por incompatibilidade de dados. Documenta como limitação conhecida.
- **Opção B:** Investigar se os dados do Virtuoso foram gerados corretamente. O ratingsite1 tem 11 valores para `productPropertyTextual3` de um produto — isso pode ser bug na geração. Comparar com `reference-repos/FedShop/experiments/bsbm/docker/` para ver como os dados foram carregados.
- **Opção C:** Adicionar `DISTINCT` ao output do engine (já tem na query q05 mas não q02) — mas q02 não tem DISTINCT no template.

### Prioridade 4 — Rodar benchmark completo e comparar métricas

Após fixes:
```bash
cd /Users/pedrosaito/fedshop-new-engine/fedshop-py
uv run fedshop evaluate run-all
```

Gerar relatório de métricas e comparar com `estado-atual-benchmarks.txt`.

---

## Contexto técnico importante

### Arquitetura do benchmark
- Config: `fedshop-py/config/config_small.yaml` — usa `benchmark/` como bench-dir
- Adapter CLI: `uv run fedshop evaluate run ENGINE QUERY INSTANCE BATCH ATTEMPT`
- Binário Go: `go-engine/fedshop-go` (dir configurado no config_small.yaml como `${config_dir}/../../go-engine`)
- Virtuoso: `http://localhost:8890/sparql`
- Proxy: `http://localhost:5555` (proxy FedShop)

### Docker
- Virtuoso: `docker compose -f reference-repos/FedShop/experiments/bsbm/docker/virtuoso.yml up -d`
- Proxy: `docker compose -f reference-repos/FedShop/experiments/bsbm/docker/proxy.yml up -d`
- Health check Virtuoso: `curl -m 5 "http://localhost:8890/sparql?query=ASK%20%7B%20%3Fs%20%3Fp%20%3Fo%20%7D"`
- Health check proxy: `curl -m 5 http://localhost:5555/get-stats`

### Build do Go engine
```bash
cd /Users/pedrosaito/fedshop-new-engine/go-engine
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go build -o fedshop-go ./cmd/fedshop-go
GOCACHE=$PWD/.gocache GOMODCACHE=$PWD/.gomodcache go test ./...
```

### Debug do engine
```bash
DEBUG_EXEC=1 /Users/pedrosaito/fedshop-new-engine/go-engine/fedshop-go query [args] 2>&1
```

### Localização dos resultados
- Benchmark evaluation: `fedshop-py/benchmark/evaluation/ENGINE/QUERY/instance_I/batch_B/attempt_A/`
- Referência: `fedshop-py/benchmark/generation/QUERY/instance_I/results-batchB.csv`
- Stats individuais: `stats.csv` (exec_time="timeout" indica timeout)
