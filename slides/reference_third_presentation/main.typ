#import "@preview/codly:1.3.0": *
#import "@preview/mannot:0.3.1": markrect, annot, mark, markul
#import "@preview/touying:0.6.1": *
#import themes.university: *
#import "@preview/cetz:0.3.1"
#import "@preview/numbly:0.1.0": numbly

/* ******************** CONFIGURAÇÕES ******************** */

#set text(lang: "pt")
#set math.equation(numbering: "(1)")
#show figure.caption: set text(size: 18pt)

#let cetz-canvas = touying-reducer.with(reduce: cetz.canvas, cover: cetz.draw.hide.with(bounds: true))

// https://github.com/touying-typ/touying/blob/main/themes/university.typ

#show: university-theme.with(
  aspect-ratio: "16-9",
  config-info(
    title: [Recuperação da Informação],
    subtitle: [Experimentação / Resultados / Conclusões / Trabalhos Futuros / Validação],
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

= Experimentação

== Modelos

#v(-.3em)

#h(-13pt)"$italic("Análise comparativa entre modelos esparsos, semânticos e híbridos")$ \
#v(-11pt)
#h(185pt)$italic("no contexto jurídico brasileiro.")$"

#place(dx: -23pt, dy: 30pt)[
#grid(
  columns: (190pt, 249pt, 287pt),
  // column-gutter: 55pt,
  [
    #align(top + left)[*Esparsos*]
    #v(-11pt)
    #align(top + left)[
      BM25+#linebreak()#v(-3pt)
      BMX#linebreak()#v(-3pt)
      Lucene#linebreak()#v(-3pt)
      ATIRE#linebreak()#v(-3pt)
      Pyserini com RM3#linebreak()#v(-3pt)
      BM25 Robertson (Baseline)#linebreak()#v(-3pt)
    ]
  ],
  [
    #place(dx: 62pt)[
    #align(top + left)[*Semânticos*]
    #v(-12pt)
    #align(top + left)[
      Qwen3-Embedding-0.6B#linebreak()
      embeddinggemma-300m#linebreak()#v(-12pt)
      gte-multilingual-base#linebreak()#v(-12pt)
      jina-embeddings-v3#linebreak()#v(-12pt)
      *Pré-treinados*#linebreak()#v(-12pt)
      qwen-pgm-pairs#linebreak()#v(-12pt)
      gemma-pgm-pairs#linebreak()#v(-12pt)
      gte-pgm-pairs#linebreak()#v(-12pt)
    ]
    ]
  ],
  [
    #place(dx: 92pt)[
    #align(top + left)[*Híbridos*]
    #v(-12pt)
    #align(top + left)[
      MNZ#linebreak()#v(-12pt)
      Weighted MNZ (WMNZ)#linebreak()
      Weighted SUM (WSUM)#linebreak()#v(-12pt)
      Mixed = WMNZ + WSUM#linebreak()#v(-12pt)
      *Ranqueadores*#linebreak()#v(-12pt)
      bge-reranker-base#linebreak()#v(-12pt)
      gte-multilingual-reranker#linebreak()#v(-12pt)
      qwen3‑reranker‑0.6b
      // gte-pgm-pairs#linebreak()#v(-12pt)
    ]
    ]
  ]
)
]

== Experimentação

#v(.0em)

#text(size: 24pt)[
+ Realizou-se um estudo de ablação conforme a apresentação anterior.

+ Selecionaram-se conjuntamente as variantes de _embeddings_ e BM25 com melhor *MAP*.

+ Biblioteca `ranx` para avaliação, algoritmos de fusão e testes de hipóteses.

#v(13pt)

#pagebreak()

#v(31pt)

#place(dx: -24pt, dy: 17pt)[
#scale(x: 70%, y: 70%)[
#place(dx: 11.4em, dy: 63pt)[#text(size: 47pt)[$arrow.double.r$]]
#place(dx: 11.4em, dy: 299pt)[#text(size: 47pt)[$arrow.double.r$]]
#place(dx: 2pt, dy: -19pt)[*Random Search* com BM25]
#place(dx: 28.4em, dy: 26pt)[*Re-ranqueador*]
#place(dx: 13.5em, dy: 296pt)[*Candidato _Embeddings_*#linebreak()_segundo MAP $dots$_]
#place(dx: -.7em, dy: 9.3em)[Variantes _Embeddings_ $("dim"=768)$]
#place(dx: .1em, dy: 10.8em)[
#rect(
  stroke: 2pt,
  inset: 10pt,
  [
    `jina-embeddings-v3`#linebreak()
    `Qwen3-Embedding-0.6B`#linebreak()
    `gte-multilingual-base`#linebreak()
    `embeddinggemma-300m` $dots$
  ]
)
]
#place(dx: 13.7em, dy: 74pt)[*Candidato BM25*#linebreak()_segundo MAP$dots$_]
#place(dx: 27.0em, dy: 185pt)[*Grid Search* com Fusão e Normalização]
#place(dx: 24.8em, dy: 157pt)[
  #scale(y: 239pt, x: 40pt)[
  #set math.cases(reverse: true)
  $cases()$
  ]
]
#place(dx: 2pt, dy: 18pt)[
#rect(
  stroke: 2pt,
  inset: 10pt,
  [
    `bm25+` com $b,k_1,delta in bb("R")$#linebreak()
    `pyserini` com $b,k_1 in bb("R")$#linebreak()
    #h(111pt)$dots.v$#linebreak()
    `bm25l` com $b,k_1 in bb("R")$#linebreak()
    `bmx` com $alpha,beta in bb("R")$
  ]
)
]

#place(dx: 28em, dy: 9em)[
#rect(
  stroke: 2pt,
  inset: 10pt,
  [
    _Algoritmos de Fusão_#linebreak()
    `rrf`, `min`, `max`, `med`, `sum`#linebreak()
    `anz`, `mnz`, `gmnz`, `isr`, `logn_isr`, $dots$#linebreak()
    _Estratégias de Normalização_#linebreak()
    `min-max`, `max`, `sum`, `zmuv`, `rank`#linebreak()
    `borda`
    #linebreak()
    
  ]
)
]
#place(dx: 28em, dy: 62pt)[
#rect(
  stroke: 2pt,
  inset: 10pt,
  [
    `bge-reranker-base`#linebreak()
    `gte-multilingual-reranker`#linebreak()
  ]
)
]
#place(dx: 16em, dy: 177pt)[#text(size: 52pt)[$+$]]
]
]
#grid(
  columns: 2,
  [
    
  ]
)

]
// #figure(
//   image("ranx.png", width: 4%),
//   caption: [Biblioteca `ranx` para comparação, fusão e avaliação dos modelos.]
// )

= Resultados

== Bases de Dados

#let gut = 40pt

#let nonumber = math.equation.with(
  block: true,
  numbering: none,
)

#place(dx: -21pt, dy: 15pt)[
#align(left)[
    #grid(
      columns: (16em, 15em),
      column-gutter: 13pt,
      stroke: (x, y) => if x == 0 {red + 2pt} else {blue + 2pt},
      inset: 25pt,
      [
    #align(top + left)[*JurisTCU*#linebreak()]
    #align(top + left)[
    #align(left)[
      _Legal Information Retrieval_#linebreak()#v(-8pt)
      16.045 documentos#linebreak()#v(-8pt)
      150 consultas anotadas#linebreak()#v(-8pt)
      Grupos de consultas:#linebreak()#v(-8pt)
      #box(stroke: 2pt + red, inset: 14pt)[
      + Usuários.#linebreak()
      + LLM.#linebreak()
      + _keywords_ extraídas de LLMs.
      ]
    ]
    ]
      ],
      [
    #align(left)[*Ulysses Relevance Feedback*]
    #align(left)[
      _Ulysses-RFCorpus_#linebreak()#v(-8pt)
      105.669 documentos#linebreak()#v(-8pt)
      692 consultas anotadas#linebreak()#v(-8pt)
      Consultores especialistas#linebreak()#v(28pt)
      #h(56pt)#text(fill: blue, size: 34pt)[Relatório Final]
    ]
      ]
    )
]
]

// Precisão

==

#v(.6em)

#place(dx: 108pt, dy: -1pt)[
#scale(x: 134%, y:134%)[
  #image("precision.png", width: 78%) 
]
]

// Revocação

==

#v(.6em)

#place(dx: 108pt, dy: 2pt)[
#scale(x: 134%, y:135%)[
  #image("recall.png", width: 78%) 
]
]

// nDCG

==

#v(.6em)

#place(dx: 108pt, dy: 1pt)[
#scale(x: 134%, y:135%)[
  #image("ndcg.png", width: 78%) 
]
]

== 

#v(.6em)

#place(dx: 50pt, dy: 44pt)[
#scale(x: 132%, y:143%)[
  #image("simple_view_res.png", width: 86%, height: 60%) 
]
]

== Curva Precisão $times$ Revocação

#figure(
  scale(x: 114%, y: 108%)[#image("pr_curve.png", width: 62%)],
  caption: [_A área abaixo do gráfico corresponde ao MAP $approx$ 0.4621._]
)

== Métricas Rasas $times$ Profundas

#v(23pt)

Métricas rasas tiveram ganhos 2.3$times$ maiores.

#v(27pt)

#figure(
  image("rasas_prof.png", width: 56%),
  caption: [_Comparação entre métricas rasas e profundas._]
)

= Desempenho

==

#place(dx: 141pt, dy: 18pt)[
#scale(x: 142%, y:139%)[
  #image("time.png", width: 63%) 
]
]

== Heatmap

#place(dx: 155pt, dy: 23pt)[
#scale(x: 150%, y:146%)[
  #image("group123_heatmap.png", width: 53%) 
]
]

== Configurações

#v(-79pt)

#align(center + horizon)[
#table(
    columns: 2,
    inset: 8pt,
    align: (center, left),
    stroke: none,
    row-gutter: 4pt,
    fill: (x, y) => if calc.odd(y) { rgb("#f8fafc") },
    [*Componente*], [*Configuração*],
    table.hline(stroke: 1.5pt),
    [CPU], [AMD Ryzen Threadripper PRO 7995WX (96 cores)],
    [RAM], [1 TiB (991 GiB disponível)],
    [GPU], [$2 times$ NVIDIA RTX 6000 Ada (49 GB cada)],
    [Disco], [1 TiB],
    [SO], [Debian GNU/Linux 13 (kernel 6.12.48)],
  )
]

= Estudo de Ablação

== 

#v(.7em)

#figure(
  scale(x: 120%, y: 121%)[#image("optimizing_group123_hyperparameter.png", width: 83%)],
  // caption: []
)

==

== Teste de Hipótese

= Comparação - JurisTCU

== Grupo 3

#figure(
  image("compare_juristcu.png"),
  caption: [__]
)

== Teste de Hipótese - Wilcoxon

#v(86pt)

#figure(
  image("wilcoxon.png", width: 92%),
  caption: [_Resultados dos Testes de Wilcoxon_ $(alpha = 0.05)$]
)

== Conclusão

#v(5pt)

#align(center)[
  #block(
    width: auto,
    height: auto,
    stroke: 2.9pt + red,
    inset: 17pt,
    [
  *Hipótese Artigo Base*: "Recuperadores densos necessitam, sobretudo, do BM25 para métricas profundas."
    ]
  )
]

#align(center)[
  #block(
    width: auto,
    height: auto,
    stroke: 2.9pt + green,
    inset: 17pt,
    [
  *Observação*: Métricas rasas tiveram ganhos mais expressivos em comparação às métricas profundas.
    ]
  )
]


#align(center)[
  #block(
    width: auto,
    height: auto,
    stroke: 2.9pt + green,
    inset: 17pt,
    [
  *Minha Hipótese*: Busca híbrida seria mais robusta que métodos puramente léxicos ou semânticos.
    ]
  )
]



// == _Precision_ $times$ _Recall_

// == Resultado Preliminar - JurisTCU

// #v(1em)

// #figure(
//   image("optimizing_group123_visualization_res.png", width: 111%),
//   caption: [_Resultado Preliminar : Melhor variante dos embeddings $times$ Melhor BM25 (BM25+), melhor embeddings e melhor algoritmo de fusão._]
// )

// == Resultado Preliminar - Hiperparâmetros

// #v(-.1em)

// #figure(
//  image("hyperparameter_study.png", width: 92%),
//  caption: [_"Pior" $times$ "Melhor" estratégia de fusão segundo o MAP._]
// )

= Trabalhos Futuros

== Retrieval-Augmented Knowledge Graph

#v(.5em)

Construção de um grafo de conhecimento enriquecido a partir dos documentos do corpus

- Utilização do GliNER para reconhecimento e extração de entidades;

Avaliação de modelos esparsos baseados em redes neurais (SPLADE).

- Permitem generalização sobre uma grande variedade de _datasets_;

#emoji.zzz

== Aplicação

#align(left + horizon)[
  #grid(
    columns: 2,
    [
     #figure(
    image("res.png", width: 79%),
    caption: [_Resultados da busca com BM25._]
     ) 
    ],
    [
  #link("https://saitoi.foo/?key=abc123")[#underline[*Clique Aqui*]]
    ]
  )
]

==

#text(size: 14pt)[
  #bibliography(
    "referencias.bib",
    title: "Referências",
    full: true,
    style: "american-chemical-society",
  )
]
