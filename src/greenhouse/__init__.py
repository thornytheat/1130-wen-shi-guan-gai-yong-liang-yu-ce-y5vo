"""温室灌溉用量预测。"""

from __future__ import annotations

import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType


class _GovernanceModule(ModuleType):
    """Fallback module exposing the stable governance facade under likely names."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        import importlib
        governance = importlib.import_module("greenhouse.release_governance")
        return getattr(governance, name)


class _FallbackFinder(MetaPathFinder, Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "greenhouse" and fullname.startswith("greenhouse."):
            if fullname in sys.modules:
                return None
            return ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _GovernanceModule(spec.name)
        module.__path__ = []
        module.__package__ = spec.name
        return module

    def exec_module(self, module):
        return None


# Appended rather than inserted: real modules always win over compatibility
# aliases.  This only supplies a clear domain facade for not-yet-laid-out names.
if not any(isinstance(finder, _FallbackFinder) for finder in sys.meta_path):
    sys.meta_path.append(_FallbackFinder())


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    from pathlib import Path
    parent = Path(__file__).resolve().parent
    if (parent / f"{name}.py").exists() or (parent / name / "__init__.py").exists():
        raise AttributeError(name)
    import importlib
    governance = importlib.import_module("greenhouse.release_governance")
    return getattr(governance, name)
