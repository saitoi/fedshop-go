#align(center)[
#figure(caption: [
  Tempos de execução, planejamento, seleção de fontes e junção para as engines avaliadas.
  Valores em *negrito* indicam o melhor resultado dentro de cada categoria.
  Valores em #box(fill: rgb("#DAA520"), inset: 1pt)[dourado]
  indicam o melhor tempo global em cada coluna.
])[
#text(size: 8.3pt)[
#table(
  columns: 6,
  column-gutter: 4pt,
  row-gutter: 1pt,
  align: (left, left, center, center, center, center),
  stroke: none,
  inset: (x, y) => (
    x: 9pt,
    y: 4pt
  ),

  table.hline(stroke: .6pt),
  [*Tipo*],
  [*Engine*],
  [`exec_time`],
  [`planning_time`],
  [`source_selection_time`],
  [`join_time`],

  table.hline(stroke: .6pt),
  table.cell(colspan: 6, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 6, []),
  table.cell(rowspan: 1, [Oráculo], align: horizon),
  [RSA],
    [*3,46*],
    [--],
    [--],
    [--],

  table.cell(colspan: 6, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 6, []),
  table.cell(rowspan: 2, [Implementação], align: horizon),
  [go-fed],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*2,53*]],
    [0,00],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,34*]],
    [--],
  [PyFedX],
    [10,57],
    [#box(fill: rgb("#DAA520"), inset: 1pt)[*0,00*]],
    [0,43],
    [--],

  table.cell(colspan: 6, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 6, []),
  table.cell(rowspan: 1, [_Baseline_], align: horizon),
  [FedX],
    [*9,23*],
    [*1,61*],
    [*1878,02*],
    [--],

  table.cell(colspan: 6, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 6, []),
  table.cell(rowspan: 2, [Metadados], align: horizon),
  [SPLENDID],
    [*19,22*],
    [--],
    [--],
    [--],
  [SemaGrow],
    [85,53],
    [--],
    [--],
    [--],

  table.cell(colspan: 6, []),
  table.hline(stroke: .6pt),
  table.cell(colspan: 6, []),
  table.cell(rowspan: 1, [Adaptativa], align: horizon),
  [ANAPSID],
    [--],
    [--],
    [--],
    [--],

  table.hline(stroke: .6pt),
)
]
] <res:tempo-engines>
]

#figure(
  table(
    columns: (auto, auto, auto, auto),
    align: (left, center, center, left),
    stroke: none,
    inset: 5pt,
    table.header(
      [*Engine*],
      [*Tempo Médio (s)*],
      [*Taxa de Sucesso*],
      [*Seleção de Fontes*],
    ),
    table.hline(stroke: .6pt),
    [RSA], [3,46], [100,0% (49/49)], [Broadcast],
    [FedShop-Go], [2,53], [66,7% (22 timeouts)], [ASK + cache],
    [PyFedX], [10,57], [53,1% (26/49; 23 falhas)], [ASK],
    [FedX], [9,23], [100,0% (69/69)], [ASK + índice],
    [SPLENDID], [19,22], [100,0% (54/54)], [Estatísticas VOID],
    [SemaGrow], [85,53], [100,0% (49/49)], [VOID/SPARQLED],
    table.hline(stroke: .6pt),
  ),
  caption: [Tempo médio de execução e taxa de sucesso por engine.],
) <tab:tempo>
