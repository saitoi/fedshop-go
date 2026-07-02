"""Render FedShop metrics DataFrames as Typst benchmark tables."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


TIMING_COLUMNS = ("exec_time", "planning_time", "source_selection_time", "join_time")
QUERY_PERFORMANCE_ENGINES = ("fedshop-go", "fedx", "rsa", "splendid", "semagrow", "pyfedx")
SOURCE_SELECTION_COLUMNS = (
    "tpwss",
    "avg_rwss",
    "min_rwss",
    "max_rwss",
    "nb_distinct_sources",
    "relevant_sources_selectivity",
    "false_positive_sources",
    "redundant_requests",
)
HYPOTHESIS_COLUMNS = (
    "test",
    "metric",
    "engine_a",
    "engine_b",
    "n_pairs",
    "statistic",
    "p_value",
    "p_corrected",
    "significant",
    "median_a",
    "median_b",
    "direction",
)


@dataclass(frozen=True)
class EngineSpec:
    group: str
    metric_engine: str
    timing_label: str
    summary_label: str
    source_selection: str


ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec("Oráculo", "rsa", "RSA", "RSA", "Broadcast"),
    EngineSpec("Implementação", "fedshop-go", "go-fed", "FedShop-Go", "ASK + cache"),
    EngineSpec("Implementação", "pyfedx", "PyFedX", "PyFedX", "ASK"),
    EngineSpec("_Baseline_", "fedx", "FedX", "FedX", "ASK + índice"),
    EngineSpec("Metadados", "splendid", "SPLENDID", "SPLENDID", "Estatísticas VOID"),
    EngineSpec("Metadados", "semagrow", "SemaGrow", "SemaGrow", "VOID/SPARQLED"),
    EngineSpec("Adaptativa", "anapsid", "ANAPSID", "ANAPSID", "Adaptativa"),
)


def read_metrics(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"metrics file not found: {path}")
    df = pd.read_csv(path)
    required = {"engine", "status"}
    missing = required - set(df.columns)
    if missing:
        missing_s = ", ".join(sorted(missing))
        raise ValueError(f"metrics file is missing columns: {missing_s}")
    for column in TIMING_COLUMNS:
        if column not in df.columns:
            df[column] = math.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def read_hypothesis(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"hypothesis file not found: {path}")
    df = pd.read_csv(path)
    missing = {"test", "metric", "engine_a", "engine_b", "statistic", "p_value"} - set(df.columns)
    if missing:
        missing_s = ", ".join(sorted(missing))
        raise ValueError(f"hypothesis file is missing columns: {missing_s}")
    for column in ("n_pairs", "statistic", "p_value", "p_corrected", "median_a", "median_b"):
        if column not in df.columns:
            df[column] = math.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if "significant" not in df.columns:
        df["significant"] = False
    return df


def apply_attempt_policy(df: pd.DataFrame, policy: str) -> pd.DataFrame:
    if policy == "all":
        return df.copy()
    if policy == "primary":
        if "attempt" not in df.columns:
            return df.copy()
        attempts = pd.to_numeric(df["attempt"], errors="coerce")
        return df[attempts == 0].copy()
    raise ValueError(f"unknown attempt policy: {policy}")


def mean_ok(df: pd.DataFrame, engine: str, column: str) -> float:
    rows = df[(df["engine"] == engine) & (df["status"] == "ok")]
    if rows.empty:
        return math.nan
    return float(pd.to_numeric(rows[column], errors="coerce").mean())


def timing_values(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        spec.metric_engine: {column: mean_ok(df, spec.metric_engine, column) for column in TIMING_COLUMNS}
        for spec in ENGINES
    }


def source_selection_values(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        spec.metric_engine: {column: mean_ok(df, spec.metric_engine, column) for column in SOURCE_SELECTION_COLUMNS}
        for spec in ENGINES
    }


def finite_min(values: list[float]) -> float | None:
    finite = [value for value in values if not math.isnan(value)]
    return min(finite) if finite else None


def finite_max(values: list[float]) -> float | None:
    finite = [value for value in values if not math.isnan(value)]
    return max(finite) if finite else None


def fmt_decimal(value: float, decimals: int) -> str:
    if math.isnan(value):
        return "--"
    return f"{value:.{decimals}f}".replace(".", ",")


def fmt_pct(value: float) -> str:
    if math.isnan(value):
        return "--"
    return f"{value * 100:.1f}\\%".replace(".", ",")


def fmt_pvalue(value: float) -> str:
    if math.isnan(value):
        return "--"
    if value < 0.000001:
        return "< 0,000001"
    if value < 0.001:
        return f"{value:.6f}".replace(".", ",")
    return f"{value:.4f}".replace(".", ",")


def typst_cell(text: str, *, bold: bool = False, gold: bool = False) -> str:
    if text == "--":
        return "[--]"
    content = f"*{text}*" if bold else text
    if gold:
        return f'[#box(fill: rgb("#DAA520"), inset: 1pt)[{content}]]'
    return f"[{content}]"


def timing_table(df: pd.DataFrame, decimals: int) -> str:
    values = timing_values(df)
    global_best = {
        column: finite_min([values[spec.metric_engine][column] for spec in ENGINES])
        for column in TIMING_COLUMNS
    }
    group_best: dict[tuple[str, str], float | None] = {}
    for group in {spec.group for spec in ENGINES}:
        specs = [spec for spec in ENGINES if spec.group == group]
        for column in TIMING_COLUMNS:
            group_best[(group, column)] = finite_min([values[spec.metric_engine][column] for spec in specs])

    lines = [
        "#align(center)[",
        "#figure(caption: [",
        "  Tempos de execução, planejamento, seleção de fontes e junção para as engines avaliadas.",
        "  Valores em *negrito* indicam o melhor resultado dentro de cada categoria.",
        '  Valores em #box(fill: rgb("#DAA520"), inset: 1pt)[dourado]',
        "  indicam o melhor tempo global em cada coluna.",
        "])[",
        "#text(size: 8.3pt)[",
        "#table(",
        "  columns: 6,",
        "  column-gutter: 4pt,",
        "  row-gutter: 1pt,",
        "  align: (left, left, center, center, center, center),",
        "  stroke: none,",
        "  inset: (x, y) => (",
        "    x: 9pt,",
        "    y: 4pt",
        "  ),",
        "",
        "  table.hline(stroke: .6pt),",
        "  [*Tipo*],",
        "  [*Engine*],",
        "  [`exec_time`],",
        "  [`planning_time`],",
        "  [`source_selection_time`],",
        "  [`join_time`],",
        "",
        "  table.hline(stroke: .6pt),",
        "  table.cell(colspan: 6, []),",
    ]

    first_in_group: dict[str, bool] = {}
    for spec in ENGINES:
        group_specs = [item for item in ENGINES if item.group == spec.group]
        if spec.group not in first_in_group:
            if lines[-1] != "  table.cell(colspan: 6, []),":
                lines.extend(["", "  table.cell(colspan: 6, []),"])
            lines.append("  table.hline(stroke: .6pt),")
            lines.append("  table.cell(colspan: 6, []),")
            lines.append(f"  table.cell(rowspan: {len(group_specs)}, [{spec.group}], align: horizon),")
            first_in_group[spec.group] = True

        row = [f"  [{spec.timing_label}],"]
        for column in TIMING_COLUMNS:
            value = values[spec.metric_engine][column]
            text = fmt_decimal(value, decimals)
            is_group_best = (
                not math.isnan(value)
                and group_best[(spec.group, column)] is not None
                and value == group_best[(spec.group, column)]
            )
            is_global_best = (
                not math.isnan(value)
                and global_best[column] is not None
                and value == global_best[column]
            )
            row.append(f"    {typst_cell(text, bold=is_group_best, gold=is_global_best)},")
        lines.extend(row)

    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <res:tempo-engines>", "]"])
    return "\n".join(lines)


def success_cell(df: pd.DataFrame, engine: str) -> str:
    rows = df[df["engine"] == engine]
    total = len(rows)
    if total == 0:
        return "--"
    ok = int((rows["status"] == "ok").sum())
    pct = 100 * ok / total
    failures = total - ok
    pct_s = f"{pct:.1f}".replace(".", ",")
    if failures == 0:
        return f"{pct_s}% ({ok}/{total})"
    timeouts = int((rows["status"] == "timeout").sum())
    if timeouts == failures:
        return f"{pct_s}% ({timeouts} timeouts)"
    return f"{pct_s}% ({ok}/{total}; {failures} falhas)"


def summary_table(df: pd.DataFrame, decimals: int) -> str:
    lines = [
        "#figure(",
        "  table(",
        "    columns: (auto, auto, auto, auto),",
        "    align: (left, center, center, left),",
        "    stroke: none,",
        "    inset: 5pt,",
        "    table.header(",
        "      [*Engine*],",
        "      [*Tempo Médio (s)*],",
        "      [*Taxa de Sucesso*],",
        "      [*Seleção de Fontes*],",
        "    ),",
        "    table.hline(stroke: .6pt),",
    ]
    for spec in ENGINES:
        if spec.metric_engine == "anapsid" and spec.metric_engine not in set(df["engine"]):
            continue
        avg = mean_ok(df, spec.metric_engine, "exec_time")
        lines.append(
            f"    [{spec.summary_label}], "
            f"[{fmt_decimal(avg, decimals)}], "
            f"[{success_cell(df, spec.metric_engine)}], "
            f"[{spec.source_selection}],"
        )
    lines.extend(
        [
            "    table.hline(stroke: .6pt),",
            "  ),",
            "  caption: [Tempo médio de execução e taxa de sucesso por engine.],",
            ") <tab:tempo>",
        ]
    )
    return "\n".join(lines)


def _engine_specs_present(df: pd.DataFrame) -> list[EngineSpec]:
    present = set(df["engine"])
    return [spec for spec in ENGINES if spec.metric_engine in present]


def _agg_correctness(df: pd.DataFrame, spec: EngineSpec) -> dict[str, float]:
    rows = df[df["engine"] == spec.metric_engine]
    total = len(rows)
    ok = rows[rows["status"] == "ok"].copy()
    if ok.empty:
        return {
            "precision": math.nan,
            "recall": math.nan,
            "f1": math.nan,
            "nb_spurious": math.nan,
            "nb_missing": math.nan,
            "nb_duplicates": math.nan,
            "missing_vars": math.nan,
            "mismatch_rate": math.nan,
            "ok_rate": (0.0 if total else math.nan),
        }

    def _mean(column: str) -> float:
        return float(pd.to_numeric(ok[column], errors="coerce").mean())

    def _sum(column: str) -> float:
        return float(pd.to_numeric(ok[column], errors="coerce").fillna(0).sum())

    mismatch = ok["mismatch"].fillna(False).astype(bool)
    return {
        "precision": _mean("precision"),
        "recall": _mean("recall"),
        "f1": _mean("f1"),
        "nb_spurious": _sum("nb_spurious"),
        "nb_missing": _sum("nb_missing"),
        "nb_duplicates": _sum("nb_duplicates"),
        "missing_vars": _sum("missing_vars"),
        "mismatch_rate": float(mismatch.mean()),
        "ok_rate": float(len(ok) / total) if total else math.nan,
    }


def _metric_cell(
    value: float,
    text: str,
    *,
    best_value: float | None,
    higher_is_better: bool,
) -> str:
    if math.isnan(value):
        return "[--]"
    is_best = best_value is not None and value == best_value
    content = f"*{text}*" if is_best else text
    if is_best:
        return f'[#rect(fill: rgb("#90EE90"), inset: 1pt)[{content}]]'
    return f"[{content}]"


def correctness_table(df: pd.DataFrame, decimals: int) -> str:
    specs = _engine_specs_present(df)
    aggregates = {spec.metric_engine: _agg_correctness(df, spec) for spec in specs}
    metrics = (
        ("precision", True, "pct"),
        ("recall", True, "pct"),
        ("f1", True, "pct"),
        ("nb_spurious", False, "int"),
        ("nb_missing", False, "int"),
        ("nb_duplicates", False, "int"),
        ("missing_vars", False, "int"),
        ("mismatch_rate", False, "pct"),
        ("ok_rate", True, "pct"),
    )
    best: dict[str, float | None] = {}
    for key, higher_is_better, _kind in metrics:
        values = [aggregates[spec.metric_engine][key] for spec in specs]
        best[key] = finite_max(values) if higher_is_better else finite_min(values)

    lines = [
        "#align(center)[",
        "#figure(caption: [",
        "  Tabela. Métricas de corretude agregadas por engine. Valores em *negrito* indicam o melhor valor na coluna.",
        '  Valores em #box(rect(fill: rgb("#90EE90"), inset: 1pt)[verde]) indicam o melhor valor global da coluna.',
        "  Para Precision, Recall, F1 e OK, maior é melhor; para as demais métricas, menor é melhor.",
        "])[",
        "#text(size: 8.4pt)[",
        "#table(",
        "  columns: 11,",
        "  column-gutter: 3pt,",
        "  row-gutter: 1pt,",
        "  align: (left, left, center, center, center, center, center, center, center, center, center),",
        "  stroke: none,",
        "  inset: (x, y) => (",
        "    x: if y == 0 or y == 1 or x == 1 { 0pt } else { 0.5pt },",
        "    y: if y == 0 or y == 1 { 4pt } else if x == 1 { 1.9pt } else { 2pt }",
        "  ),",
        "",
        "  table.hline(stroke: .6pt),",
        "  table.cell(rowspan: 2, [*Tipo*], align: horizon),",
        "  table.cell(rowspan: 2, [*Engine*], align: horizon),",
        "  table.cell(colspan: 3, [*Qualidade do Resultado*]),",
        "  table.cell(colspan: 5, [*Erros*]),",
        "  table.cell(rowspan: 2, [*OK*], align: horizon),",
        "",
        "  table.hline(start: 2, end: 10, stroke: 0.3pt),",
        "",
        "  [Precision], [Recall], [F1],",
        "  [Espúrios], [Faltantes], [Duplicatas], [Vars ausentes], [Mismatch (%)],",
        "",
        "  table.hline(stroke: .6pt),",
        "  table.cell(colspan: 11, []),",
    ]

    first_in_group: dict[str, bool] = {}
    for spec in specs:
        group_specs = [item for item in specs if item.group == spec.group]
        if spec.group not in first_in_group:
            if first_in_group:
                lines.extend(["", "  table.cell(colspan: 11, []),", "  table.hline(stroke: .6pt),", "  table.cell(colspan: 11, []),"])
            lines.append(f"  table.cell(rowspan: {len(group_specs)}, [{spec.group}], align: horizon),")
            first_in_group[spec.group] = True

        row = [f"  [{spec.summary_label}],"]
        agg = aggregates[spec.metric_engine]
        for key, higher_is_better, kind in metrics:
            value = agg[key]
            text = fmt_pct(value) if kind == "pct" else ("--" if math.isnan(value) else f"{value:.0f}")
            row.append(
                f"    {_metric_cell(value, text, best_value=best[key], higher_is_better=higher_is_better)},"
            )
        lines.extend(row)

    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <tab:corretude>", "]"])
    return "\n".join(lines)


def source_selection_table(df: pd.DataFrame, decimals: int) -> str:
    specs = _engine_specs_present(df)
    values = source_selection_values(df)
    best = {
        column: finite_min([values[spec.metric_engine][column] for spec in specs])
        for column in SOURCE_SELECTION_COLUMNS
    }

    lines = [
        "#align(center)[",
        "#figure(caption: [",
        "  Tabela. Métricas de seleção de fontes agregadas por engine. Valores em *negrito* indicam o menor valor na coluna.",
        '  Valores em #box(rect(fill: rgb("#90EE90"), inset: 1pt)[verde]) indicam o menor valor global da coluna.',
        "  Para todas as métricas, menor é melhor.",
        "])[",
        "#text(size: 8.4pt)[",
        "#table(",
        "  columns: 10,",
        "  column-gutter: 3pt,",
        "  row-gutter: 1pt,",
        "  align: (left, left, center, center, center, center, center, center, center, center),",
        "  stroke: none,",
        "  inset: (x, y) => (",
        "    x: if y == 0 or y == 1 or x == 1 { 0pt } else { 0.5pt },",
        "    y: if y == 0 or y == 1 { 4pt } else if x == 1 { 1.9pt } else { 2pt }",
        "  ),",
        "",
        "  table.hline(stroke: .6pt),",
        "  table.cell(rowspan: 2, [*Tipo*], align: horizon),",
        "  table.cell(rowspan: 2, [*Engine*], align: horizon),",
        "  table.cell(colspan: 8, [*Seleção de Fontes*]),",
        "",
        "  table.hline(start: 2, end: 10, stroke: 0.3pt),",
        "",
        "  [TPWSS], [Avg RWSS], [Min RWSS], [Max RWSS], [Fontes distintas], [Selectividade], [Falsos positivos], [Requisições redundantes],",
        "",
        "  table.hline(stroke: .6pt),",
        "  table.cell(colspan: 10, []),",
    ]

    first_in_group: dict[str, bool] = {}
    for spec in specs:
        group_specs = [item for item in specs if item.group == spec.group]
        if spec.group not in first_in_group:
            if first_in_group:
                lines.extend(["", "  table.cell(colspan: 10, []),", "  table.hline(stroke: .6pt),", "  table.cell(colspan: 10, []),"])
            lines.append(f"  table.cell(rowspan: {len(group_specs)}, [{spec.group}], align: horizon),")
            first_in_group[spec.group] = True

        row = [f"  [{spec.summary_label}],"]
        agg = values[spec.metric_engine]
        for column in SOURCE_SELECTION_COLUMNS:
            value = agg[column]
            if column == "relevant_sources_selectivity":
                text = fmt_pct(value)
            else:
                text = fmt_decimal(value, decimals)
            row.append(
                f"    {_metric_cell(value, text, best_value=best[column], higher_is_better=False)},"
            )
        lines.extend(row)

    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <tab:selection-fontes>", "]"])
    return "\n".join(lines)


def _query_number(query: str) -> int:
    try:
        return int(str(query).lstrip("q"))
    except ValueError:
        return 0


def _time_fill(value: float) -> str:
    if math.isnan(value):
        return "soft-red"
    if value < 2:
        return "soft-green"
    if value <= 15:
        return "soft-yellow"
    if value <= 60:
        return "soft-orange"
    return "soft-red"


def _time_cell(value: float, decimals: int) -> str:
    if math.isnan(value):
        return "cell-to"
    text = fmt_decimal(value, decimals)
    if value < 15:
        return f'cell-time({value:.{decimals}f},"{text}")'
    return f"table.cell(fill: {_time_fill(value)})[{text}]"


def query_performance_table(df: pd.DataFrame, decimals: int, batch_id: int = 1) -> str:
    engines = list(QUERY_PERFORMANCE_ENGINES)
    if "anapsid" in set(df["engine"]) and "anapsid" not in engines:
        engines.append("anapsid")
    label_by_engine = {spec.metric_engine: spec.summary_label for spec in ENGINES}
    batch = df[df["batch"] == batch_id].copy()
    queries = sorted(batch["query"].dropna().unique(), key=_query_number)
    columns = ", ".join(["auto"] * (len(engines) + 1))

    lines = [
        "#figure(",
        "text(size: 18.5pt)[",
        "#align(center)[",
        "  #table(",
        f"    columns: ({columns}),",
        "    inset: 7pt,",
        "    align: center,",
        "    stroke: none,",
        "    fill: (x, y) => {",
        "      if y == 0 { soft-blue }",
        "      else { white }",
        "    },",
        "    [*Consulta*], table.vline(), "
        + ", ".join(f"[*{label_by_engine[engine]}*]" for engine in engines)
        + ",",
        "    table.hline(stroke: 1.5pt),",
    ]

    for query in queries:
        cells = [f"    [{_query_number(query)}]"]
        for engine in engines:
            rows = batch[(batch["engine"] == engine) & (batch["query"] == query) & (batch["status"] == "ok")]
            value = float(rows["exec_time"].mean()) if not rows.empty else math.nan
            cells.append(_time_cell(value, decimals))
        lines.append(", ".join(cells) + ",")

    lines.extend(
        [
            "  )",
            "]",
            "],",
            "caption: [",
            "  #box(fill: soft-green, inset: 5pt, radius: 3pt)[< 2s] rápido, #box(fill: soft-yellow, inset: 5pt, radius: 3pt)[2–15s] médio, #box(fill: soft-orange, inset: 5pt, radius: 3pt)[15–60s] lento, #box(fill: soft-red, inset: 5pt, radius: 3pt)[> 60s / T/O] crítico",
            "]",
            f") <tab:desempenho-consulta-batch{batch_id}>",
        ]
    )
    return "\n".join(lines)


def _label_engine(engine: str) -> str:
    for spec in ENGINES:
        if spec.metric_engine == engine:
            return spec.summary_label
    return engine


def _label_metric(metric: str) -> str:
    labels = {
        "exec_time": "Tempo",
        "source_selection_time": "Seleção",
        "planning_time": "Planejamento",
        "f1": "F1",
        "precision": "Precision",
        "recall": "Recall",
        "tpwss": "TPWSS",
        "avg_rwss": "Avg RWSS",
        "redundant_requests": "Req. redundantes",
        "false_positive_sources": "Falsos positivos",
    }
    return labels.get(metric, metric.replace("_", " "))


def _label_test(test: str) -> str:
    labels = {
        "wilcoxon": "Wilcoxon",
        "friedman": "Friedman",
        "spearman": "Spearman",
    }
    return labels.get(test, test)


def _hypothesis_comparison(row: pd.Series) -> str:
    test = str(row.get("test", ""))
    engine_a = str(row.get("engine_a", ""))
    engine_b = str(row.get("engine_b", ""))
    if test == "friedman":
        return "Todas as engines"
    if test == "spearman":
        return f"{_label_engine(engine_a)} $times$ batch"
    return f"{_label_engine(engine_a)} $times$ {_label_engine(engine_b)}"


def hypothesis_table(
    df: pd.DataFrame,
    decimals: int = 2,
    *,
    alpha: float = 0.05,
    target_engine: str = "fedshop-go",
    top_n: int = 8,
) -> str:
    available = [column for column in HYPOTHESIS_COLUMNS if column in df.columns]
    rows = df[available].copy()
    rows = rows[
        (rows["test"] == "wilcoxon")
        & (rows["engine_a"] == target_engine)
        & (pd.to_numeric(rows["n_pairs"], errors="coerce") >= 5)
    ].copy()
    for column in ("median_a", "median_b", "statistic", "p_value", "p_corrected"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows["median_delta"] = rows["median_a"] - rows["median_b"]
    rows["abs_median_delta"] = rows["median_delta"].abs()
    rows = (
        rows.dropna(subset=["median_delta", "p_value"])
        .sort_values(["abs_median_delta", "metric", "engine_b"], ascending=[False, True, True])
        .head(top_n)
    )

    lines = [
        "#figure(",
        "  table(",
        "    columns: (auto, auto, auto, auto, auto, auto),",
        "    align: (left, left, center, center, center, center),",
        "    stroke: none,",
        "    inset: 5pt,",
        "",
        "    table.header(",
        "      [*Comparação*],",
        "      [*Métrica*],",
        "      [*Δ mediana*],",
        "      [*W*],",
        "      [*P-ajustado*],",
        "      [*$n$*],",
        "    ),",
        "    table.hline(stroke: .6pt),",
    ]
    for _, row in rows.iterrows():
        statistic = row.get("statistic", math.nan)
        p_corrected = row.get("p_corrected", math.nan)
        n_pairs = row.get("n_pairs", math.nan)
        stat_text = "--" if math.isnan(statistic) else f"{statistic:.{decimals}f}".replace(".", ",")
        delta = row.get("median_delta", math.nan)
        delta_text = "--" if math.isnan(delta) else f"{delta:+.{decimals}f}".replace(".", ",")
        n_text = "--" if math.isnan(n_pairs) else f"{int(n_pairs)}"
        lines.append(
            f"    [{_hypothesis_comparison(row)}], "
            f"[{_label_metric(str(row.get('metric', '')))}], "
            f"[{delta_text}], "
            f"[{stat_text}], "
            f"[{fmt_pvalue(float(p_corrected))}], "
            f"[{n_text}],"
        )

    lines.extend(
        [
            "    table.hline(stroke: .6pt),",
            "  ),",
            (
                f"  caption: [Principais testes de Wilcoxon pareado: {_label_engine(target_engine)} "
                f"$times$ demais engines $(alpha = {alpha:g})$. Linhas ordenadas por diferença absoluta de mediana; "
                "P-ajustado usa correção de Holm.],"
            ),
            ") <tab:testes-hipotese>",
        ]
    )
    return "\n".join(lines)


def render(
    df: pd.DataFrame,
    mode: str,
    decimals: int,
    *,
    batch_id: int = 1,
    hypothesis_df: pd.DataFrame | None = None,
    alpha: float = 0.05,
    hypothesis_top_n: int = 8,
) -> str:
    parts = []
    if mode in {"all", "timing"}:
        parts.append(timing_table(df, decimals))
    if mode in {"all", "summary"}:
        parts.append(summary_table(df, decimals))
    if mode in {"all", "correctness"}:
        parts.append(correctness_table(df, decimals))
    if mode in {"all", "source-selection"}:
        parts.append(source_selection_table(df, decimals))
    if mode in {"all", "query-performance"}:
        parts.append(query_performance_table(df, decimals, batch_id=batch_id))
    if mode in {"all", "hypothesis"} and hypothesis_df is not None:
        parts.append(hypothesis_table(hypothesis_df, decimals, alpha=alpha, top_n=hypothesis_top_n))
    return "\n\n".join(parts) + "\n"
