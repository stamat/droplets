"""Headless test for offscreen-geometry rejection (no GUI, fake screens)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets.droplet_pywebview import _rect_on_screen  # noqa: E402


class _Screen:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


# One 2560px display to the left of the built-in one, as saved; then unplugged.
BOTH = [_Screen(-2560, 0, 2560, 1440), _Screen(0, 0, 1512, 982)]
LAPTOP_ONLY = [_Screen(0, 0, 1512, 982)]


def test_position_kept_while_its_display_is_attached():
    assert _rect_on_screen(-1393, 75, 140, 140, BOTH)


def test_position_dropped_once_that_display_is_gone():
    assert not _rect_on_screen(-1393, 75, 140, 140, LAPTOP_ONLY)


def test_onscreen_and_partially_onscreen_positions_kept():
    assert _rect_on_screen(1167, 75, 140, 140, LAPTOP_ONLY)
    assert _rect_on_screen(-70, 75, 140, 140, LAPTOP_ONLY)
