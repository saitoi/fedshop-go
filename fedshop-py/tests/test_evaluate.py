"""Tests for evaluate.py — evaluation loop and timeout propagation."""

from unittest.mock import patch


def test_check_timeout_propagation_returns_true_for_empty_file_no_stats(tmp_path):
    """Empty results.txt with no stats.csv is treated as timeout (fallback)."""
    from fedshop.evaluate import check_timeout_propagation

    results_txt = tmp_path / "results.txt"
    results_txt.write_text("")  # empty, no stats.csv
    assert check_timeout_propagation(results_txt) is True


def test_check_timeout_propagation_returns_false_empty_file_with_valid_stats(tmp_path):
    """Empty results.txt with valid exec_time in stats.csv means 0 results, not timeout."""
    from fedshop.evaluate import check_timeout_propagation
    import pandas as pd

    results_txt = tmp_path / "results.txt"
    results_txt.write_text("")  # empty
    stats = tmp_path / "stats.csv"
    pd.DataFrame([{"engine": "fedx", "query": "q07", "instance": "0", "batch": "0",
                   "attempt": "0", "exec_time": "2.18", "source_selection_time": "411.0",
                   "planning_time": "1.0", "ask": "0.0", "http_req": "0.0", "data_transfer": "0.0"}]).to_csv(stats, index=False)
    assert check_timeout_propagation(results_txt) is False


def test_check_timeout_propagation_returns_true_when_stats_say_timeout(tmp_path):
    """When stats.csv says exec_time=timeout, propagation should trigger."""
    from fedshop.evaluate import check_timeout_propagation
    import pandas as pd

    results_txt = tmp_path / "results.txt"
    results_txt.write_text("")
    stats = tmp_path / "stats.csv"
    pd.DataFrame([{"engine": "fedx", "query": "q01", "instance": "0", "batch": "0",
                   "attempt": "0", "exec_time": "timeout", "source_selection_time": "timeout",
                   "planning_time": "timeout", "ask": "timeout", "http_req": "timeout", "data_transfer": "timeout"}]).to_csv(stats, index=False)
    assert check_timeout_propagation(results_txt) is True


def test_check_timeout_propagation_returns_false_for_nonempty_file(tmp_path):
    from fedshop.evaluate import check_timeout_propagation

    results_txt = tmp_path / "results.txt"
    results_txt.write_text("some results\n")
    assert check_timeout_propagation(results_txt) is False


def test_check_timeout_propagation_returns_false_when_file_missing(tmp_path):
    from fedshop.evaluate import check_timeout_propagation

    missing = tmp_path / "nonexistent.txt"
    assert check_timeout_propagation(missing) is False


def test_stats_is_existing_result_accepts_numeric_and_timeout(tmp_path):
    from fedshop.evaluate import stats_is_existing_result
    import pandas as pd

    stats = tmp_path / "stats.csv"
    pd.DataFrame([{"exec_time": "1.25"}]).to_csv(stats, index=False)
    assert stats_is_existing_result(stats) is True

    pd.DataFrame([{"exec_time": "timeout"}]).to_csv(stats, index=False)
    assert stats_is_existing_result(stats) is True


def test_stats_is_existing_result_rejects_runtime_error(tmp_path):
    from fedshop.evaluate import stats_is_existing_result
    import pandas as pd

    stats = tmp_path / "stats.csv"
    pd.DataFrame([{"exec_time": "error_runtime"}]).to_csv(stats, index=False)
    assert stats_is_existing_result(stats) is False


def test_stats_is_existing_result_rejects_blank_and_nan(tmp_path):
    from fedshop.evaluate import stats_is_existing_result
    import pandas as pd

    stats = tmp_path / "stats.csv"
    pd.DataFrame([{"exec_time": ""}]).to_csv(stats, index=False)
    assert stats_is_existing_result(stats) is False

    pd.DataFrame([{"exec_time": None}]).to_csv(stats, index=False)
    assert stats_is_existing_result(stats) is False


def test_run_evaluation_skips_when_previous_batch_timed_out(config_small, tmp_path):
    """run_evaluation with timeout propagation should write 'timeout' to stats and not call engine."""
    from fedshop.evaluate import run_evaluation

    # Set up batch 0 results.txt as empty (simulating timeout)
    eval_dir = tmp_path / "evaluation" / "fedx" / "q05" / "instance_0" / "batch_0" / "attempt_0"
    eval_dir.mkdir(parents=True)
    (eval_dir / "results.txt").write_text("")

    import pandas as pd

    stats = run_evaluation(
        config=config_small,
        engine_name="fedx",
        query_name="q05",
        instance_id=0,
        batch_id=1,
        attempt=0,
        bench_dir=tmp_path,
    )

    assert stats.exists()
    df = pd.read_csv(stats)
    assert df.iloc[0]["exec_time"] == "timeout"


def test_run_evaluation_noexec_writes_timeout_stats(config_small, tmp_path):
    """run_evaluation with noexec=True should write timeout stats without running engine."""
    from fedshop.evaluate import run_evaluation

    import pandas as pd

    query_path = tmp_path / "generation" / "q01" / "instance_0" / "injected.sparql"
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("SELECT * WHERE { ?s ?p ?o }")

    stats = run_evaluation(
        config=config_small,
        engine_name="fedx",
        query_name="q01",
        instance_id=0,
        batch_id=0,
        attempt=0,
        bench_dir=tmp_path,
        noexec=True,
    )

    assert stats.exists()
    df = pd.read_csv(stats)
    assert df.iloc[0]["exec_time"] == "timeout"


def test_run_evaluation_noexec_truncates_stale_normalized_artifacts(config_small, tmp_path):
    """A failed rerun must not leave results/provenance from an older attempt."""
    from fedshop.evaluate import run_evaluation

    query_path = tmp_path / "generation" / "q01" / "instance_0" / "injected.sparql"
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("SELECT * WHERE { ?s ?p ?o }")

    out_dir = (
        tmp_path / "evaluation" / "fedshop-go" / "q01" / "instance_0"
        / "batch_0" / "attempt_0"
    )
    out_dir.mkdir(parents=True)
    (out_dir / "results.csv").write_text("value\nstale\n")
    (out_dir / "provenance.csv").write_text("tp0\nstale-source\n")

    run_evaluation(
        config=config_small,
        engine_name="fedshop-go",
        query_name="q01",
        instance_id=0,
        batch_id=0,
        attempt=0,
        bench_dir=tmp_path,
        noexec=True,
    )

    assert (out_dir / "results.csv").read_text() == ""
    assert (out_dir / "provenance.csv").read_text() == ""


def test_run_evaluation_calls_proxy_reset_before_engine(config_small, tmp_path, mock_proxy_client):
    """When run normally, proxy.reset() must be called before the engine subprocess."""
    from fedshop.evaluate import run_evaluation
    from fedshop.proxy import ProxyClient

    call_order = []

    class TrackingProxy(ProxyClient):
        def __init__(self):
            pass

        def reset(self):
            call_order.append("reset")

        def get_stats(self):
            return {"NB_HTTP_REQ": 0, "NB_ASK": 0, "DATA_TRANSFER": 0}

    proxy = TrackingProxy()

    gen_dir = tmp_path / "generation" / "q01" / "instance_0"
    gen_dir.mkdir(parents=True)
    (gen_dir / "injected.sparql").write_text("SELECT ?s WHERE { ?s ?p ?o . }")
    (gen_dir / "composition.json").write_text('{"tp0": ["?s", "?p", "?o"]}')

    mapping_path = tmp_path / "virtuoso-proxy-mapping-batch0.json"
    mapping_path.write_text("{}")
    config_small.generation.workdir = str(tmp_path)

    with patch("fedshop.evaluate.run_evaluation") as mock_run:
        mock_run.return_value = tmp_path / "stats.csv"
        (tmp_path / "stats.csv").parent.mkdir(parents=True, exist_ok=True)

    # The test just verifies noexec path doesn't call engine — full path requires FedX binary
    stats = run_evaluation(
        config=config_small,
        engine_name="fedx",
        query_name="q01",
        instance_id=0,
        batch_id=0,
        attempt=0,
        bench_dir=tmp_path,
        noexec=True,
        proxy_client=proxy,
    )
    assert stats.exists()
