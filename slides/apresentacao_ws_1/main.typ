#import "@preview/codly:1.3.0": *
#import "@preview/mannot:0.3.1": markrect, annot, mark, markul
#import "@preview/touying:0.6.1": *
#import themes.university: *
#import "@preview/cetz:0.3.1"
#import "@preview/numbly:0.1.0": numbly
#import "@preview/fletcher:0.5.8" as fletcher: diagram, node, edge


/* ******************** CONFIGURAÇÕES ******************** */

#set text(lang: "pt")
#set math.equation(numbering: "(1)")
#show figure.caption: set text(size: 18pt)

#let cetz-canvas = touying-reducer.with(reduce: cetz.canvas, cover: cetz.draw.hide.with(bounds: true))

// https://github.com/touying-typ/touying/blob/main/themes/university.typ

#show: university-theme.with(
  aspect-ratio: "16-9",
  config-info(
    title: [Web Semântica],
    subtitle: [Introdução / Fundamentação Teórica / #linebreak()Trabalhos Relacionados],
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

#let icon = text(size: 1pt, "\u{ebbe}")

#title-slide()

/* ******************** SLIDES ******************** */

/*

FALAS
-----

Ola boa tarde a todos, meu nome é Pedro Saito e meu trabalho trata da construcao
de um motor de consulta para ambientes distribuidos e consultas federadas em SPARQL

Relembrando o conceito de consulta federada em SPARQL: Consulta que busca combinar dados 

Em vez de copiar todos os grafos RDF para um repositório central, a engine divide
a consulta em subconsultas, envia cada parte ao endpoint apropriado e depois junta
os resultados localmente.

A cláusula SERVICE indica o endpoint remoto que ira avaliar a subconsulta.

*/

= Introdução

== Introdução

#v(.4em)

Uma *consulta federada* combina dados
em #underline[endpoints SPARQL independentes].

#v(-1.7em)

#move(dx: 178pt, dy: 4pt)[
#rect(width: 19em, stroke: none)[
#text(size: 17.6pt)[
#codly(
  highlights: (
    (
  (line: 2, start: 3, end: 22, fill: blue),
  (line: 8, start: 5, end: 19, fill: red),
  (line: 9, start: 5, end: 29, fill: green),
)
  ),
  annotations: (
    (
      start: 2,
      end: 6,
      content: block(
        width: 8em,
        rotate(
          -0deg,
          align(left, box(width: 66pt)[SERVICE com filtro])
        )
      ),
    ),
    (
      start: 8,
      end: 8,
      content: block(
        width: 8em,
        rotate(
          -0deg,
          align(left, box(width: 67pt)[Bound join])
        )
      ),
    ),
    (
      start: 9,
      end: 10,
      content: block(
        width: 8em,
        rotate(
          -0deg,
          align(left, box(width: 102pt)[Tripple pattern])
        )
      ),
    ),
  ),
)
```sparql
SELECT ?product ?price ?rating {
  SERVICE <vendor_001> {
    ?offer ex:forProduct ?product ;
           ex:price ?price .
    FILTER(?price < 1000)
  }
  SERVICE <review_001> {
    VALUES ?product {ex:p1}
    ?review ex:about ?product ;
            ex:rating ?rating .
  }
}
```
]
]

]
#pagebreak()

== Anatomia

#v(.7em)

#let circleee(pos, text, name, width: 54mm, height: 33mm, stroke: 1pt, corner-radius: 132pt) = node(
  pos,
  align(center)[#text],
  name: name,
  width: width,
  height: height,
  stroke: stroke,
  corner-radius: corner-radius,
)

#let groupbox(pos, name, width: 44mm, height: 30mm, stroke: 1pt) = node(
  pos,
  [],
  name: name,
  width: width,
  height: height,
  stroke: stroke,
  corner-radius: 3pt,
  inset: 3mm,
)

#let groupbox-title(pos, title) = node(
  pos,
  align(center)[#strong(title)],
  stroke: none,
  inset: 0pt,
)

#figure(
scale(78%, reflow: true)[
  #diagram(
    spacing: 11mm,
    edge-stroke: 1pt,
    mark-scale: 152%,

    groupbox((-1, 0), <client>, width: 8em, height: 4.9em),
    groupbox-title((-1, -0.59), [Cliente]),
    
    circleee((-1, 0), [SPARQL Query], <query>),
    circleee((1, 0), [Federated\ Engine], <engine>),
    // circleee((.4, 1.1), [Bound\ Joins], <join>, width: 4em, stroke: 2pt + red),
    circleee((.2, -.66), [Cache], <cache>, width: 4em, stroke: 2pt + green, corner-radius: 2pt, height: 1.7em),
  
    circleee((4.6, -1), [localhost:8891/sparql], <ep1>, width: 10em),
    circleee((4.6, 0), [localhost:8892/sparql], <ep2>, width: 10em),
    circleee((4.6, 1), [localhost:8893/sparql], <ep3>, width: 10em),

    // edge(<engine>, <join>, "-|>", bend: 20deg, stroke: 1.2pt + red),
    // edge(<join>, <engine>, "-|>", bend: 20deg, stroke: 1.2pt + red),

    edge(<engine>, <cache>, "-|>", bend: 20deg, stroke: 1.2pt + green),
    edge(<cache>, <engine>, "-|>", bend: 20deg, stroke: 1.2pt + green),
    
    edge(<engine>, <engine>, "-|>", bend: -121deg, stroke: 1.2pt + red, text(fill: red)[Bound Join], label-pos: .23, label-sep: -3pt),
    
    edge(<query>, <engine>, "-|>"),
    edge(<engine>, <ep1>, "-|>", [`ask`#super[1]], label-pos: .6, label-side: right, label-sep: -.1em, label-size: .8em, stroke: 1.2pt + blue),
    edge(<engine>, <ep2>, "-|>", [], stroke: 1.2pt + blue),
    edge(<engine>, <ep3>, "-|>", [`service`#super[2]], label-pos: .4, label-side: left, label-sep: -.0em, label-size: .8em, stroke: 1.2pt + blue),
    
    edge(<ep1>, <engine>, "-|>", bend: -20deg, stroke: 1.2pt + blue, [`(?s, ?p, ?o)`], label-sep: -.1em),
    edge(<ep2>, <engine>, "-|>", bend: -9deg, stroke: 1.2pt + blue),
    edge(<ep3>, <engine>, "-|>", bend: 20deg, stroke: 1.2pt + blue),
    
    edge(<engine>, <client>, "-|>", bend: 11deg, stroke: 1.2pt),
  )
],
  caption: [_Funcionamento de motores de consultas federadas._],
)

#pagebreak()

== Proposta

#v(.7em)

*Objetivo*: Construir uma engine mínima para o cenário _FedShop_, unindo
ideias de engines federadas já conhecidas.#linebreak()

#v(.4em)

- *FedX*: `ASK`, cache de fontes, _exclusive groups_ e _bound joins_ com `VALUES`.

- *SPLENDID*: catálogo VoID com predicados, tipos e cardinalidades.
// - *SemaGrow*: Ordenação por custo quando houver metadados.
- *ANAPSID*: _timeouts_ e _fallbacks_ para endpoints lentos/intermitentes.
- *CostFed*: Estimativa de cardinalidade e poda _join-aware_.

#v(.2em)

// citar as dimensoes analisadas no benchmark

*Resultado esperado*: Atingir resultados comparáveis ou superiores para métricas:
#v(-28pt)
#h(182pt)_Tempo de Execução_#h(54pt)_Timeout_#h(57pt)_Status de Erro_

= Fundamentação Teórica

== FedShop

#v(.3em)

Benchmark inspirado no *Berlin SPARQL Benchmark* (BSBM).#linebreak()

Simula usuário navegando uma loja virtual composta por:

_Produtos_ #h(7.9em)_Vendedores_ #h(5em)_Sites de avaliação_

Ao invés de uma loja centralizada como o BSBM, o FedShop divide em:

_Catálogo Virtual_ #h(5em) _Vendedores_ #h(5em) _Sites de Avaliação_

As consultas são dividas em três categorias:

1. _Single Domain_ (SD): Padrões resolvidos em um único endpoint;
2. _Multi Domain_ (MD): Padrões de vários endpoints mas sem junções;
3. _Cross-Domain_ (CD): Padrões exigem junções de endpoints diferentes;

// As consultas recuperam produtos com base em critérios, obtêm mais informações,
// comparam produtos, encontram produtos semelhantes e localizam avaliações.

// #v(.6em)

// Cada membro opera de forma independente dos demais. A federação cria a impressão
// de uma loja única, mas os dados continuam distribuídos.

#pagebreak()

== Dataset

#image("fedshop-data-structure.png")

#pagebreak()

== Estratégias de Otimização

#v(.25em)

#h(12pt)$italic("Como processar consultas SPARQL federadas com poucas req.")$ \
#h(149pt)$italic("e sem metadados pré-computados ?     — FedX")$

*_Source selection_* : Selecionar endpoints adequados para dado padrão.

#align(center)[*FedX*]
#v(29pt)
#place(dx: 1em, dy: -.2em)[
`ASK { ?offer ex:price ?price }`
]
#place(dx: 17em, dy: -1.1em)[
#rect(width: 13em, height: 4em, stroke: none)[
#text(size: 1em)[
  `V1` $arrow$ true#linebreak()
  `R2` $arrow$ false $dots$#linebreak()
]
]
]

#v(1.8em)

#place(dx: 0em, dy: .5em)[*SPLENDID*]
#place(dx: 0em, dy: 1.9em)[
#text(size: 1em)[
`Ip(ex:price)` $arrow$ `{(V1, 200)}`#linebreak()
`Iτ(ex:Review)` $arrow$ `{
  (R2, 1500), ...
}`
]
]

#place(dx: 13.5em, dy: .4em)[
*CostFed*
#v(-.5em)
#place(dx: 0em, dy: 1.3em)[
#text(size: 1em)[
V1 $join$ R1 $->$ mantém#h(15pt)V2 $join$ R1 $->$ poda#linebreak()
V1 $join$ R2 $->$ mantém#h(15pt)V2 $join$ R2 $->$ poda#linebreak()
]
]
]

#pagebreak()

*_Bound Join_* : Usa resultados intermediários para limitar nova consulta

#v(15pt)

#let rectnode(pos, text, name, width: 9em, height: 3.2em, stroke: 1pt) = node(
  pos,
  align(center)[#text],
  name: name,
  width: width,
  height: height,
  stroke: stroke,
  corner-radius: 3pt,
  inset: 2mm,
)

#let query-text = [
  #text(size: .72em)[
    `?drug db:cas ?id` \
    `?kegg bio2rdf:xRef ?id` \
    `?kegg purl:title ?title`
  ]
]

#figure(
scale(78%, reflow: true)[
  #diagram(
    spacing: 12mm,
    edge-stroke: 1pt,
    mark-scale: 145%,


    rectnode((-0.45, 0), [Motor\ Federado], <all-engine>, width: 5em, height: 3.6em),
    rectnode((-0.45, 1.05), [Join local\ em `?id`], <all-join>, width: 8.4em, height: 3.2em, stroke: 1.4pt + red),

    circleee((2.3, -0.75), [DrugBank\ endpoint], <all-drugbank>, width: 7em, height: 3.3em),
    circleee((2.3, 0.24), [KEGG\ endpoint], <all-kegg>, width: 6em, height: 3.3em),


    edge(<all-engine>, <all-drugbank>, "-|>", [`subquery A`], label-pos: .35, label-size: .75em, stroke: 1.2pt + blue),
    edge(<all-engine>, <all-kegg>, "-|>", [`subquery B`], label-pos: .65, label-size: .75em, stroke: 1.2pt + blue),

    
    edge(<all-drugbank>, <all-engine>, "-|>", stroke: 1.8pt + red, bend: -47deg, [`(?drug, ?id)`]),

    // edge(<all-r1>, <all-engine>, "-|>", bend: -28deg, [`materializa A`], label-size: .72em, stroke: 1.8pt + red),
    edge(<all-kegg>, <all-engine>, "-|>", bend: 28deg, [`(?drug, ?id)`], stroke: 1.8pt + red, label-pos: .2),

    edge(<all-engine>, <all-join>, "-|>", bend: 18deg, stroke: 1.3pt + red),
    edge(<all-join>, <all-engine>, "-|>", bend: 18deg, stroke: 1.3pt + red),

  )
],
numbering: none,
caption: [Estratégia 1: _Recuperar resultados amplos das fontes e fazer o join localmente._],
)

#pagebreak()

#v(1.1em)

#figure(
scale(78%, reflow: true)[
  #diagram(
    spacing: 12mm,
    edge-stroke: 1pt,
    mark-scale: 145%,


    rectnode((-0.45, 0), [Motor\ Federado], <bj-engine>, width: 5em, height: 3.6em),
    rectnode((-0.45, 1.15), [Agrupa\ bindings], <bj-block>, width: 4.4em, height: 3.2em, stroke: 1.4pt + green),

    circleee((2.35, -0.9), [DrugBank\ endpoint], <bj-drugbank>, width: 7em, height: 3.3em),
    circleee((3.35, 0), [KEGG\ endpoint], <bj-kegg>, width: 6em, height: 3.3em),

    rectnode((1.75, .4), [
      #text(size: .9em)[
        `VALUES ?id { id1 id2 id3 }` \
        `?kegg bio2rdf:xRef ?id` \
        `?kegg purl:title ?title`
      ]
    ], <bj-values>, width: 12.5em, height: 4.3em, stroke: 1.2pt + blue),


    edge(<bj-engine>, <bj-drugbank>, "-|>", [`IDs`], label-pos: .45, label-size: .75em, label-sep: 14pt, stroke: 1.2pt + blue),
    edge(<bj-drugbank>, <bj-engine>, "-|>", stroke: 1.2pt + green, bend: -34deg, [`id1, id2, id3, ...`]),
    // edge(<bj-bindings>, <bj-engine>, "-|>", bend: -25deg, [`bindings`], label-size: .72em, stroke: 1.2pt + green),

    edge(<bj-engine>, <bj-block>, "-|>", bend: 18deg, stroke: 1.2pt + green),
    edge(<bj-engine>, <bj-values>, "-|>", stroke: 1.2pt + blue),
    edge(<bj-block>, <bj-engine>, "-|>", bend: 18deg, stroke: 1.2pt + green),

    edge(<bj-values>, <bj-kegg>, "-|>", stroke: 1.2pt + blue),
    edge(<bj-kegg>, <bj-engine>, "-|>", [reconstrução local], stroke: 1.2pt + blue, bend: 51deg),


  )
],
numbering: none,
caption: [_Estratégia 2: bound join, enviando várias bindings juntas para restringir a subconsulta remota._],
)

#pagebreak()

// - *FedX*: prioriza baixo custo operacional. Seleciona fontes com `ASK`, agrupa
// padrões que pertencem ao mesmo endpoint, reordena joins e usa _bound joins_ para
// diminuir o número de requisições.

// - *SPLENDID*: usa descrições *VoID* para construir índices locais de predicados e tipos. Com isso, descarta fontes improváveis antes de consultar os endpoints.

// - *SemaGrow*: combina metadados, plano baseado em custo e execução não bloqueante. É útil quando um plano ligeiramente mais caro de construir evita intermediários grandes.

// == CostFed

// - *CostFed*: adiciona seleção de fontes sensível a joins e estimativas de cardinalidade
// mais realistas, evitando assumir distribuição uniforme dos recursos RDF.

// - *ANAPSID*: foca em adaptatividade. A execução muda conforme disponibilidade,
// atrasos e respostas parciais dos endpoints.

// #v(.7em)

// *Proposta*: uma engine mínima chamada *MiniFedShopEngine*, com seleção híbrida
// `VoID + ASK`, agrupamento de padrões por endpoint, planejamento simples por
// cardinalidade estimada, execução assíncrona e fallback adaptativo para endpoints lentos.

// #v(.7em)

// *Dimensão otimizada*: efetividade de *seleção de fontes e decomposição da consulta*,
// medida por tempo total, número de subconsultas, volume de intermediários,
// _timeouts/errors_ e distância em relação à *Reference Source Assignment* do FedShop.

== Trabalhos Relacionados

#v(-2.4em)

#place(dx: -125pt, dy: 80pt)[
#scale(70%)[
#grid(
  rows: 1,
  columns: (14em, 13em, 13em),
  column-gutter: 10pt,
  stroke: 3pt + red,
  inset: 10pt,
  [
    #align(center + top)[*FedShop*]
    #v(-.3em)
    #align(top + left)[
    Benchmark para escalabilidade#linebreak()
    Federações \[20-200\] endpoints#linebreak()
    _Reference Source Assignment_
    ]
  ],
  [
    #align(center + top)[*FedX*]
    #v(-.3em)
    #align(left)[
    Seleção de fontes com `ASK`#linebreak()
    Cache de fontes candidatas#linebreak()
    _Exclusive groups_ e _bound joins_
    ]
  ],
  [
    #align(center + top)[*SPLENDID*]
    #v(-.3em)
    #align(top + left)[
    Catálogo local VoID#linebreak()
    Índices de predicados e tipos#linebreak()
    Cardinalidades por endpoint
    ]
  ],
)
#v(-.7em)
#grid(
  rows: 1,
  columns: (10.0em, 11.5em, 11em, 7.1em),
  column-gutter: 10pt,
  stroke: (x, y) => if x == 2 { 3pt + red } else if x == 1 or x == 0 { 3pt + blue },
  inset: 10pt,
  [
    #align(center + top)[*SemaGrow*]
    #v(-.3em)
    #align(top + left)[
    Ordenação por custo#linebreak()
    Uso de metadados#linebreak()
    Execução assíncrona
    ]
  ],
  [
    #align(center + top)[*CostFed*]
    #v(-.3em)
    #align(top + left)[
    Poda _join-aware_#linebreak()
    Prefixos comuns de URI#linebreak()
    Estimativa sensível a _skew_
    ]
  ],
  [
    #align(center + top)[*ANAPSID*]
    #v(-.3em)
    #align(top + left)[
    Execução adaptativa#linebreak()
    _Timeouts_ e _fallbacks_#linebreak()
    Endpoints intermitentes
    ]
  ],
  [
    #align(left)[*Legenda*]
    #v(-.5em)
    #align(top + left)[
      #box(stroke: 1pt, fill: red, width: 24pt, height: 25pt, []) Adicionado.#linebreak()
      #box(stroke: 1pt, fill: blue, width: 24pt, height: 25pt, []) Talvez.
    ]
  ]
)
// #v(-.7em)
// #grid(
//   rows: 1,
//   columns: (19.4em, 12em),
//   column-gutter: 10pt,
//   stroke: (x, y) => if x == 0 or x == 1 { 3pt + red } else { 3pt + blue },
//   inset: 10pt,
//   [
//     #align(center + top)[*MiniFedShopEngine*]
//     #v(-.3em)
//     #align(top + left)[
//     Seleção híbrida `VoID + ASK`#linebreak()
//     Agrupamento por endpoint#linebreak()
//     Planejamento por cardinalidade estimada
//     ]
//   ],
// )
// #v(0em)
// #place(dy: 11pt)[#grid(
//   rows: 1,
//   columns: (13em, 12.1em, 16.1em),
//   column-gutter: 10pt,
//   stroke: (x, y) => if x == 0 or x == 1 { 3pt + red } else { 3pt + blue },
//   inset: 10pt,
//   [
//     #align(center + top)[*Decomposição*]
//     #v(-.3em)
//     #align(top + left)[
//     Subconsultas por fonte#linebreak()
//     Redução de requisições remotas#linebreak()
//     Menos resultados intermediários
//     ]
//   ],
//   [
//     #align(center + top)[*Execução*]
//     #v(-.3em)
//     #align(top + left)[
//     Requisições assíncronas#linebreak()
//     Fallback para endpoints lentos#linebreak()
//     Cache de `ASK`
//     ]
//   ],
//   [
//     #align(center + top)[*Avaliação*]
//     #v(-.3em)
//     #align(top + left)[
//     Tempo total#linebreak()
//     Nº de subconsultas e _timeouts_#linebreak()
//     Distância da RSA do FedShop
//     ]
//   ]
// )]
]
]


= Obrigado #h(6pt)#emoji.globe

==

#text(size: 14pt)[
  #bibliography(
    "referencias.bib",
    title: "Referências",
    full: true,
    style: "springer-lecture-notes-in-computer-science",
  )
]
