"""Headless tests for backend selection (no GTK/pywebview needed)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets.backend import backend_name  # noqa: E402


def test_platform_defaults():
    assert backend_name("linux", {}) == "gtk"
    assert backend_name("linux2", {}) == "gtk"
    assert backend_name("darwin", {}) == "pywebview"
    assert backend_name("win32", {}) == "pywebview"


def test_env_override_wins_and_is_case_insensitive():
    assert backend_name("linux", {"DROPLETS_BACKEND": "pywebview"}) == "pywebview"
    assert backend_name("darwin", {"DROPLETS_BACKEND": "GTK"}) == "gtk"


def test_unknown_override_raises():
    try:
        backend_name("linux", {"DROPLETS_BACKEND": "qt"})
    except SystemExit:
        pass
    else:
        raise AssertionError("expected SystemExit for unknown backend")


if __name__ == "__main__":
    test_platform_defaults()
    test_env_override_wins_and_is_case_insensitive()
    test_unknown_override_raises()
    print("ok")
