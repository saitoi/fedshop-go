import subprocess
from pathlib import Path
from unittest.mock import patch

import pandas as pd


def test_run_benchmark_marks_arq_timeout_as_timeout(config_small, tmp_path):
    from fedshop.engines.rsa import RsaAdapter

    adapter = RsaAdapter.__new__(RsaAdapter)
    adapter.config = config_small
    adapter.engine_dir = tmp_path
    adapter.fedup_dir = tmp_path / "fedup"
    adapter._fedup_jar = str(tmp_path / "fedup.jar")
    adapter._jena_bin = str(tmp_path / "jena" / "bin")
    adapter._java_bin = "java"
    (tmp_path / "jena" / "bin").mkdir(parents=True)

    query_path = tmp_path / "query.sparql"
    query_path.write_text("SELECT * WHERE { ?s ?p ?o }")
    out_dir = tmp_path / "evaluation" / "rsa" / "q05" / "instance_0" / "batch_0" / "attempt_0"
    out_dir.mkdir(parents=True)

    class Proxy:
        def reset(self):
            pass

        def get_stats(self):
            return {"NB_HTTP_REQ": 0, "NB_ASK": 0, "DATA_TRANSFER": 0}

    class FedupProcess:
        returncode = 0

        def __init__(self, *args, **kwargs):
            kwargs["stderr"].write(
                "SELECT * WHERE { SERVICE <http://example.test/sparql> { ?s ?p ?o } }\n"
                "Took 1 ms to perform the source assignment.\n"
            )

        def wait(self, timeout=None):
            return 0

    with patch("fedshop.engines.rsa._wait_jena"), \
         patch("fedshop.engines.rsa.subprocess.Popen", side_effect=FedupProcess), \
         patch("fedshop.engines.rsa.subprocess.run", side_effect=subprocess.TimeoutExpired(["arq"], 1)):
        adapter.run_benchmark(
            query_path=query_path,
            batch_id=0,
            out_result=out_dir / "results.txt",
            out_source_selection=out_dir / "source_selection.txt",
            query_plan=out_dir / "query_plan.txt",
            stats=out_dir / "stats.csv",
            proxy_client=Proxy(),
        )

    df = pd.read_csv(out_dir / "stats.csv")
    assert df.iloc[0]["exec_time"] == "timeout"
