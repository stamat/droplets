"""The pywebview shim must inject a drag grip, else full-surface apps (the
calculator) can't be moved -- there's no bare pixel to grab. Guards the one
thing that makes the grip actually drag: the .pywebview-drag-region class."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_shim_injects_a_working_drag_grip():
    # Imports webview (pywebview backend); skip where it isn't installed.
    try:
        from droplets.droplet_pywebview import _BRIDGE_SHIM_TAG as tag
    except ImportError:
        return
    # .pywebview-drag-region is what routes the mousedown to Cocoa's native
    # window move (customize.js). Drop it and the grip is just a dead dot.
    assert "pywebview-drag-region" in tag
    assert "droplet-grip" in tag
    assert "DOMContentLoaded" in tag  # body must exist before we append


if __name__ == "__main__":
    test_shim_injects_a_working_drag_grip()
    print("ok")
