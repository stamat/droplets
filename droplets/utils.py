"""Backend-agnostic helpers shared by the GTK and pywebview droplet backends."""

import importlib.util
import os


def import_from_uri(uri, absl=False):
    """Import a widget's Python module from a file path (imp is gone in 3.12)."""
    if not absl:
        uri = os.path.normpath(os.path.join(os.path.dirname(__file__), uri))
    path, fname = os.path.split(uri)
    mname, _ext = os.path.splitext(fname)
    source = os.path.join(path, mname) + ".py"
    if not os.path.exists(source):
        return None
    spec = importlib.util.spec_from_file_location(mname, source)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
