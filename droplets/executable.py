"""Run a droplet's non-Python executable as a long-lived JSON-over-stdio child.

A droplet's `executable` (manifest) is normally a Python module, imported
in-process and called directly. When it's `main.js` / `main.rb` instead we can't
import it -- we spawn it once and speak line-delimited JSON, one request -> one
reply, so recieve() can call `proxy.method(**args)` exactly as if it were a
Python module (StdioExecutable duck-types a module via __getattr__).

Protocol (one JSON object per line):
    host  -> child : {"method": <str>, "args": {...}}
    child -> host  : {"result": <any>}   OR   {"error": <str>}

stdout is the reply channel ONLY. The child must send logs/diagnostics to
stderr; anything printed to stdout that isn't a reply desyncs the stream. stderr
is drained to the host log on a daemon thread so a chatty or crashing child
never dies on a full pipe and its errors are still surfaced.

Lifecycle: spawned on load, reaped by close() (called from droplet_deactivate;
also registered with atexit so an unexpected host exit never orphans the child).
A child that has died is respawned on the next call (warm state is lost -- logged).
"""

import atexit
import json
import os
import subprocess
import sys
import threading

from .utils import import_from_uri

# executable extension -> interpreter argv prefix.
_INTERPRETERS = {
    ".js": ["node"],
    ".mjs": ["node"],
    ".cjs": ["node"],
    ".rb": ["ruby"],
}


def _log(msg):
    sys.stderr.write("[droplet exec] %s\n" % msg)
    sys.stderr.flush()


class ExecutableError(Exception):
    """A droplet's executable failed to spawn, crashed, or returned an error."""


class StdioExecutable:
    """Long-lived child process spoken to as JSON lines. Duck-types a module:
    getattr(proxy, name) returns a callable that RPCs `name` to the child."""

    def __init__(self, cmd, cwd, name="executable"):
        self._cmd = cmd
        self._cwd = cwd
        self._name = name
        self._proc = None
        self._lock = threading.Lock()  # calls are strictly sequential (1 reply/req)
        self._closed = False
        self._spawn()
        atexit.register(self.close)  # safety net: never orphan the child

    # ---- lifecycle ------------------------------------------------------
    def _spawn(self):
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                cwd=self._cwd,
                text=True,
                bufsize=1,  # line-buffered pipes
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ExecutableError(
                "%s: interpreter %r not found on PATH" % (self._name, self._cmd[0])
            )
        # Drain stderr on a daemon thread: keeps the pipe from filling (which would
        # deadlock the child) and forwards the child's diagnostics to the host log.
        threading.Thread(
            target=self._drain_stderr, args=(self._proc.stderr,), daemon=True
        ).start()

    def _drain_stderr(self, stderr):
        for line in stderr:
            _log("%s: %s" % (self._name, line.rstrip()))

    def _alive(self):
        return self._proc is not None and self._proc.poll() is None

    def close(self):
        """Reap the child. Idempotent; safe from droplet_deactivate and atexit."""
        self._closed = True
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    # ---- dispatch -------------------------------------------------------
    def __getattr__(self, method):
        # Private/dunder lookups must never spawn an RPC (pickling, repr, etc.).
        if method.startswith("_"):
            raise AttributeError(method)

        def call(**args):
            return self._call(method, args)

        return call

    def _call(self, method, args):
        with self._lock:
            if self._closed:
                raise ExecutableError("%s: called after close()" % self._name)
            if not self._alive():
                _log("%s: child not running, respawning (warm state lost)" % self._name)
                self._spawn()
            try:
                self._proc.stdin.write(json.dumps({"method": method, "args": args}) + "\n")
                self._proc.stdin.flush()
                line = self._proc.stdout.readline()
            except (BrokenPipeError, OSError) as e:
                raise ExecutableError(
                    "%s: pipe broke calling %r: %s" % (self._name, method, e)
                )
            if not line:  # EOF -> child exited mid-call
                raise ExecutableError(
                    "%s: child exited during %r" % (self._name, method)
                )
            try:
                reply = json.loads(line)
            except ValueError as e:
                # Almost always a stray stdout write from the child (see module
                # docstring): the reply channel is corrupted, not merely a bad call.
                raise ExecutableError(
                    "%s: non-JSON reply to %r (%s): %r"
                    % (self._name, method, e, line[:200])
                )
            if "error" in reply:
                raise ExecutableError("%s.%s: %s" % (self._name, method, reply["error"]))
            return reply.get("result")


def load_executable(uri, absl=False):
    """Load a droplet's executable, mirroring import_from_uri's signature.

    main.py -> imported in-process (unchanged fast path). main.js / main.rb (etc.)
    -> a StdioExecutable proxy. Python wins when several exist, for back-compat.
    Returns None when no executable file is found.
    """
    if not absl:
        uri = os.path.normpath(os.path.join(os.path.dirname(__file__), uri))
    stem = os.path.splitext(uri)[0]
    if os.path.exists(stem + ".py"):
        return import_from_uri(uri, True)
    for ext, argv in _INTERPRETERS.items():
        if os.path.exists(stem + ext):
            # Absolute script path so the interpreter never re-resolves it against
            # cwd (which we set to the widget dir for the child's relative imports).
            src = os.path.abspath(stem + ext)
            return StdioExecutable(argv + [src], os.path.dirname(src), os.path.basename(src))
    return None


if __name__ == "__main__":
    # Self-check with a Python echo child so the test needs no node/ruby: it
    # exercises the request/reply, {error} reporting, and respawn-after-death.
    _CHILD = (
        "import sys,json\n"
        "for line in sys.stdin:\n"
        "  r=json.loads(line)\n"
        "  if r['method']=='boom':\n"
        "    print(json.dumps({'error':'kaboom'}))\n"
        "  else:\n"
        "    print(json.dumps({'result':r['args'].get('n',0)+1}))\n"
        "  sys.stdout.flush()\n"
    )
    ex = StdioExecutable([sys.executable, "-c", _CHILD], os.getcwd(), "selfcheck")
    assert ex.inc(n=41) == 42
    assert ex.inc(n=1) == 2  # second call proves the child stays warm

    try:
        ex.boom()
    except ExecutableError as e:
        assert "kaboom" in str(e), e
    else:
        raise AssertionError("expected ExecutableError from {error} reply")

    ex._proc.kill()  # simulate a crash; next call must respawn
    ex._proc.wait()
    assert ex.inc(n=7) == 8

    ex.close()
    try:
        ex.inc(n=0)
    except ExecutableError:
        pass
    else:
        raise AssertionError("expected ExecutableError after close()")

    assert load_executable("does/not/exist", True) is None
    print("ok")
