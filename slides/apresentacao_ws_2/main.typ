#import "@preview/codly:1.3.0": *
#import "@preview/touying:0.6.1": *
#import themes.university: *
#import "@preview/cetz:0.3.1"
#import "@preview/numbly:0.1.0": numbly
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge

/* ******************** CONFIGURACOES ******************** */

#set text(lang: "pt")
#set math.equation(numbering: "(1)")
#show figure.caption: set text(size: 17pt)

#let cetz-canvas = touying-reducer.with(
  reduce: cetz.canvas,
  cover: cetz.draw.hide.with(bounds: true),
)

#show: university-theme.with(
  aspect-ratio: "16-9",
  config-info(
    title: [Web Semântica],
    subtitle: [Proposta / Implementação / Avaliação Preliminar],
    author: [Pedro Saito],
    date: datetime.today(),
    institution: [Universidade Federal do Rio de Janeiro],
  ),
  config-page(
    header: place(
      bottom + right,
      dx: -26.6cm,
      dy: 14.0cm,
      image("../apresentacao_ws_1/images/ufrj-logo.png", width: 78pt, height: 72pt),
    ),
  ),
)

#set heading(numbering: numbly("{1}.", default: "1.1"))
#show: codly-init.with()
#codly(zebra-fill: none, number-format: none)

#let ok = text(fill: rgb("#15803d"), weight: "bold", [CONCLUÍDO])
#let wip = text(fill: rgb("#b45309"), weight: "bold", [EM DESENVOLVIMENTO])
#let next = text(fill: rgb("#1d4ed8"), weight: "bold", [PRÓXIMO])
#let soft-blue = rgb("#dbeafe")
#let soft-green = rgb("#dcfce7")
#let soft-orange = rgb("#ffedd5")
#let soft-gray = rgb("#f8fafc")

#title-slide()

// Corpo ligeiramente mais compacto para manter cada tópico em um único slide.
#set text(size: 20pt)

/* ******************** SLIDES ******************** */

= Proposta

== Objetivo

#v(-.1em)

#align(center)[
  #text(size: 28pt, style: "italic")[
    Construir uma engine mínima para consultas federadas em SPARQL,
  ]
  #v(-.5em)
  #text(size: 25pt, style: "italic")[
    mensurável pelo FedShop e implementada em Go.
  ]
]

#v(.5em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 16pt,
  [
    #block(fill: soft-green, inset: 13pt, radius: 5pt)[
      *Benchmark* #linebreak()
      #v(3pt)
      Reimplementar o pipeline do FedShop em Python, removendo a dependência central do Snakemake.
      #v(8pt)
      #ok
    ]
  ],
  [
    #block(fill: soft-orange, inset: 13pt, radius: 5pt)[
      *Protótipo* #linebreak()
      #v(3pt)
      Validar parser, seleção de fontes, execução remota e artefatos antes da implementação definitiva.
      #v(8pt)
      #ok
    ]
  ],
  [
    #block(fill: soft-blue, inset: 13pt, radius: 5pt)[
      *Engine em Go* #linebreak()
      #v(3pt)
      Consolidar as estratégias do WS1 em uma arquitetura pequena, testável e integrada ao benchmark.
      #v(8pt)
      #wip
    ]
  ],
)

== Ambiente Experimental

#v(.2em)

#grid(
  columns: (1fr, 1.45fr),
  column-gutter: 24pt,
  [
    #text(size: 24pt)[*FedShop*]
    #v(.2em)

    Benchmark para medir escalabilidade de engines SPARQL federadas.

    #v(.35em)

    Cada execução fixa uma combinação:

    #v(.2em)

    *engine* $times$ *consulta* $times$ *instância* $times$ *batch* $times$ *tentativa*

    #v(.45em)

    O objetivo é isolar o impacto do tamanho da federação e da estratégia da engine.
  ],
  [
    #align(center)[
      #table(
        columns: (.85fr, 1.25fr),
        inset: 8pt,
        align: (left, left),
        fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
        stroke: none,
        [*Eixo*], [*Variações consideradas*],
        table.hline(stroke: 1.2pt),
        [Consultas], [12 templates (`q01`–`q12`)],
        [Instâncias], [10 valores concretos por template],
        [Escala], [10 batches: 20, 40, ..., 200 membros],
        [Fontes], [vendedores + sites de avaliação],
        [Tentativas], [repetições controladas por combinação],
        [Engines], [FedX, CostFed, FedUP/RSA, protótipos],
      )
    ]
    #v(.35em)
    #align(center)[
      #block(stroke: 1.5pt + rgb("#64748b"), radius: 5pt, inset: 10pt)[
        Métricas: *tempo*, *HTTP*, *transferência*, *fontes selecionadas* e *timeout*.
      ]
    ]
  ],
)

= Implementação

== `fedshop-py`: Pipeline Reprodutível

#v(.2em)

#figure(
  scale(86%)[
    #diagram(
      spacing: 12mm,
      edge-stroke: 1.2pt,
      node((0, 0), [*1. Gerar*#linebreak()WatDiv / N-Quads], name: <generate>, width: 39mm, height: 18mm, fill: soft-blue, radius: 3pt),
      node((1, 0), [*2. Ingerir*#linebreak()Virtuoso], name: <ingest>, width: 34mm, height: 18mm, fill: soft-blue, radius: 3pt),
      node((2, 0), [*3. Instanciar*#linebreak()consultas], name: <query>, width: 38mm, height: 18mm, fill: soft-blue, radius: 3pt),
      node((3, 0), [*4. Avaliar*#linebreak()engines], name: <evaluate>, width: 35mm, height: 18mm, fill: soft-orange, radius: 3pt),
      node((4, 0), [*5. Medir*#linebreak()resultados], name: <metrics>, width: 35mm, height: 18mm, fill: soft-green, radius: 3pt),
      edge(<generate>, <ingest>, "->"),
      edge(<ingest>, <query>, "->"),
      edge(<query>, <evaluate>, "->"),
      edge(<evaluate>, <metrics>, "->"),
    )
  ],
  caption: [_Fluxo reimplementado como pacote e CLI Python._],
)

#v(-.15em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 24pt,
  [
    *Mudanças principais*

    - configuração YAML tipada;
    - manipulação SPARQL com `rdflib`;
    - execução via adapters;
    - métricas agregadas com `pandas`.
  ],
  [
    *Artefatos preservados*

    - `results.csv` e `provenance.csv`;
    - `source_selection.txt`;
    - `query_plan.txt`;
    - tempos, requisições e transferência.
  ],
)

== `pyfedx`: Protótipo de Validação

#v(.1em)

#grid(
  columns: (1fr, 1.08fr),
  column-gutter: 24pt,
  [
    #block(fill: soft-orange, radius: 5pt, inset: 14pt)[
      *Papel do protótipo*

      Reduzir incertezas antes da engine em Go: exercitar o caminho completo entre uma consulta SPARQL e os endpoints remotos.
    ]

    #v(.4em)

    *Escopo implementado*

    - BGPs, `FILTER`, `OPTIONAL` e `UNION`;
    - `ORDER BY`, `LIMIT` e `DISTINCT`;
    - seleção por `ASK` com cache;
    - joins de bindings compatíveis;
    - execução HTTP e saída FedShop.
  ],
  [
    #text(size: 17.5pt)[
```text
parse(query)
      ↓
select_sources(ASK + cache)
      ↓
execute(SERVICE requests)
      ↓
join + filter + project
      ↓
results / sources / stats / plan
```
    ]
    #v(.35em)
    #align(center)[
      #text(size: 19pt, fill: rgb("#9a3412"))[
        Protótipo de pesquisa — não é a engine final.
      ]
    ]
  ],
)

== Engine em Go

#v(.0em)

#figure(
  scale(78%)[
    #diagram(
      spacing: 13mm,
      edge-stroke: 1.2pt,
      node((0, 0), [Consulta#linebreak()*SPARQL*], name: <input>, width: 30mm, height: 17mm, radius: 3pt),
      node((1, 0), [Parser +#linebreak()*Álgebra*], name: <parser>, width: 32mm, height: 17mm, fill: soft-blue, radius: 3pt),
      node((2, 0), [Seleção de#linebreak()*fontes*], name: <selection>, width: 35mm, height: 17mm, fill: soft-orange, radius: 3pt),
      node((3, 0), [Plano de#linebreak()*execução*], name: <plan>, width: 35mm, height: 17mm, fill: soft-orange, radius: 3pt),
      node((4, 0), [Executor +#linebreak()*joins*], name: <executor>, width: 34mm, height: 17mm, fill: soft-blue, radius: 3pt),
      node((5, 0), [Resultados +#linebreak()*métricas*], name: <output>, width: 37mm, height: 17mm, fill: soft-green, radius: 3pt),
      node((2, 1), [`ASK` / resumo#linebreak()/ cache], name: <metadata>, width: 35mm, height: 15mm, fill: soft-gray, radius: 3pt),
      node((4, 1), [Endpoints#linebreak()*SPARQL*], name: <endpoints>, width: 34mm, height: 15mm, fill: soft-gray, radius: 3pt),
      edge(<input>, <parser>, "->"),
      edge(<parser>, <selection>, "->"),
      edge(<selection>, <plan>, "->"),
      edge(<plan>, <executor>, "->"),
      edge(<executor>, <output>, "->"),
      edge(<metadata>, <selection>, "->"),
      edge(<executor>, <endpoints>, "<->"),
    )
  ],
  caption: [_Arquitetura incremental da implementação definitiva._],
)

#v(-.2em)

#table(
  columns: (1.1fr, 1.55fr, .9fr),
  inset: 7pt,
  align: (left, left, center),
  stroke: none,
  fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
  [*Referência do WS1*], [*Incorporação planejada*], [*Estado*],
  table.hline(stroke: 1.2pt),
  [FedX], [`ASK`, cache, grupos exclusivos e bound joins], [#wip],
  [SPLENDID / CostFed], [resumos, cardinalidades e ordenação], [#next],
  [ANAPSID], [timeouts e continuidade sob falhas], [#next],
)

= Avaliação

== Métricas

#v(.35em)

#align(center)[
  #table(
    columns: (1.1fr, 1.4fr, 1.55fr),
    inset: 9pt,
    align: (left, left, left),
    stroke: none,
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    [*Dimensão*], [*Métricas*], [*Pergunta respondida*],
    table.hline(stroke: 1.5pt),
    [Correção], [`nb_results`, mismatch], [A resposta é equivalente à referência?],
    [Tempo], [`source_selection`, `planning`, `exec_time`], [Onde o tempo é consumido?],
    [Rede], [`ask`, `http_req`, `data_transfer`], [Quanto custa consultar a federação?],
    [Seleção], [`TPWSS`, `RWSS`, fontes distintas], [Quantas fontes irrelevantes foram escolhidas?],
    [Robustez], [`timeout`, erro de runtime], [O plano continua útil sob falhas?],
  )
]

== Estudo de Ablação

#v(.25em)

#align(center)[
  #table(
    columns: (1.4fr, .55fr, .55fr, .55fr, .55fr),
    inset: 9pt,
    align: center,
    stroke: none,
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    [*Variante*], [*ASK*], [*Cache*], [*Bound*], [*Metadados*],
    table.hline(stroke: 1.5pt),
    [Baseline], [—], [—], [—], [—],
    [Seleção dinâmica], [✓], [—], [—], [—],
    [Seleção reutilizada], [✓], [✓], [—], [—],
    [Execução vinculada], [✓], [✓], [✓], [—],
    [Plano completo], [✓], [✓], [✓], [✓],
  )
]

#v(.35em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 22pt,
  [
    *Controle experimental*

    Mesma consulta, instância, batch, tentativa e infraestrutura para todas as variantes.
  ],
  [
    *Efeito esperado*

    Comparar cada componente por tempo, requisições, transferência e precisão da seleção.
  ],
)

== Validação Atual

#v(.2em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 24pt,
  [
    #block(fill: soft-green, radius: 6pt, inset: 16pt)[
      #align(center)[
        #text(size: 45pt, weight: "bold", fill: rgb("#166534"))[69]
        #linebreak()
        *testes do `fedshop-py`*
      ]
      #v(.35em)
      Configuração, álgebra, geração, ingestão, avaliação, métricas e adapters.
    ]
  ],
  [
    #block(fill: soft-orange, radius: 6pt, inset: 16pt)[
      #align(center)[
        #text(size: 45pt, weight: "bold", fill: rgb("#9a3412"))[24]
        #linebreak()
        *testes internos do `pyfedx`*
      ]
      #v(.35em)
      Parser, filtros, joins, `OPTIONAL`, `UNION`, ordenação, seleção e execução simulada.
    ]
  ],
)

#v(.55em)

#align(center)[
  #block(width: 86%, stroke: 1.5pt + rgb("#64748b"), radius: 5pt, inset: 12pt)[
    Os testes validam comportamento e integração local. #linebreak()
    *Ainda não representam desempenho no workload completo do FedShop.*
  ]
]

== Resultado Preliminar

#v(.25em)

#align(center)[
  #block(width: 88%, fill: rgb("#fff7ed"), stroke: 1.5pt + rgb("#fb923c"), radius: 6pt, inset: 12pt)[
    #align(center)[*PLACEHOLDER — medições serão inseridas antes da apresentação*]
  ]
]

#v(.35em)

#align(center)[
  #table(
    columns: (1.1fr, .85fr, .85fr, .85fr, .85fr),
    inset: 9pt,
    align: center,
    stroke: none,
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    [*Engine*], [*Tempo*], [*HTTP*], [*TPWSS*], [*Status*],
    table.hline(stroke: 1.5pt),
    [FedX], [—], [—], [—], [pendente],
    [CostFed], [—], [—], [—], [pendente],
    [`pyfedx`], [—], [—], [—], [pendente],
    [Engine Go], [—], [—], [—], [em desenvolvimento],
  )
]

#v(.4em)

#align(center)[
  Resultados só serão comparados após validar equivalência com o conjunto de referência.
]

== Plano Experimental

#v(.2em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 16pt,
  [
    #block(fill: soft-green, radius: 5pt, inset: 13pt)[
      #align(center)[#text(size: 29pt, weight: "bold")[1]]
      #align(center)[*Smoke test*]
      #v(.2em)
      Configuração pequena, uma consulta e uma instância. Validar todo o caminho e os artefatos.
    ]
  ],
  [
    #block(fill: soft-orange, radius: 5pt, inset: 13pt)[
      #align(center)[#text(size: 29pt, weight: "bold")[2]]
      #align(center)[*Execução filtrada*]
      #v(.2em)
      Fixar engine, consulta, batch e tentativa. Comparar resultados e diagnosticar falhas.
    ]
  ],
  [
    #block(fill: soft-blue, radius: 5pt, inset: 13pt)[
      #align(center)[#text(size: 29pt, weight: "bold")[3]]
      #align(center)[*Workload completo*]
      #v(.2em)
      Executar 12 templates, 10 instâncias e até 200 membros, com repetição controlada.
    ]
  ],
)

#v(.55em)

#align(center)[
  #text(size: 23pt)[
    Correção $arrow.r$ estabilidade $arrow.r$ escala $arrow.r$ comparação
  ]
]

== Em Ação

#v(.2em)

#grid(
  columns: (1.15fr, 1fr),
  column-gutter: 20pt,
  [
    #text(size: 17pt)[
```bash
# Preparar os dados
fedshop generate products
fedshop generate sources
fedshop ingest batch 0

# Instanciar consultas e avaliar
fedshop query run-all --batch-id 0
fedshop evaluate run-all \
  --engine pyfedx --query q01
```
    ]
  ],
  [
    #text(size: 18pt)[*Saída por execução*]
    #v(.25em)

    #block(fill: soft-gray, radius: 4pt, inset: 12pt)[
      `results.csv` #linebreak()
      `provenance.csv` #linebreak()
      `source_selection.txt` #linebreak()
      `query_plan.txt` #linebreak()
      `stats.csv`
    ]
    #v(.35em)
    Os mesmos contratos serão implementados pelo adapter da engine em Go.
  ],
)

== Configurações e Próximos Passos

#v(.05em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 24pt,
  [
    #text(size: 22pt)[*Ambiente atual*]

    #table(
      columns: (.9fr, 1.4fr),
      inset: 7pt,
      stroke: none,
      fill: (x, y) => if calc.odd(y) { soft-gray },
      [Linguagem], [Python 3.12],
      [CLI], [`click` + `uv`],
      [SPARQL], [`rdflib` / SPARQLWrapper],
      [Dados], [WatDiv + Virtuoso],
      [Engine final], [Go],
    )
  ],
  [
    #text(size: 22pt)[*Sequência de entrega*]

    1. Completar o núcleo da engine em Go.
    2. Implementar seleção `ASK` e cache.
    3. Adicionar joins e execução `SERVICE`.
    4. Criar adapter compatível com `fedshop-py`.
    5. Rodar smoke, ablação e benchmark completo.
    6. Inserir resultados no slide preliminar.
  ],
)

#v(.4em)

#align(center)[
  #block(width: 88%, fill: soft-blue, radius: 5pt, inset: 11pt)[
    Próximo marco: uma consulta FedShop completa executada pela engine Go,
    com resultados, fontes, plano e métricas reproduzíveis.
  ]
]

==

#text(size: 12pt)[
  #bibliography(
    "../apresentacao_ws_1/referencias.bib",
    title: "Referências",
    full: true,
    style: "american-chemical-society",
  )
]
