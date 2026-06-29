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
    subtitle: [Proposta / Implementação / Avaliação Preliminar],
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

= Proposta

== Objetivo

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

== Bases de Dados

#v(.0em)

#let gut = 40pt

#let nonumber = math.equation.with(
  block: true,
  numbering: none,
)

#align(center)[
    #grid(
      columns: (16em, 15em),
      [
    #align(top + left)[*JurisTCU*#linebreak()]
    #align(top + left)[
    #align(left)[
      _Legal Information Retrieval_#linebreak()#v(-8pt)
      16.045 documentos#linebreak()#v(-8pt)
      150 consultas anotadas#linebreak()#v(-8pt)
      Grupos de consultas:#linebreak()#v(-8pt)
      + Usuários.#linebreak()
      + LLM.#linebreak()
      + _keywords_ extraídas de LLMs.
    ]
    ]
      ],
      [
    #align(left)[*Votos do TCU e Acórdãos do STJ*]
    #align(left)[
      _Document Similarity_#linebreak()#v(-8pt)
      *STJ*: Pares entre 6.345 documentos#linebreak()#v(-8pt)
      *TCU*: Pares entre 338 documentos#linebreak()#v(5pt)
    ]
    #place(dx: 10pt, dy: 18pt)[
    #nonumber(
    $
    [0, 5] => cases(
      0 arrow.double.l 0 <= s < 1\,75,
      1 arrow.double.l 1\,75 <= s < 3\,75,
      2 arrow.double.l 3\,75 <= s <= 5,
    )
    $
    )
        ]
      ]
    )
]

= Implementação

== Pipeline de Pré-processamento

#v(.6em)

1. Persiste os campos de indexação do artigo no banco de dados.

2. `BeautifulSoup4` para extração de arquivos HTML.

3. Normalização de termos jurídicos específicos #text(size: 20.6pt)[(`art. nº` $->$ `artigo número`)].

4. _RSLP Stemmer_ desenvolvido para língua portuguesa.

#grid(
  columns: 3,
  // stroke: (x, y) => if x > 0 { (left: 1pt + gray) },
  column-gutter: 11pt,
  [
#figure(
  image("bm25s.png", width: 47%),
  caption: [_Biblioteca `bm25s` moderna e performática do bm25_]
)
  ],
  [
#figure(
  image("pyserini.png", width: 53%),
  caption: [Biblioteca `pyserini` para o BM25 com RM3]
)
  ],
  [
#figure(
  image("mixedbread.png", width: 44%),
  caption: [Biblioteca `baguetter` do Mixedbread para o BMX.]
)
  ]
)

== _Sentence Embeddings_

#v(.7em)

1. _Chunking_ dos documentos em passagens usando `langchain-text-splitters`.

2. Computar os _embeddings_ de cada _chunk_.

3. Agregar os _embeddings_ usando _Aggregate Mean Pooling_.

#v(-6em)

#place(dx: 236pt, dy: 7.5em)[
  #scale(86%)[
#rect(width: 238pt, height: 179pt, stroke: 1pt + gray, inset: 9pt)[
  #text(size: 16pt)[
    #highlight(fill: green)[
    Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod
    tempor incididunt 
    ]#highlight(fill: blue)[
      ut labore et dolore magnam aliquam quaerat voluptatem. Ut
    enim aeque doleamus animo
    ]#highlight[
      , cum corpore dolemus, fieri tamen permagna
    accessio potest, si.
    ]
  ]
  #v(-5pt)
  #h(18pt)#text(size: 22pt)[`chunk_size = 1024`]
]
  ]
]

#place(dx: -62pt, dy: 195pt)[
  #scale(74%)[
  #figure(
    image("duckdb.png", width: 26%),
    caption: [_Banco de dados embarcado OLAP._],
  )
  ]
]

#place(dx: 470pt, dy: 253pt)[
  #text(size: 2.4em)[$=>$]
]


#place(dx: 180pt, dy: 249pt)[
  #text(size: 2.4em)[$=>$]
]

#place(dx: 271pt, dy: 245pt)[
  #scale(73%)[
  #figure(
    [
    #text(size: 37pt)[
    $
    v_(italic("mean")) = 1/n sum_(i=1)^n v_i
    $
    ]
    ],
    caption: [_Técnica de Aggregate Mean Pooling._]
  )
  ]
]

== Reranquedores

#v(.7em)

- União e deduplicação dos resultados anteriores.

- Re-ranqueamento dos resultados desconsiderando os _scores_ atribuídos.

#v(-2.1em)

#place(dx: 15.4em, dy: 7.6em)[#text(27pt)[$sans("gte-multilingual-reranker")thin(q,D)$]]

#place(dx: 13.7em, dy: 5.5em)[#text(size: 45pt)[#sym.arrow.br]]
#place(dx: 13.6em, dy: 9.4em)[#text(size: 45pt)[#sym.arrow.tr]]

#place(dx: 55pt, dy: 196pt)[#text(20pt)[`top-k output: embeddings`]]
#place(dx: -62pt, dy: 86pt)[
#scale(73%)[
#text(weight: "thin", size: 129pt)[\{] #box(
  [
    `["texto": ..., "score": 0.5444]` \
    `["texto": ..., "score": 0.4955]` \
    `["texto": ..., "score": 0.0161]` \
    `["texto": ..., "score": 1.0000]` \
    #v(-24pt)
  ]
) #text(weight: "thin", size: 129pt)[\}]
]
]

#place(dx: 21.6em, dy: 9.2em)[#text(size: 39pt)[$arrow.double.b$]]

#place(dx: 13em, dy: 10.6em)[
#scale(73%)[
#text(weight: "thin", size: 129pt)[\{] #box(
  [
    `["texto": ..., "novo_score": 0.5444]` \
    #h(7em)$dots.v$ \
    `["texto": ..., "novo_score": 0.0161]` \
    `["texto": ..., "novo_score": 1.0000]` \
    #v(-24pt)
  ]
) #text(weight: "thin", size: 129pt)[\}]
]
]

#place(dx: 87pt, dy: 330pt)[#text(20pt)[`top-k output: bm25`]]
#place(dx: -61pt, dy: 221pt)[
#scale(73%)[
#text(weight: "thin", size: 129pt)[\{] #box(
  [
    `["texto": ..., "score": 0.5444]` \
    `["texto": ..., "score": 0.4955]` \
    `["texto": ..., "score": 0.0161]` \
    `["texto": ..., "score": 1.0000]` \
    #v(-24pt)
  ]
) #text(weight: "thin", size: 129pt)[\}]
]
]

= Avaliação

== Métricas

#v(.6em)

#align(top + center)[
    #table(
      columns: 3,
      align: (left, left, left),
      column-gutter: 6pt,
      row-gutter: 6pt,
      stroke: none,
      inset: 10pt,
      fill: (x, y) => if y == 0 { rgb("#dbeafe") } else if calc.odd(y) { rgb("#f8fafc") },
      [*Tipo*], table.vline(stroke: 1.5pt), [*Rasas $(k <= 10)$*], [*Profundas*],
      table.hline(stroke: 1.5pt),
      [Precision], [P\@1, \@3, \@5, \@10], [P\@100, \@1000],
      [Recall], [R\@1, \@3, \@5, \@10], [R\@100, \@1000],
      [nDCG], [nDCG\@1, \@3, \@5, \@10], [nDCG\@100, \@1000],
      table.hline(stroke: 0.5pt),
      [*Ranking*], [MRR\@10], [*MAP*, BPref, R-Prec],
      [*Outros*], [Hits\@10, F1\@10], [—],
    )
  ]

#align(center)[
  #block(
    width: auto,
    height: auto,
    stroke: 2pt + gray,
    inset: 17pt,
    [
  *Hipótese*: Recuperadores densos necessitam do BM25 para métricas profundas.
    ]
  )
]

== Estudo de Ablação

#v(.7em)

#h(12pt)"$italic("Processo de modificar ou isolar componentes de um modelo")$ \
// #v(-1em)
#h(47pt)$italic("ou algoritmo para avaliar seu impacto no desempenho.")$"

#v(-.5em)

#figure(
  image("grid_random_search.png", width: 56%),
  caption: [_Grid Search $times$ Random Search para otimização do BM25 e da busca híbrida._]
)

== Resultado Preliminar - JurisTCU

#v(1em)

#figure(
  image("optimizing_group123_visualization_res.png", width: 111%),
  caption: [_Resultado Preliminar : Melhor variante dos embeddings $times$ Melhor BM25 (BM25+), melhor embeddings e melhor algoritmo de fusão._]
)

== Resultado Preliminar - Hiperparâmetros

#v(-.1em)

#figure(
 image("hyperparameter_study.png", width: 92%),
 caption: [_"Pior" $times$ "Melhor" estratégia de fusão segundo o MAP._]
)

== Em Ação

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

== Configurações

// #v(-2em)

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

==

#text(size: 14pt)[
  #bibliography(
    "referencias.bib",
    title: "Referências",
    full: true,
    style: "american-chemical-society",
  )
]
