"""Headless tests for the local-tier document server (no GUI, no socket)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets import server  # noqa: E402

CLOCK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps", "clock")


def call(app, path):
    """Drive the WSGI app directly. Returns (status, headers dict, body)."""
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app({"PATH_INFO": path}, start_response))
    return captured["status"], captured["headers"], body


def test_entry_carries_the_csp_header_and_the_injected_tag():
    app, entry = server.make_app(CLOCK, "index.html", "local", "<script>SHIM</script>")
    status, headers, body = call(app, entry)
    assert status.startswith("200")
    policy = headers["Content-Security-Policy"]
    # Served documents are same-origin; file: would hand the widget the disk.
    assert "file:" not in policy
    assert "http:" not in policy and "https:" not in policy
    assert b"SHIM" in body and b"<canvas" in body


def test_assets_are_served_with_their_type():
    app, entry = server.make_app(CLOCK, "index.html", "local")
    status, headers, body = call(app, os.path.dirname(entry) + "/clock-face.png")
    assert status.startswith("200")
    assert headers["Content-Type"] == "image/png"
    assert body[:8] == b"\x89PNG\r\n\x1a\n"


def test_everything_outside_the_secret_prefix_is_404():
    app, entry = server.make_app(CLOCK, "index.html", "local")
    prefix = os.path.dirname(entry)
    # The root must not redirect to the prefix -- that would leak the secret.
    for path in ("/", "/index.html", "/clock-face.png", prefix.rstrip("/") + "x/index.html"):
        status, _, _ = call(app, path)
        assert status.startswith("404"), path


def test_traversal_out_of_the_widget_is_refused():
    app, entry = server.make_app(CLOCK, "index.html", "local")
    prefix = os.path.dirname(entry) + "/"
    for path in ("../manifest_pattern", "../../droplets/csp.py", "..%2f..%2fdroplets/csp.py"):
        status, _, _ = call(app, prefix + path)
        assert status.startswith("404"), path


def test_port_is_stable_per_widget():
    assert server._port_for(CLOCK) == server._port_for(CLOCK)
    assert server._port_for(CLOCK) != server._port_for(CLOCK + "2")
    assert 1024 < server._port_for(CLOCK) < 65536


if __name__ == "__main__":
    test_entry_carries_the_csp_header_and_the_injected_tag()
    test_assets_are_served_with_their_type()
    test_everything_outside_the_secret_prefix_is_404()
    test_traversal_out_of_the_widget_is_refused()
    test_port_is_stable_per_widget()
    print("ok")
