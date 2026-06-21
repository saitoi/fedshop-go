from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import BenchmarkConfig


class EngineAdapter(ABC):
    """Abstract base for FedShop engine adapters."""

    def __init__(self, config: BenchmarkConfig, engine_dir: Path) -> None:
        self.config = config
        self.engine_dir = engine_dir

    @abstractmethod
    def prerequisites(self) -> None:
        """Compile/verify the engine is ready to run."""

    @abstractmethod
    def generate_config_file(self, batch_id: int, proxy_mapping: dict[str, str]) -> Path:
        """Write the engine's federation config for a given batch.

        Returns path to the written config file.
        """

    @abstractmethod
    def run_benchmark(
        self,
        query_path: Path,
        batch_id: int,
        out_result: Path,
        out_source_selection: Path,
        query_plan: Path,
        stats: Path,
        *,
        noexec: bool = False,
    ) -> None:
        """Execute the query and write per-run artefacts."""

    @abstractmethod
    def transform_results(self, infile: Path, outfile: Path) -> None:
        """Convert raw engine result output to normalized results.csv."""

    @abstractmethod
    def transform_provenance(
        self,
        infile: Path,
        outfile: Path,
        composition_file: Path,
    ) -> None:
        """Convert raw source_selection.txt to provenance.csv."""
