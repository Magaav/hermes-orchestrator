from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
CLONE_MANAGER_PATH = REPO_ROOT / "scripts" / "public" / "clone" / "clone_manager.py"


@pytest.fixture
def cm():
    module_name = f"clone_manager_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, CLONE_MANAGER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load clone_manager module from {CLONE_MANAGER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
