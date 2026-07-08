"""Typst tables and plots for the distributed-topology benchmark.

Consumes the merged CSV from `fedshop topology merge` and the hypothesis CSV
from `fedshop topology hypothesis`. Rendering helpers are reused from
typst_tables.py so the tables match the article's visual style.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .typst_tables import ENGINES, finite_min, fmt_decimal, fmt_pct, fmt_pvalue, typst_cell

TIMING_COLUMNS = ("exec_time", "planning_time", "source_selection_time", "join_time")

TOPOLOGY_LABELS = {
    "topo1": "T1 — 1 máquina",
    "topo2": "T2 — endpoints remotos",
    "topo3": "T3 — 3 máquinas",
}

_ENGINE_LABELS = {spec.metric_engine: spec.timing_label for spec in ENGINES}


def _engine_label(engine: str) -> str:
    return _ENGINE_LABELS.get(engine, engine)


def _topology_label(topology: str) -> str:
    return TOPOLOGY_LABELS.get(topology, topology)


def _mean_ok(df: pd.DataFrame, column: str) -> float:
    rows = df[df["status"] == "ok"]
    if rows.empty or column not in rows.columns:
        return math.nan
    return float(pd.to_numeric(rows[column], errors="coerce").mean())


def _engines_present(df: pd.DataFrame) -> list[str]:
    present = list(df["engine"].unique())
    ordered = [spec.metric_engine for spec in ENGINES if spec.metric_engine in present]
    return ordered + sorted(set(present) - set(ordered))


# ─── Table 1: timing per topology ────────────────────────────────────────────

def topology_timing_table(df: pd.DataFrame, decimals: int = 2) -> str:
    """Mean stage times per (topology, engine); gold = global best per column."""
    topologies = sorted(df["topology"].unique())
    engines = _engines_present(df)

    values: dict[tuple[str, str], dict[str, float]] = {}
    for topology in topologies:
        for engine in engines:
            sub = df[(df["topology"] == topology) & (df["engine"] == engine)]
            values[(topology, engine)] = {c: _mean_ok(sub, c) for c in TIMING_COLUMNS}

    global_best = {
        column: finite_min([values[key][column] for key in values])
        for column in TIMING_COLUMNS
    }
    topo_best = {
        (topology, column): finite_min([values[(topology, e)][column] for e in engines])
        for topology in topologies
        for column in TIMING_COLUMNS
    }

    lines = [
        "#align(center)[",
        "#figure(caption: [",
        "  Tempos médios (em segundos) por estágio e por topologia.",
        "  Valores em *negrito* indicam o melhor motor dentro da topologia;",
        '  células em #box(fill: rgb("#DAA520"), inset: 1pt)[dourado] indicam o',
        "  melhor tempo global da coluna.",
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
        "  [*Topologia*],",
        "  [*Motor*],",
        "  [`exec_time`],",
        "  [`planning_time`],",
        "  [`source_selection_time`],",
        "  [`join_time`],",
        "",
    ]

    for topology in topologies:
        lines.append("  table.hline(stroke: .6pt),")
        lines.append(
            f"  table.cell(rowspan: {len(engines)}, [{_topology_label(topology)}], align: horizon),"
        )
        for engine in engines:
            row = [f"  [{_engine_label(engine)}],"]
            for column in TIMING_COLUMNS:
                value = values[(topology, engine)][column]
                text = fmt_decimal(value, decimals)
                is_topo_best = (
                    not math.isnan(value)
                    and topo_best[(topology, column)] is not None
                    and value == topo_best[(topology, column)]
                )
                is_global_best = (
                    not math.isnan(value)
                    and global_best[column] is not None
                    and value == global_best[column]
                )
                row.append(f"    {typst_cell(text, bold=is_topo_best, gold=is_global_best)},")
            lines.extend(row)

    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <res:tempo-topologias>", "]"])
    return "\n".join(lines)


# ─── Table 2: exec_time × batch × topology ───────────────────────────────────

def topology_batch_table(df: pd.DataFrame, decimals: int = 2) -> str:
    """Mean exec_time per batch for each (engine, topology) row."""
    batches = sorted(int(b) for b in df["batch"].unique())
    engines = _engines_present(df)
    topologies = sorted(df["topology"].unique())
    n_cols = 2 + len(batches)

    lines = [
        "#align(center)[",
        "#figure(caption: [",
        "  Tempo médio de execução (s) por lote (nº de endpoints = 20 + 20·lote),",
        "  motor e topologia.",
        "])[",
        "#text(size: 7.5pt)[",
        "#table(",
        f"  columns: {n_cols},",
        "  column-gutter: 3pt,",
        "  row-gutter: 1pt,",
        f"  align: (left, left{', center' * len(batches)}),",
        "  stroke: none,",
        "  inset: (x, y) => (x: 5pt, y: 3pt),",
        "",
        "  table.hline(stroke: .6pt),",
        "  [*Motor*],",
        "  [*Topo.*],",
    ]
    lines.extend(f"  [*b{batch}*]," for batch in batches)
    lines.append("")

    for engine in engines:
        lines.append("  table.hline(stroke: .6pt),")
        first = True
        for topology in topologies:
            sub = df[(df["engine"] == engine) & (df["topology"] == topology)]
            label = _engine_label(engine) if first else ""
            if first:
                lines.append(
                    f"  table.cell(rowspan: {len(topologies)}, [{label}], align: horizon),"
                )
                first = False
            row = [f"  [{topology.replace('topo', 'T')}],"]
            for batch in batches:
                value = _mean_ok(sub[sub['batch'] == batch], "exec_time")
                row.append(f"    {typst_cell(fmt_decimal(value, decimals))},")
            lines.extend(row)

    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <res:tempo-batch-topologia>", "]"])
    return "\n".join(lines)


# ─── Table 3: distributed-systems summary ────────────────────────────────────

def topology_summary_table(df: pd.DataFrame, decimals: int = 2) -> str:
    """Per (engine, topology): slowdown, network ratio, jitter, reliability."""
    engines = _engines_present(df)
    topologies = sorted(df["topology"].unique())

    lines = [
        "#align(center)[",
        "#figure(caption: [",
        "  Métricas de sistemas distribuídos por motor e topologia: _slowdown_",
        "  mediano vs T1, fração do tempo em rede (>1 indica requisições",
        "  sobrepostas), jitter (coeficiente de variação do tempo entre",
        "  execuções), vazão e taxa de sucesso.",
        "])[",
        "#text(size: 7.5pt)[",
        "#table(",
        "  columns: 7,",
        "  column-gutter: 3pt,",
        "  row-gutter: 1pt,",
        "  align: (left, left, center, center, center, center, center),",
        "  stroke: none,",
        "  inset: (x, y) => (x: 6pt, y: 3pt),",
        "",
        "  table.hline(stroke: .6pt),",
        "  [*Motor*],",
        "  [*Topo.*],",
        "  [_slowdown_ vs T1],",
        "  [tempo em rede],",
        "  [jitter (CV)],",
        "  [vazão (linhas/s)],",
        "  [sucesso],",
        "",
    ]

    for engine in engines:
        lines.append("  table.hline(stroke: .6pt),")
        first = True
        for topology in topologies:
            sub = df[(df["engine"] == engine) & (df["topology"] == topology)]
            if first:
                lines.append(
                    f"  table.cell(rowspan: {len(topologies)}, [{_engine_label(engine)}], align: horizon),"
                )
                first = False
            ok = sub[sub["status"] == "ok"]
            total = len(sub)
            success = len(ok) / total if total else math.nan

            def _median(column: str) -> float:
                if column not in ok.columns or ok.empty:
                    return math.nan
                return float(pd.to_numeric(ok[column], errors="coerce").median())

            lines.append(f"  [{topology.replace('topo', 'T')}],")
            lines.append(f"    {typst_cell(fmt_decimal(_median('slowdown_vs_t1'), decimals))},")
            lines.append(f"    {typst_cell(fmt_decimal(_median('network_time_ratio'), decimals))},")
            lines.append(f"    {typst_cell(fmt_decimal(_median('exec_time_cv'), decimals))},")
            lines.append(f"    {typst_cell(fmt_decimal(_median('throughput_rows_s'), 1))},")
            lines.append(f"    {typst_cell(fmt_pct(success))},")

    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <res:resumo-topologias>", "]"])
    return "\n".join(lines)


# ─── Table 4: hypothesis results ─────────────────────────────────────────────

def topology_hypothesis_table(hyp_df: pd.DataFrame, alpha: float = 0.05) -> str:
    lines = [
        "#align(center)[",
        "#figure(caption: [",
        f"  Testes de hipótese sobre topologias (α = {str(alpha).replace('.', ',')},",
        "  correção de Holm-Bonferroni nos pares Wilcoxon).",
        "])[",
        "#text(size: 7.5pt)[",
        "#table(",
        "  columns: 8,",
        "  column-gutter: 3pt,",
        "  row-gutter: 1pt,",
        "  align: (left, left, left, left, center, center, center, left),",
        "  stroke: none,",
        "  inset: (x, y) => (x: 5pt, y: 3pt),",
        "",
        "  table.hline(stroke: .6pt),",
        "  [*Hip.*],",
        "  [*Teste*],",
        "  [*Métrica*],",
        "  [*Comparação*],",
        "  [*n*],",
        "  [*p (corr.)*],",
        "  [*Signif.*],",
        "  [*Direção*],",
        "",
        "  table.hline(stroke: .6pt),",
    ]
    for _, row in hyp_df.iterrows():
        comparison = f"{row['group_a']} vs {row['group_b']}"
        p_corr = row.get("p_corrected", math.nan)
        significant = bool(row.get("significant", False))
        lines.append(f"  [{row['hypothesis']}],")
        lines.append(f"  [{row['test']}],")
        lines.append(f"  [`{row['metric']}`],")
        lines.append(f"  [{comparison}],")
        lines.append(f"  [{int(row['n_pairs'])}],")
        lines.append(f"    {typst_cell(fmt_pvalue(float(p_corr)) if pd.notna(p_corr) else '--', bold=significant)},")
        lines.append(f"  [{'sim' if significant else 'não'}],")
        lines.append(f"  [{row['direction']}],")
    lines.extend(["", "  table.hline(stroke: .6pt),", ")", "]", "] <res:hipoteses-topologias>", "]"])
    return "\n".join(lines)


def render_topology_tables(
    df: pd.DataFrame,
    hypothesis_df: pd.DataFrame | None = None,
    decimals: int = 2,
    alpha: float = 0.05,
) -> str:
    parts = [
        topology_timing_table(df, decimals),
        topology_batch_table(df, decimals),
        topology_summary_table(df, decimals),
    ]
    if hypothesis_df is not None and not hypothesis_df.empty:
        parts.append(topology_hypothesis_table(hypothesis_df, alpha))
    return "\n\n".join(parts) + "\n"


# ─── Plots ───────────────────────────────────────────────────────────────────

_TOPOLOGY_COLORS = {"topo1": "#4477AA", "topo2": "#EE6677", "topo3": "#228833"}


def plot_topology(df: pd.DataFrame, output_dir: Path | str) -> list[Path]:
    """Write exec_time×batch, slowdown, and network-ratio figures as PDF+PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    engines = _engines_present(df)
    topologies = sorted(df["topology"].unique())
    ok = df[df["status"] == "ok"]

    # 1. exec_time vs batch, one line per topology, faceted per engine.
    fig, axes = plt.subplots(
        1, len(engines), figsize=(4.2 * len(engines), 3.4), sharey=True, squeeze=False,
    )
    for ax, engine in zip(axes[0], engines):
        for topology in topologies:
            sub = ok[(ok["engine"] == engine) & (ok["topology"] == topology)]
            series = sub.groupby("batch")["exec_time"].mean().sort_index()
            ax.plot(
                series.index, series.values, marker="o", markersize=3.5,
                label=topology.replace("topo", "T"),
                color=_TOPOLOGY_COLORS.get(topology),
            )
        ax.set_title(_engine_label(engine))
        ax.set_xlabel("lote (batch)")
        ax.grid(True, alpha=0.25)
    axes[0][0].set_ylabel("tempo de execução médio (s)")
    axes[0][-1].legend(title="Topologia", fontsize=8)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        path = output_dir / f"exec-time-batch-topology.{ext}"
        fig.savefig(path, dpi=200)
        written.append(path)
    plt.close(fig)

    # 2. Median slowdown vs T1 per engine and topology.
    if "slowdown_vs_t1" in ok.columns:
        fig, ax = plt.subplots(figsize=(1.4 + 1.6 * len(engines), 3.2))
        width = 0.8 / max(1, len(topologies))
        for t_idx, topology in enumerate(topologies):
            medians = [
                ok[(ok["engine"] == e) & (ok["topology"] == topology)]["slowdown_vs_t1"].median()
                for e in engines
            ]
            positions = [i + t_idx * width for i in range(len(engines))]
            ax.bar(
                positions, medians, width,
                label=topology.replace("topo", "T"),
                color=_TOPOLOGY_COLORS.get(topology),
            )
        ax.axhline(1.0, color="gray", linewidth=0.8, linestyle="--")
        ax.set_xticks([i + width * (len(topologies) - 1) / 2 for i in range(len(engines))])
        ax.set_xticklabels([_engine_label(e) for e in engines])
        ax.set_ylabel("slowdown mediano vs T1")
        ax.legend(title="Topologia", fontsize=8)
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        for ext in ("pdf", "png"):
            path = output_dir / f"slowdown-topology.{ext}"
            fig.savefig(path, dpi=200)
            written.append(path)
        plt.close(fig)

    # 3. Network-time ratio per engine and topology.
    if "network_time_ratio" in ok.columns and ok["network_time_ratio"].notna().any():
        fig, ax = plt.subplots(figsize=(1.4 + 1.6 * len(engines), 3.2))
        width = 0.8 / max(1, len(topologies))
        for t_idx, topology in enumerate(topologies):
            medians = [
                ok[(ok["engine"] == e) & (ok["topology"] == topology)]["network_time_ratio"].median()
                for e in engines
            ]
            positions = [i + t_idx * width for i in range(len(engines))]
            ax.bar(
                positions, medians, width,
                label=topology.replace("topo", "T"),
                color=_TOPOLOGY_COLORS.get(topology),
            )
        ax.axhline(1.0, color="gray", linewidth=0.8, linestyle="--")
        ax.set_xticks([i + width * (len(topologies) - 1) / 2 for i in range(len(engines))])
        ax.set_xticklabels([_engine_label(e) for e in engines])
        ax.set_ylabel("tempo em rede / tempo total")
        ax.legend(title="Topologia", fontsize=8)
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        for ext in ("pdf", "png"):
            path = output_dir / f"network-ratio-topology.{ext}"
            fig.savefig(path, dpi=200)
            written.append(path)
        plt.close(fig)

    return written
