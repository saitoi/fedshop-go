# Visualizador do motor de consultas federado

Aplicação web que **executa uma consulta SPARQL federada de verdade** — com o
`pyfedx` (Python, `../pyfedx/`) ou com o `fedshop-go` (Go, `../../go-engine/`) —
contra os endpoints do FedShop no Virtuoso e reproduz a execução como uma animação
fiel e controlável.

## Como rodar

Pré-requisito: Virtuoso de pé em `localhost:8890` com os grafos do batch
(`http://www.vendor0.fr/` … `http://www.ratingsite9.fr/`).

```bash
# 1. compilar o frontend (React + shadcn/ui) — só na primeira vez ou após mudanças
cd webapp/frontend && npm install && npm run build

# 2. subir o servidor
cd webapp
uv run uvicorn app:app --port 8000
# abrir http://localhost:8000/
```

Para desenvolver o frontend com hot-reload: `npm run dev` em `frontend/` (o Vite
faz proxy de `/api` para `localhost:8022` — ajuste em `vite.config.ts`).

Para usar o fedshop-go, o binário precisa existir em `../../go-engine/fedshop-go`
(ou apontar `FEDSHOP_GO_BINARY`); o seletor "Motor" no topo passa a listá-lo.

## Demonstração distribuída

O webapp separa o cliente visual do trabalho real: o FastAPI recebe a consulta,
executa o motor (`pyfedx` ou `fedshop-go`) e o motor faz requisições HTTP reais
para os endpoints SPARQL. Para a apresentação, a topologia mais estável é deixar
o navegador e o motor na mesma máquina e mover os endpoints Virtuoso para uma ou
duas máquinas remotas.

O webapp pressupõe que a preparação FedShop já foi feita. Ele lê as consultas de
`../fedshop-py/benchmark/generation/` e consulta grafos que já precisam estar
ingeridos no Virtuoso. Ele não gera dados, não instancia queries e não carrega
N-Quads durante o startup.

### Preparar dados e consultas

Neste checkout já existem consultas instanciadas em `fedshop-py/benchmark/generation/`
e arquivos `.nq` em `fedshop-py/inputs/product-dataset/`. Se precisar recriar
esses artefatos, rode a preparação no diretório `fedshop-py`:

```bash
cd trabalho-final-sistemas-distribuidos/fedshop-py
uv run fedshop generate products --config inputs/config/config_small.yaml
uv run fedshop generate sources --config inputs/config/config_small.yaml
```

Na máquina que hospeda o Virtuoso, suba o serviço e carregue os batches que serão
usados na demo:

```bash
cd trabalho-final-sistemas-distribuidos/fedshop-py
docker compose -f docker/virtuoso.yml up -d

uv run fedshop ingest batch 0 --config inputs/config/config_small.yaml
uv run fedshop ingest batch 1 --config inputs/config/config_small.yaml
```

Depois gere ou atualize as consultas instanciadas contra os dados carregados:

```bash
uv run fedshop query run-all \
  --config inputs/config/config_small.yaml \
  --bench-dir benchmark \
  --batch-id 0
```

Se essa preparação for feita numa máquina diferente da máquina A, copie para a
máquina A pelo menos:

```text
fedshop-py/benchmark/generation/
fedshop-py/data/virtuoso-proxy-mapping-batch*.json
```

Para a topologia de três máquinas, a forma mais simples e confiável é ingerir o
mesmo dataset completo nas máquinas B e C. O webapp então usa B apenas para
`vendor*` e C apenas para `ratingsite*`; não é necessário implementar ingestão
parcial por tipo de fonte para a apresentação.

### Duas máquinas

- Máquina A: apresentação, `webapp` e motor de consulta.
- Máquina B: Virtuoso com os grafos FedShop.

Na máquina B, suba o Virtuoso e confirme que a porta `8890` está acessível pela
rede local:

```bash
cd trabalho-final-sistemas-distribuidos/fedshop-py
docker compose -f docker/virtuoso.yml up -d
curl "http://IP_DA_MAQUINA_B:8890/sparql?query=ASK%20%7B%3Fs%20%3Fp%20%3Fo%7D"
```

Na máquina A, aponte o webapp para o Virtuoso remoto e desative o gerenciamento
local de Docker:

```bash
cd trabalho-final-sistemas-distribuidos/webapp
FEDSHOP_WEBAPP_MANAGE_INFRA=0 \
FEDSHOP_VIRTUOSO_ENDPOINT=http://IP_DA_MAQUINA_B:8890/sparql \
uv run uvicorn app:app --host 0.0.0.0 --port 8000
```

Abra `http://IP_DA_MAQUINA_A:8000/` no navegador da apresentação.

### Três máquinas

- Máquina A: apresentação, `webapp` e motor de consulta.
- Máquina B: Virtuoso que servirá os grafos `vendor*`.
- Máquina C: Virtuoso que servirá os grafos `ratingsite*`.

Com os dois Virtuoso acessíveis pela rede, rode o webapp assim:

```bash
cd trabalho-final-sistemas-distribuidos/webapp
FEDSHOP_WEBAPP_MANAGE_INFRA=0 \
FEDSHOP_VENDOR_ENDPOINT=http://IP_DA_MAQUINA_B:8890/sparql \
FEDSHOP_RATINGSITE_ENDPOINT=http://IP_DA_MAQUINA_C:8890/sparql \
uv run uvicorn app:app --host 0.0.0.0 --port 8000
```

Há um script por máquina em `trabalho-final-sistemas-distribuidos/scripts/` que
automatiza os passos acima (subir Virtuoso, ingerir os batches, e no caso da
máquina A checar os dois endpoints antes de subir o servidor):

```bash
# Máquina B (vendor*)
bash trabalho-final-sistemas-distribuidos/scripts/machine-vendor.sh

# Máquina C (ratingsite*)
bash trabalho-final-sistemas-distribuidos/scripts/machine-ratingsite.sh

# Máquina A (webapp)
bash trabalho-final-sistemas-distribuidos/scripts/machine-webapp.sh \
  --vendor-host IP_DA_MAQUINA_B \
  --ratingsite-host IP_DA_MAQUINA_C
```

Os scripts de B e C pressupõem que `fedshop-py/data/dataset/*.nq` já foi
sincronizado nessa máquina (copiado de onde os dados foram gerados) — eles
carregam o mesmo dataset completo nas duas, exatamente como descrito acima. O
script da máquina A pressupõe `benchmark/generation/` e
`data/virtuoso-proxy-mapping-batch*.json` já copiados e o frontend já
compilado; ele compila automaticamente se `webapp/frontend/dist` não existir.

O mapping gerado pelo webapp mantém o `default-graph-uri` correto em cada
requisição. Assim, `vendor0`, `vendor1`, ... usam a máquina B, enquanto
`ratingsite0`, `ratingsite1`, ... usam a máquina C.

### Variáveis de execução

| Variável | Uso |
| --- | --- |
| `FEDSHOP_WEBAPP_MANAGE_INFRA=0` | Não tenta iniciar Docker/Virtuoso/proxy localmente no startup. |
| `FEDSHOP_VIRTUOSO_ENDPOINT` | Endpoint SPARQL único para todos os grafos. |
| `FEDSHOP_VENDOR_ENDPOINT` | Endpoint SPARQL para grafos `vendor*`; tem precedência sobre `FEDSHOP_VIRTUOSO_ENDPOINT`. |
| `FEDSHOP_RATINGSITE_ENDPOINT` | Endpoint SPARQL para grafos `ratingsite*`; tem precedência sobre `FEDSHOP_VIRTUOSO_ENDPOINT`. |
| `FEDSHOP_GO_BINARY` | Caminho do binário `fedshop-go`, se quiser mostrar o motor Go. |

Para voltar ao modo local, pare o servidor e rode sem essas variáveis:

```bash
uv run uvicorn app:app --port 8000
```

## Arquitetura: executar → gravar → reproduzir

1. **Trace**: a consulta roda de verdade e cada operação vira um evento JSON com
   timestamps reais e payloads integrais (o SPARQL de cada ASK/SELECT, tamanhos e
   amostras de bindings dos joins, filtros, pós-processamento).
   - `tracer.py` — pyfedx instrumentado (importa `pyfedx_engine` de `../pyfedx/`).
     Joins em hash + ordenação por conectividade (mesmas respostas, sem explosão);
     teto de 500 mil bindings intermediários e orçamento total de tempo.
   - `go_engine.py` — chama `fedshop-go query --trace` e normaliza os ids de
     endpoint; o schema de eventos é o mesmo.
2. **`app.py`** (FastAPI): `POST /api/execute {query, config_id, engine}` → trace
   JSON completo. Serve também o build do frontend (`frontend/dist`).
3. **Frontend** (`frontend/`, React + Vite + shadcn/ui): `compile()` transforma o
   trace numa timeline lógica e o player a reproduz num relógio virtual — a
   partícula de resposta só parte quando a de requisição chega ao endpoint (ordem
   causal por construção). Controles: play/pausa (espaço), velocidade 0.25×–8×,
   passo a passo (←/→) e scrub na timeline.

## O que a interface mostra

- **Grafo**: CLIENTE → MOTOR central → endpoints em círculo (vendors azuis,
  ratingsites verdes); partículas ASK (amarelas) e SELECT (magenta) com o número
  de linhas na volta.
- **Visão geral**: o SPARQL integral da requisição em voo, a matriz de seleção de
  fontes (tripla × endpoint) preenchendo em tempo real e as métricas acumuladas.
- **Joins**: as tuplas reais dentro do motor em cada instante — a tabela cresce ou
  encolhe a cada passo (semear, join ⋈, UNION, OPTIONAL, FILTER, DISTINCT/LIMIT),
  com amostras esquerda/direita, variáveis compartilhadas e o delta de linhas.
  Clicar num passo leva a animação até ele.
- **Log**: narrativa de tudo que o motor fez, com os tempos reais.
- **Resultados**: a tabela final entregue ao cliente + nº de requisições HTTP e
  tempo total.

## Observação sobre os dados

As queries instanciadas em `fedshop-py/benchmark/generation/` foram geradas a partir de
outra instância do dataset: algumas referenciam constantes (ex.: `Product6346` na q05)
que não existem nos grafos carregados e retornam 0 linhas. Com os dados atuais,
**q06, q09, q11 e q12 retornam resultados** — boas para demonstração.
