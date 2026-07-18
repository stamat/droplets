"""Per-tier Content-Security-Policy: the enforcement half of the three-tier
security model the README promises.

The promise: a `local` widget "cannot have communication to the web through
HTTP ... only through the python interface". Until now nothing enforced it -- a
local widget could pull a remote `<script src>` and, via the open Python bridge,
get remote code execution on the host (see PR #5 review, finding #2). This is
that enforcement.

Only the `local` tier is locked down: it may load its own files (file:/data:/
blob:) and run inline scripts (Dashboard-style widgets rely on inline), but no
http/https/ws origin appears in any directive, so remote scripts, fetch/XHR,
remote images and frames are all blocked by the browser before they ever reach
the bridge. `remote` and `hosted` are, by design, allowed to talk to the web
(they have no system bridge), so they get no policy.

The policy is delivered as a `<meta http-equiv>` baked into the entry HTML at
parse time (see `inject`), which is the spec-honoured way -- both WebKitGTK and
WKWebView enforce a meta CSP present when the document is parsed.

ponytail: `'unsafe-inline'`/`'unsafe-eval'` stay allowed because existing local
widgets (clock, calculator, ...) use inline scripts; the tier threat is *remote*
loading, which this blocks. Tighten to nonces only if/when widgets are updated.
ponytail: meta is injected into the *entry* document only. Local navigation is
already pinned to the widget's own directory by the backend nav policy, so a
sub-page can't be remote anyway; if whole-context coverage is ever needed, move
to WebKit content-filters (GTK) / WKContentRuleList (Cocoa) -- same policy source.
"""

import re

# file:/data:/blob: cover the widget's own tree and inline assets; no remote
# scheme is listed, so http/https/ws are denied by each directive's fallback.
_LOCAL_SOURCES = "'self' file: data: blob:"

_LOCAL_POLICY = "; ".join(
    [
        "default-src " + _LOCAL_SOURCES,
        "script-src " + _LOCAL_SOURCES + " 'unsafe-inline' 'unsafe-eval'",
        "style-src " + _LOCAL_SOURCES + " 'unsafe-inline'",
        "img-src " + _LOCAL_SOURCES,
        "font-src " + _LOCAL_SOURCES,
        "media-src " + _LOCAL_SOURCES,
        "connect-src " + _LOCAL_SOURCES,
        "frame-src " + _LOCAL_SOURCES,
        "object-src 'none'",
    ]
)

_HEAD_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
_HTML_RE = re.compile(r"<html\b[^>]*>", re.IGNORECASE)


def policy_for(origin):
    """CSP string for a tier, or None when the tier gets no policy.

    Only `local` is restricted (it has the system bridge). `remote`/`hosted`
    are meant to reach the web and have no bridge, so they're unrestricted.
    """
    return _LOCAL_POLICY if origin == "local" else None


def meta_tag(origin):
    """The `<meta http-equiv>` line for a tier, or "" when there's no policy."""
    policy = policy_for(origin)
    if policy is None:
        return ""
    return '<meta http-equiv="Content-Security-Policy" content="%s">' % policy


def inject(html, origin):
    """Return `html` with the tier's CSP meta as the first thing in <head>.

    Inserted at parse position (right after <head>, else after <html>, else at
    the top) so the browser enforces it. No-op when the tier has no policy.
    """
    tag = meta_tag(origin)
    if not tag:
        return html
    m = _HEAD_RE.search(html)
    if m:
        return html[: m.end()] + tag + html[m.end() :]
    m = _HTML_RE.search(html)
    if m:
        return html[: m.end()] + "<head>" + tag + "</head>" + html[m.end() :]
    return tag + html


if __name__ == "__main__":
    # local tier: policy exists, blocks remote, keeps local + inline.
    p = policy_for("local")
    assert p and "http" not in p, p
    assert "'unsafe-inline'" in p and "file:" in p
    # remote/hosted: no policy, injection is a no-op.
    assert policy_for("remote") is None and policy_for("hosted") is None
    assert inject("<html><head></head></html>", "remote") == "<html><head></head></html>"
    # meta lands inside <head> for a local widget.
    out = inject("<html><head><title>x</title></head><body></body></html>", "local")
    assert out.index("Content-Security-Policy") > out.index("<head>")
    assert out.index("Content-Security-Policy") < out.index("<title>")
    # HEAD uppercase / attributes still matched.
    out = inject('<HTML><HEAD lang="en"></HEAD></HTML>', "local")
    assert "Content-Security-Policy" in out and out.count("<head>") == 0
    # no <head>: one is created after <html>.
    out = inject("<html><body>hi</body></html>", "local")
    assert "<head>" in out and "Content-Security-Policy" in out
    # no <html> at all: meta prepended, still enforced at parse top.
    out = inject("<body>hi</body>", "local")
    assert out.startswith("<meta")
    print("ok")
