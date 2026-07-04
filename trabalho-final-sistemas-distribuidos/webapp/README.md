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
