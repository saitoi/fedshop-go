"""Tests for config.py — config loading without OmegaConf."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_config_small_yaml_returns_benchmark_config(config_small):
    from fedshop.config import BenchmarkConfig
    assert isinstance(config_small, BenchmarkConfig)


def test_n_batch_is_two(config_small):
    assert config_small.generation.n_batch == 2


def test_n_query_instances_is_two(config_small):
    assert config_small.generation.n_query_instances == 2


def test_federation_members_batch0_has_20_members(config_small):
    batch0 = config_small.generation.virtuoso.federation_members["batch0"]
    assert len(batch0) == 20


def test_federation_members_batch1_has_40_members(config_small):
    batch1 = config_small.generation.virtuoso.federation_members["batch1"]
    assert len(batch1) == 40


def test_batch0_contains_vendor0(config_small):
    batch0 = config_small.generation.virtuoso.federation_members["batch0"]
    assert "vendor0" in batch0
    assert batch0["vendor0"] == "http://www.vendor0.fr/"


def test_batch0_contains_ratingsite0(config_small):
    batch0 = config_small.generation.virtuoso.federation_members["batch0"]
    assert "ratingsite0" in batch0


def test_batch1_has_vendor10(config_small):
    batch1 = config_small.generation.virtuoso.federation_members["batch1"]
    assert "vendor10" in batch1


def test_virtuoso_port_is_8890(config_small):
    assert config_small.generation.virtuoso.port == 8890


def test_virtuoso_default_endpoint_is_interpolated(config_small):
    ep = config_small.generation.virtuoso.default_endpoint
    assert "localhost" in ep
    assert "sparql" in ep


def test_proxy_endpoint_interpolated(config_small):
    ep = config_small.evaluation.proxy.endpoint
    assert "localhost" in ep
    assert "5555" in ep


def test_engines_include_fedx(config_small):
    assert "fedx" in config_small.evaluation.engines


def test_engines_include_rsa(config_small):
    assert "rsa" in config_small.evaluation.engines


def test_evaluation_timeout_is_120(config_small):
    assert config_small.evaluation.timeout == 120


def test_vendor_n_param_is_batch_times_10(config_small):
    vendor_n = config_small.generation.schema["vendor"].params.get("vendor_n")
    assert vendor_n == config_small.generation.n_batch * 10


def test_ratingsite_n_param_is_batch_times_10(config_small):
    ratingsite_n = config_small.generation.schema["ratingsite"].params.get("ratingsite_n")
    assert ratingsite_n == config_small.generation.n_batch * 10


def test_product_schema_is_not_source(config_small):
    assert config_small.generation.schema["product"].is_source is False


def test_vendor_schema_is_source(config_small):
    assert config_small.generation.schema["vendor"].is_source is True


def test_ratingsite_schema_is_source(config_small):
    assert config_small.generation.schema["ratingsite"].is_source is True


def test_use_docker_is_true(config_small):
    assert config_small.use_docker is True
