"""Backend-agnostic helpers shared by the GTK and pywebview droplet backends."""

import importlib.util
import os


# Drag grip: an app that paints its whole surface (the calculator's keypad, say)
# leaves no bare pixel to grab. This injects one small hover-revealed grip in the
# top-left corner -- ~16px, so it steals clicks only in its own square while the
# app stays interactive everywhere else. It only draws the grip; each backend
# wires the drag: pywebview via the .pywebview-drag-region class (Cocoa moves the
# window natively), GTK by coordinate-gating begin_move_drag on the top-left
# corner (the class is inert there). Keep the 16px width in sync with GRIP_PX.
GRIP_PX = 18  # click-gate size for GTK; CSS grip is 16px + slop
DRAG_GRIP_JS = (
    "window.addEventListener('DOMContentLoaded', function () {"
    "  var s = document.createElement('style');"
    "  s.textContent = '.droplet-grip{position:fixed;top:0;left:0;width:16px;"
    "height:16px;z-index:2147483647;cursor:grab;opacity:0;transition:opacity .15s;"
    "border-bottom-right-radius:6px;background:radial-gradient("
    "circle at 3px 3px,rgba(0,0,0,.6) 1.3px,transparent 0) 0 0/5px 5px}"
    "body:hover .droplet-grip{opacity:.75}"
    ".droplet-grip:active{cursor:grabbing;opacity:1}';"
    "  document.head.appendChild(s);"
    "  var g = document.createElement('div');"
    "  g.className = 'pywebview-drag-region droplet-grip';"
    "  g.title = 'Drag to move';"
    "  document.body.appendChild(g);"
    "});"
)


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
