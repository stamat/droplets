"""Headless test for the scrollbar-gutter fix (no GUI: fake window, Droplet
built without __init__).

Legacy macOS/Windows scrollbars reserve a permanent ~17px gutter, which lays a
widget out narrower than its window and paints an opaque track over a
transparent one. See Droplet._hide_scrollbars.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets.droplet_pywebview import Droplet  # noqa: E402


class _Window:
    def __init__(self):
        self.scripts = []

    def evaluate_js(self, script):
        self.scripts.append(script)


def test_widget_page_stops_reserving_a_scrollbar_gutter():
    droplet = Droplet.__new__(Droplet)  # __init__ would start the GUI event loop
    droplet.window = _Window()

    droplet._hide_scrollbars()

    # documentElement, not ::-webkit-scrollbar: styling the thumb leaves the
    # gutter reserved (measured -- clientWidth stays 203 in a 220px window).
    assert droplet.window.scripts == [
        "document.documentElement.style.overflow = 'hidden'"
    ]
