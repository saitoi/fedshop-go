from pathlib import Path


def test_pyfedx_modules_are_not_core_reexport_stubs():
    root = Path(__file__).resolve().parents[2] / "pyfedx" / "pyfedx_engine"
    assert not (root / "core.py").exists()

    modules = [
        "artifacts.py",
        "cli.py",
        "client.py",
        "executor.py",
        "federation.py",
        "filtering.py",
        "model.py",
        "parser.py",
        "planner.py",
        "selftest.py",
    ]

    for name in modules:
        source = (root / name).read_text()
        assert "from .core import" not in source, name
        assert len(source.splitlines()) > 20, name

    assert "from .core import" not in (root / "__init__.py").read_text()
