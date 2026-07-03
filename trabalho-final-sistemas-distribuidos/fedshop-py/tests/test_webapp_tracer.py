import sys
from pathlib import Path


def test_tracer_uses_full_modular_pyfedx_core():
    root = Path(__file__).resolve().parents[2]
    webapp_dir = root / "webapp"
    sys.path.insert(0, str(webapp_dir))
    try:
        sys.modules.pop("tracer", None)
        tracer = __import__("tracer")
    finally:
        sys.path.remove(str(webapp_dir))

    assert tracer.pyfedx.__name__ == "pyfedx_engine"
    assert hasattr(tracer.pyfedx, "_collect_all_triples")


def test_tracer_pushes_filter_bgp_to_endpoint():
    root = Path(__file__).resolve().parents[2]
    webapp_dir = root / "webapp"
    sys.path.insert(0, str(webapp_dir))
    try:
        sys.modules.pop("tracer", None)
        tracer = __import__("tracer")
    finally:
        sys.path.remove(str(webapp_dir))

    query = tracer.pyfedx.parse_query(
        "SELECT ?product WHERE { "
        "<P> <feature> ?feature . "
        "?product <feature> ?feature . "
        "FILTER(<P> != ?product) "
        "}"
    )
    endpoint = tracer.pyfedx.Endpoint("e1", "http://e1/sparql")
    source_map = {triple: [endpoint] for triple in query.group.triples}
    tp_ids, _ = tracer.assign_tp_ids(query.group)
    trace = tracer.Trace()

    class FakeClient:
        def __init__(self):
            self.calls = []

        def traced_select(self, endpoint, sparql, tp_id):
            self.calls.append((endpoint, sparql, tp_id))
            return [{"product": "P2", "feature": "F1"}]

    client = FakeClient()
    rows = tracer.traced_execute_group(
        query.group, source_map, client, query.prefixes, tp_ids, trace
    )

    assert rows == [{"product": "P2", "feature": "F1"}]
    assert len(client.calls) == 1
    assert "FILTER(<P> != ?product)" in client.calls[0][1]
    assert client.calls[0][2] == "bgp"
