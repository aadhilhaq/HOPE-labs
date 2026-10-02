"""The hub: a small web server on this computer, serving the page that fronts every tool.

It runs on the laptop, not on the cluster. It holds the one SSH connection, starts a tool on the
login node when the page asks, forwards a local port to it and tells the page the URL. The tools
themselves are untouched: each is the same page it always was, shown inside the hub's shell.

Nothing here is reachable from outside this computer: the server binds the loopback address and
every request carries a token the page was opened with.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import tools as catalogue
from . import tunnel

def _web():
    """Where the page's files are, whether this is a checkout or a bundled executable.

    PyInstaller puts added data under its own unpacked folder, so the path beside this module is
    tried first and the bundle's root second; a build that forgot to carry the page is caught by
    --selftest rather than by a blank window.
    """
    beside = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    if os.path.isdir(beside):
        return beside
    root = getattr(sys, "_MEIPASS", "")
    return os.path.join(root, "hope_labs", "web") if root else beside


WEB = _web()
START_TIMEOUT = 120          # a cold login node takes a while to import a tool's environment


class Running:
    """A tool that is up: its channel on the shared connection and the local port reaching it."""

    def __init__(self, tool, channel, forwarder, local_port, remote_port, token):
        self.tool = tool
        self.channel = channel
        self.forwarder = forwarder
        self.local_port = local_port
        self.remote_port = remote_port
        self.token = token
        self.started = time.time()
        self.log = ""

    @property
    def url(self):
        return "http://127.0.0.1:%d/%s" % (self.local_port, ("?t=" + self.token) if self.token else "")

    def alive(self):
        return not (self.channel.exit_status_ready() and not self.channel.recv_ready())

    def stop(self):
        for close in (getattr(self.channel, "close", None),
                      getattr(self.forwarder, "shutdown", None),
                      getattr(self.forwarder, "server_close", None)):
            try:
                if close:
                    close()
            except Exception:                                   # noqa: BLE001
                pass


class Hub:
    """Everything the page talks to: the connection, the tools that are up, the runs."""

    def __init__(self, transport, user="", host="", say=None, installs=None):
        self.t = transport
        self.user = user
        self.host = host
        self.say = say or (lambda *a: None)
        #: {tool key: where it is on the cluster}, for anyone whose copies are not the lab's.
        #: Empty means every tool is where tools.py says, which is what a lab member wants.
        self.installs = dict(installs or {})
        self.running = {}                 # key -> Running
        self.token = secrets.token_urlsafe(12)
        self.lock = threading.Lock()
        self._runs_cache = (0.0, [])

    # ---- starting and stopping ------------------------------------------
    def free_remote_port(self):
        """A port nothing is using on the login node, for the two tools that cannot choose one.

        Asked for over the connection we already hold. There is a moment between asking and
        binding in which somebody else could take it; the tools that pick their own port avoid
        that, which is why only two go through here.
        """
        status, out, _ = tunnel.run(self.t, 'python3 -c "import socket; s=socket.socket(); '
                                            "s.bind(('127.0.0.1', 0)); print(s.getsockname()[1]); s.close()\"",
                                    timeout=30)
        got = (out or "").strip().splitlines()
        if status == 0 and got and got[-1].isdigit():
            return int(got[-1])
        return 8800 + secrets.randbelow(600)

    def launch(self, key, runs=""):
        """Start a tool and forward a port to it. Returns what the page needs to show it."""
        tool = catalogue.BY_KEY.get(key)
        if tool is None:
            raise ValueError("there is no tool called %r" % key)
        with self.lock:
            up = self.running.get(key)
            if up is not None and up.alive():
                return self.state_of(key)
            if up is not None:
                up.stop()
                self.running.pop(key, None)

        asked = self.free_remote_port() if tool.needs_port else 0
        line = tool.command(install=self.install_of(tool), runs=runs, port=asked)
        self.say("%s: starting on the login node" % tool.name)
        channel = self.t.open_session()
        channel.get_pty()                 # so the tool dies with this connection
        channel.exec_command(line)
        channel.settimeout(1.0)
        buf, deadline = "", time.time() + START_TIMEOUT
        while time.time() < deadline:
            if channel.exit_status_ready() and not channel.recv_ready():
                raise RuntimeError(self.why(tool, buf))
            try:
                chunk = channel.recv(65536).decode("utf8", "replace")
            except Exception:                                   # noqa: BLE001
                chunk = ""
            if chunk:
                buf += chunk
            got = tool.ready(buf, asked)
            if got:
                remote_port, token = got
                forwarder = tunnel.forward(self.t, tunnel.free_port(), remote_port)
                local = forwarder.server_address[1]
                up = Running(tool, channel, forwarder, local, remote_port, token)
                up.log = buf
                with self.lock:
                    self.running[key] = up
                self.say("%s: ready on 127.0.0.1:%d" % (tool.name, local))
                return self.state_of(key)
            time.sleep(0.2)
        channel.close()
        raise RuntimeError(self.why(tool, buf) or
                           "%s did not report a URL within %ds. What it said:\n%s"
                           % (tool.name, START_TIMEOUT, tail(buf)))

    def install_of(self, tool):
        """Where this copy of a tool is: what the settings say, else the lab's own."""
        return self.installs.get(tool.key) or tool.install

    def why(self, tool, buf):
        """What went wrong, in terms that can be acted on."""
        low = buf.lower()
        where = self.install_of(tool)
        # The markers come from the start lines in tools.py. A missing install is checked first:
        # with no folder there is no activate.sh or environment either, and that is not the news.
        if "no-install" in low or ("no such file or directory" in low and "cd" in low):
            return "there is no %s on the cluster: %s" % (tool.name, where)
        if "no-activate" in low:
            return ("%s is installed at %s but its activate.sh is missing, so its environment "
                    "cannot be entered. Running its install.sh again writes it."
                    % (tool.name, where))
        if "no-env" in low:
            return ("%s is installed at %s but there is no environment at envs/hope beside it. "
                    "HOPE Labs looks for the environment in the folder that holds the install, "
                    "where its install.sh puts it." % (tool.name, where))
        if "no module named" in low:
            return ("%s was not found in its install at %s.\n%s" % (tool.name, where, tail(buf)))
        if "future feature annotations" in low or "syntaxerror" in low:
            return ("the cluster ran %s with a Python too old to parse it; its environment did not "
                    "load.\n%s" % (tool.name, tail(buf)))
        if "address already in use" in low:
            return "the port %s was given is taken; try again and it will be given another" % tool.name
        if "permission denied" in low:
            return "permission denied starting %s:\n%s" % (tool.name, tail(buf))
        if buf.strip():
            return "%s stopped before it was ready:\n%s" % (tool.name, tail(buf))
        return ""

    def stop(self, key):
        with self.lock:
            up = self.running.pop(key, None)
        if up is not None:
            up.stop()
            self.say("%s: stopped" % up.tool.name)
        return True

    def stop_all(self):
        for key in list(self.running):
            self.stop(key)

    # ---- what the page shows --------------------------------------------
    def state_of(self, key):
        tool = catalogue.BY_KEY[key]
        up = self.running.get(key)
        if up is not None and not up.alive():
            self.running.pop(key, None)
            up = None
        info = tool.as_json()
        info["install"] = self.install_of(tool)      # the copy in use, not always the lab's
        info["running"] = up is not None
        info["url"] = up.url if up else ""
        info["since"] = int(time.time() - up.started) if up else 0
        return info

    def state(self):
        return {"user": self.user, "host": self.host,
                "tools": [self.state_of(tool.key) for tool in catalogue.TOOLS],
                "categories": catalogue.categories()}

    # ---- runs, across every tool ----------------------------------------
    def runs(self, refresh=False, limit_each=12):
        """The most recent run folders of every tool, read in one go over the connection.

        One shell command rather than one per tool: each round trip to a login node costs a
        moment, and this is read whenever the Results view is opened.
        """
        age, cached = self._runs_cache
        if cached and not refresh and time.time() - age < 20:
            return cached
        parts = []
        for tool in catalogue.TOOLS:
            for folder in tool.runs:
                # ls -dt: newest first, directories only, and silence when the folder is absent.
                parts.append('for d in $(ls -dt %s/*/ 2>/dev/null | head -%d); do '
                             'printf "%s\\t%%s\\t%%s\\n" "$d" "$(stat -c %%Y "$d" 2>/dev/null)"; done'
                             % (folder, limit_each, tool.key))
        status, out, _ = tunnel.run(self.t, "; ".join(parts), timeout=60)
        found = []
        for line in (out or "").splitlines():
            bits = line.rstrip("\n").split("\t")
            if len(bits) != 3 or not bits[0]:
                continue
            key, path, when = bits[0], bits[1].rstrip("/"), bits[2]
            if key not in catalogue.BY_KEY:
                continue
            found.append({"tool": key, "tool_name": catalogue.BY_KEY[key].name,
                          "name": os.path.basename(path), "path": path,
                          "when": int(when) if when.isdigit() else 0,
                          "next_steps": [{"to": to, "label": label}
                                         for to, label in catalogue.BY_KEY[key].next_steps]})
        found.sort(key=lambda row: row["when"], reverse=True)
        self._runs_cache = (time.time(), found)
        return found


def index_page():
    """The launcher's page, with the bar along its bottom filled in from the docs' credit line."""
    from . import docs, docskit
    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    return (page.replace("/*__CREDITBAR_CSS__*/", docskit.CREDITBAR_CSS.strip())
                .replace("<!--__CREDITBAR__-->", docs.creditbar()))


def tail(buf, n=12):
    lines = [l for l in (buf or "").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def handler_for(hub):
    class Handler(BaseHTTPRequestHandler):
        server_version = "hope-labs"

        def log_message(self, fmt, *args):
            pass                          # the window is the log; a browser's chatter is not news

        def _send(self, code, kind, payload):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _json(self, data, code=200):
            self._send(code, "application/json", json.dumps(data).encode())

        def _allowed(self, query):
            return query.get("t", [""])[0] == hub.token or self.headers.get("X-Token") == hub.token

        def _static(self, name):
            path = os.path.realpath(os.path.join(WEB, name.lstrip("/")))
            if not path.startswith(os.path.realpath(WEB)) or not os.path.isfile(path):
                return self._send(404, "text/plain", b"not found")
            kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as handle:
                self._send(200, kind, handle.read())

        def _docs(self, path):
            from . import docs
            status, kind, body, location = docs.respond(path)
            if location:
                self.send_response(status)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return self._send(status, kind, body)

        def do_GET(self):                                       # noqa: N802
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8", index_page().encode("utf-8"))
            # The documentation needs no token: it is the same for everyone, holds nothing of the
            # session, and a page of it kept as a bookmark has no token to carry.
            if url.path == "/docs" or url.path.startswith("/docs/"):
                return self._docs(url.path)
            # Each tool opens in a window of its own, and that window is served from here: the
            # tool's own page below, a bar across the top that reaches every other tool.
            if url.path == "/tool":
                return self._static("tool.html")
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if not self._allowed(query):
                return self._send(403, "text/plain", b"open the page from the launcher window")
            try:
                if url.path == "/api/state":
                    return self._json(hub.state())
                if url.path == "/api/runs":
                    return self._json({"runs": hub.runs(refresh=query.get("refresh", [""])[0] == "1")})
            except Exception as exc:                            # noqa: BLE001
                traceback.print_exc()
                return self._json({"error": str(exc)}, 500)
            self._send(404, "text/plain", b"not found")

        def do_POST(self):                                      # noqa: N802
            url = urlparse(self.path)
            if not self._allowed(parse_qs(url.query)):
                return self._send(403, "text/plain", b"missing or wrong token")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "could not read that request"}, 400)
            try:
                if url.path == "/api/launch":
                    return self._json(hub.launch(body.get("tool", ""), body.get("runs", "")))
                if url.path == "/api/stop":
                    hub.stop(body.get("tool", ""))
                    return self._json(hub.state_of(body.get("tool", "")))
            except Exception as exc:                            # noqa: BLE001
                return self._json({"error": str(exc)}, 400)
            self._send(404, "text/plain", b"not found")

    return Handler


class _Server(ThreadingHTTPServer):
    # Off, so a busy port raises instead of being shared. On Windows SO_REUSEADDR lets a second
    # process bind a port that is already listening, which would split one person's traffic
    # between two launchers; HTTPServer turns it on by default.
    allow_reuse_address = False


def serve(hub, port=0, host="127.0.0.1", tries=8):
    """Start the hub's own server. Returns (httpd, url).

    The same port every time, for the same person. Chrome remembers "always allow pop-ups" per
    address, and the address includes the port, so a page that moved port every session would be
    blocked again every session however often it was allowed. `port` is tried first, then the
    next few above it, then any free one, so a busy port never stops the launcher starting.
    """
    httpd = None
    for want in ([port + n for n in range(tries)] if port else []):
        try:
            httpd = _Server((host, want), handler_for(hub))
            break
        except OSError:
            continue
    if httpd is None:
        httpd = _Server((host, 0), handler_for(hub))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    bound = httpd.server_address[1]
    return httpd, "http://127.0.0.1:%d/?t=%s" % (bound, hub.token)
