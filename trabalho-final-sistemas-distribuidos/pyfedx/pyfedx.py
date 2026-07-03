#!/usr/bin/env python3
"""Compatibility entry point and import shim for the modular PyFedX package."""

from pyfedx_engine import *  # noqa: F401,F403
from pyfedx_engine.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
