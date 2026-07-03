# Visualizador do motor de consultas federado (pyfedx)

Aplicação web que **executa uma consulta SPARQL federada de verdade** (via o motor
`scripts/pyfedx.py`) contra os endpoints do FedShop no Virtuoso e reproduz a execução
como uma animação fiel e controlável.

## Como rodar

Pré-requisito: Virtuoso de pé em `localhost:8890` com os grafos do batch
(`http://www.vendor0.fr/` … `http://www.ratingsite9.fr/`):

```bash
cd webapp
uv run uvicorn app:app --port 8000
# abrir http://localhost:8000/
```

## Arquitetura: executar → gravar → reproduzir

1. **`tracer.py`** roda a consulta com o pyfedx instrumentado e grava um *trace*
   completo: cada ASK/SELECT com o texto SPARQL integral, timestamps reais, resultados,
   joins (tamanhos e variáveis compartilhadas), filtros e pós-processamento.
   - A ordem de junção usa conectividade de variáveis (evita produto cartesiano) e os
     joins são hash joins — mesmas respostas do pyfedx original, sem explosão de tempo.
   - Proteções: teto de 500 mil bindings intermediários e orçamento total de tempo;
     ao estourar, o trace parcial é devolvido com um evento `error`.
2. **`app.py`** (FastAPI): `POST /api/execute {query, config_id}` → trace JSON.
3. **`static/app.js`** compila o trace numa timeline lógica e a reproduz num relógio
   virtual: a partícula de resposta só parte quando a de requisição chega ao endpoint
   (ordem causal por construção). Controles: play/pausa (espaço), velocidade 0.25×–8×,
   passo a passo (←/→) e scrub na timeline.

## O que a animação mostra

- **Fase 1 — seleção de fontes**: partículas ASK (amarelas) do motor para cada
  endpoint; respostas verdes (tem dados) ou cinzas (não tem); matriz tripla × endpoint
  preenchendo em tempo real.
- **Fase 2 — execução**: SELECTs (magenta) apenas para as fontes selecionadas, com o
  número de linhas na partícula de volta; joins/filtros/UNION/OPTIONAL no nó do motor
  com contagens de bindings no log.
- **Resposta**: partícula verde motor → cliente + tabela com as linhas finais.
- Painel "Operação atual" exibe o SPARQL integral da requisição em voo, com a duração
  real em ms.

## Observação sobre os dados

As queries instanciadas em `fedshop-py/benchmark/generation/` foram geradas a partir de
outra instância do dataset: algumas referenciam constantes (ex.: `Product6346` na q05)
que não existem nos grafos carregados e retornam 0 linhas. Com os dados atuais,
**q06, q09, q11 e q12 retornam resultados** — boas para demonstração.
