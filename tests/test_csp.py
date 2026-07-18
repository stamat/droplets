"""Headless tests for per-tier CSP (no GTK/pywebview required)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from droplets import csp  # noqa: E402


def test_local_policy_blocks_remote_keeps_local():
    p = csp.policy_for("local")
    assert p is not None
    assert "http" not in p                 # no remote scheme anywhere
    assert "file:" in p                    # widget's own tree allowed
    assert "'unsafe-inline'" in p          # inline scripts (compat) allowed
    assert "object-src 'none'" in p        # plugins denied


def test_remote_and_hosted_get_no_policy():
    assert csp.policy_for("remote") is None
    assert csp.policy_for("hosted") is None
    assert csp.meta_tag("remote") == ""


def test_inject_is_noop_for_unrestricted_tiers():
    html = "<html><head></head><body></body></html>"
    assert csp.inject(html, "remote") == html
    assert csp.inject(html, "hosted") == html


def test_inject_places_meta_first_in_head():
    html = "<html><head><title>x</title></head><body></body></html>"
    out = csp.inject(html, "local")
    assert "Content-Security-Policy" in out
    # meta must precede existing head content so it applies at parse time
    assert out.index("Content-Security-Policy") < out.index("<title>")


def test_inject_handles_uppercase_and_attrs():
    out = csp.inject('<HTML><HEAD lang="en"></HEAD></HTML>', "local")
    assert "Content-Security-Policy" in out


def test_inject_creates_head_when_missing():
    out = csp.inject("<html><body>hi</body></html>", "local")
    assert "<head>" in out and "Content-Security-Policy" in out


def test_inject_prepends_when_no_html():
    out = csp.inject("<body>hi</body>", "local")
    assert out.startswith("<meta")


if __name__ == "__main__":
    test_local_policy_blocks_remote_keeps_local()
    test_remote_and_hosted_get_no_policy()
    test_inject_is_noop_for_unrestricted_tiers()
    test_inject_places_meta_first_in_head()
    test_inject_handles_uppercase_and_attrs()
    test_inject_creates_head_when_missing()
    test_inject_prepends_when_no_html()
    print("ok")
