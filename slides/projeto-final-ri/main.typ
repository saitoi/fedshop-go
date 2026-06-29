#import "lib.typ": lncs, institute, author, theorem, proof

#let inst_princ = institute("Universidade Federal do Rio de Janeiro", 
  addr: "Ilha do Fundão, Rio de Janeiro"
)
#let inst_springer = institute("Springer Heidelberg", 
  addr: "Tiergartenstr. 17, 69121 Heidelberg, Germany", 
  email: "lncs@springer.com",
  url: "http://www.springer.com/gp/computer-science/lncs"
)
#let inst_abc = institute("ABC Institute", 
  addr: "Rupert-Karls-University Heidelberg, Heidelberg, Germany", 
  email: "{abc,lncs}@uni-heidelberg.de"
)

#show: lncs.with(
  title: "Análise Comparativa de Métodos de Recuperação de Informação no Contexto Jurídico Brasileiro",
  // thanks: "Supported by Universidade Federal do Rio de Janeiro.",
  authors: (
    author("Pedro Henrique Honorio Saito", 
      insts: (inst_princ),
      oicd: "DRE: 122149392",
    ),
  ),
  abstract: [#set text(lang: "pt")
    Sistemas de recuperação de informação jurídica lidam com desafios como linguagem técnica e alto volume de dados. Este estudo apresenta uma análise comparativa de abordagens lexicais, semânticas e híbridas aplicadas à jurisprudência brasileira, utilizando o _dataset_ *JurisTCU* que contempla 16.045 documentos do Tribunal de Contas da União e 150 consultas com julgamentos de relevância. Avaliei: (1) modelos esparsos como variações do BM25 (_Lucene_, _BM25L_, _BM25+_, _ATIRE_, _BMX_ e _Pyserini_ com RM3); (2) Modelos densos baseados em _sentence embeddings_ (GTE, Jina, Qwen, Gemma e variantes pré-treinadas); e (3) métodos de busca híbrido com _reranking_ e algoritmos de fusão como _Reciprocal Rank Fusion_ (RRF), _MNZ_, _WMNZ_, _WSUM_, _TM2C2_, dentre outros. Resultados indicam que a combinação de sinais lexicais e semânticos supera abordagens exclusivamente de um dos tipos em coleções reais de decisões judiciais.
  ],
  keywords: ("Recuperação de Informação", "Busca Híbrida", "Reranking", "Reciprocal Rank Fusion", "Jurisprudência Brasileira", "Dense Retrievers", "Embeddings", "BM25"),
  bibliography: bibliography("refs.bib"),
  // optional configuration of page (takes all page parameter)
  // page_config: (paper: "a4")
)

#set text(lang: "pt")

= Introdução

_Legal Information Retrieval_ (LIR) foca em métodos de busca aplicados a
documentos jurídicos como leis, jurisprudências, acórdãos e processos. A
recuperação de informação em domínios especializados, como o jurídico, apresenta
desafios significativos devido à linguagem técnica, ao grande volume de
documentos e à necessidade de capturar nuances semânticas complexas.

Com o crescimento contínuo da jurisprudência, modelos esparsos como o BM25 permanecem relevantes por serem eficientes e interpretáveis em cenários _out-of-domains_ e consultas com termos léxicos específicos. No entanto, modelos de linguagem permitem o uso de _embeddings_, que capturam relações semânticas para além da correspondência exata dos termos.

O objetivo deste trabalho é realizar uma análise comparativa entre diferentes abordagens de busca no contexto de LIR em português. As abordagens avaliadas incluem:

#v(.7em)

- Modelos esparsos (variantes do BM25).#v(.2em)
- Modelos densos baseados em _sentence embeddings_.#v(.2em)
- Pipeline de duas etapas com reranqueadores.#v(.2em)
- Algoritmos de fusão de busca híbrida e estratégias de normalização.

#v(9pt)

O resultado esperado é que a combinação de sinais lexicais e semânticos supere métodos puramente léxicos ou semânticos em coleções reais de decisões judiciais.

= Fundamentação Teórica

== BM25 e Variantes

// Citar o BM25 Okapi

O BM25 é uma função de ranqueamento que avalia a pertinência de um documento
considerando a frequência dos termos na consulta, a raridade deles na coleção e
a normalização pelo tamanho do documento. Diversas variantes foram propostas
para melhorar o desempenho em diferentes cenários:

=== BM25 Lucene

#v(.8em)

Implementação padrão com suavização no cálculo do IDF e fator de normalização
TF. A fórmula incorpora um termo de suavização $(+ 1)$ no numerador do IDF para
evitar valores negativos.

#v(1em)

$
"BM25"_(italic("lucene"))(q, D) = sum_(t in q thin inter thin D) [
  log(1 + (N - n_i + 0,5)/(n_i + 0,5)) dot
    (f_(t,D) (k_1 + 1))/(f_(t,D) + k_1 dot (1 - b + b (abs(D))/("avgdl")))
]
$

#v(1em)

De modo geral, é uma abordagem bem conservadora.

=== BM25L

#v(.8em)

Variante que modifica o componente TF para lidar melhor com documentos longos, introduzindo um parâmetro $delta$ que ajusta a penalização por comprimento do documento

// formula do BM25L

#v(1em)

$
"BM25L"(q, D) = sum_(t in q thin inter thin D) [
  log((N - n_i + 0,5)/(n_i + 0,5)) dot
  "TF"'_(t,D)
] \ \
"onde" med med "TF"'_(t,D) = cases(
  ((k_1 + 1) dot (c/"norm" + delta))/(k_1 + (c/"norm" + delta)) quad "se" f_(t,D) > 0,
  0 quad quad quad quad quad quad c.c.
)
$

#v(1em)

O termo $c/"norm"$ é o TF normalizado pelo comprimento do documento:

#v(1em)

$
c/"norm" = c_(t,D) / (1 - b + b abs(D)/"avgdl")
$

#v(1em)

O BM25 penaliza excessivamente documentos muito longos: A normalização faz
$c/"norm"$ tender a zero, levando o TF a valores que praticamente ignoram a
ocorrência do termo. Assim, documentos extensos deixam de ser distinguidos de
documentos sem o termo.

O BM25L introduz um deslocamento $delta > 0$, garantindo um limite inferior
positivo para o TF sempre que há ocorrência. Isso preserva a separação entre
presença e ausência do termo e evita o colapso do _score_ em documentos longos.

A função ajustada mantém as propriedades essenciais do BM25, adicionando outras: TF nulo sem ocorrência, crescimento monotônico com a frequência e mínimo assintótico significativo quando o termo está presente.

=== BM25+ e ATIRE

#v(.8em)

As variantes BM25+ e ATIRE partem do mesmo princípio do BM25L de tratar
documentos mais longos, porém com algumas variações. O BM25+ adiciona um
_offset_ positivo $delta times "IDF"(t)$ ao _score_ final, garantindo que
documentos com correspondência de termos sempre recebam _score_ positivo. Por
outro lado, a variante ATIRE modifica o cálculo da normalização por comprimento
do documento, invertendo a relação entre o tamanho médio dos documentos
$("avgdl")$ e o tamanho do documento $(abs(D))$ no denominador do TF.

A função de ranqueamento de ambas as variantes está dada abaixo:

#v(1em)

$
"BM25+"(q,D) = "OkapiBM25" + delta dot "IDF"(t) \ \
"BM25"_"ATIRE" (q, D) = sum_(t in q thin inter thin D) [
  "IDF"(t) dot (f_(t,D) (k_1 + 1))/(f_t,D + k_1 dot (b + (1 - b) italic("avgdl")/abs(D)))
]
$

#v(1em)

Ambas as variantes ajustam o BM25 para reduzir a penalização de documentos longos e estabilizar o score, mantendo a estrutura básica do modelo.

=== BMX

#v(.7em)

Variante recente que incorpora entropia ponderada e componentes semânticos,
adicionando termos para expansão de consulta $(E)$ e similaridade semântica
$(S)$ com parâmetros $alpha$ e $beta$.

#v(1em)

$
"BMX"(q, D) = sum_(t in q thin inter thin D)^m "IDF"(q_i) dot (f_(q,D) dot (alpha + 1) )/(f_(q,D) + alpha dot abs(D)/italic("avgdl") + alpha dot E) + beta dot E(q_i) dot S(q,D)
$

#v(1em)

Os parâmetros $alpha$ e $beta$ controlam, respectivamente, a influência da componente lexical normalizada e o peso d parcela semântica de expansão de consulta, equilibrando a contribuição de $E$ e $S$ no _score_ final.

=== Pyserini com RM3

#v(3pt)

Além das variantes implementadas diretamente, este trabalho também avalia o BM25
com RM3 por meio da biblioteca `Pyserini`, incorporando _pseudo-relevance
feedback_ como uma configuração esparsa adicional para comparação com os demais
modelos.

== Embeddings Contextuais

Modelos como BERT produzem token-level embeddings e não são otimizados para medir similaridade entre sentenças. Para resolver essa limitação, foi desenvolvido o Sentence-BERT (SBERT) com objetivos de treino específicos:

#v(.8em)

- *Cross-Entropy Loss (NLI)*: Aprende relações entre pares de sentenças classificando-as como implicação (entailment), sem relações lógicas (neutral) ou contradição (contradiction).

#v(.8em)

- *Cosine Similarity Loss (STS)*: O modelo recebe duas sentenças e prevê um valor de similaridade seguindo julgamento humano.

#v(.8em)

- *Multiple Negative Ranking Loss*: Cada item do batch de treinamento se torna um negativo para todos os outros, exceto seu par positivo, aumentando a eficiência do treino.

#v(.8em)

- *Matryoshka Learning*: Técnica que força um embedding maior conter múltiplas representações aninhadas de tamanhos fixos, permitindo flexibilidade na escolha da dimensionalidade sem necessidade de retreinamento.

#v(.8em)

- *Aggregate Mean Pooling*: Técnica de agregação usada para transformar um conjunto de vetores em um único vetor representativo via média:

#v(.9em)

$
v_(italic("mean")) = (1/n)  sum_(i=1)^n v_i
$

#v(.9em)

== Re-ranqueadores

Re-ranqueadores são modelos que, dado um par $(q,D)$, atribuem um _score_ usado
para refinar a ordenação dos documentos. Integram pipelines de recuperação em
duas etapas, nas quais um modelo esparso ou denso recupera os _top-k_ candidatos
e o re-ranqueador reordena esse conjunto. Na prática, adotam predominantemente
arquiteturas *cross-encoder*, que se distinguem das demais abordagens conforme
ilustrado a seguir:

#v(.7em)

#align(center)[
  #grid(
    columns: 2,
    column-gutter: 10pt,
    [
      #align(left + top)[
      *Bi-encoder*#linebreak()
      #v(.4em)
      #set par(first-line-indent: 0em)
      Codifica consulta e documento separadamente.#linebreak()
      Menor custo computacional e menor precisão.#linebreak()
      Indexação e processamento _offline_.#linebreak()
      Similaridade via cosseno.#linebreak()
      ]
    ],
    [
      #align(left + top)[
      #v(.4em)
      #set par(first-line-indent: 0em)
      *Cross-encoder*#linebreak()
      Processa consulta e documento em conjunto.#linebreak()
      Maior custo computacional e maior precisão.#linebreak()
      Modela interações _token_ a _token_.#linebreak()
      Similaridade aprendida $f_theta(q,d):(q,d) arrow.r.bar bb("R")$.
      ]
    ]
  )
]

#set par(first-line-indent: 15pt)

= Trabalhos Relacionados

Este estudo se fundamenta em um conjunto amplo de contribuições da literatura de Recuperação da Informação (RI), abrangendo desde a construção de bases de dados nacionais até avanços em métodos lexicais, densos e híbridos.

#v(.5em)

- *JurisTCU* @Fernandes2025JurisTCU: Conjunto de dados brasileiro para RI jurídica, contendo julgamentos anotados, metadados estruturados e diretrizes de indexação, servindo de referência para pesquisas na área de LIR.

#v(.4em)

- *BERT-based Dense Retrievers Require Interpolation with BM25* @Wang2021InterpolateDR: Demonstra que recuperadores densos dependem de interpolação com BM25 para desempenho consistente, ressaltando a complementaridade entre sinais lexicais e semânticos.

#v(.4em)

- *Análise da Eficácia de Fine-Tuning de Embeddings* @Unknown202XFineTuningLegalBrasil: Avaliação do impacto do fine-tuning em modelos densos (GTE, Jina, Gemma, Qwen) e técnicas como Matryoshka Learning, discutindo ganhos de desempenho e custo computacional.

#v(.4em)

- *When Documents Are Very Long, BM25 Fails* @Zhai2011VeryLongDocs: Introduz a variante BM25L e evidencia suas vantagens na recuperação de documentos extensos, validando diferenças por meio de testes estatísticos.

#v(.4em)

- *BMX – Entropy-weighted Similarity and Semantic-enhanced Lexical Search* @Li2024BMX: Propõe o BMX, que combina pesos lexicais ajustados por entropia com query augmentation, ampliando a efetividade da busca lexical.

#v(.4em)

- *Ulysses Tesemô* @Unknown202XFeedbackCorpusBrasil: Dataset legislativo da Câmara dos Deputados, com aproximadamente 105 mil documentos e 692 consultas anotadas, adequado para estudos de recuperação e análise de consultas.

#v(.4em)

- *An Analysis of Fusion Functions for Hybrid Retrieval* @Bruch2022Fusion: Estudo sobre funções de fusão em pipelines híbridos, incluindo TM2C2 e comparações com RRF.

#v(.4em)

- *Ranx* @ranx: Biblioteca Python voltada para avaliação, comparação e fusão de rankings, com suporte a diversas métricas e algoritmos de combinação.

#v(.4em)

- *Pyserini* @Lin_etal_SIGIR2021_Pyserini: Toolkit para experimentação reprodutível em RI com métodos lexicais, densos e híbridos, incluindo pseudo-relevance feedback como RM3.

#v(.4em)

= Proposta

Este trabalho propõe uma análise comparativa entre modelos esparsos, semânticos e híbridos no contexto jurídico brasileiro. A seguir são as abordagens avaliadas:

#v(.7em)

#grid(
  columns: 2,
  column-gutter: 7pt,
  [
    #align(left + top)[
      *Modelos Esparsos*#linebreak()
      #v(-.7em)#linebreak()
      - BM25+ (_offset_ positivo)#v(-.8em)#linebreak()
      - BMX (_entropy-weighted_)#v(-.8em)#linebreak()
      - Lucene (suavização do IDF)#v(-.8em)#linebreak()
      - ATIRE (normalização alternativa)#v(-.8em)#linebreak()
      - Pyserini com RM3 (PRF)#v(-.7em)#linebreak()
      - BM25 Robertson (Baseline)#linebreak()
    ]
  ],
  [
    #align(left + top)[
      #align(center + top)[*Modelos Semânticos*]#linebreak()
      #v(-.9em)
      #grid(
        columns: 2,
        gutter: 17pt,
        [
      #v(-.9em)#linebreak()
      _Modelos Base_
      #v(-.9em)#linebreak()
      - Qwen-Embedding-0.6B#v(-.8em)#linebreak()
      - embeddinggemma-300m#v(-.8em)#linebreak()
      - gte-multilingual-base#v(-.8em)#linebreak()
      - jina-embeddings-v3#v(-.8em)#linebreak()
        ],
        [
      #v(-.9em)#linebreak()
      _Variantes Pré-treinadas_
      #v(-.9em)#linebreak()
      - qwen-pgm-pairs#v(-.8em)#linebreak()
      - gemma-pgm-pairs#v(-.8em)#linebreak()
      - gte-pgm-pairs#v(-.8em)#linebreak()
      Treinadas no _dataset_ da#linebreak()PGM-Rio, conforme @Unknown202XFineTuningLegalBrasil
        ]
      )
    ]
  ]
)

#v(1em)

Para os modelos híbridos:

#v(.8em)

#align(top + center)[*Modelos Híbridos*]
#align(center)[
#grid(
  columns: (171pt, -65pt, 171pt, 153pt),
  align: top,
  column-gutter: (30pt, 49pt, 10pt),
  [
    #v(-.6em)#linebreak()
    #align(top + left)[
    _Algoritmos de Fusão_#v(-.8em)#linebreak()
    - _Reciprocal-Rank Fusion_ (RRF)#v(-.7em)#linebreak()
    - _Multiple Number of Zeros_ (MNZ)#v(-.7em)#linebreak()
    - _Weighted_ MNZ (WMNZ)#v(-.7em)#linebreak()
    - _Weighted_ SUM (WSUM)#v(-.7em)#linebreak()
    - _Mixed_ = WMNZ + WSUM#v(-.7em)#linebreak()
    _E muitos outros algoritmos de fusão $dots$_
    ]
  ],
  [
    #v(49pt)
    \+
  ],
  [
    #v(-.6em)#linebreak()
    #align(top + left)[
    #h(-15pt)_Estratégias de Normalização_#v(-.8em)#linebreak()
    _Min-Max Scaling_#v(-.7em)#linebreak()
    _Max Normalization_ (MNZ)#v(-.7em)#linebreak()
    _Sum Normalization_#v(-.7em)#linebreak()
    _Z-Score Mean-Unit Variance_ (Z-MUV)#v(-.7em)#linebreak()
    _Rank-Based Normalization_#v(-.7em)#linebreak()
    _E outras estratégias de normalização $dots$_
  ]],
  [
    #v(-.6em)#linebreak()
    #align(top + left)[
    _Reranqueadores_#v(-.8em)#linebreak()
    - bge-reranker-base#v(-.7em)#linebreak()
    - gte-multilingual-reranker#v(-.7em)#linebreak()
    ]
  ]
)
]

== Hipóteses

A análise experimental busca testar as seguintes hipóteses:

// #v(-10pt)

#show figure.where(kind: "hipo"): it => block[
  #let n = counter("hipo").step()
  #v(11pt)
  #it.caption
  #v(3pt)
  #it.body
  #v(30pt)
]

#figure(
  [
    #block(width: 78%)[
      #align(left)[
        Métodos de busca híbrida, que combinam BM25 e recuperadores densos
        por meio de algoritmos de fusão ou re-ranqueadores, resultam em
        melhorias estatisticamente significativas em relação ao BM25
        _baseline_ e ao melhor recuperador denso isolado. 
      ]
    ]
  ],
  supplement: "Hipótese",
  kind: "hipo",
  caption: [_Busca Híbrida $times$ Baseline._]
) <hip1>


#v(-21pt)

#figure(
  [
    #block(width: 77%)[
      #align(left)[
        Segundo o artigo base @Wang2021InterpolateDR, os ganhos relativos
        obtidos pela busca híbrida são mais expressivos nas métricas profundas
        (R\@1000, nDCG\@1000), em comparação às métricas rasas.
      ]
    ]
  ],
  supplement: "Hipótese",
  kind: "hipo",
  caption: [_Métricas rasas $times$ Métricas profundas._]
) <hip2>

#v(-29pt)

= Implementação

== Base de Dados

O estudo emprega o *JurisTCU*, _dataset_ de _Legal Information Retrieval_
composto por 16.045 decisões do TCU e 150 consultas anotadas com julgamento de
relevância. As consultas compreendem três grupos: (i) Consultas reais submetidas
por usuários do sistema, (ii) consultas sintéticas em formato de palavras-chave
e (iii) consultas sintéticas em formato de pergunta, ambas geradas por LLMs.
Neste trabalho, todas as consultas foram avaliadas conjuntamente para produzir
uma estimativa global de desempenho.

== BM25

#set par(first-line-indent: 0em)

A _pipeline_ de pré-processamento implementada consiste nas seguintes etapas:

#v(.6em)

+ Persistência dos campos de indexação do artigo no banco de dados;#v(.2em)
+ Extração de arquivos HTML usando `BeautifulSoup4`;#v(.2em)
+ Normalização de termos jurídicos específicos (ex. "art. n#super[o]" $->$ "artigo número");#v(.2em)
+ Aplicação do RSLP Stemmer desenvolvido para língua portuguesa;#v(.2em)

#v(.6em)

#set par(first-line-indent: 15pt)

As implementações utilizam diferentes bibliotecas especializadas: `bm25s`
(biblioteca moderna e performática para BM25), `pyserini` (para BM25 com RM3) e
`baguetter` do MixedBread (para BMX).

== Sentence Embeddings

O processamento dos _embeddings_ segue o fluxo abaixo:

#v(.6em)

+ Segmentação dos documentos em passagens por meio da biblioteca `langchain-text-splitters` com `chunk_size` = 1024;#v(.2em)
+ Computação dos _embeddings_ com dimensão de 768 para cada segmento usando os modelos selecionados;#v(.2em)
+ Agregação dos _embeddings_ usando _Aggregate Mean Pooling_;#v(.2em)

#v(.6em)

Os _embeddings_ são armazenados no DuckDB, um banco de dados embarcado OLAP
otimizado para operações analíticas.

== Reranqueadores <abord:rerank>

O processo de re-ranqueamento consiste em:

#v(.6em)

+ União e deduplicação dos resultados das etapas anteriores (BM25 e _embeddings_);#v(.2em)
+ Re-ranqueamento dos resultados desconsiderando os _scores_ anteriormente atribuídos, computando novos _scores_ com modelos como `gte-multilingual-reranker`.#v(.2em)

#v(.6em)

Os re-ranqueadores processam conjuntamente a consulta a cada documento
candidato, produzindo novos _scores_ que refletem a relevância semântica do par.

== Estudo de Ablação <hiper>

Esta etapa consiste na parametrização sistemática dos modelos avaliados. Para os
métodos esparsos, o foco recai para os fatores de suavização do BM25, tais como
o $k_1$ que controla a saturação da frequência de termos e $b$ que regula a
normalização pelo comprimento do documento. No caso dos métodos híbridos, a
ablação incide sobre os algoritmos de fusão disponibilizados pela biblioteca
`ranx`, os pesos empregados na combinação entre buscadores e as respectivas
estratégias de normalização.

#v(6pt)

Visto isso, adotaram-se três etapas complementares:

#v(4pt)

1. _Random Search_ para BM25: Realizou-se uma busca estocástica nos hiperparâmetros $k_1 in [0.3, 3.0]$ e $b in [0.0, 1.0]$, avaliando-se cada variante do BM25 e seus parâmetros específicos ($b$, $k_1$, $delta$, $alpha$, $beta$). Retive-se exclusivamente a configuração com maior MAP.

#v(7pt)

2. Seleção dos candidatos: Concluída a busca dos hiperparâmetros do BM25, selecionou-se o modelo de _embeddings_ com maior MAP no conjunto integral de consultas. Definiram-se, assim, os dois sistemas submetidos às fases subsequentes de re-ranqueamento e fusão.

#v(7pt)

3. _Grid Search_ para fusão híbrida: Executou-se combinação simétrica entre algoritmos de fusão (RRF, MNZ, WMNZ, WSUM, $dots$) e estratégias de normalização (`min-max`, `sum`, `zmuv`, `rank`, `borda` $dots$) totalizando 132 configurações avaliadas.

#v(4pt)

A seguir, apresenta-se um esquema das etapas realizadas.

#v(-11pt)

#align(center)[
#figure(
  image("hiper.png", width: 91%),
  supplement: "Diagrama",
  caption: [
    #h(0pt)1#super[a] Fase: _Busca de hiperparâmetros e seleção de candidatos._#linebreak()#h(87pt)2#super[a] Fase: _Re-ranqueamento com resultado dos candidatos ou fusão_.]
)
]

#v(-14pt)



= Resultados

Os resultados são apresentados em dois grupos de métricas, em linha com @Wang2021InterpolateDR:

#v(6pt)

- *Métricas rasas*: Avaliam a qualidade do topo do _ranking_ $(k <= 10)$, incluindo P\@K, R\@K, F1\@10, Hit\@10 e nDCG\@K;

#v(6pt)

- *Métricas profundas*: Consideram o _ranking_ em maior profundidade, como MAP, R-Prec, R\@100/R\@1000 e nDCG\@100/nDCG\@1000;

#v(6pt)

*Observação*: Por simplicidade, não foi possível disponibilizar todas as métricas calculadas no artigo presente. Portanto, refira-se ao #underline[#link("https://github.com/saitoi/projeto-final-ri")[repositório]].

#v(6pt)

Neste trabalho, o MAP é adotado como métrica-síntese global, enquanto P\@10, R\@10 e
nDCG\@10 caracterizam a qualidade no topo da lista e R\@1000/nDCG\@1000 indicam
a capacidade de cobertura em profundidade. A tabela a seguir resume os
resultados para todos os modelos avaliados:

#align(center)[
#figure(caption: [
  MAP, métricas rasas e profundas
  para os grupos 1–3. Valores em *negrito* indicam o melhor resultado dentro de cada categoria
  (Esparso, Semântico, Re-ranqueadores, Fusão). Valores em #box(fill: rgb("#DAA520"), inset: 1pt)[dourado]
  indicam a melhor métrica global em cada coluna.])[
#text(size: 8.3pt)[
#table(
  columns: 8,
  column-gutter: 4pt,
  row-gutter: 1pt,
  align: (left, left, center, center, center, center, center, center),
  stroke: none,
  inset: (x, y) => (
    x: if y == 0 or y == 1 or x == 1 { 2.1pt } else { 0pt },
    y: if y == 0 or y == 1 { 4pt } else if y == 2 { 3pt } else if y == 3 { 2.9pt } else if x == 1 { 1.4pt } else { 1.1pt }
  ),

  // Cabeçalho
  table.hline(stroke: .6pt),
  table.cell(rowspan: 2, [*Tipo*], align: horizon),
  table.cell(rowspan: 2, [*Modelo*], align: horizon),
  table.cell(rowspan: 2, [*MAP*], align: horizon),
  table.cell(colspan: 3, [*Métricas Rasas* $(k <= 10)$]),
  table.cell(colspan: 2, [*Métricas Profundas*]),

  table.hline(start: 3, end: 6, stroke: 0.3pt),
  table.hline(start: 6, end: 8, stroke: 0.3pt),

  [P\@10], [R\@10], [nDCG\@10], [R\@1000], [nDCG\@1000],

  table.hline(stroke: .6pt),
  table.cell(colspan: 8, []),

  // Modelos Esparsos
  table.cell(rowspan: 7, [Esparso], align: horizon),
  [BM25+ ($k_1$=1,8, $b$=0,75, $delta$=1,5)],
    [*0.309*], [*0.341*], [*0.292*], [*0.440*], [0.871], [0.638],
  [BM25L ($k_1$=1,0, $b$=0,75, $delta$=1,5)],
    [*0.309*], [0.336], [0.288], [0.438], [*0.875*], [*0.639*],
  [Lucene ($k_1$=2,5, $b$=0,6)],
    [*0.309*], [0.336], [0.288], [0.438], [*0.875*], [*0.639*],
  [ATIRE ($k_1$=2,5, $b$=0,6)],
    [0.308], [0.336], [0.288], [0.438], [*0.875*], [*0.639*],
  [BMX ($k_1$=2.5, $b$=0,7, $alpha$=1,0, $beta$=0.0)],
    [0.305], [0.335], [0.286], [0.434], [0.872], [0.636],
  [Pyserini ($k_1$=2,0, $b$=0,5)],
    [0.302], [0.339], [0.289], [0.439], [0.864], [0.636],
    [Robertson (Baseline) ($k_1$=2,5, $b$=0,7)],
    [0.296], [0.325], [0.279], [0.417], [0.869], [0.621],

  table.cell(colspan: 8, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 8, []),

  // Modelos Semânticos
  table.cell(rowspan: 6, [Semântico], align: horizon),
  [jina-embeddings-v3],
    [*0.402*], [*0.443*], [*0.376*], [*0.532*], [*0.908*], [*0.702*],
  [Qwen-Embedding-0.6B],
    [0.373], [0.402], [0.340], [0.511], [0.877], [0.684],
  [gte-multilingual-base (Alibaba)],
    [0.329], [0.372], [0.313], [0.458], [0.870], [0.644],
  [gte-lamdec-pairs],
    [0.300], [0.337], [0.284], [0.416], [0.863], [0.607],
  [gemma-lamdec-pairs],
    [0.154], [0.193], [0.162], [0.240], [0.714], [0.412],
  [qwen-lamdec-pairs],
    [0.143], [0.167], [0.141], [0.216], [0.689], [0.393],

  table.cell(colspan: 8, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 8, []),

  // Re-ranqueadores
  table.cell(rowspan: 2, [Re-ranqueadores], align: horizon),
  [gte-multilingual-reranker-base],
    [*0.364*], [*0.401*], [*0.339*], [*0.504*],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.919]], [*0.697*],

  [bge-reranker-base],
    [0.195], [0.219], [0.183], [0.279], [0.883], [0.513],

  table.cell(colspan: 8, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 8, []),

  // Fusão
  table.cell(rowspan: 5, [Fusão], align: horizon),
  [_Mixed_ (WMNZ + WSUM) (norm=sum)],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.462]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.493]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.420]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.605]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.919]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.764]],

  [Sum Fusion (norm=sum)],
    [0.461], [0.492], [0.419], [0.604],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.919]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.764]],

  [Weighted Sum (norm=sum)],
    [0.461], [0.492], [0.419], [0.604],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.919]],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.764]],

  [MNZ (Min-Non-Zero) (norm=sum)],
    [0.461], [0.492], [0.419], [0.604],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.919]],
    [0.763],

  [GMNZ (Geometric MNZ) (norm=sum)],
    [0.461], [0.492], [0.419], [0.604],
    [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.919]],
    [0.763],

  table.hline(stroke: .6pt),
)
]
] <res:tbl1>
]

#v(-7pt)

*Observação*: A métrica P\@1000 foi omitida pois assumiu o valor 0,011 para praticamente todos os modelos e, desse modo, não agregou informações relevantes às análises. 

#v(4pt)

// começe falando sobre os algoritmos de fusão que obtiveram o melhor MAP.
// Emende falando o que já está embaixo sobre o jina, ou seja, só continue..

A partir da @res:tbl1, verifica-se que os algoritmos de fusão obtiveram os
melhores resultados globais. O _Mixed_ (WMNZ + WSUM) com normalização `sum`
alcançou MAP de 0,462 superando todas as demais abordagens em métricas rasas e
profundas. Como esperado, os modelos semânticos superaram os
lexicais puros. O `jina-embeddings-v3` apresentou o maior MAP na categoria
semântica $(0,402)$ e dominou tanto as métricas rasas quanto as profundas quando
comparado às variante do BM25, constituindo um recuperador denso altamente
competitivo.

Esse resultado é consistente com o artigo original do JurisTCU @Fernandes2025JurisTCU, no
qual os _embeddings_ são computados apenas sobre o campo de resumo (`summary`), enquanto o
BM25 opera sobre o texto integral (`enunciado`). Tal configuração favorece modelos semânticos
ao reduzir o ruído lexical. Por outro lado, o desempenho superior do Jina sobre
o GTE diverge dos achados de Vargas @Unknown202XFineTuningLegalBrasil, que
reportou nDCG\@20 de 0,533 para o GTE contra 0,517 para o Jina em similaridade
fraca. As diferenças podem ser atribuídas às diferenças entre os _datasets_ e o
objetivo das consultas.

Notavelmente, os re-ranqueadores apresentaram desempenho inferior aos melhores
modelos semânticos, em particular, o `gte-multilingual-reranker-base` obteve MAP
de 0,364, abaixo do `jina-embeddings-v3` (0,402). Esse achado sugere que a
estratégia de unir e deduplicar os resultados dos sistemas léxicos e semânticos
descrita na @abord:rerank, descartando os _scores_ originais, não foi eficaz.

As variantes pré-treinadas no _dataset_ jurídico da PGM-Rio com sufixo
`-lamdec-pairs` não apresentaram o desempenho esperado. Os modelos
`gemma-lamdec-pairs` e `qwen-lamdec-pairs` obtiveram MAP de 0,154 e 0,143,
respectivamente. Tais resultados são inferiores até mesmo à _baseline_ BM25
Robertson (0,296). Isso sugere que o _fine-tuning_ em um domínio jurídico
específico pode não generalizar para outros.

Entre os modelos esparsos, as variantes do BM25 apresentaram desempenho similar
entre si, com MAP variando de 0,296 (Robertson) a 0,309 (BM25+, BM25L,
_Lucene_), indicando baixa sensibilidade à escolha da variante após a etapa de
otimização dos hiperparâmetros.

Por fim, os ganhos da fusão híbrida foram mais expressivos nas métricas rasas
$(+36,7%)$ do que nas profundas $(+16,27%)$, conforme a @shallow_deep_tbl. Essa
diferença de 20,5 pontos percentuais indica que a combinação de sinais léxicos e
semânticos beneficia principalmente a qualidade dos primeiros resultados
apresentados ao usuário.

#v(-12pt)

#figure(
  table(
    columns: (auto, auto),
    align: (left, center),
    stroke: none,
    inset: 5pt,
    table.header(
      [*Categoria*],
      [*Ganho Médio*],
    ),
    table.hline(),
    [Métricas Rasas],
    [+36.7%],
    [Métricas Profundas],
    [+16.2%],
    table.hline(),
    [#text(weight: "bold")[Diferença]],
    [+20.5pp],
  ),
  caption: [Comparação de ganhos: Métricas rasas $times$ profundas]
) <shallow_deep_tbl>

#v(-15pt)

*Observação*: O ganho foi calculado com base em todas as métricas rasas obtidas no código original e, portanto, não se restringe às métricas expostas na @res:tbl1.

== Hiperparâmetros

A @hiper_study ilustra a evolução do MAP ao longo das 570 configurações avaliadas. A variação é expressiva: de 0,008 (RRF com normalização `borda`) a 0,453 (_Mixed_ com normalização `sum`), evidenciando alta sensibilidade à escolha do algoritmo de fusão e da estratégia de normalização.

#figure(
  image("hyperparameter_study.png", width: 75%),
caption: [_Comparação entre estratégias de fusão e normalização segundo o _MAP_ durante a etapa de Grid Search._]
) <hiper_study>

== Desempenho

A @res:tempo apresenta o tempo de execução por consulta para cada modelo. A ordenação dos resultados corresponde às expectativas: Modelos esparsos são os mais rápidos (mediana $tilde 1,2$ ms), seguidos dos semânticos ($tilde 83\-107$ ms), algoritmos de fusão ($tilde 129\-138$ ms) e, por fim, re-ranqueadores ($tilde 6.424-82.165$ ms).

Comparando as duas abordagens híbridas, os algoritmos de fusão são significativamente mais eficientes que os re-ranqueadores. O _Mixed_ (WMNZ + WSUM) apresenta mediana de $136,6$ ms, enquanto o `bge-reranker-base` requer 6.424 ms, ou seja, cerca de 47 _vezes_ mais lento.

#align(center)[
#figure(caption: [Tabela. Tempo de execução de consultas para o grupo 1, 2, 3. Valores em *negrito* indicam o menor tempo (mais rápido) dentro de cada categoria. Valores em #box(rect(fill: rgb("#90EE90"), inset: 1pt)[verde]) indicam o menor tempo global.])[
#text(size: 8.4pt)[
#table(
      columns: 7,
      column-gutter: 3pt,
      row-gutter: 1pt,
      align: (left, left, center, center, center, center, center),
      stroke: none,
      inset: (x, y) => (
        x: if y == 0 or y == 1 or x == 1 { 0pt } else { 0.5pt },
        y: if y == 0 or y == 1 { 4pt } else if y == 2 { 3.1pt } else if y == 3 { 3.1pt } else if x == 1 { 1.9pt } else { 2pt }
      ),

      // Header rows
      table.hline(stroke: .6pt),
      table.cell(rowspan: 2, [*Tipo*], align: horizon),
      table.cell(rowspan: 2, [*Modelo*], align: horizon),
      table.cell(colspan: 5, [*Tempo de Consulta (ms)*]),

      table.hline(start: 2, end: 7, stroke: 0.3pt),

      // Sub-headers
      [Média], [Mediana], [P95], [P99], [Máx],

      table.hline(stroke: .6pt),
      table.cell(colspan: 7, []),

      // Modelos Esparsos
      table.cell(rowspan: 7, [Esparso], align: horizon),
      [BM25+], [#rect(fill: rgb("#90EE90"), inset: 1pt)[1.248]], [#rect(fill: rgb("#90EE90"), inset: 1pt)[1.219]], [#rect(fill: rgb("#90EE90"), inset: 1pt)[1.429]], [#rect(fill: rgb("#90EE90"), inset: 1pt)[1.517]], [4.071],
      [BM25L], [1.274], [1.249], [1.463], [1.803], [4.062],
      [Lucene], [1.265], [1.231], [1.500], [1.636], [4.037],
      [ATIRE], [1.302], [1.231], [1.696], [2.440], [4.284],
      [BMX], [3.920], [1.734], [2.231], [2.930], [325.695],
      [Pyserini BM25 com RM3], [41.844], [41.084], [48.478], [52.060], [124.087],
      [BM25 Robertson (Baseline)], [1.351], [1.293], [1.823], [2.966], [#rect(fill: rgb("#90EE90"), inset: 1pt)[3.890]],

      table.cell(colspan: 7, []),
      table.hline(stroke: .6pt),
      table.cell(colspan: 7, []),

      // Modelos Semânticos
      table.cell(rowspan: 6, [Semântico], align: horizon),
      [jina-embeddings-v3], [95.789], [93.657], [100.710], [106.097], [371.476],
      [Qwen-Embedding-0.6B], [102.256], [101.723], [107.587], [111.873], [165.264],
      [gte-multilingual-base], [*83.274*], [*82.622*], [*90.318*], [*92.333*], [129.927],
      [gte-lamdec-pairs], [91.982], [91.799], [99.843], [102.641], [*107.524*],
      [gemma-lamdec-pairs], [105.013], [104.405], [111.565], [114.790], [120.042],
      [qwen-lamdec-pairs], [107.881], [106.342], [119.141], [125.193], [126.472],

      table.cell(colspan: 7, []),
      table.hline(stroke: .6pt),
      table.cell(colspan: 7, []),

      // Re-ranqueadores
      table.cell(rowspan: 2, [Re-ranqueadores], align: horizon),
      [gte-multilingual-reranker-base],
      [85311.906], [82165.312], [111014.787], [132483.799], [148444.723],
      [bge-reranker-base],
      [*6433.176*], [*6424.173*], [*6847.512*], [*6985.753*], [*7190.475*],

      table.cell(colspan: 7, []),
      table.hline(stroke: .6pt),
      table.cell(colspan: 7, []),

      // Fusão
      table.cell(rowspan: 5, [Fusão], align: horizon),
      [_Mixed_ (WMNZ + WSUM)], [137.362], [136.604], [143.119], [148.792], [194.907],
      [Sum Fusion], [131.342], [130.926], [137.001], [142.557], [200.150],
      [Weighted Sum], [138.660], [137.988], [145.639], [148.696], [211.934],
      [MNZ (Min-Non-Zero)], [*129.172*], [*128.746*], [*134.893*], [*137.543*], [*187.551*],
      [GMNZ (Geometric MNZ)], [134.204], [133.607], [140.578], [145.428], [208.638],

      table.hline(stroke: .6pt),
    )
  ]
] <res:tempo>
]

#v(-17pt)

== Configuração

Os experimentos foram executados no ambiente descrito na @tbl:config. Os testes
e avaliações utilizaram Python 3.13 e CUDA 13.0, e os modelos densos e
re-ranqueadores foram servidos por meio do framework PyTorch 2.9.1.

#v(15em)

#place(dx: 81pt, dy: -165pt)[
#figure(caption: [_Configurações do Ambiente Computacional utilizado._])[
#text(size: 9pt)[
#table(
    columns: 2,
    inset: 4pt,
    align: (center, left),
    stroke: none,
    row-gutter: 4pt,
    // fill: (x, y) => if calc.odd(y) { rgb("#f0fafc") },
    [*Componente*], [*Configuração*],
    table.hline(stroke: .6pt),
    [CPU], [Intel(R) Core(TM) i7-10700 CPU \@ 2.90GHz],
    [RAM], [94GB],
    [GPU], [2 × NVIDIA RTX (8 GB cada)],
    [Disco], [907GB (`/`)],
    [SO], [Debian GNU/Linux 12 (bookworm)],
  )
]
] <tbl:config>
]

== Comparação

A @tbl:cmp reproduz os resultados do artigo JurisTCU apenas para o Grupo 3 (consultas em formato de pergunta). Este cenário favorece métodos léxicos, visto que as perguntas tendem a compartilhar vocabulário com os documentos, elevando a _baseline_ do BM25.

#v(-8pt)

#align(center)[
#figure(caption: [Comparação com o artigo JurisTCU (Grupo 3). Valores em #box(fill: rgb("#DAA520"), inset: 1pt)[dourado] indicam o melhor resultado de cada métrica; Trechos em #box(fill: rgb("#ADD8E6"), inset: 1pt)[azul] correspondem aos modelos deste trabalho.])[
#text(size: 9pt)[
#table(
      columns: 6,
      column-gutter: 4pt,
      row-gutter: 1pt,
      align: (left, left, center, center, center, center),
      stroke: none,
      inset: (x, y) => (
        x: if y == 0 or y == 1 or x == 1 { 3pt } else { 0.5pt },
        y: if y == 0 or y == 1 { 4pt } else if y == 2 { 3pt } else { 1.5pt }
      ),

      // Header
      table.hline(stroke: .6pt),
      table.cell(rowspan: 2, [*Tipo*], align: horizon),
      table.cell(rowspan: 2, [*Modelo*], align: horizon),
      table.cell(colspan: 4, [*Métricas \@10*]),

      table.hline(start: 2, end: 6, stroke: 0.3pt),
      [P\@10], [R\@10], [MRR], [nDCG\@10],

      table.hline(stroke: .6pt),
      table.cell(colspan: 6, []),

      // Modelos Esparsos (BM25)
      table.cell(rowspan: 9, [Esparso], align: horizon),
      [BM25 (baseline)], [0.388], [0.345], [0.918], [0.533],
      [BM25.dT5q], [0.408], [0.362], [0.939], [0.556],
      [BM25.Syn(GPT3.5)], [0.406], [0.361], [0.915], [0.546],
      [BM25.Syn(GPT4o)], [0.408], [0.363], [0.934], [0.552],
      [BM25.Syn(Llama3)], [0.396], [0.352], [0.923], [0.541],
      [BM25.dT5q.Syn(GPT35)], [0.416], [0.369], [0.919], [0.557],
      [BM25.dT5q.Syn(GPT4o)], [0.416], [0.369], [0.940], [0.564],
      [BM25.dT5q.Syn(Llama3)], [*0.420*], [*0.372*], [0.929], [*0.564*],
      [#rect(fill: rgb("#ADD8E6"), inset: 2pt)[BM25+ (k1=3.0, b=0.6)]], [0.402], [0.358], [*0.943*], [0.551],

      table.cell(colspan: 6, []),
      table.hline(stroke: .6pt),
      table.cell(colspan: 6, []),

      // Modelos Semânticos (Embeddings)
      table.cell(rowspan: 7, [Semântico], align: horizon),
      [BERT.pt.TCU], [0.202], [0.180], [0.608], [0.288],
      [BERT.pt.large], [0.222], [0.196], [0.607], [0.289],
      [BERT.pt.large.legal], [0.348], [0.307], [0.868], [0.466],
      [BERT.ml], [0.344], [0.305], [0.792], [0.452],
      [OpenAI.small], [0.482], [0.425], [0.917], [0.609],
      [OpenAI.large], [0.472], [0.415], [0.915], [0.608],
      [#rect(fill: rgb("#ADD8E6"), inset: 2pt)[Qwen-Embedding-0.6B]], [*0.500*], [*0.440*], [*0.982*], [*0.654*],

      table.cell(colspan: 6, []),
      table.hline(stroke: .6pt),
      table.cell(colspan: 6, []),

      // Fusão (Nosso)
      table.cell(rowspan: 1, [Fusão], align: horizon),
      [#rect(fill: rgb("#ADD8E6"), inset: 2pt)[Fusão MNZ (norm=zmuv, k=20)]], [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.554]], [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.490]], [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.990]], [#rect(fill: rgb("#DAA520"), inset: 1pt)[0.698]],

      table.hline(stroke: .6pt),
    )
  ]
] <tbl:cmp>
]

// complete a frase, dizendo que  comparação entre o fusao e o melhor mod elo do artigo original nao é totalmente justa por que o qwen por si só já supera.
// mas dito isso, os resultados da busca híbrida ainda são relevantes
// comente da otimização dos parametros do bm25 que ele consegue uma performance comparavel mesmo sem usar a tecnica de expansao de consulta como nos outros modelos descritos.

No bloco semântico, o modelo `Qwen-Embedding-0.6B`, menor e aberto,
supera os _embeddings_ da OpenAI utilizados no artigo, em todas as métricas. Assim, como o Qwen, mesmo sem ajuste adicional, já supera todos os modelos semânticos do artigo original, a comparação direta entre a fusão proposta e o melhor modelo do estudo de referência torna-se assimétrica. Apesar disso, os resultados da busca híbrida demonstram ganhos reais superando o Qwen em P\@10 $(+10,8%)$ e nDCG\@10 (+6,7%).
// Essa superioridade implica que a comparação entre a fusão híbrida e o melhor
// modelo do artigo original não é equilibrada, pois o Qwen
// isolado já ultrapassa os resultados reportados. Ainda assim, os ganhos da
// busca híbrida permanecem relevantes: o MNZ alcançou P\@10 de 0,554 e
// nDCG\@10 de 0,698, superando o Qwen em 10,8% e 6,7%,
// respectivamente.

No bloco esparso, o BM25+ com $k_1=3,0$ e $b=0,6$, parâmetros obtidos via _Random Search_, atinge MRR de 0,943, superando todas as variantes do artigo nessa métrica. O resultado dá indícios de que a otimização de hiperparâmetros pode alcançar desempenho comparável às técnicas de expansão de consulta (dT5q, Syn) sem a complexidade adicional dessas abordagens.

== Teste de Hipótese

Para verificação dos resultados, foi conduzido o teste não paramétrico de Wilcoxon pareado, que dispensa pressupostos de normalidade na distribuição dos dados, comparando a mediana da diferença entre as precisões médias das consultas. Adotou-se um nível de significância de $alpha=0,05$.

#figure(
  table(
    columns: (auto, auto, auto),
    align: (left, center, center),
    stroke: none,
    inset: 5pt,

    // Header
    table.header(
      [*Comparação*],
      [*Estatística W*],
      [*P-valor*],
    ),
    table.hline(),

    // BM25 Robertson vs Fusion Mixed
    [BM25 Robertson $times$ Fusion Mixed],
    [165.00],
    [< 0.000001],

    // Embedding Jina vs Fusion Mixed
    [Embedding Jina $times$ Fusion Mixed],
    [3104.00],
    [< 0.000002],
  ),
  caption: [Resultados dos Testes de Wilcoxon $(alpha = 0.05)$]
)

#v(-1.4em)

Os resultados do teste de Wilcoxon $(alpha = 0,05)$ rejeitam as hipóteses nulas de equivalência entre:
#v(5pt)
- BM25 Robertson (_baseline_) e _Fusion Mixed_ $(p < 0.000001)$;
#v(5pt)
- `jina-embeddings-v3` e _Fusion Mixed_ $(p < 0.000002).$
#v(5pt)
Portanto, conclui-se que o método de fusão supera significativamente tanto a _baseline_ esparsa quanto o melhor modelo denso isolado.

= Conclusão

Este trabalho apresentou uma análise comparativa de métodos de recuperação da informação no contexto jurídico brasileiro, avaliando abordagens lexicais, semânticas e híbridas sobre o _dataset_ JurisTCU.

Os resultados confirmam a @hip1: a busca híbrida supera consistentemente métodos puramente lexicais ou semânticos. O algoritmo _Mixed_ (WMNZ + WSUM) alcançou MAP de 0,462, representando ganhos de 56% sobre a _baseline_ Robertson (0,296) e 15% sobre o melhor modelo denso isolado, o `jina-embeddings-v3` (0,402). A significância estatística dessas diferenças foi confirmada pelo teste de hipótese de Wilcoxon.

Com relação à @hip2, observou-se um comportamento distinto, os ganhos da fusão foram mais expressivos nas métricas rasas $(+36,7%)$ do que nas profundas $(+16,2%)$. Isso sugere que a combinação de sinais lexicais e semânticos beneficia principalmente os primeiros resultados.

Adicionalmente, constatou-se que: (i) modelos pré-treinados em domínios jurídicos específicos nem sempre generalizam para outros _datasets_ da mesma área; (ii) a otimização de hiperparâmetros do BM25 pode alcançar desempenho comparável a técnicas de expansão de consulta; e (iii) algoritmos de fusão podem oferecer melhor eficiência para níveis superiores ou comparáveis de performance em comparação aos re-ranqueadores.

= Trabalhos Futuros

Como extensão deste estudo, identifiquei as seguintes direções de pesquisa:

#v(4pt)

- _Retrieval-Augmented Knowledge Graph_: Expansão de consulta baseada em grafo de conhecimento gerado com entidades nomeadas extraídas via GliNER. Permite enriquecer a recuperação com relações estruturadas entre conceitos e termos do _corpus_.
// - _Retrieval-Augmented Knowledge Graph_: Construção de um grafo de conhecimento empregando o GliNER para reconhecimento e extração de entidades nomeadas, permitindo expansão de consulta. Essa abordagem permite enriquecer a recuperação com relações estruturadas entre conceitos jurídicos.
- Validação em outros _datasets_: Replicação no _dataset_ _Ulysses Relevance Feedback Corpus_ (105.669 documentos), para avaliar a generalização das conclusões para outros domínios jurídicos.

#v(-16pt)