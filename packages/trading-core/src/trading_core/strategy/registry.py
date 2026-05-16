"""Strategy registry — YAML-based loader for config/strategies/*.yaml files.

Phase 2: supports ORBStrategy only. Phase 7 adds dynamic class dispatch via
importlib when additional strategies are registered.

Usage:
    strategy = StrategyRegistry.load("config/strategies/orb.yaml")
    names = StrategyRegistry.list_strategies("config/strategies/")
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .orb import ORBConfig, ORBStrategy


class StrategyRegistry:
    """YAML-based strategy loader.

    load(yaml_path): reads a strategy YAML file, constructs ORBConfig from
        the `params` block, and returns an ORBStrategy instance.

    list_strategies(strategies_dir): globs *.yaml in the given directory and
        returns the `name` field from each file.

    Phase 7 note: the `class` key in each YAML is stored for future dynamic
    dispatch via importlib.import_module. For now, only ORBStrategy is
    instantiated (hardcoded). When Phase 7 adds multi-strategy support, replace
    the hardcoded ORBStrategy() call with:
        module_path, cls_name = data["class"].rsplit(".", 1)
        cls = getattr(importlib.import_module(module_path), cls_name)
        return cls(config)
    """

    @staticmethod
    def load(yaml_path: str | Path) -> ORBStrategy:
        """Load a strategy from a YAML config file.

        Args:
            yaml_path: Path to the *.yaml strategy config (absolute or relative
                to the cwd at call time). Accepts str or pathlib.Path.

        Returns:
            An ORBStrategy instance configured from the YAML params block.

        Raises:
            FileNotFoundError: if yaml_path does not exist.
            yaml.YAMLError: if the YAML is malformed.
            TypeError: if required params are missing or wrong type.
        """
        path = Path(yaml_path)
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        params = data.get("params", {})
        config = ORBConfig(
            strategy_id=data.get("strategy_id", "orb-v1"),
            strategy_version=str(data.get("version", "1.0")),
            **params,
        )
        return ORBStrategy(config)

    @staticmethod
    def list_strategies(strategies_dir: str | Path) -> list[str]:
        """List strategy names from all *.yaml files in a directory.

        Args:
            strategies_dir: Path to directory containing *.yaml strategy configs.

        Returns:
            Sorted list of strategy `name` field values from each YAML file.
            Files without a `name` key are skipped silently.
        """
        d = Path(strategies_dir)
        names: list[str] = []
        for p in sorted(d.glob("*.yaml")):
            with p.open("r", encoding="utf-8") as f:
                file_data = yaml.safe_load(f)
            if file_data and "name" in file_data:
                names.append(file_data["name"])
        return names
