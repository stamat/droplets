"""Headless tests for offscreen-geometry rejection and drag-end persistence
(no GUI: fake screens, fake manifest, Droplet built without __init__)."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets import droplet_pywebview  # noqa: E402
from droplets.droplet_pywebview import (  # noqa: E402
    Droplet,
    _layout_key,
    _rect_on_screen,
    _screen_for,
    _top_left_point,
)


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
    """The fields save_geometry reads, plus real layout()/save_layout() semantics
    over an in-memory settings dict (droplets.manifest owns the file I/O)."""

    def __init__(self, layouts=None, **kwargs):
        self.x, self.y, self.width, self.height = 100, 100, 140, 140
        self.resizable = False
        self.__dict__.update(kwargs)
        self.settings = {"layouts": layouts or {}}
        self.saves = []

    def layout(self, key):
        return self.settings["layouts"].get(key, {})

    def save_layout(self, key, **values):
        self.settings["layouts"].setdefault(key, {}).update(values)
        self.saves.append((key, values))
        self.__dict__.update(values)


def _droplet(manifest, settle=0.05, layout="1512x982+0+0"):
    # Bypass __init__: it would start the GUI event loop.
    droplet_pywebview._SETTLE_DELAY = settle
    droplet = Droplet.__new__(Droplet)
    droplet.manifest = manifest
    droplet.layout_key = layout
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

    assert manifest.saves == [(LAPTOP, {"x": 240, "y": 190})]


def test_two_drags_write_once_each():
    manifest = _Manifest()
    droplet = _droplet(manifest)

    _drag(droplet, [(110, 100), (200, 160)])
    _drag(droplet, [(210, 160), (300, 240)])

    assert manifest.saves == [
        (LAPTOP, {"x": 200, "y": 160}),
        (LAPTOP, {"x": 300, "y": 240}),
    ]


def test_close_mid_drag_flushes_pending_position():
    manifest = _Manifest()
    # Settle far longer than the test runs, so only the close-flush can save.
    droplet = _droplet(manifest, settle=30)

    droplet.on_moved(300, 240)
    droplet.on_close()

    assert manifest.saves == [(LAPTOP, {"x": 300, "y": 240})]


def test_resize_persisted_only_when_resizable():
    fixed, sizeable = _Manifest(), _Manifest(resizable=True)

    for manifest in (fixed, sizeable):
        droplet = _droplet(manifest)
        droplet.on_resized(300, 200)
        time.sleep(0.2)

    assert fixed.saves == []
    assert sizeable.saves == [(LAPTOP, {"width": 300, "height": 200})]


# ---- multi-monitor: one position per arrangement -------------------------

LAPTOP = _layout_key(LAPTOP_ONLY)
DOCKED = _layout_key(BOTH)


def test_layout_key_is_stable_and_order_independent():
    assert LAPTOP == "1512x982+0+0"
    assert DOCKED == "1512x982+0+0|2560x1440-2560+0"
    assert _layout_key(list(reversed(BOTH))) == DOCKED
    assert LAPTOP != DOCKED


def test_each_arrangement_keeps_its_own_position():
    manifest = _Manifest()

    docked = _droplet(manifest, layout=DOCKED)
    _drag(docked, [(-1393, 75)])
    undocked = _droplet(manifest, layout=LAPTOP)
    _drag(undocked, [(1300, 40)])

    assert manifest.settings["layouts"] == {
        DOCKED: {"x": -1393, "y": 75},
        LAPTOP: {"x": 1300, "y": 40},
    }


# ---- restoring onto the right screen -------------------------------------
#
# Two 2560x1440 displays, the secondary to the LEFT of the primary (Cocoa puts
# the primary at the origin and grows x to the right, so a left-hand screen has
# a negative origin). This is the arrangement that exposed the bug.
TWIN = [_Screen(0, 0, 2560, 1440), _Screen(-2560, 0, 2560, 1440)]
PRIMARY, LEFT = TWIN


def test_saved_position_resolves_to_the_screen_it_was_saved_on():
    assert _screen_for(2183, 1223, TWIN) is PRIMARY
    assert _screen_for(-377, 1223, TWIN) is LEFT


def test_position_on_no_screen_falls_back_to_primary():
    assert _screen_for(99999, 1223, TWIN) is PRIMARY


def test_position_saved_on_primary_restores_on_primary():
    # Regression: pywebview's move() would add mainScreen().origin.x to an
    # already-global x, landing the widget on the left screen at (-377, ...).
    assert _top_left_point(2183, 1223, TWIN) == (2183, 217)


def test_position_saved_on_the_left_screen_restores_there():
    assert _top_left_point(-377, 1223, TWIN) == (-377, 217)


def test_screens_of_different_heights_flip_against_their_own_top():
    # Laptop (982 tall) right of a 1440 external, both bottom-aligned at y=0:
    # the same drop-from-top means different global y on each.
    screens = [_Screen(0, 0, 1512, 982), _Screen(-2560, 0, 2560, 1440)]
    assert _top_left_point(100, 75, screens) == (100, 907)
    assert _top_left_point(-2460, 75, screens) == (-2460, 1365)


def test_redocking_does_not_rewrite_the_position_it_restored():
    # Position restored from the layout, window never dragged: nothing to save,
    # even though the manifest's own x/y (last-known, from the other layout) differ.
    manifest = _Manifest(layouts={DOCKED: {"x": -1393, "y": 75}}, x=1300, y=40)
    droplet = _droplet(manifest, layout=DOCKED)
    droplet.temp.update(x=-1393, y=75)  # what prepare_widget seeds on restore

    droplet.save_geometry()

    assert manifest.saves == []


if __name__ == "__main__":
    test_position_kept_while_its_display_is_attached()
    test_position_dropped_once_that_display_is_gone()
    test_onscreen_and_partially_onscreen_positions_kept()
    test_drag_writes_settings_once_at_the_end()
    test_two_drags_write_once_each()
    test_close_mid_drag_flushes_pending_position()
    test_resize_persisted_only_when_resizable()
    test_layout_key_is_stable_and_order_independent()
    test_each_arrangement_keeps_its_own_position()
    test_saved_position_resolves_to_the_screen_it_was_saved_on()
    test_position_on_no_screen_falls_back_to_primary()
    test_position_saved_on_primary_restores_on_primary()
    test_position_saved_on_the_left_screen_restores_there()
    test_screens_of_different_heights_flip_against_their_own_top()
    test_redocking_does_not_rewrite_the_position_it_restored()
    print("ok")
