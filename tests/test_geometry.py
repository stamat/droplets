"""Headless tests for offscreen-geometry rejection and drag-end persistence
(no GUI: fake screens, fake manifest, Droplet built without __init__)."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets import droplet_pywebview  # noqa: E402
from droplets.droplet_pywebview import Droplet, _rect_on_screen  # noqa: E402


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


class _Manifest:
    """Just the fields save_geometry reads, plus save_setting's record-and-apply."""

    def __init__(self, **kwargs):
        self.x, self.y, self.width, self.height = 100, 100, 140, 140
        self.resizable = False
        self.__dict__.update(kwargs)
        self.saves = []

    def save_setting(self, **values):
        self.saves.append(values)
        self.__dict__.update(values)


def _droplet(manifest, settle=0.05):
    # Bypass __init__: it would start the GUI event loop.
    droplet_pywebview._SETTLE_DELAY = settle
    droplet = Droplet.__new__(Droplet)
    droplet.manifest = manifest
    droplet.temp = {"x": manifest.x, "y": manifest.y}
    droplet._save_timer = None
    return droplet


def _drag(droplet, points):
    for x, y in points:
        droplet.on_moved(x, y)
        time.sleep(0.01)
    time.sleep(0.2)  # > _SETTLE_DELAY: let the debounce fire


def test_drag_writes_settings_once_at_the_end():
    manifest = _Manifest()
    droplet = _droplet(manifest)

    _drag(droplet, [(110, 100), (150, 120), (200, 160), (240, 190)])

    assert manifest.saves == [{"x": 240, "y": 190}]


def test_two_drags_write_once_each():
    manifest = _Manifest()
    droplet = _droplet(manifest)

    _drag(droplet, [(110, 100), (200, 160)])
    _drag(droplet, [(210, 160), (300, 240)])

    assert manifest.saves == [{"x": 200, "y": 160}, {"x": 300, "y": 240}]


def test_close_mid_drag_flushes_pending_position():
    manifest = _Manifest()
    # Settle far longer than the test runs, so only the close-flush can save.
    droplet = _droplet(manifest, settle=30)

    droplet.on_moved(300, 240)
    droplet.on_close()

    assert manifest.saves == [{"x": 300, "y": 240}]


def test_resize_persisted_only_when_resizable():
    fixed, sizeable = _Manifest(), _Manifest(resizable=True)

    for manifest in (fixed, sizeable):
        droplet = _droplet(manifest)
        droplet.on_resized(300, 200)
        time.sleep(0.2)

    assert fixed.saves == []
    assert sizeable.saves == [{"width": 300, "height": 200}]


if __name__ == "__main__":
    test_position_kept_while_its_display_is_attached()
    test_position_dropped_once_that_display_is_gone()
    test_onscreen_and_partially_onscreen_positions_kept()
    test_drag_writes_settings_once_at_the_end()
    test_two_drags_write_once_each()
    test_close_mid_drag_flushes_pending_position()
    test_resize_persisted_only_when_resizable()
    print("ok")
