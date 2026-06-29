#import "@preview/codly:1.3.0": *
#import "@preview/mannot:0.3.1": markrect, annot, mark, markul
#import "@preview/touying:0.6.1": *
#import themes.university: *
#import "@preview/cetz:0.3.1"
#import "@preview/numbly:0.1.0": numbly

/* ******************** CONFIGURAÇÕES ******************** */

#set text(lang: "pt")
#set math.equation(numbering: "(1)")
#show figure.caption: set text(size: 17pt)

#let cetz-canvas = touying-reducer.with(reduce: cetz.canvas, cover: cetz.draw.hide.with(bounds: true))

#show: university-theme.with(
  aspect-ratio: "16-9",
  config-info(
    title: [Web Semântica],
    subtitle: [Experimentação / Resultados / Desempenho / Ablação / Conclusão],
    author: [Pedro Saito],
    date: datetime.today(),
    institution: [
      Universidade Federal do Rio de Janeiro
    ],
  ),
  config-page(
    header: place(
      bottom + right,
      dx: -26.6cm,
      dy: 14.0cm,
      image("images/ufrj-logo.png", width: 78pt, height: 72pt)
    )
  )
)

#set heading(numbering: numbly("{1}.", default: "1.1"))
#show: codly-init.with()
#codly(zebra-fill: none, number-format: none)

#let ok   = text(fill: rgb("#15803d"), weight: "bold", [✓])
#let fail = text(fill: rgb("#b91c1c"), weight: "bold", [T/O])
#let med  = text(fill: rgb("#b45309"), weight: "bold", [~])

#let soft-blue   = rgb("#dbeafe")
#let soft-green  = rgb("#dcfce7")
#let soft-orange = rgb("#ffedd5")
#let soft-red    = rgb("#fee2e2")
#let soft-gray   = rgb("#f8fafc")
#let soft-yellow = rgb("#fef9c3")

#let cell-time(v, t) = {
  if v < 2.0       { table.cell(fill: soft-green)[#t] }
  else if v < 15.0 { table.cell(fill: soft-yellow)[#t] }
  else if v < 60.0 { table.cell(fill: soft-orange)[#t] }
  else             { table.cell(fill: soft-red)[#t] }
}

#let cell-to = table.cell(fill: soft-red)[*T/O*]
#let cell-na = table.cell(fill: soft-gray)[—]

#title-slide()

#set text(size: 20pt)

/* ******************** SLIDES ******************** */

= Experimentação

== Configuração Experimental

#v(.2em)

#grid(
  columns: (1fr, 1.4fr),
  column-gutter: 24pt,
  [
    #text(size: 24pt)[*FedShop*]
    #v(.2em)

    Benchmark para medir a escalabilidade de engines SPARQL federadas @Dang2023FedShop.

    #v(.35em)

    Cada execução fixa uma combinação:

    #v(.2em)

    *engine* $times$ *consulta* $times$ *instância* $times$ *batch*

    #v(.45em)

    O objetivo é isolar o impacto do tamanho da federação e da estratégia da engine.
  ],
  [
    #align(center)[
      #table(
        columns: (.9fr, 1.3fr),
        inset: 8pt,
        align: (left, left),
        fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
        stroke: none,
        [*Eixo*], [*Configuração*],
        table.hline(stroke: 1.2pt),
        [Consultas],  [12 templates (`q01`–`q12`)],
        [Instâncias], [10 valores por template],
        [Escala],     [2 batches: 20 e 40 endpoints],
        [Fontes],     [vendedores + sites de avaliação],
        [Engines],    [6 engines avaliados],
        [Artefatos],  [`results.csv`, `stats.csv`, `provenance.csv`],
      )
    ]
  ],
)

== Engines Avaliados

#v(.1em)

#align(center)[
  #table(
    columns: (1.1fr, 1.3fr, 1.0fr, 1.0fr),
    inset: 8pt,
    align: (left, left, center, center),
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    stroke: none,
    [*Engine*], [*Estratégia principal*], [*Linguagem*], [*Execuções*],
    table.hline(stroke: 1.5pt),
    [FedShop-Go],  [ASK + cache + bound join],      [Go],     [68],
    [FedX],        [ASK exclusivo + bound join],     [Java],   [69],
    [RSA],         [SERVICE pré-atribuído (baseline)], [Go], [49],
    [SPLENDID],    [VoID + estimativa de cardinalidade], [Java], [54],
    [SemaGrow],    [Metadados de endpoint],          [Java],   [49],
    [PyFedX],      [Protótipo Python (pyfedx)],      [Python], [49],
  )
]

== Métricas Avaliadas

#v(.35em)

#align(center)[
  #table(
    columns: (1.0fr, 1.3fr, 1.6fr),
    inset: 9pt,
    align: (left, left, left),
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    stroke: none,
    [*Dimensão*], [*Métricas*], [*Pergunta respondida*],
    table.hline(stroke: 1.5pt),
    [Correção],  [`nb_results`, `mismatch`],                     [A resposta equivale à referência?],
    [Tempo],     [`exec_time`, `source_selection_time`, `planning_time`], [Onde o tempo é consumido?],
    [Rede],      [`ask`, `http_req`, `data_transfer`],           [Quanto custa consultar a federação?],
    [Seleção],   [`tpwss`, `nb_distinct_sources`, `relevant_sources_selectivity`], [Fontes irrelevantes selecionadas?],
    [Robustez],  [`is_timeout`, `is_error`],                     [O plano é estável sob carga?],
  )
]

= Resultados

== Tempo de Execução

#v(.1em)

#align(center)[
  #table(
    columns: (1.0fr, .85fr, .85fr, .7fr),
    inset: 8pt,
    align: (left, center, center, center),
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    stroke: none,
    [*Engine*], [*Tempo Médio (s)*], [*Execuções OK*], [*Ranking*],
    table.hline(stroke: 1.5pt),
    [RSA],        [3,46], [49 / 49], [#text(fill: rgb("#15803d"))[*1º*]],
    [FedShop-Go], [7,19], [43 / 68], [#text(fill: rgb("#1d4ed8"))[*2º*]],
    [FedX],       [9,23], [69 / 69], [*3º*],
    [PyFedX],     [10,57],[26 / 49], [*4º*],
    [SPLENDID],   [19,22],[54 / 54], [*5º*],
    [SemaGrow],   [85,53],[49 / 49], [*6º*],
  )
]

#v(.4em)

#align(center)[
  #block(width: 90%, fill: soft-yellow, stroke: 1.5pt + rgb("#ca8a04"), radius: 5pt, inset: 11pt)[
    RSA é a baseline mais rápida por usar `SERVICE` pré-atribuído — sem seleção de fontes. #linebreak()
    FedShop-Go é competitivo, mas acumula 25 timeouts em consultas com muitos intermediários.
  ]
]

== Taxa de Sucesso e Confiabilidade

#v(.3em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 16pt,
  [
    #block(fill: soft-green, radius: 6pt, inset: 16pt)[
      #align(center)[
        #text(size: 34pt, weight: "bold", fill: rgb("#166534"))[100%]
        #linebreak()
        *FedX · RSA · SPLENDID · SemaGrow*
      ]
      #v(.2em)
      Nenhum timeout. Todos completaram todas as execuções previstas.
    ]
  ],
  [
    #block(fill: soft-orange, radius: 6pt, inset: 16pt)[
      #align(center)[
        #text(size: 34pt, weight: "bold", fill: rgb("#9a3412"))[63,2%]
        #linebreak()
        *FedShop-Go*
      ]
      #v(.2em)
      25 timeouts em q02, q04 e q05 — consultas com grande volume de resultados intermediários.
    ]
  ],
  [
    #block(fill: soft-red, radius: 6pt, inset: 16pt)[
      #align(center)[
        #text(size: 34pt, weight: "bold", fill: rgb("#b91c1c"))[53,1%]
        #linebreak()
        *PyFedX*
      ]
      #v(.2em)
      Timeouts em consultas com múltiplas fontes — protótipo sem otimizações de execução.
    ]
  ],
)

== Desempenho por Consulta

#v(.0em)

#text(size: 13.5pt)[
#align(center)[
  #table(
    columns: (auto, auto, auto, auto, auto, auto, auto),
    inset: 6pt,
    align: center,
    stroke: none,
    fill: (x, y) => {
      if y == 0 { soft-blue }
      else { white }
    },
    [*Consulta*], [*FedShop-Go*], [*FedX*], [*RSA*], [*SPLENDID*], [*SemaGrow*], [*PyFedX*],
    table.hline(stroke: 1.5pt),
    [q01], cell-time(5.62,"5,62"), table.cell(fill: soft-red)[120,07], cell-time(6.78,"6,78"), cell-time(10.17,"10,17"), table.cell(fill: soft-red)[93,23], cell-to,
    [q02], cell-to, cell-time(1.02,"1,02"), table.cell(fill: soft-orange)[22,09], table.cell(fill: soft-red)[120,69], table.cell(fill: soft-red)[92,48], cell-to,
    [q03], cell-time(5.03,"5,03"), cell-time(1.59,"1,59"), cell-time(2.36,"2,36"), table.cell(fill: soft-orange)[14,33], cell-time(1.72,"1,72"), cell-to,
    [q04], table.cell(fill: soft-red)[61,48], table.cell(fill: soft-orange)[30,95], cell-time(2.38,"2,38"), table.cell(fill: soft-orange)[29,21], table.cell(fill: soft-red)[82,94], cell-to,
    [q05], cell-to, cell-time(1.09,"1,09"), cell-time(1.83,"1,83"), table.cell(fill: soft-red)[97,29], table.cell(fill: soft-red)[120,04], cell-to,
    [q06], cell-time(0.47,"0,47"), cell-time(2.25,"2,25"), cell-time(3.47,"3,47"), table.cell(fill: soft-orange)[13,48], table.cell(fill: soft-red)[66,60], table.cell(fill: soft-red)[84,75],
    [q07], cell-time(0.68,"0,68"), cell-time(0.84,"0,84"), cell-time(2.15,"2,15"), table.cell(fill: soft-red)[167,18], table.cell(fill: soft-red)[120,07], cell-time(7.37,"7,37"),
    [q08], cell-time(0.17,"0,17"), cell-time(0.90,"0,90"), cell-time(1.89,"1,89"), cell-time(2.58,"2,58"), table.cell(fill: soft-red)[120,12], cell-time(0.69,"0,69"),
    [q09], cell-time(0.02,"0,02"), cell-time(1.40,"1,40"), cell-time(1.82,"1,82"), cell-time(0.59,"0,59"), table.cell(fill: soft-orange)[63,64], cell-time(0.05,"0,05"),
    [q10], cell-time(0.50,"0,50"), cell-time(0.79,"0,79"), cell-time(1.63,"1,63"), cell-time(3.31,"3,31"), table.cell(fill: soft-orange)[70,63], cell-time(0.31,"0,31"),
    [q11], cell-time(0.14,"0,14"), cell-time(1.39,"1,39"), cell-time(1.76,"1,76"), cell-time(1.28,"1,28"), table.cell(fill: soft-red)[92,62], cell-time(0.10,"0,10"),
    [q12], cell-time(0.73,"0,73"), cell-time(0.70,"0,70"), cell-time(1.89,"1,89"), table.cell(fill: soft-orange)[10,95], table.cell(fill: soft-red)[120,06], cell-time(8.80,"8,80"),
  )
]
]

#v(.2em)

#align(center)[
  #text(size: 15pt)[
    #box(fill: soft-green, inset: 5pt, radius: 3pt)[< 2s] rápido #h(10pt)
    #box(fill: soft-yellow, inset: 5pt, radius: 3pt)[2–15s] médio #h(10pt)
    #box(fill: soft-orange, inset: 5pt, radius: 3pt)[15–60s] lento #h(10pt)
    #box(fill: soft-red, inset: 5pt, radius: 3pt)[> 60s / T/O] crítico
  ]
]

== Uso de Rede

#v(.3em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 24pt,
  [
    #text(size: 22pt)[*FedShop-Go* (batch 0, runs OK)]

    #v(.2em)

    #table(
      columns: (1.1fr, .9fr),
      inset: 8pt,
      align: (left, right),
      fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
      stroke: none,
      [*Métrica*], [*Média*],
      table.hline(stroke: 1.2pt),
      [ASK probes],      [166 por execução],
      [HTTP requests],   [366 por execução],
      [Transferência],   [7,4 MB por execução],
      [Fontes distintas],[20 endpoints],
    )

    #v(.3em)

    #block(fill: soft-orange, radius: 5pt, inset: 10pt)[
      ASK probes verificam cada triple pattern em cada endpoint — custo linear no número de padrões × endpoints.
    ]
  ],
  [
    #text(size: 22pt)[*Seleção de Fontes*]

    #v(.2em)

    #align(center)[
      #table(
        columns: (1.1fr, .9fr),
        inset: 8pt,
        align: (left, right),
        fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
        stroke: none,
        [*Componente*], [*Valor*],
        table.hline(stroke: 1.2pt),
        [`source_selection_time`], [0,30s avg],
        [Fração do `exec_time`],   [4,2%],
        [`planning_time`],         [< 0,001ms],
        [`tpwss`],                 [166 (= \# ASK)],
        [`relevant_sources_sel.`], [100% (batch 0)],
      )
    ]

    #v(.3em)

    #block(fill: soft-green, radius: 5pt, inset: 10pt)[
      Seleção de fontes consome apenas *4,2%* do tempo total — o gargalo está na execução dos joins.
    ]
  ],
)

= Desempenho

== Breakdown de Tempo

#v(.3em)

#align(center)[
  #table(
    columns: (1.1fr, .8fr, .8fr, .8fr, .8fr),
    inset: 9pt,
    align: (left, center, center, center, center),
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    stroke: none,
    [*Componente*], [*Tempo Médio*], [*% Total*], [*Min*], [*Max*],
    table.hline(stroke: 1.5pt),
    [Seleção de Fontes (`source_selection_time`)], [0,30s],  [4,2%],  [0,01s], [1,2s],
    [Planejamento (`planning_time`)],              [< 0,001ms], [≈ 0%], [0s],   [0,001s],
    [Execução + Joins (residual)],                 [6,89s],  [95,8%], [0,02s], [120s],
    [*Total (`exec_time`)*],                       [*7,19s*],[*100%*],[*0,02s*],[*120s*],
  )
]

#v(.5em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 22pt,
  [
    #block(fill: soft-yellow, radius: 5pt, inset: 12pt)[
      *Achado:* a seleção de fontes via ASK é rápida. O custo dominante é o processamento de joins e o volume de dados trocado com os endpoints.
    ]
  ],
  [
    #block(fill: soft-blue, radius: 5pt, inset: 12pt)[
      *Implicação:* otimizações de join (bound join, reordenação de triple patterns) têm maior potencial de ganho do que acelerar os probes ASK.
    ]
  ],
)

== Escalabilidade

#v(.2em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 24pt,
  [
    #align(center)[
      #table(
        columns: (1.0fr, .9fr, .9fr),
        inset: 9pt,
        align: (left, center, center),
        fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
        stroke: none,
        [*Batch*], [*Endpoints*], [*Tempo Médio*],
        table.hline(stroke: 1.5pt),
        [batch\_0], [20],  [4,68s],
        [batch\_1], [40],  [9,59s],
        [Razão],    [×2], [*×2,05*],
      )
    ]

    #v(.3em)

    #align(center)[
      #table(
        columns: (1.0fr, .9fr, .9fr),
        inset: 9pt,
        align: (left, center, center),
        fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
        stroke: none,
        [*Batch*], [*Endpoints*], [*Taxa de Sucesso*],
        table.hline(stroke: 1.5pt),
        [batch\_0], [20], [66% (21/32)],
        [batch\_1], [40], [61% (22/36)],
      )
    ]
  ],
  [
    #v(.5em)

    #block(fill: soft-orange, radius: 6pt, inset: 16pt)[
      *Comportamento observado:*

      O tempo de execução dobra ao dobrar o número de endpoints — escalabilidade *linear* com a federação.

      #v(.4em)

      A taxa de sucesso cai levemente (66% → 61%), sugerindo que consultas na fronteira do timeout tornam-se falhas com mais endpoints.
    ]

    #v(.4em)

    #block(fill: soft-yellow, radius: 5pt, inset: 10pt)[
      *Contexto:* apenas batches 0 e 1 foram avaliados neste trabalho. A escala completa (até 200 endpoints) é trabalho futuro.
    ]
  ],
)

= Estudo de Ablação

== 5 Variantes

#v(.2em)

#align(center)[
  #table(
    columns: (1.5fr, .55fr, .55fr, .55fr, .55fr),
    inset: 9pt,
    align: (left, center, center, center, center),
    stroke: none,
    fill: (x, y) => if y == 0 { soft-blue } else if calc.odd(y) { soft-gray },
    [*Variante*], [*ASK*], [*Cache*], [*Bound Join*], [*Metadados*],
    table.hline(stroke: 1.5pt),
    [Baseline (broadcast)],  [—],  [—], [—], [—],
    [Seleção dinâmica],      [✓],  [—], [—], [—],
    [Seleção reutilizada],   [✓], [✓], [—], [—],
    [Execução vinculada],    [✓], [✓], [✓], [—],
    [Plano completo],        [✓], [✓], [✓], [✓],
  )
]

#v(.3em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 22pt,
  [
    *Controle experimental*

    Mesma consulta, instância, batch, tentativa e infraestrutura para todas as variantes.
  ],
  [
    *Efeito esperado por componente*

    - *ASK*: eliminar fontes irrelevantes (-HTTP, -tempo)
    - *Cache*: reutilizar seleção em instâncias similares
    - *Bound Join*: reduzir resultados intermediários
    - *Metadados*: reordenar triple patterns por cardinalidade
  ],
)

== Impacto por Variante

#v(.1em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 14pt,
  [
    #block(fill: soft-blue, radius: 6pt, inset: 14pt)[
      #align(center)[#text(weight: "bold")[Seleção Dinâmica (ASK)]]
      #v(.2em)
      Reduz fontes irrelevantes — essencial para q06–q12 onde apenas 2–4 endpoints têm dados relevantes.
      #v(.3em)
      *Efeito:* menos HTTP requests e joins desnecessários.
    ]
  ],
  [
    #block(fill: soft-green, radius: 6pt, inset: 14pt)[
      #align(center)[#text(weight: "bold")[Seleção Reutilizada (Cache)]]
      #v(.2em)
      Ao reaproveitar o mapeamento ASK entre instâncias similares, elimina 166 probes adicionais por consulta.
      #v(.3em)
      *Efeito:* reduz `source_selection_time` em consultas repetidas.
    ]
  ],
  [
    #block(fill: soft-orange, radius: 6pt, inset: 14pt)[
      #align(center)[#text(weight: "bold")[Bound Join + Metadados]]
      #v(.2em)
      Bound join envia bindings parciais ao endpoint, reduzindo resultados intermediários. Metadados reordenam padrões.
      #v(.3em)
      *Efeito:* crítico para q02/q05 (ainda sem resolução).
    ]
  ],
)

#v(.4em)

#align(center)[
  #block(width: 90%, fill: soft-gray, stroke: 1.5pt + rgb("#64748b"), radius: 5pt, inset: 10pt)[
    A variante *Plano Completo* é o FedShop-Go avaliado neste trabalho. #linebreak()
    O estudo de ablação completo (rodando cada variante no FedShop) é trabalho futuro.
  ]
]

= Conclusão e Trabalhos Futuros

== Principais Achados

#v(.1em)

#align(center)[
  #block(
    width: auto,
    stroke: 2.9pt + soft-green,
    inset: 14pt,
    radius: 6pt,
    [
      *Achado 1 — Queries seletivas:* FedShop-Go supera FedX em q06–q11. #linebreak()
      Em q09, 0,02s vs 1,40s do FedX — *70× mais rápido* em consultas de domínio único com fontes concentradas.
    ]
  )
]

#v(.25em)

#align(center)[
  #block(
    width: auto,
    stroke: 2.9pt + soft-orange,
    inset: 14pt,
    radius: 6pt,
    [
      *Achado 2 — Gargalo de joins:* 95,8% do tempo é gasto em execução e joins. #linebreak()
      A seleção de fontes (ASK) consome apenas 4,2% — o custo está em processar os resultados intermediários.
    ]
  )
]

#v(.25em)

#align(center)[
  #block(
    width: auto,
    stroke: 2.9pt + soft-red,
    inset: 14pt,
    radius: 6pt,
    [
      *Achado 3 — Escalabilidade linear:* dobrar os endpoints (batch 0→1) dobra o tempo de execução. #linebreak()
      Consultas q02 e q05 geram timeout independente do batch — problema estrutural de cardinalidade.
    ]
  )
]

== Limitações e Próximos Passos

#v(.2em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 24pt,
  [
    #text(size: 22pt)[*Limitações atuais*]

    #v(.2em)

    #table(
      columns: (auto, 1fr),
      inset: 7pt,
      stroke: none,
      fill: (x, y) => if calc.odd(y) { soft-gray },
      [#text(fill: rgb("#b91c1c"))[✗]], [q02 e q05: timeout estrutural (cardinalidade)],
      [#text(fill: rgb("#b91c1c"))[✗]], [63,2% taxa de sucesso (25 timeouts)],
      [#text(fill: rgb("#b45309"))[~]], [Somente batches 0 e 1 avaliados],
      [#text(fill: rgb("#b45309"))[~]], [Ablação completa não executada no FedShop],
      [#text(fill: rgb("#b45309"))[~]], [Sem métrica de correção (mismatch pendente)],
    )
  ],
  [
    #text(size: 22pt)[*Próximos passos*]

    #v(.2em)

    1. *Filter pushdown* — empurrar filtros para o endpoint antes de materializar resultados.

    2. *Planner baseado em custo* — reordenar triple patterns por cardinalidade estimada (CostFed @Saleem2018CostFed).

    3. *Resolver q02 / q05* — limitar intermediários com execução paginada.

    4. *Escala completa* — executar batches 2–9 (até 200 endpoints).

    5. *Ablação no FedShop* — comparar as 5 variantes com dados reais.
  ],
)

==

#text(size: 13pt)[
  #bibliography(
    "referencias.bib",
    title: "Referências",
    full: true,
    style: "american-chemical-society",
  )
]
