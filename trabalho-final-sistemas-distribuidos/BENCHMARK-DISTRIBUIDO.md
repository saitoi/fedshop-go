# Benchmark distribuído (topologias T1/T2/T3)

Benchmarks de sistemas distribuídos sobre os motores `pyfedx`, `fedshop-go` e
`rsa`, em três topologias de rede. Tudo contido em
`trabalho-final-sistemas-distribuidos/`; as saídas ficam em
`fedshop-py/benchmark-dist/` (os resultados antigos em `fedshop-py/benchmark/`
não são tocados).

## Topologias

| Nome  | Descrição |
|-------|-----------|
| T1    | Engine/cliente + todos os endpoints na mesma máquina |
| T2    | Todos os endpoints (Virtuoso) numa máquina remota; engine/cliente noutra |
| T3    | Vendors na máquina B, ratingsites na máquina C, engine/cliente na máquina A |

O proxy FedShop roda sempre na máquina A (fora do caminho de dados; só
`/reset`/`/get-stats`), então as medições são comparáveis entre topologias.

## Métricas novas (por execução, colunas extras no stats.csv)

- `data_transfer` / `request_bytes` — bytes recebidos/enviados pelo motor
- `net_req_count`, `net_total_time`, `net_mean_time`, `net_p50_time`,
  `net_p95_time` — latência de rede por requisição
- `endpoints_contacted`, `endpoint_load_imbalance` — balanceamento entre
  membros da federação (razão máx/média de requisições)
- `planning_time`/`join_time` reais também no pyfedx (antes só no go)

Derivadas no merge (`metrics_topology.csv`): `slowdown_vs_t1`,
`network_time_ratio` (>1 = requisições sobrepostas / latência escondida),
`throughput_rows_s`, `bytes_per_result`, `predicted_net_time`
(nº req × RTT — modelo de custo de comunicação), `exec_time_cv` (jitter),
mais covariáveis do manifest (`rtt_vendor_ms`, `rtt_ratingsite_ms`,
`bandwidth_mbps`).

## Testes de hipótese (`fedshop topology hypothesis`)

- **HT1** — topologia afeta `exec_time`: Friedman T1/T2/T3 (blocado por
  motor×consulta×lote) + Wilcoxon pareado pós-hoc com correção de Holm.
- **HT2** — motores "conversadores" sofrem mais: Spearman entre nº de
  requisições em T1 e o slowdown em T3, por motor e agregado.
- **HT3** — fase mais afetada pela latência: Wilcoxon pareado entre as razões
  T3/T1 de `source_selection_time` e `join_time`.
- **HT4** — interação escala×topologia: Spearman `exec_time`×lote por
  (motor, topologia).
- **HT5** — dividir endpoints em 2 máquinas (T3) vs 1 (T2): Wilcoxon pareado.

## Execução

### 0. Preparação (máquina A, uma vez)

```bash
cd fedshop-py
uv run fedshop generate products --config inputs/config/config_dist.yaml
uv run fedshop generate sources  --config inputs/config/config_dist.yaml
docker compose -f docker/virtuoso.yml up -d
for b in $(seq 0 9); do uv run fedshop ingest batch $b --config inputs/config/config_dist.yaml; done
for b in $(seq 0 9); do
  uv run fedshop query run-all --config inputs/config/config_dist.yaml \
    --bench-dir benchmark-dist --batch-id $b
done
# copiar data-dist/dataset para as máquinas B e C (ex.: rsync/tar)
```

### 1. T1 (tudo local)

```bash
bash scripts/run-topology-benchmark.sh --topology 1
```

### 2. T2 (endpoints remotos)

```bash
# máquina B:
bash scripts/machine-endpoints.sh
# máquina A:
bash scripts/run-topology-benchmark.sh --topology 2 --vendor-host IP_B --ratingsite-host IP_B
```

### 3. T3 (três máquinas)

```bash
# máquina B: bash scripts/machine-vendor.sh --config inputs/config/config_dist.yaml
# máquina C: bash scripts/machine-ratingsite.sh --config inputs/config/config_dist.yaml
# máquina A:
bash scripts/run-topology-benchmark.sh --topology 3 --vendor-host IP_B --ratingsite-host IP_C
```

### 4. Agregação (máquina A)

```bash
cd fedshop-py
uv run fedshop topology merge benchmark-dist/metrics_topology.csv
uv run fedshop topology hypothesis benchmark-dist/hypothesis_topology.csv \
  --from-csv benchmark-dist/metrics_topology.csv
uv run fedshop topology typst-tables benchmark-dist/tables_topology.typ \
  --from-csv benchmark-dist/metrics_topology.csv \
  --hypothesis-csv benchmark-dist/hypothesis_topology.csv
uv run fedshop topology plot benchmark-dist/plots \
  --from-csv benchmark-dist/metrics_topology.csv
```

## Notas

- `--iperf` no run-topology-benchmark.sh mede banda (requer `iperf3 -s` na
  máquina remota).
- O RSA em T3 depende do parser de lambda do FedUP aceitar ternário no
  `--modify` (não verificado); se falhar, restrinja o RSA a T1/T2 com
  `--engines pyfedx,fedshop-go` no T3.
- Virtuoso nas máquinas B/C precisa aceitar conexões externas (porta 8890
  exposta no docker/virtuoso.yml).
- `--skip-existing-ok` permite retomar uma topologia interrompida sem repetir
  execuções válidas.
