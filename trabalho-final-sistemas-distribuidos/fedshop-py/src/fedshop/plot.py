"""Plotting utilities for FedShop benchmark metrics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _f1_isocurve(f1: float, n: int = 300) -> tuple[np.ndarray, np.ndarray]:
    """Precision values for a given F1 iso-curve over recall in [f1/2, 1]."""
    r = np.linspace(f1 / 2 + 1e-6, 1.0, n)
    p = f1 * r / (2 * r - f1)
    valid = (p >= 0) & (p <= 1.0)
    return r[valid], p[valid]


def plot_precision_recall(
    df: pd.DataFrame,
    output: str | Path | None = None,
    title: str = "Precision × Recall",
    f1_levels: list[float] | None = None,
    annotate_queries: bool = False,
) -> None:
    """Scatter precision vs recall per engine, with filled area under sorted curve.

    Each point is one (engine, query, instance, batch) observation. Points are
    sorted by recall before drawing the line so the fill covers the area between
    the curve and the x-axis. F1 iso-curves are drawn as reference lines.

    Args:
        df: Full metrics DataFrame — must contain columns precision, recall, engine.
        output: Path to save the figure. If None, plt.show() is called.
        title: Figure title.
        f1_levels: F1 values for which to draw iso-curves (default 0.25, 0.5, 0.75).
        annotate_queries: Label each point with its query name.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    if f1_levels is None:
        f1_levels = [0.25, 0.5, 0.75]

    sub = df[["engine", "query", "instance", "batch", "precision", "recall"]].dropna(
        subset=["precision", "recall"]
    )
    if sub.empty:
        raise ValueError("No rows with valid precision and recall values.")

    engines = sorted(sub["engine"].unique())
    palette = plt.cm.tab10.colors  # type: ignore[attr-defined]

    fig, ax = plt.subplots(figsize=(8, 7))

    # ── F1 iso-curves ────────────────────────────────────────────────────────
    for f1 in f1_levels:
        r_iso, p_iso = _f1_isocurve(f1)
        ax.plot(r_iso, p_iso, "--", color="gray", linewidth=0.8, alpha=0.5, zorder=1)
        # Label near the bottom-right of each iso-curve
        ax.annotate(
            f"F1={f1:.2f}",
            xy=(r_iso[-1], p_iso[-1]),
            xytext=(3, -8),
            textcoords="offset points",
            fontsize=7,
            color="gray",
            alpha=0.8,
        )

    # ── Per-engine curve + fill ──────────────────────────────────────────────
    legend_handles = []
    for i, engine in enumerate(engines):
        color = palette[i % len(palette)]
        eng_df = sub[sub["engine"] == engine].sort_values("recall")

        recalls = eng_df["recall"].values
        precisions = eng_df["precision"].values

        # Fill the area between the curve and the x-axis
        ax.fill_between(recalls, precisions, alpha=0.18, color=color, zorder=2)

        # Line connecting the sorted points
        ax.plot(recalls, precisions, "-", color=color, linewidth=1.6, zorder=3, alpha=0.8)

        # Scatter each observation
        ax.scatter(
            recalls,
            precisions,
            color=color,
            s=45,
            zorder=5,
            edgecolors="white",
            linewidths=0.6,
        )

        if annotate_queries:
            for _, row in eng_df.iterrows():
                ax.annotate(
                    str(row["query"]),
                    xy=(row["recall"], row["precision"]),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=6,
                    color=color,
                    alpha=0.7,
                )

        legend_handles.append(mpatches.Patch(color=color, label=engine, alpha=0.8))

    # ── Axes decoration ──────────────────────────────────────────────────────
    ax.set_xlabel("Recall", fontsize=12)
    ax.set_ylabel("Precision", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlim(-0.04, 1.04)
    ax.set_ylim(-0.04, 1.04)
    ax.set_xticks(np.arange(0, 1.1, 0.1))
    ax.set_yticks(np.arange(0, 1.1, 0.1))
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.legend(handles=legend_handles, loc="lower left", framealpha=0.9, fontsize=10)

    plt.tight_layout()

    if output:
        plt.savefig(str(output), dpi=150, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
