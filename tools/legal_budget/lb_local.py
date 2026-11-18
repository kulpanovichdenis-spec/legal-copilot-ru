"""Load sibling modules under unique names.

Bare ``import model`` collides with ``tools/matter_model/model.py`` when pytest
collects the whole ``tools`` tree: the first imported ``model`` stays in
``sys.modules``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load(name: str):
    mod_name = f"legal_budget_{name}"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(mod_name, _DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module
