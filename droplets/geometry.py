"""Backend-agnostic screen geometry math (no GUI toolkit imported).

One global coordinate frame: x and y both measured from the top-left of the
whole desktop, y growing downward -- what GTK/X11 `window.move()` and
`get_position()` speak. The pywebview backend keeps its own copy of the same
math in a screen-relative-y frame (macOS Cocoa reports window y from each
screen's own top), so this module stays gi/webview-free and unit-testable
without a display.

A "screen" here is a plain (x, y, width, height) tuple.
"""

# Room left at the top of a screen so a clamped widget clears a menu bar / panel.
_TOP_MARGIN = 25


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
