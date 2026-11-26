"""蒸腾需水估计和持久化拟合矩。"""

from pathlib import Path


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    parent = Path(__file__).resolve().parent
    if (parent / f"{name}.py").exists() or (parent / name / "__init__.py").exists():
        raise AttributeError(name)
    from importlib import import_module
    governance = import_module("greenhouse.release_governance")
    return getattr(governance, name)
