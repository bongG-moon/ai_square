"""Load this directory as a package without requiring its parent on sys.path."""
import hashlib
import importlib.util
from pathlib import Path
import sys


def load_package():
    root = Path(__file__).resolve().parent
    name = '_square_runtime_' + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, root / '__init__.py', submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        for key in list(sys.modules):
            if key == name or key.startswith(name + '.'):
                sys.modules.pop(key, None)
        raise
    return module
