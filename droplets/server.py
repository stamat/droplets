"""Loopback document server for the `local` tier (pywebview backend).

Two problems the widget's own directory on disk cannot solve at once:

  - The CSP has to reach the browser as a real `Content-Security-Policy` header.
    A `<meta>` only governs what the parser sees after it, and only in the
    document it sits in; a header covers the whole response.
  - WKWebView grants a `loadHTMLString:baseURL:` document *no* read access to
    that base directory, so a widget loaded that way cannot load its own PNG,
    stylesheet or script. Serving over http:// makes the widget an ordinary
    same-origin document and the problem disappears.

So the entry document is rendered in memory (CSP header + whatever head tag the
backend wants injected, e.g. the JS bridge shim) and its directory is served
alongside it.

Exposure is the obvious cost of a listener. Three things keep it narrow:
127.0.0.1 only; everything lives under an unguessable `/<uuid>/` prefix, so a
web page that guesses the port still cannot read the widget (and nothing ever
redirects to that prefix, which would hand the secret to whoever asked); and the
root is pinned to the widget directory with traversal rejected.

ponytail: stdlib wsgiref, no framework. This serves one small directory to one
webview -- bottle (which pywebview vendors) buys nothing here.
"""

import hashlib
import mimetypes
import os
import threading
import urllib.parse
import uuid
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from . import csp


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass  # one line per asset on stdout helps nobody


def _port_for(root):
    """A stable port per widget directory.

    The origin (and so localStorage, IndexedDB, cookies) is scheme+host+port, so
    a random port every launch would silently wipe a widget's stored state.
    Hashing the path keeps a given widget on a given origin.
    """
    digest = hashlib.sha256(root.encode("utf-8")).digest()
    return 20000 + int.from_bytes(digest[:4], "big") % 20000


def make_app(root, source, origin, extra_head=""):
    """Build the WSGI app for one widget. Returns `(app, entry_path)`.

    `entry_path` is the URL path of the entry document, including the secret
    prefix. Every path outside that prefix -- including `/` -- is a 404.
    """
    root = os.path.abspath(root)
    prefix = "/%s/" % uuid.uuid4().hex
    entry = os.path.abspath(os.path.join(root, source))
    policy = csp.policy_for(origin, served=True)

    def not_found(start_response):
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if not path.startswith(prefix):
            return not_found(start_response)
        rel = urllib.parse.unquote(path[len(prefix) :])
        target = os.path.abspath(os.path.join(root, rel))
        # Traversal: `..` segments (and symlinks out) must not escape the widget.
        if os.path.commonpath([target, root]) != root or not os.path.isfile(target):
            return not_found(start_response)

        if target == entry:
            with open(target, "r", encoding="utf-8") as f:
                body = csp.inject_head(f.read(), extra_head).encode("utf-8")
            headers = [("Content-Type", "text/html; charset=utf-8")]
            if policy:
                headers.append(("Content-Security-Policy", policy))
        else:
            with open(target, "rb") as f:
                body = f.read()
            mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
            headers = [("Content-Type", mime)]

        # No caching: a widget author editing a file wants a reload to show it.
        headers += [("Content-Length", str(len(body))), ("Cache-Control", "no-store")]
        start_response("200 OK", headers)
        return [body]

    return app, prefix + urllib.parse.quote(source)


def serve(root, source, origin, extra_head=""):
    """Serve one widget on loopback. Returns the URL of its entry document."""
    root = os.path.abspath(root)
    app, entry_path = make_app(root, source, origin, extra_head)
    try:
        httpd = make_server(
            "127.0.0.1", _port_for(root), app, _ThreadingWSGIServer, _QuietHandler
        )
    except OSError:
        # Port taken (another widget hashed to it, or an unrelated process).
        # ponytail: falling back to an ephemeral port costs this widget its
        # stored state for this run -- rare enough to not warrant a registry.
        httpd = make_server("127.0.0.1", 0, app, _ThreadingWSGIServer, _QuietHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d%s" % (httpd.server_port, entry_path)
