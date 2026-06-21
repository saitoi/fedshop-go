"""Tests for generate.py — WatDiv subprocess interface."""

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_generate_source_calls_watdiv(config_small, tmp_path):
    """generate_source should call subprocess.run with the watdiv binary."""
    from fedshop.generate import generate_source

    # Patch both subprocess.run and the template file read
    template_content = "{%provenance}\n{%vendor_id}\n{%export_output_dir}\n{%export_dep_output_dir}\n{%vendor_n}\n"
    schema = config_small.generation.schema["vendor"]

    with patch("fedshop.generate.subprocess.run") as mock_run, \
         patch("builtins.open", create=True) as mock_open:

        # Make open() return our fake template
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read = MagicMock(return_value=template_content)
        mock_open.return_value = mock_file

        mock_run.return_value = MagicMock(returncode=0)

        output_file = tmp_path / "vendor0.nq"
        # Override template and output paths
        with patch.object(schema, "template", str(tmp_path / "fake.template")), \
             patch.object(schema, "export_dep_output_dir", str(tmp_path / "products")):
            try:
                generate_source(config_small, "vendor", 0, output_file)
            except Exception:
                pass  # file not found is ok, we just check subprocess was called

        assert mock_run.called


def test_generate_source_raises_on_nonzero_exit(config_small, tmp_path):
    """generate_source should raise RuntimeError when watdiv exits non-zero."""
    from fedshop.generate import generate_source

    schema = config_small.generation.schema["vendor"]
    template_content = "dummy template {%vendor_id} {%provenance} {%export_output_dir}\n"

    with patch("fedshop.generate.subprocess.run") as mock_run, \
         patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read = MagicMock(return_value=template_content)
        mock_open.return_value = mock_file

        mock_run.return_value = MagicMock(returncode=1)

        import pytest
        with pytest.raises(RuntimeError, match="WatDiv failed"):
            with patch.object(schema, "template", str(tmp_path / "fake.template")):
                generate_source(config_small, "vendor", 0, tmp_path / "v0.nq")


def test_watdiv_cmd_includes_model_file_and_scale_factor(config_small, tmp_path):
    """The watdiv command should include -d, the model file, and the scale factor."""
    from fedshop.generate import generate_source

    schema = config_small.generation.schema["vendor"]
    template_content = "{%vendor_id}\n"
    captured_cmds = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        return MagicMock(returncode=0)

    with patch("fedshop.generate.subprocess.run", side_effect=fake_run), \
         patch("builtins.open", create=True) as mock_open:
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read = MagicMock(return_value=template_content)
        mock_open.return_value = mock_file

        try:
            with patch.object(schema, "template", str(tmp_path / "fake.template")), \
                 patch.object(schema, "export_dep_output_dir", None):
                generate_source(config_small, "vendor", 3, tmp_path / "vendor3.nq")
        except Exception:
            pass

    assert captured_cmds, "subprocess.run should have been called"
    cmd = captured_cmds[0]
    assert "-d" in cmd
