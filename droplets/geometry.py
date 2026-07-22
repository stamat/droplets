"""Backend-agnostic screen geometry math (no GUI toolkit imported).

One global coordinate frame: x and y both measured from the top-left of the
whole desktop, y growing downward -- what GTK/X11 `window.move()` and
`get_position()` speak. The pywebview backend keeps its own copy of the same
math in a screen-relative-y frame (macOS Cocoa reports window y from each
screen's own top), so this module stays gi/webview-free and unit-testable
without a display.

A "screen" here is a plain (x, y, width, height) tuple.
"""

import re

# Room left at the top of a screen so a clamped widget clears a menu bar / panel.
_TOP_MARGIN = 25

_KEY_PART = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def screen_at(x, y, screens):
    """The screen containing (x, y), or the first screen when none does."""
    for s in screens:
        if s[0] <= x < s[0] + s[2] and s[1] <= y < s[1] + s[3]:
            return s
    return screens[0]


def nearest_screen(rect, screens):
    """The screen whose centre is closest to `rect`'s centre.

    Maps an old screen to its counterpart after a change: a display left
    untouched is nearest itself, so a widget on it stays put; the survivor of an
    unplug is nearest the display that is gone.
    """
    cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
    return min(
        screens,
        key=lambda s: (s[0] + s[2] / 2 - cx) ** 2 + (s[1] + s[3] / 2 - cy) ** 2,
    )


def clamp(x, y, width, height, screen):
    """Pull a window rect fully inside one screen, leaving a top margin."""
    sx, sy, sw, sh = screen
    return (
        min(max(x, sx), max(sx, sx + sw - width)),
        min(max(y, sy + _TOP_MARGIN), max(sy + _TOP_MARGIN, sy + sh - height)),
    )


def remap(x, y, width, height, old_screens, new_screens):
    """Move a window to ~the same relative spot when the display setup changed.

    Take the widget's fractional place on the screen it sat on, then drop it at
    that fraction of the matching current screen. Clamped so rounding or a
    smaller display can't push it off the edge.
    """
    old = screen_at(x, y, old_screens)
    new = nearest_screen(old, new_screens)
    fx = (x - old[0]) / old[2]
    fy = (y - old[1]) / old[3]
    nx = new[0] + round(fx * new[2])
    ny = new[1] + round(fy * new[3])
    return clamp(nx, ny, width, height, new)


# ---- per-arrangement memory: fingerprint a monitor layout ----------------
# A widget's position is stored keyed by these fingerprints, so each resolution
# / monitor setup keeps its own remembered spot (see manifest.save_layout).


def layout_key(screens):
    """Fingerprint a monitor arrangement, e.g. "1512x982+0+0|2560x1440-2560+0".

    Sorted so the same displays enumerated in a different order stay one key.
    Matches the string the pywebview backend builds, so the two never diverge.
    """
    return "|".join(sorted("%dx%d%+d%+d" % (s[2], s[3], s[0], s[1]) for s in screens))


def screens_from_key(key):
    """Inverse of layout_key: the (x, y, w, h) screens a saved key was made of.

    Lets a position saved under one arrangement be scaled onto another. Empty on
    a malformed key, so a bad settings entry never drives a remap off a guess.
    """
    out = []
    for part in key.split("|"):
        m = _KEY_PART.match(part)
        if not m:
            return []
        w, h, x, y = (int(g) for g in m.groups())
        out.append((x, y, w, h))
    return out


def source_layout(x, y, layouts):
    """The layout key whose saved position is (x, y), else None.

    save_layout mirrors every save to the top-level x/y the launch fallback
    reads, so the arrangement a position was last saved in is the matching one.
    """
    for key, geom in layouts.items():
        if geom.get("x") == x and geom.get("y") == y:
            return key
    return None


def remap_from_layouts(x, y, width, height, layouts, screens):
    """Launch-time remap: recover the old screens from saved history and scale.

    For an arrangement seen for the first time (resolution changed or a monitor
    added/removed while the widget was NOT running). Falls back to a plain clamp
    when there is no saved history to read a fraction from.
    """
    key = source_layout(x, y, layouts)
    old = screens_from_key(key) if key else []
    if not old:
        return clamp(x, y, width, height, screen_at(x, y, screens))
    return remap(x, y, width, height, old, screens)
