"""Tests for generate.py's Python WatDiv integration."""

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_generate_source_calls_python_watdiv(config_small, tmp_path):
    """generate_source should invoke the in-process WatDiv implementation."""
    from fedshop.generate import generate_source

    # Patch the in-process generator and template file read.
    template_content = "{%provenance}\n{%vendor_id}\n{%export_output_dir}\n{%export_dep_output_dir}\n{%vendor_n}\n"
    schema = config_small.generation.schema["vendor"]

    with patch("fedshop.generate.watdiv_run") as mock_run, \
         patch("builtins.open", create=True) as mock_open:

        # Make open() return our fake template
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read = MagicMock(return_value=template_content)
        mock_open.return_value = mock_file

        output_file = tmp_path / "vendor0.nq"
        # Override template and output paths
        with patch.object(schema, "template", str(tmp_path / "fake.template")), \
             patch.object(schema, "export_dep_output_dir", str(tmp_path / "products")):
            generate_source(config_small, "vendor", 0, output_file)

        assert mock_run.called


def test_generate_products_calls_python_watdiv_with_output_directory(config_small, tmp_path):
    from fedshop.generate import generate_products

    schema = config_small.generation.schema["product"]
    template_content = "{%provenance}\n{%export_output_dir}\n{%product_n}\n"
    with patch("fedshop.generate.watdiv_run") as mock_run, \
         patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read = MagicMock(return_value=template_content)
        mock_open.return_value = mock_file

        with patch.object(schema, "template", str(tmp_path / "fake.template")):
            assert generate_products(config_small, tmp_path) == tmp_path

    mock_run.assert_called_once()
    assert mock_run.call_args.args[2] == tmp_path
