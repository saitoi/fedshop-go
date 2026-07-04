from urllib.parse import parse_qs, urlparse
from unittest.mock import patch
import unittest

import infra
from config_support import build_batch_mapping, normalize_mapping


class ConfigSupportTests(unittest.TestCase):
    def test_batch_mapping_builds_cumulative_default_graph_endpoints(self):
        mapping = build_batch_mapping(2)

        self.assertEqual(60, len(mapping))
        self.assertIn("http://www.vendor20.fr/", mapping)
        self.assertIn("http://www.vendor29.fr/", mapping)
        self.assertIn("http://www.ratingsite29.fr/", mapping)

        parsed = urlparse(mapping["http://www.vendor20.fr/"])
        self.assertEqual("http", parsed.scheme)
        self.assertEqual("localhost:8890", parsed.netloc)
        self.assertEqual("/sparql", parsed.path)
        self.assertEqual(
            ["http://www.vendor20.fr/"],
            parse_qs(parsed.query)["default-graph-uri"],
        )

    def test_normalize_mapping_rewrites_legacy_member_routes(self):
        mapping = normalize_mapping({
            "http://www.vendor20.fr/": "http://localhost:8890/vendor20/sparql",
        })

        url = mapping["http://www.vendor20.fr/"]
        self.assertNotIn("/vendor20/sparql", url)
        self.assertEqual(
            ["http://www.vendor20.fr/"],
            parse_qs(urlparse(url).query)["default-graph-uri"],
        )

    def test_global_remote_endpoint_applies_to_generated_and_normalized_mappings(self):
        with patch.dict(
            "os.environ",
            {"FEDSHOP_VIRTUOSO_ENDPOINT": "http://10.10.0.2:8890/sparql"},
        ):
            generated = build_batch_mapping(0, members_per_batch=1)
            normalized = normalize_mapping({
                "http://www.vendor0.fr/": "http://localhost:8890/vendor0/sparql",
            })

        for url in (
            generated["http://www.vendor0.fr/"],
            generated["http://www.ratingsite0.fr/"],
            normalized["http://www.vendor0.fr/"],
        ):
            parsed = urlparse(url)
            self.assertEqual("10.10.0.2:8890", parsed.netloc)
            self.assertEqual("/sparql", parsed.path)
            self.assertIn("default-graph-uri", parse_qs(parsed.query))

    def test_split_remote_endpoints_route_vendors_and_ratingsites_separately(self):
        with patch.dict(
            "os.environ",
            {
                "FEDSHOP_VENDOR_ENDPOINT": "http://10.10.0.2:8890/sparql",
                "FEDSHOP_RATINGSITE_ENDPOINT": "http://10.10.0.3:8890/sparql",
            },
        ):
            mapping = build_batch_mapping(0, members_per_batch=1)
            normalized = normalize_mapping({
                "http://www.vendor0.fr/": "http://localhost:8890/vendor0/sparql",
                "http://www.ratingsite0.fr/": "http://localhost:8890/ratingsite0/sparql",
            })

        self.assertEqual(
            "10.10.0.2:8890", urlparse(mapping["http://www.vendor0.fr/"]).netloc
        )
        self.assertEqual(
            "10.10.0.3:8890",
            urlparse(mapping["http://www.ratingsite0.fr/"]).netloc,
        )
        self.assertEqual(
            "10.10.0.2:8890",
            urlparse(normalized["http://www.vendor0.fr/"]).netloc,
        )
        self.assertEqual(
            "10.10.0.3:8890",
            urlparse(normalized["http://www.ratingsite0.fr/"]).netloc,
        )

    def test_manage_infra_zero_skips_local_docker_checks(self):
        with patch.dict("os.environ", {"FEDSHOP_WEBAPP_MANAGE_INFRA": "0"}):
            with patch.object(infra, "_url_ok") as url_ok:
                with patch.object(infra, "_ensure_docker_daemon") as docker_up:
                    infra.ensure_infra()

        url_ok.assert_not_called()
        docker_up.assert_not_called()


if __name__ == "__main__":
    unittest.main()
