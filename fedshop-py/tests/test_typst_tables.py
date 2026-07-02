from __future__ import annotations

import pandas as pd


def _metrics_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "engine": "fedshop-go",
                "query": "q01",
                "instance": 0,
                "batch": 1,
                "attempt": 0,
                "status": "ok",
                "exec_time": 1.0,
                "planning_time": 0.5,
                "source_selection_time": 0.2,
                "join_time": 0.3,
                "precision": 1.0,
                "recall": 0.5,
                "f1": 2 / 3,
                "nb_spurious": 0,
                "nb_missing": 1,
                "nb_duplicates": 0,
                "missing_vars": 0,
                "mismatch": True,
                "tpwss": 4.0,
                "avg_rwss": 2.0,
                "min_rwss": 1.0,
                "max_rwss": 3.0,
                "nb_distinct_sources": 3.0,
                "relevant_sources_selectivity": 0.15,
                "false_positive_sources": 1.0,
                "redundant_requests": 2.0,
            },
            {
                "engine": "fedshop-go",
                "query": "q01",
                "instance": 0,
                "batch": 1,
                "attempt": 1,
                "status": "ok",
                "exec_time": 3.0,
                "planning_time": 0.8,
                "source_selection_time": 0.4,
                "join_time": 1.8,
                "precision": 0.5,
                "recall": 0.5,
                "f1": 0.5,
                "nb_spurious": 2,
                "nb_missing": 2,
                "nb_duplicates": 1,
                "missing_vars": 0,
                "mismatch": False,
                "tpwss": 6.0,
                "avg_rwss": 3.0,
                "min_rwss": 2.0,
                "max_rwss": 4.0,
                "nb_distinct_sources": 4.0,
                "relevant_sources_selectivity": 0.20,
                "false_positive_sources": 2.0,
                "redundant_requests": 3.0,
            },
            {
                "engine": "fedshop-go",
                "query": "q02",
                "instance": 0,
                "batch": 0,
                "attempt": 0,
                "status": "ok",
                "exec_time": 100.0,
                "planning_time": 2.0,
                "source_selection_time": 1.0,
                "join_time": 97.0,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "nb_spurious": 0,
                "nb_missing": 0,
                "nb_duplicates": 0,
                "missing_vars": 0,
                "mismatch": False,
                "tpwss": 2.0,
                "avg_rwss": 1.0,
                "min_rwss": 1.0,
                "max_rwss": 1.0,
                "nb_distinct_sources": 2.0,
                "relevant_sources_selectivity": 0.10,
                "false_positive_sources": 0.0,
                "redundant_requests": 0.0,
            },
            {
                "engine": "fedx",
                "query": "q01",
                "instance": 0,
                "batch": 1,
                "attempt": 0,
                "status": "timeout",
                "exec_time": None,
                "planning_time": None,
                "source_selection_time": None,
                "join_time": None,
                "precision": None,
                "recall": None,
                "f1": None,
                "nb_spurious": None,
                "nb_missing": None,
                "nb_duplicates": None,
                "missing_vars": None,
                "mismatch": None,
                "tpwss": None,
                "avg_rwss": None,
                "min_rwss": None,
                "max_rwss": None,
                "nb_distinct_sources": None,
                "relevant_sources_selectivity": None,
                "false_positive_sources": None,
                "redundant_requests": None,
            },
            {
                "engine": "fedx",
                "query": "q02",
                "instance": 0,
                "batch": 1,
                "attempt": 0,
                "status": "timeout",
                "exec_time": None,
                "planning_time": None,
                "source_selection_time": None,
                "join_time": None,
                "precision": None,
                "recall": None,
                "f1": None,
                "nb_spurious": None,
                "nb_missing": None,
                "nb_duplicates": None,
                "missing_vars": None,
                "mismatch": None,
                "tpwss": None,
                "avg_rwss": None,
                "min_rwss": None,
                "max_rwss": None,
                "nb_distinct_sources": None,
                "relevant_sources_selectivity": None,
                "false_positive_sources": None,
                "redundant_requests": None,
            },
            {
                "engine": "rsa",
                "query": "q01",
                "instance": 0,
                "batch": 1,
                "attempt": 0,
                "status": "ok",
                "exec_time": 61.0,
                "planning_time": 5.0,
                "source_selection_time": 2.0,
                "join_time": 54.0,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "nb_spurious": 0,
                "nb_missing": 0,
                "nb_duplicates": 0,
                "missing_vars": 0,
                "mismatch": False,
                "tpwss": 2.0,
                "avg_rwss": 1.0,
                "min_rwss": 1.0,
                "max_rwss": 1.0,
                "nb_distinct_sources": 1.0,
                "relevant_sources_selectivity": 0.05,
                "false_positive_sources": 0.0,
                "redundant_requests": 0.0,
            },
        ]
    )


def _hypothesis_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "test": "wilcoxon",
                "metric": "exec_time",
                "engine_a": "fedshop-go",
                "engine_b": "fedx",
                "n_pairs": 12,
                "statistic": 10.0,
                "p_value": 0.0000004,
                "p_corrected": 0.000002,
                "significant": True,
                "median_a": 1.0,
                "median_b": 2.0,
                "direction": "lower",
            },
            {
                "test": "wilcoxon",
                "metric": "tpwss",
                "engine_a": "fedshop-go",
                "engine_b": "rsa",
                "n_pairs": 12,
                "statistic": 2.0,
                "p_value": 0.00001,
                "p_corrected": 0.00003,
                "significant": True,
                "median_a": 80.0,
                "median_b": 2.0,
                "direction": "higher",
            },
            {
                "test": "wilcoxon",
                "metric": "precision",
                "engine_a": "fedshop-go",
                "engine_b": "splendid",
                "n_pairs": 4,
                "statistic": 1.0,
                "p_value": 0.5,
                "p_corrected": 0.5,
                "significant": False,
                "median_a": 1.0,
                "median_b": 0.0,
                "direction": "higher",
            },
            {
                "test": "friedman",
                "metric": "f1",
                "engine_a": "all",
                "engine_b": "all",
                "n_pairs": 12,
                "statistic": 5.5,
                "p_value": 0.02,
                "p_corrected": 0.02,
                "significant": True,
                "median_a": None,
                "median_b": None,
                "direction": "engines=fedshop-go,fedx,rsa",
            },
            {
                "test": "spearman",
                "metric": "tpwss",
                "engine_a": "rsa",
                "engine_b": "batch",
                "n_pairs": 12,
                "statistic": -0.3,
                "p_value": 0.4,
                "p_corrected": 0.4,
                "significant": False,
                "median_a": 2.0,
                "median_b": None,
                "direction": "decreases",
            },
        ]
    )


def test_apply_attempt_policy_primary_keeps_attempt_zero_only():
    from fedshop.typst_tables import apply_attempt_policy

    df = apply_attempt_policy(_metrics_df(), "primary")

    assert set(df["attempt"]) == {0}
    assert len(df[df["engine"] == "fedshop-go"]) == 2


def test_correctness_table_aggregates_all_attempts_by_default():
    from fedshop.typst_tables import correctness_table

    table = correctness_table(_metrics_df(), decimals=1)

    assert "<tab:corretude>" in table
    assert "[FedShop-Go]," in table
    assert "[83,3\\%]," in table
    assert "[66,7\\%]," in table
    assert "[72,2\\%]," in table
    assert "[3]," in table
    assert "[33,3\\%]," in table
    assert "100,0\\%" in table


def test_source_selection_table_aggregates_all_attempts_by_default():
    from fedshop.typst_tables import source_selection_table

    table = source_selection_table(_metrics_df(), decimals=1)

    assert "<tab:selection-fontes>" in table
    assert "[FedShop-Go]," in table
    assert "[2,0]," in table
    assert "15,0\\%" in table
    assert "[1,0]," in table
    assert "[*0,0*]" in table
    assert "[RSA]," in table


def test_render_all_includes_source_selection_table():
    from fedshop.typst_tables import render

    output = render(_metrics_df(), "all", decimals=1, batch_id=1)

    assert "<tab:selection-fontes>" in output
    assert "<tab:corretude>" in output
    assert "<tab:desempenho-consulta-batch1>" in output


def test_query_performance_table_filters_batch_one_and_marks_timeouts():
    from fedshop.typst_tables import query_performance_table

    table = query_performance_table(_metrics_df(), decimals=2, batch_id=1)

    assert "<tab:desempenho-consulta-batch1>" in table
    assert "[1], cell-time(2.00,\"2,00\")" in table
    assert "[2], cell-to" in table
    assert "100,00" not in table
    assert "table.cell(fill: soft-red)[61,00]" in table
    assert "[*FedShop-Go*], [*FedX*], [*RSA*]" in table


def test_hypothesis_table_renders_current_statistical_tests():
    from fedshop.typst_tables import hypothesis_table

    table = hypothesis_table(_hypothesis_df(), decimals=2, alpha=0.05)

    assert "<tab:testes-hipotese>" in table
    assert "[FedShop-Go $times$ RSA], [TPWSS], [+78,00], [2,00], [0,000030], [12]," in table
    assert "[FedShop-Go $times$ FedX], [Tempo], [-1,00], [10,00], [0,000002], [12]," in table
    assert "[Friedman]" not in table
    assert "[Spearman]" not in table
    assert "SPLENDID" not in table


def test_render_all_includes_hypothesis_table_when_dataframe_is_provided():
    from fedshop.typst_tables import render

    output = render(_metrics_df(), "all", decimals=1, batch_id=1, hypothesis_df=_hypothesis_df())

    assert "<tab:testes-hipotese>" in output
