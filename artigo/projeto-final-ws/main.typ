#import "lib.typ": sbc, institute, author

#let inst_ufrj = institute(
  "Instituto de Computação – Universidade Federal do Rio de Janeiro (UFRJ)",
  addr: "Rio de Janeiro – RJ – Brasil",
)

// Cores e helpers da tabela de desempenho por consulta
#let soft-blue = rgb("#dbeafe")
#let soft-green = rgb("#dcfce7")
#let soft-yellow = rgb("#fef9c3")
#let soft-orange = rgb("#ffedd5")
#let soft-red = rgb("#fee2e2")
#let cell-time(v, s) = {
  let f = if v < 2.0 { soft-green } else if v < 15.0 { soft-yellow } else if v < 60.0 { soft-orange } else { soft-red }
  table.cell(fill: f)[#s]
}
#let cell-to = table.cell(fill: soft-red)[T/O]

#show: sbc.with(
  title: [FedShop-Go: Um Motor de Consultas SPARQL Federadas Mínimo Avaliado com o Benchmark FedShop],
  authors: (
    author(
      "Pedro Henrique Honorio Saito",
      insts: (inst_ufrj),
      email: "phenriquesaito@gmail.com",
      note: [DRE: 122149392],
    ),
  ),
  abstract: [#set text(lang: "en")
    This work presents *FedShop-Go*, a federated SPARQL query engine
    implemented in Go and evaluated with the _FedShop_ benchmark over
    federations of varying size, alongside *fedshop-py*, a reproducible Python
    pipeline that replaces the original FedShop orchestrator. The evaluation
    compares six engines on the 12 query templates derived from the Berlin
    SPARQL Benchmark (BSBM). FedShop-Go outperforms FedX on single-domain
    queries (q06--q12) with speedups between 3$times$ and 20$times$, but
    suffers timeouts on cross-domain queries with large intermediate results
    (q02, q05). ASK-based source selection accounts for approximately 13% of
    total execution time, confirming its low relative overhead.
  ],
  resumo: [
    Este trabalho apresenta o *FedShop-Go*, um motor de consultas SPARQL
    federadas implementado em Go e avaliado com o benchmark _FedShop_ sobre
    federações de tamanho variável, junto ao *fedshop-py*, um pipeline
    reprodutível em Python que substitui o orquestrador original do FedShop. A
    avaliação compara seis motores nos 12 templates de consulta derivados do
    Berlin SPARQL Benchmark (BSBM). O FedShop-Go supera o FedX nas consultas
    de domínio único (q06--q12), com _speedups_ entre 3$times$ e 20$times$,
    mas enfrenta _timeouts_ nas consultas de domínio cruzado com alto volume
    intermediário (q02, q05). A seleção de fontes via consultas `ASK` consome
    cerca de 13% do tempo total, confirmando sua baixa sobrecarga relativa.
  ],
  bibliography: bibliography("refs.bib", style: "sbc.csl"),
)

#set text(lang: "pt")

= Introdução

Consultas SPARQL federadas permitem que um cliente explore múltiplos
repositórios RDF simultaneamente, tratando a federação como uma fonte de dados
unificada @sparql11. À medida que a Web de Dados Ligados cresce, federações com
dezenas ou centenas de _endpoints_ tornam-se comuns, introduzindo desafios
fundamentais: Quais _endpoints_ contêm dados relevantes para cada padrão de
tripla? Em que ordem executar os padrões para minimizar a transferência de
dados intermediários? Como garantir robustez diante de _endpoints_ lentos ou
instáveis?

O benchmark *FedShop* @fedshop foi proposto para medir escalabilidade de
motores federados em cenários próximos à realidade, com federações que crescem
de 20 a 200 _endpoints_ e 12 templates de consulta derivados do Berlin SPARQL
Benchmark (BSBM) @bsbm. Apesar de seu valor, reproduzir e estender experimentos
com o FedShop original requer poder computacional adequado para gerar e
avaliar localmente federações de até 200 membros, além de uma cadeia de
dependências complexa centrada no Snakemake. Em vista disso, este trabalho
usa o FedShop como artigo e benchmark base e apresenta três contribuições
principais:

- *FedShop-Go*: motor _standalone_ de consultas SPARQL federadas implementado
  em Go, sem dependências de RDF4J, Jena ou outros frameworks de grande porte.
  O motor implementa seleção de fontes por consultas `ASK`, planejamento por
  ordenação de padrões de tripla, junções por _hash_ e por vinculação
  (_bind join_), e emite artefatos compatíveis com o FedShop.

- *fedshop-py*: pipeline Python reprodutível que substitui o Snakemake do
  FedShop, expondo as etapas de geração de dados, ingestão, instanciação de
  consultas, avaliação e coleta de métricas como CLI e API programável.

- *Avaliação comparativa*: execução do FedShop-Go contra FedX @fedx, RSA,
  PyFedX, SPLENDID @splendid e SemaGrow @semagrow com métricas de corretude,
  tempo, rede e seleção de fontes.

= Fundamentação Teórica

== SPARQL Federado e a Cláusula SERVICE

O padrão SPARQL 1.1 @sparql11 introduz a cláusula `SERVICE`, que permite
delegar a avaliação de um padrão de tripla a um _endpoint_ remoto específico.
Motores federados generalizam esse mecanismo: dada uma consulta sem `SERVICE`
explícito, o motor determina automaticamente quais _endpoints_ respondem a
cada subpadrão, decompõe a consulta em subplanos por _endpoint_ e combina os
resultados parciais. Uma *federação* é um conjunto de _endpoints_ SPARQL
independentes, cada um mantendo um grafo RDF local com esquema, seletividade e
latência distintos. A chave para o desempenho está em identificar, para cada
padrão de tripla $(s, p, o)$, o subconjunto mínimo de _endpoints_ que contêm
triplas correspondentes --- o problema de *seleção de fontes*.

== Seleção de Fontes

A seleção de fontes pode ser realizada de forma *estática*, com base em
metadados pré-calculados, ou *dinâmica*, com consultas enviadas aos
_endpoints_ em tempo de execução. As principais abordagens são:

- *Consultas `ASK`*: a abordagem mais simples envia, para cada _endpoint_,
  uma consulta `ASK { <padrão> }` e inclui o _endpoint_ somente se a resposta
  for verdadeira. Usada pelo FedX @fedx, é precisa mas gera tráfego
  proporcional ao produto (padrões de tripla) $times$ (_endpoints_); com um
  cache de resultados, o custo amortiza-se em execuções repetidas sobre a
  mesma federação.

- *Estatísticas VoID*: abordagens como SPLENDID @splendid e CostFed @costfed
  exploram descritores `void:Dataset` que resumem, para cada _endpoint_, os
  predicados presentes e estimativas de cardinalidade, substituindo a consulta
  `ASK` por uma busca em índice local.

== Estratégias de Junção

Após a seleção de fontes, os resultados parciais de cada _endpoint_ precisam
ser combinados. No *hash join*, o motor materializa os _bindings_ de um lado
da junção em uma tabela hash indexada pelas variáveis compartilhadas e
percorre o outro lado consultando a tabela --- adequado quando o conjunto
intermediário cabe em memória. No *bind join*, o motor injeta _bindings_
parciais na subconsulta enviada ao _endpoint_ (por exemplo, via cláusula
`VALUES`), eliminando resultados irrelevantes na própria fonte antes da
transferência @fedx --- especialmente eficaz quando a junção é seletiva.

== FedShop Benchmark

O FedShop @fedshop simula um cenário de comércio eletrônico federado derivado
do BSBM. A @fig:db apresenta o modelo de dados: um *catálogo virtual* global
descreve produtos, tipos, produtores e características, enquanto *vendedores*
autônomos publicam ofertas e *sites de avaliação* publicam resenhas. Cada
vendedor e site de avaliação é um _endpoint_ SPARQL independente, e suas
entidades locais são ligadas ao catálogo global por links `owl:sameAs` --- por
isso a maioria das consultas do benchmark envolve junções sobre `owl:sameAs`.

#figure(
  placement: auto,
  image("images/db-2.png", width: 78%),
  caption: [Modelo de dados do FedShop: catálogo virtual, vendedores autônomos
    e sites de avaliação.],
) <fig:db>

O benchmark parametriza a avaliação em quatro eixos: *templates de consulta*
(12 padrões derivados do BSBM, cobrindo domínio único --- SD, múltiplos
domínios --- MD e domínio cruzado --- CD); *instâncias* (10 instanciações
concretas por template, com URIs que afetam a seletividade); *batches* (10
escalas da federação, de 20 a 200 _endpoints_, cada batch adicionando 10
vendedores e 10 sites de avaliação); e *tentativas* (repetições controladas
por combinação). Os artefatos exigidos por execução são: `results.csv`
(resultados da consulta), `source_selection.txt` (_endpoints_ selecionados por
padrão de tripla), `provenance.csv` (seleção reformatada) e `stats.csv`
(métricas de tempo e rede).

= Trabalhos Relacionados

Motores de consulta SPARQL federada têm sido amplamente estudados na última
década, com diferentes estratégias de seleção de fontes, planejamento e
execução.

- *FedX* @fedx é o motor mais referenciado. Implementado sobre RDF4J, usa
  consultas `ASK` para seleção dinâmica de fontes, mantém um cache de
  seletividade por padrão, emprega _bound joins_ para reduzir a transferência
  intermediária e executa grupos de padrões com fonte exclusiva
  (_exclusive groups_) como uma única subconsulta remota.

- *SPLENDID* @splendid explora descritores `void:Dataset` publicados pelos
  _endpoints_ para seleção estática de fontes sem consultas `ASK` adicionais.

- *CostFed* @costfed estende a ideia de metadados com estimação de
  cardinalidade: usa um catálogo de predicados por _endpoint_ para ordenar os
  padrões de tripla e selecionar fontes de baixo custo.

- *SemaGrow* @semagrow planeja a execução a partir de um serviço de metadados
  (SPARQLED) que expõe estatísticas de predicados, evitando consultas `ASK`
  individuais.

- *ANAPSID* @anapsid adota processamento adaptativo: inicia a execução sem
  esperar pela seleção completa de fontes, melhorando a latência do primeiro
  resultado ao custo de possível trabalho adicional.

- *RSA* (_Reference Source Assignment_) é o motor-oráculo do próprio FedShop
  @fedshop: executa subconsultas `SERVICE` com fontes pré-atribuídas pelo
  gerador do benchmark, sem seleção dinâmica, servindo como referência de
  corretude e piso de custo de seleção para os demais motores.

A @tab:estrategias compara as estratégias dos motores avaliados neste
trabalho.

#figure(
  table(
    columns: (auto, auto, auto, auto, auto),
    align: (left, left, left, center, left),
    inset: 5pt,

    [*Motor*],
    table.vline(start: 0, stroke: .5pt),
    [*Fontes*],
    [*Junção*],
    [*Pré-proc.*],
    [*Cardinalidade*],
    table.hline(stroke: .6pt),

    [*RSA*], [Broadcast de `SERVICE`], [Hash join local], [Não], [--],
    [*FedShop-Go*], [`ASK` + cache], [Hash / bind join], [Não], [--],
    [*FedX*], [`ASK` + cache], [Bound join], [Não], [_join order_],
    [*PyFedX*], [`ASK`], [Hash join local], [Não], [--],
    [*SPLENDID*], [Índice VoID], [Hash join], [Sim], [_triple count_ + partições],
    [*ANAPSID*], [Catálogo LAV], [`agjoin` adaptativo], [Parcial], [stats + _sampling_],
    [*SemaGrow*], [SPARQLED / VoID], [Hash join], [Sim], [custo com cardinalidade],

    table.hline(stroke: .6pt),
  ),
  caption: [Comparação das estratégias dos motores avaliados.],
) <tab:estrategias>

= Proposta

== FedShop-Go

O FedShop-Go é um motor _standalone_ de consultas SPARQL federadas projetado
para ser minimalista, testável e completamente compatível com o contrato de
saída do FedShop. A motivação é oferecer uma base limpa sobre a qual
estratégias de seleção de fontes e planejamento possam ser estudadas
isoladamente, sem a complexidade de frameworks como RDF4J ou Jena.

#figure(
  placement: auto,
  image("images/go-fed-diagram.svg", width: 88%),
  caption: [Arquitetura do FedShop-Go: parser, seleção de fontes, planejador,
    executor e artefatos compatíveis com o FedShop.],
) <fig:arch>

Como mostra a @fig:arch, a arquitetura segue cinco estágios lineares: (i) o
*parser* produz uma álgebra compacta com padrões de tripla numerados; (ii) a
*seleção de fontes* mapeia cada padrão a um conjunto de _endpoints_
candidatos; (iii) o *planejador* ordena os padrões por uma função de custo;
(iv) o *executor* envia as subconsultas e combina os resultados por junções;
e (v) o módulo de *artefatos* grava as saídas no formato do benchmark. O
motor é estruturado em pacotes Go independentes (`sparql`, `federation`,
`metadata`, `planner`, `executor`, `artifact`), detalhados na Seção 6.

== fedshop-py

O fedshop-py é um pacote Python que reimplementa o pipeline do FedShop sem
dependência de Snakemake, expondo as etapas do benchmark como subcomandos de
CLI:

+ `fedshop generate` --- gera os dados RDF sintéticos (produtos, ofertas e
  resenhas) e os particiona em N-Quads por vendedor, site de avaliação e
  batch;
+ `fedshop ingest` --- carrega os N-Quads no Virtuoso, um grafo nomeado por
  _endpoint_ da federação;
+ `fedshop query` --- instancia os 12 templates de consulta com valores
  concretos extraídos dos dados, produzindo os `injected.sparql` por template
  e instância;
+ `fedshop evaluate` --- executa os motores via _adapters_ e coleta os
  artefatos por combinação (motor, consulta, instância, batch, tentativa);
+ `fedshop metrics` --- agrega os `stats.csv` em uma tabela única de métricas.

A configuração é declarada em YAML tipado, a manipulação SPARQL usa `rdflib` e
as métricas são agregadas com `pandas`. O pipeline preserva os contratos de
artefatos do FedShop original e inclui 69 testes de integração.

= Hipóteses

Com base na arquitetura e nas características de cada motor, formulamos
quatro hipóteses a serem testadas com os dados do benchmark:

*H1 --- Desempenho global*: o FedShop-Go apresenta tempo de execução igual ou
inferior ao de cada motor de referência sobre o conjunto de execuções
pareadas do workload, pois a seleção por `ASK` restringe as subconsultas aos
_endpoints_ responsáveis e a execução direta com hash join evita camadas de
abstração intermediárias.

*H2 --- Eficiência da seleção de fontes*: a fase de seleção via consultas
`ASK` com cache é mais rápida que a fase de seleção de fontes dos motores de
referência que a reportam.

*H3 --- Escalabilidade com o número de endpoints*: o tempo de execução cresce
monotonicamente ao dobrar o número de _endpoints_ (de 20 para 40), pois o
número de consultas `ASK` e a cardinalidade das junções aumentam com a
federação.

*H4 --- Qualidade da seleção de fontes*: a seleção por `ASK` alcança _recall_
e precisão não inferiores aos dos demais motores, ao custo de menor
seletividade (mais fontes selecionadas por padrão de tripla) que o FedX.

= Implementação

== Parser e Álgebra SPARQL

O parser cobre o subconjunto de SPARQL exercitado pelos 12 templates FedShop:
`SELECT [DISTINCT]`, padrões de tripla (BGPs), `UNION`, `OPTIONAL`, `FILTER`,
modificadores de resultado (`ORDER BY`, `LIMIT`, `OFFSET`) e prefixos.
Construções fora do escopo dos templates (`SERVICE`, `GRAPH`, `BIND`,
`VALUES`, `GROUP BY`, `HAVING`) são intencionalmente rejeitadas. Cada padrão
de tripla recebe um identificador inteiro estável, propagado entre os estágios
de seleção, planejamento, execução e escrita de artefatos, garantindo
rastreabilidade de ponta a ponta.

== Seletor ASK com Cache

Para cada padrão de tripla, o seletor envia a consulta `ASK { <s> <p> <o> }` a
cada _endpoint_ da configuração; os que respondem `true` são incluídos como
candidatos. Um cache em memória indexado pelo padrão evita consultas
duplicadas dentro de uma sessão de avaliação. A seleção inclui ainda um
mecanismo de *grupos exclusivos*: se um padrão tem exatamente um _endpoint_
candidato, ele é processado sem junção posterior, o mesmo mecanismo empregado
pelo FedX.

== Planejador

O módulo de planejamento ordena os padrões de tripla dentro do plano de
execução. Dois planejadores estão disponíveis: o *source-count* ordena pelo
número de _endpoints_ candidatos (menor primeiro), priorizando padrões mais
seletivos; o *cost* usa cardinalidades de predicado do catálogo gerado pelo
subcomando `summarize`. A sobrecarga de planejamento é negligível (inferior a
1 ms), pois opera sobre estruturas em memória sem consultas adicionais.

== Executor e Junções

O executor percorre o plano de padrões de tripla, executando subconsultas por
_endpoint_ e combinando resultados via junção por variáveis compartilhadas,
com as duas estratégias descritas na Seção 2.3: *hash join* para conjuntos
intermediários pequenos e *bind join* --- injetando _bindings_ parciais via
cláusula `VALUES` na subconsulta --- a partir do segundo padrão do plano,
quando há _bindings_ disponíveis. Resultados idênticos provenientes de
múltiplos _endpoints_ (decorrentes de replicação de dados entre membros da
federação) são deduplicados antes da projeção final.

== Saídas Compatíveis com o FedShop

O módulo de artefatos gera, para cada execução: `results.csv` (resultados com
variáveis projetadas), `source_selection.csv` (mapeamento padrão de tripla
$arrow$ _endpoints_), `query_plan.txt` (ordem de execução) e
`engine_stats.json` (tempo, contadores `ASK`, HTTP e bytes). O _adapter_
Python (`fedshop_go.py`) converte essas saídas para os formatos `stats.csv` e
`provenance.csv` exigidos pelo FedShop.

= Resultados

== Configuração Experimental

Os experimentos foram realizados com batch 0 (20 _endpoints_) e batch 1 (40
_endpoints_) para avaliar escalabilidade, usando as instâncias 0 e 1 de cada
template de consulta e 2--3 tentativas por combinação. O Virtuoso foi usado
como servidor SPARQL dos membros da federação e o proxy do FedShop registrou
as requisições HTTP. Os experimentos foram conduzidos no ambiente descrito na
@tbl:config. O pipeline fedshop-py e o protótipo PyFedX usaram Python 3.12;
FedX, SPLENDID e SemaGrow executaram sobre a JVM; e o FedShop-Go foi compilado
com o toolchain padrão de Go. // TODO confirmar versões de Java/Go e qual engine usou Python 3.8

#figure(caption: [Configurações do ambiente computacional utilizado.])[
#text(size: 10pt)[
#table(
  columns: 2,
  inset: 4pt,
  align: (center, left),
  row-gutter: 4pt,
  [*Componente*], [*Configuração*],
  table.hline(stroke: .6pt),
  [CPU], [Apple M5, 10 núcleos (4 desempenho + 6 eficiência)],
  [RAM], [16GB],
  [GPU], [Apple M5 integrada, 10 núcleos],
  [Disco], [995GB (`/`)],
  [SO], [macOS 26.5.2 (Build 25F84), arm64],
)
]
] <tbl:config>

As métricas coletadas contemplam cinco categorias: *corretude* (precisão,
revocação e F1 dos resultados em relação ao gabarito do RSA, além de contagens
de resultados espúrios, faltantes e duplicados); *tempo* (`exec_time` total,
`source_selection_time`, `planning_time` e tempo de junção); *rede* (número de
consultas `ASK`, total de requisições HTTP e bytes transferidos); *seleção de
fontes* (TPWSS, RWSS, fontes distintas e requisições redundantes); e
*robustez* (_timeouts_ e erros de execução).

== Corretude

A @tab:corretude apresenta as métricas de corretude agregadas por motor. O
FedShop-Go e o PyFedX obtêm precisão, revocação e F1 de 100% nas execuções
concluídas, com o FedShop-Go completando 83,3% das combinações. O FedX, embora
complete 100% das execuções, apresenta revocação de 37,5% no conjunto avaliado
--- com grande volume de resultados faltantes e variáveis ausentes ---, e o
SemaGrow combina resultados espúrios e faltantes (F1 de 59,1%).

#figure(placement: auto, caption: [
  Métricas de corretude agregadas por motor. Células em verde indicam o melhor
  valor global da coluna.
])[
#text(size: 8.4pt)[
#table(
  columns: 11,
  column-gutter: 3pt,
  row-gutter: 1pt,
  align: (left, left, center, center, center, center, center, center, center, center, center),
  inset: (x, y) => (
    x: if y == 0 or y == 1 or x == 1 { 0pt } else { 0.5pt },
    y: if y == 0 or y == 1 { 4pt } else if x == 1 { 1.9pt } else { 2pt }
  ),

  table.hline(stroke: .6pt),
  table.cell(rowspan: 2, [*Tipo*], align: horizon),
  table.cell(rowspan: 2, [*Motor*], align: horizon),
  table.cell(colspan: 3, [*Qualidade*]),
  table.cell(colspan: 5, [*Erros*]),
  table.cell(rowspan: 2, [*OK*], align: horizon),

  table.hline(start: 2, end: 10, stroke: 0.3pt),

  [Precisão], [Revocação], [F1],
  [Espúrios], [Faltantes], [Duplicatas], [Ausentes], [Mismatch (%)],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 1, [Oráculo], align: horizon),
  [RSA],
    [90,9\%],
    [90,9\%],
    [90,9\%],
    [4],
    [4194304],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [9,1\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*91,7\%*]],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 3, [Implementação], align: horizon),
  [FedShop-Go],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,0\%*]],
    [83,3\%],
  [PyFedX],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,0\%*]],
    [60,4\%],
  [PyFedX-Better],
    [80,0\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [80,0\%],
    [80],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [36],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [20,0\%],
    [83,3\%],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 1, [_Baseline_], align: horizon),
  [FedX],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [37,5\%],
    [37,5\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [4194455],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [188],
    [62,5\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 2, [Metadados], align: horizon),
  [SPLENDID],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*100,0\%*]],
    [98,9\%],
    [99,3\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [3],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [2,5\%],
    [75,5\%],
  [SemaGrow],
    [89,7\%],
    [59,1\%],
    [59,1\%],
    [30],
    [118],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0*]],
    [110],
    [40,9\%],
    [91,7\%],

  table.hline(stroke: .6pt),
)
]
] <tab:corretude>

== Tempo de Execução

A @res:tempo-engines apresenta os tempos médios por estágio, calculados sobre
os casos sem _timeout_. O FedShop-Go obtém o menor tempo médio global
(0,44 s), seguido pelo FedX (3,87 s). O RSA, embora seja o motor de referência
mais simples, paga o custo de enviar cada subconsulta `SERVICE` pré-atribuída
a todos os membros da federação.

#figure(placement: auto, caption: [
  Tempos médios (em segundos) por estágio. Células em dourado indicam o melhor
  tempo global da coluna.
])[
#text(size: 8.3pt)[
#table(
  columns: 6,
  column-gutter: 4pt,
  row-gutter: 1pt,
  align: (left, left, center, center, center, center),
  inset: (x, y) => (
    x: 9pt,
    y: 4pt
  ),

  table.hline(stroke: .6pt),
  [*Tipo*],
  [*Motor*],
  [`exec_time`],
  [`planning_time`],
  [`source_selection_time`],
  [`join_time`],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 1, [Oráculo], align: horizon),
  [RSA],
    [*9,40*],
    [*1,23*],
    [*1,23*],
    [*8,17*],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 3, [Implementação], align: horizon),
  [FedShop-Go],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,44*]],
    [0,00],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,06*]],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,38*]],
  [PyFedX],
    [9,21],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,00*]],
    [0,40],
    [8,81],
  [PyFedX-Better],
    [2,03],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,00*]],
    [0,71],
    [1,32],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 1, [_Baseline_], align: horizon),
  [FedX],
    [*3,87*],
    [*0,00*],
    [*0,14*],
    [*3,74*],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 2, [Metadados], align: horizon),
  [SPLENDID],
    [*13,67*],
    [--],
    [--],
    [--],
  [SemaGrow],
    [67,10],
    [--],
    [--],
    [--],

  table.hline(stroke: .6pt),
)
]
] <res:tempo-engines>

== Desempenho por Consulta

A @tab:desempenho detalha o tempo de execução de cada motor nos 12 templates
(batch 1, 40 _endpoints_). Nas consultas de domínio único (q06--q12), o
FedShop-Go é consistentemente mais rápido que o FedX, com _speedups_ entre
8$times$ e 41$times$; q09, extremamente seletiva (identifica um único produto
por URI exata), retorna em 10 ms --- a execução mais rápida do benchmark. Em
contrapartida, q02 e q05 resultam em _timeout_ no FedShop-Go: q02 requer
junções de alto volume que não cabem no modelo de bind join atual; q05
provoca esgotamento de memória no Virtuoso por junções de similaridade sobre
conjuntos grandes.

#figure(
placement: auto,
text(size: 8.5pt)[
#align(center)[
  #table(
    columns: (auto, auto, auto, auto, auto, auto, auto, auto),
    inset: 4pt,
    align: center,
    fill: (x, y) => {
      if y == 0 { soft-blue }
      else { white }
    },
    [*Consulta*], table.vline(), [*FedShop-Go*], [*FedX*], [*RSA*], [*SPLENDID*], [*SemaGrow*], [*PyFedX*], [*PyFedX-Better*],
    table.hline(stroke: 1pt),
    [q01], cell-time(0.44,"0,44"), cell-time(0.14,"0,14"), cell-time(2.31,"2,31"), cell-time(14.74,"14,74"), cell-time(64.56,"64,56"), cell-to, cell-time(4.27,"4,27"),
    [q02], cell-to, cell-time(3.37,"3,37"), cell-time(64.97,"64,97"), cell-to, cell-to, cell-to, cell-to,
    [q03], cell-time(4.48,"4,48"), cell-time(4.37,"4,37"), cell-time(26.98,"26,98"), cell-time(14.83,"14,83"), cell-time(1.09,"1,09"), cell-to, cell-time(7.69,"7,69"),
    [q04], cell-time(0.11,"0,11"), cell-time(3.52,"3,52"), cell-time(2.20,"2,20"), cell-time(28.52,"28,52"), cell-time(66.75,"66,75"), cell-to, cell-time(2.89,"2,89"),
    [q05], cell-to, cell-time(3.27,"3,27"), cell-to, cell-to, cell-time(62.49,"62,49"), cell-to, cell-to,
    [q06], cell-time(0.15,"0,15"), cell-time(3.10,"3,10"), cell-time(2.23,"2,23"), cell-time(1.45,"1,45"), cell-time(64.59,"64,59"), cell-time(62.83,"62,83"), cell-time(0.35,"0,35"),
    [q07], cell-time(0.13,"0,13"), cell-time(1.08,"1,08"), cell-time(1.93,"1,93"), cell-time(48.46,"48,46"), cell-time(60.98,"60,98"), cell-time(3.04,"3,04"), cell-time(3.90,"3,90"),
    [q08], cell-time(0.10,"0,10"), cell-time(0.82,"0,82"), cell-time(1.88,"1,88"), cell-time(3.04,"3,04"), cell-time(61.58,"61,58"), cell-time(1.46,"1,46"), cell-time(2.09,"2,09"),
    [q09], cell-time(0.01,"0,01"), cell-time(0.41,"0,41"), cell-time(1.81,"1,81"), cell-time(1.04,"1,04"), cell-time(62.46,"62,46"), cell-time(0.10,"0,10"), cell-time(0.12,"0,12"),
    [q10], cell-time(0.05,"0,05"), cell-time(0.70,"0,70"), cell-time(1.89,"1,89"), cell-time(3.86,"3,86"), cell-time(65.86,"65,86"), cell-time(0.73,"0,73"), cell-time(1.38,"1,38"),
    [q11], cell-time(0.03,"0,03"), cell-time(0.51,"0,51"), cell-time(1.95,"1,95"), cell-time(1.10,"1,10"), cell-time(62.84,"62,84"), cell-time(0.20,"0,20"), cell-time(0.35,"0,35"),
    [q12], cell-time(0.08,"0,08"), cell-time(0.82,"0,82"), cell-time(1.94,"1,94"), cell-time(11.67,"11,67"), cell-time(63.25,"63,25"), cell-time(4.36,"4,36"), cell-time(3.91,"3,91"),
  )
]
],
caption: [
  Tempo de execução (em segundos) por consulta e motor.
  #box(fill: soft-green, inset: 2pt, radius: 2pt)[< 2s] rápido,
  #box(fill: soft-yellow, inset: 2pt, radius: 2pt)[2--15s] médio,
  #box(fill: soft-orange, inset: 2pt, radius: 2pt)[15--60s] lento,
  #box(fill: soft-red, inset: 2pt, radius: 2pt)[> 60s / T/O] crítico.
]
) <tab:desempenho>

== Seleção de Fontes

A @tab:selection-fontes compara as métricas de seleção de fontes. O FedX
obtém a seleção mais enxuta (TPWSS de 4,62 e seletividade de 7,7%), enquanto o
FedShop-Go e o PyFedX selecionam mais fontes por padrão --- sem, contudo,
produzir falsos positivos.

#figure(placement: auto, caption: [
  Métricas de seleção de fontes por motor (menor é melhor); células em verde
  indicam o menor valor global da coluna.
])[
#text(size: 8.4pt)[
#table(
  columns: 10,
  column-gutter: 3pt,
  row-gutter: 1pt,
  align: (left, left, center, center, center, center, center, center, center, center),
  inset: (x, y) => (
    x: if y == 0 or y == 1 or x == 1 { 0pt } else { 0.5pt },
    y: if y == 0 or y == 1 { 4pt } else if x == 1 { 1.9pt } else { 2pt }
  ),

  table.hline(stroke: .6pt),
  table.cell(rowspan: 2, [*Tipo*], align: horizon),
  table.cell(rowspan: 2, [*Motor*], align: horizon),
  table.cell(colspan: 8, [*Seleção de Fontes*]),

  table.hline(start: 2, end: 10, stroke: 0.3pt),

  [TPWSS], [Avg RWSS], [Min RWSS], [Max RWSS], [Font. Dist.], [Seletividade], [FP], [Red.],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 1, [Oráculo], align: horizon),
  [RSA],
    [--], [--], [--], [--], [--], [--], [--], [--],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 3, [Implementação], align: horizon),
  [FedShop-Go],
    [178,82],
    [1,22],
    [1,00],
    [1,35],
    [22,70],
    [75,8\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,00*]],
    [2,20],
  [PyFedX],
    [104,90],
    [1,10],
    [1,00],
    [1,17],
    [19,59],
    [66,6\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,00*]],
    [0,48],
  [PyFedX-Better],
    [161,85],
    [1,22],
    [1,00],
    [1,35],
    [22,70],
    [75,8\%],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,00*]],
    [1,18],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 1, [_Baseline_], align: horizon),
  [FedX],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*4,62*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,13*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,08*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,15*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*2,31*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*7,7\%*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,00*]],
    [#rect(fill: rgb("#90EE90"), inset: 1pt)[*0,00*]],

  table.hline(stroke: .6pt),
  table.cell(rowspan: 2, [Metadados], align: horizon),
  [SPLENDID],
    [--], [--], [--], [--], [--], [--], [--], [--],
  [SemaGrow],
    [--], [--], [--], [--], [--], [--], [--], [--],

  table.hline(stroke: .6pt),
)
]
] <tab:selection-fontes>

== Breakdown de Tempo

O _breakdown_ de tempo do FedShop-Go revela que a *seleção de fontes* (`ASK`)
consome cerca de 13% do tempo total, com 160--320 consultas `ASK` por
execução; o *planejamento* fica abaixo de 1 ms; e a *execução* (HTTP +
junções) domina com cerca de 87%, limitada pelo tempo de resposta dos
_endpoints_ e pelo custo de transferência (640--1.200 requisições HTTP e
19--38 MB por consulta).

== Escalabilidade

Comparando batch 0 (20 _endpoints_) com batch 1 (40 _endpoints_), o tempo de
execução do FedShop-Go cresce em média 1,8$times$ ao dobrar o número de
_endpoints_, sugerindo que a sobrecarga de coordenação (consultas `ASK`
adicionais e junções de maior cardinalidade) pesa no custo marginal. Como
discutido no teste de H3, porém, essa tendência não é estatisticamente
significativa com apenas dois batches.

= Teste de Hipótese

Além da análise descritiva, aplicamos três famílias de testes
($alpha = 0.05$): (i) o teste omnibus de Friedman sobre os seis motores, que
detecta diferenças significativas em tempo de execução
($chi^2 = 117.9$, $p = 8.6 times 10^(-24)$), _recall_ e F1
($chi^2 = 88.8$, $p = 1.2 times 10^(-17)$); (ii) testes de Wilcoxon pareados
entre o FedShop-Go e cada um dos demais motores, com correção de Holm para
múltiplas comparações; e (iii) correlação de Spearman entre tempo de execução
e número de _endpoints_ (batch), para H3. A @tab:testes-hipotese resume os
principais resultados pareados.

#figure(
  table(
    columns: (auto, auto, auto, auto, auto, auto),
    align: (left, left, center, center, center, center),
    inset: 5pt,

    table.header(
      [*Comparação*],
      [*Métrica*],
      [*$Delta$ mediana*],
      [*W*],
      [*P-ajustado*],
      [*$n$*],
    ),
    table.hline(stroke: .6pt),
    [FedShop-Go $times$ FedX], [TPWSS], [+78,00], [0,00], [0,000035], [26],
    [FedShop-Go $times$ SemaGrow], [Tempo], [-63,47], [10,00], [< 0,000001], [40],
    [FedShop-Go $times$ SPLENDID], [Tempo], [-5,18], [0,00], [< 0,000001], [40],
    [FedShop-Go $times$ RSA], [Tempo], [-1,77], [0,00], [< 0,000001], [40],
    [FedShop-Go $times$ PyFedX], [Tempo], [-1,25], [0,00], [< 0,000001], [29],
    [FedShop-Go $times$ RSA], [Planejamento], [-1,11], [0,00], [< 0,000001], [40],
    [FedShop-Go $times$ RSA], [Seleção], [-1,01], [0,00], [< 0,000001], [40],
    [FedShop-Go $times$ FedX], [Seleção], [-0,25], [0,00], [< 0,000001], [26],
    [FedShop-Go $times$ PyFedX], [Seleção], [-0,25], [0,00], [< 0,000001], [29],
    [FedShop-Go $times$ FedX], [Recall], [+1,00], [0,00], [0,000008], [40],
    [FedShop-Go $times$ SemaGrow], [Recall], [0,00], [0,00], [0,000366], [40],
    [FedShop-Go $times$ FedX], [Avg RWSS], [+1,00], [3,00], [0,000004], [26],
    table.hline(stroke: .6pt),
  ),
  caption: [Testes de Wilcoxon pareado, FedShop-Go $times$ demais motores
    $(alpha = 0.05)$; P-ajustado com correção de Holm.],
) <tab:testes-hipotese>

== H1: Desempenho Global

Os testes de Wilcoxon confirmam H1 contra todos os cinco motores de
referência: o tempo de execução do FedShop-Go é significativamente inferior
ao do FedX ($p = 0.0018$, $n = 40$), do PyFedX, do RSA, do SemaGrow e do
SPLENDID (todos com $p < 10^(-8)$) sobre as execuções pareadas. A ressalva é
qualitativa: q02 e q05, de domínio cruzado com alto volume intermediário, não
concluem dentro do _timeout_ e ficam fora dos pares comparáveis, enquanto o
FedX, com seu mecanismo de bound join mais maduro, completa todas as
execuções.

*Conclusão sobre H1*: confirmada no workload pareado, com a ressalva de que
q02 e q05 permanecem intratáveis para o FedShop-Go.

== H2: Eficiência da Seleção de Fontes

Os testes de Wilcoxon sobre o tempo de seleção de fontes confirmam H2: a
seleção via `ASK` com cache é significativamente mais rápida que a fase de
seleção do FedX ($p = 3.0 times 10^(-8)$, $n = 26$), do PyFedX
($p = 7.5 times 10^(-9)$, $n = 29$) e do RSA ($p = 5.5 times 10^(-12)$,
$n = 40$). Como evidência descritiva complementar, o _breakdown_ de tempo
mostra que a seleção consome cerca de 13% do tempo total, e o cache em
memória reduz o número de consultas `ASK` em sessões com múltiplas instâncias
do mesmo template.

*Conclusão sobre H2*: confirmada.

== H3: Escalabilidade com o Número de Endpoints

A correlação de Spearman entre tempo de execução e número de _endpoints_ não
é significativa para o FedShop-Go ($rho = 0.21$, $p = 0.20$, $n = 40$),
tampouco para qualquer outro motor. O crescimento médio de 1,8$times$
observado na análise descritiva é, portanto, sugestivo, mas não estatisticamente
detectável como tendência monotônica com apenas dois batches (20 e 40
_endpoints_); a alta variância entre templates domina o efeito do tamanho da
federação nessa escala.

*Conclusão sobre H3*: não confirmada, pois nenhuma tendência monotônica
significativa foi detectada. O teste tem baixo poder estatístico com apenas
dois batches e, desse modo, a avaliação em escala completa (10 batches) é
necessária para uma conclusão definitiva.

== H4: Qualidade da Seleção de Fontes

Os testes de Wilcoxon confirmam H4. Em qualidade, o _recall_ e o F1 do
FedShop-Go são significativamente superiores aos do FedX
($p = 8.2 times 10^(-6)$) e do SemaGrow ($p = 3.7 times 10^(-4)$) e
estatisticamente equivalentes aos do PyFedX, RSA e SPLENDID; a precisão é
equivalente à de todos os motores, sem falsos positivos. Em seletividade, o
custo previsto se confirma: o TPWSS ($+78$, $p = 3.5 times 10^(-5)$) e o Avg
RWSS ($+1.0$, $p = 3.5 times 10^(-6)$) são significativamente maiores que os
do FedX, que faz a seleção mais enxuta (@tab:selection-fontes).

*Conclusão sobre H4*: confirmada, com _recall_ e precisão máximos, ao custo
de menor seletividade que o FedX.

= Conclusão

Este trabalho apresentou o FedShop-Go, um motor de consultas SPARQL federadas
_standalone_ implementado em Go, avaliado com o benchmark FedShop contra cinco
motores de referência. Os resultados mostram que: (i) o FedShop-Go apresenta
tempo de execução significativamente inferior ao dos cinco motores no
workload pareado, chegando a 20$times$ sobre o FedX nas consultas de domínio
único q06--q12, e portanto confirma H1; (ii) a fase de seleção via `ASK`
com cache é significativamente mais rápida que a dos motores de referência,
consumindo cerca de 13% do tempo total, confirmando H2; (iii) nenhuma
tendência significativa de crescimento com o número de _endpoints_ foi
detectada em dois batches, deixando H3 inconclusiva; (iv) a seleção `ASK`
atinge _recall_ e precisão máximos ao custo de menor seletividade que o FedX,
confirmando H4; e (v) as consultas de domínio cruzado com alto volume
intermediário (q02, q05) continuam sendo o principal gargalo. O fedshop-py demonstrou-se uma
alternativa funcional ao Snakemake original, com cobertura de 69 testes de
integração.

= Trabalhos Futuros

As seguintes direções são identificadas como extensões naturais:

- *Filter pushdown*: projetar filtros sobre as subconsultas enviadas aos
  _endpoints_, atacando diretamente a causa dos _timeouts_ em q02 e q05;

- *Planejador baseado em custo com VoID*: usar estatísticas VoID dos
  _endpoints_ para estimação de cardinalidade e ordenação de padrões
  otimizada;

- *Paralelização de bind joins*: executar subconsultas de bind join em
  paralelo por _endpoint_, reduzindo a latência nas consultas de múltiplos
  domínios;

- *Escala completa*: executar o workload completo do FedShop (10 batches, 10
  instâncias, 12 templates) para caracterizar federações de até 200
  _endpoints_;

- *Processamento adaptativo*: incorporar estratégias inspiradas no ANAPSID
  @anapsid, iniciando a execução sem aguardar a seleção completa de fontes.
