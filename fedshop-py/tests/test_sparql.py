from unittest.mock import MagicMock, patch


def test_select_csv_extracts_default_graph_from_endpoint_url():
    from fedshop.sparql import SparqlClient

    wrapper = MagicMock()
    wrapper.query.return_value.convert.return_value = b"value\n"
    endpoint = (
        "http://localhost:8890/sparql?"
        "default-graph-uri=http%3A%2F%2Fwww.ratingsite0.fr%2F"
    )

    with patch("fedshop.sparql.SPARQLWrapper", return_value=wrapper) as factory:
        SparqlClient().select_csv(endpoint, "SELECT ?value WHERE { ?s ?p ?value }")

    factory.assert_called_once_with("http://localhost:8890/sparql")
    wrapper.addDefaultGraph.assert_called_once_with("http://www.ratingsite0.fr/")
