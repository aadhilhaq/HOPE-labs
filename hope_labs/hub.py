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
import shlex
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import canvas
from . import settings
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
        return "http://127.0.0.1:%d%s%s" % (self.local_port, self.tool.page,
                                            ("?t=" + self.token) if self.token else "")

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
        self.starting = {}                # key -> the lock held while that tool starts
        self._scratch = ""                # the person's scratch on the cluster, asked for once
        self.flows = Flows(self)          # queueing flows, and reading back how they are getting on
        #: Where the page being served comes from: a folder taken off the cluster, or "" for the
        #: one this launcher was built with. Set once, when the connection is made.
        self.page_dir = ""
        self.page_note = ""
        self._runs_cache = (0.0, [])

    def use_cluster_page(self, install=""):
        """Serve the lab's current page instead of this launcher's own, where that is possible.

        Called once, after signing in. Whatever it decides, the launcher works: the page it was
        built with is always there to fall back to.
        """
        from . import PAGE_API
        where = install or self.installs.get("flow") or FLOW_INSTALL
        self.page_dir, self.page_note = page_from_cluster(self.t, where, PAGE_API, self.say)
        if self.page_note:
            self.say(self.page_note)
        return self.page_dir

    def web(self):
        """The folder the page is served out of."""
        return self.page_dir or WEB

    @property
    def scratch(self):
        """The person's scratch folder on the cluster.

        Asked for once and kept: it is the same for the whole session, and the clusters the lab
        uses have home quotas small enough that writing anything there is a mistake.
        """
        if not self._scratch:
            status, out, _ = tunnel.run(self.t, 'echo "${SCRATCH:-}"', timeout=30)
            got = (out or "").strip().splitlines()
            self._scratch = got[-1].strip() if status == 0 and got and got[-1].strip() else "/tmp"
        return self._scratch

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
        # One start at a time per tool: a second tab asking while the first start is still under
        # way waits for it and gets the same copy, instead of a second one on the login node.
        with self.lock:
            gate = self.starting.setdefault(key, threading.Lock())
        with gate:
            return self._launch(tool, key, runs)

    def _launch(self, tool, key, runs):
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


def index_page(name="index.html", root=""):
    """One of the launcher's pages, with the bar along its bottom filled in from the docs' credit line."""
    from . import docs, docskit
    path = os.path.join(root or WEB, name)
    if root and not os.path.isfile(path):
        path = os.path.join(WEB, name)
    with open(path, encoding="utf-8") as fh:
        page = fh.read()
    return (page.replace("/*__CREDITBAR_CSS__*/", docskit.CREDITBAR_CSS.strip())
                .replace("<!--__CREDITBAR__-->", docs.creditbar()))


def tail(buf, n=12):
    lines = [l for l in (buf or "").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def said(out, err):
    """The one line of a runner's answer worth putting in front of a person.

    A refusal from the runner is a sentence on stderr, but a bug in it is a traceback, and the
    first three hundred characters of a traceback are frames and file names rather than what went
    wrong. The last line is the sentence either way.
    """
    lines = [l.strip() for l in ((err or "").strip() or (out or "")).splitlines() if l.strip()]
    return lines[-1][:300] if lines else ""


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
            root = hub.web()
            path = os.path.realpath(os.path.join(root, name.lstrip("/")))
            if not path.startswith(os.path.realpath(root)) or not os.path.isfile(path):
                # A page taken off the cluster may be missing a file this launcher's own has,
                # and the built-in one is the answer rather than a blank panel.
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
                return self._send(200, "text/html; charset=utf-8", index_page(root=hub.web()).encode("utf-8"))
            # The documentation needs no token: it is the same for everyone, holds nothing of the
            # session, and a page of it kept as a bookmark has no token to carry.
            if url.path == "/docs" or url.path.startswith("/docs/"):
                return self._docs(url.path)
            # Each tool opens in a tab of its own. The tab comes here first, starts the tool and
            # shows the wait, then goes on to the tool's own page.
            if url.path == "/tool":
                return self._send(200, "text/html; charset=utf-8", index_page("tool.html", hub.web()).encode("utf-8"))
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if not self._allowed(query):
                return self._send(403, "text/plain", b"open the page from the launcher window")
            try:
                if url.path == "/api/state":
                    return self._json(hub.state())
                if url.path == "/api/runs":
                    return self._json({"runs": hub.runs(refresh=query.get("refresh", [""])[0] == "1")})
                # The canvas: the cards it draws from, the flow it starts from, and the flows
                # kept on this computer. Behind the token like everything else under /api.
                if url.path == "/api/flow/cards":
                    return self._json(canvas.catalogue())
                if url.path == "/api/flow/example":
                    return self._json(canvas.example())
                if url.path == "/api/flow/saved":
                    return self._json({"flows": settings.flows()})
                # The flows that have been queued, so that a person who comes back the next day
                # finds the one they started rather than a folder they have to remember.
                if url.path == "/api/flow/queued":
                    return self._json({"runs": settings.queued()})
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
                # The canvas posts the flow as it stands and is told what is wrong with it, so the
                # page and the cluster are reading one answer rather than each their own.
                if url.path == "/api/flow/check":
                    return self._json(canvas.check(body.get("flow") or {}))
                if url.path == "/api/flow/save":
                    return self._json({"flows": settings.flow_save(body.get("flow") or {})})
                if url.path == "/api/flow/delete":
                    return self._json({"flows": settings.flow_delete(body.get("name", ""))})
                # The plan is what a person reads before committing a cluster allocation: what
                # each card will queue, where it lands, and the numbers that decide what it costs.
                if url.path == "/api/flow/plan":
                    return self._json(canvas.plan(hub.flows, body.get("flow") or {},
                                                  body.get("runs", "")))
                if url.path == "/api/flow/launch":
                    got = canvas.launch(hub.flows, body.get("flow") or {}, body.get("runs", ""))
                    # The folder is the only way back to a flow once this window is closed, so it
                    # is written down with the drawing it came from before the answer goes out. A
                    # settings file that cannot be written is not worth losing the launch over:
                    # the flow is queued either way, and the folder is in the answer.
                    try:
                        settings.queued_save(body.get("flow") or {}, got.get("folder", ""))
                    except (OSError, ValueError) as why:
                        hub.say("the flow was queued but not written down: %s" % why)
                    return self._json(got)
                if url.path == "/api/flow/status":
                    return self._json(hub.flows.status(body.get("folder", "")))
                # Carrying on is queueing, so it commits as much as Launch did. The page offers it
                # only once nothing of the flow is left in the queue, and the runner queues the
                # cards that have not finished rather than the whole flow again.
                if url.path == "/api/flow/resume":
                    return self._json(hub.flows.resume(body.get("folder", "")))
                if url.path == "/api/flow/stop":
                    return self._json(hub.flows.stop(body.get("folder", "")))
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


# --- flows -----------------------------------------------------------------------------------
# A flow is queued on the cluster and runs there. The launcher's part is to put the drawing where
# the cluster can read it and to ask the runner to start it; after that, nothing of the launcher
# is involved, and closing it leaves the flow running.

FLOW_INSTALL = "/scratch/group/sflab/HOPE-labs"


#: Pythons to try for the runner, in order. A login node's own python3 is 3.6 on this cluster,
#: which cannot read the runner at all, so one is looked for rather than assumed; the lab's
#: HOPE-MD environment is the one every member already has.
FLOW_PYTHONS = ("/scratch/group/sflab/HOPE-MD/env/bin/python3", "python3.12", "python3.11",
                "python3.10", "python3.9", "python3")


def flow_command(install, args, root=""):
    """The line that runs the flow runner on the login node, in a given checkout.

    The runner needs Python 3.8 or newer. Rather than name one and fail on a cluster that keeps
    it somewhere else, the line tries each candidate and takes the first that is new enough, so
    the failure a person sees is about their flow rather than about an interpreter.
    """
    where = catalogue.rebase(install or FLOW_INSTALL, root)
    tries = " ".join(shlex.quote(p) for p in FLOW_PYTHONS)
    return ('cd %s || exit 1; PY=""; '
            'for C in "${HOPEFLOW_PYTHON:-}" %s; do '
            '[ -n "$C" ] || continue; '
            'command -v "$C" >/dev/null 2>&1 || continue; '
            '"$C" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" '
            '>/dev/null 2>&1 || continue; PY="$C"; break; done; '
            '[ -n "$PY" ] || { echo "no Python of 3.8 or newer was found for the flow runner" >&2; '
            'exit 3; }; '
            'PYTHONPATH=%s exec "$PY" -m hope_flow.cli %s'
            % (shlex.quote(where), tries, shlex.quote(where), args))


class Flows:
    """Queueing flows on the cluster, and reading back how they are getting on."""

    def __init__(self, hub):
        self.hub = hub

    def _run(self, args, timeout=180):
        install = self.hub.installs.get("flow") or FLOW_INSTALL
        line = flow_command(install, args, self.hub.installs.get("_root", ""))
        return tunnel.run(self.hub.t, line, timeout=timeout)

    def _put(self, doc, name):
        """Write the drawing where the cluster can read it, and give back its path.

        It goes beside the flow's own folders rather than into a home directory: the clusters the
        lab uses have small home quotas, and a flow is scratch work.
        """
        where = "%s/.hope_flows" % (self.hub.scratch or "/tmp")
        path = "%s/%s.json" % (where, re.sub(r"[^A-Za-z0-9_.-]", "_", name or "flow"))
        text = json.dumps(doc, indent=2)
        status, out, err = tunnel.run(
            self.hub.t, "mkdir -p %s && cat > %s <<'HOPEFLOWEOF'\n%s\nHOPEFLOWEOF"
            % (shlex.quote(where), shlex.quote(path), text), timeout=60)
        if status != 0:
            raise RuntimeError("the flow could not be written to the cluster: %s"
                               % (err or out).strip()[:300])
        return path

    def plan(self, doc, runs=""):
        """What this flow would do, worked out on the cluster, where the tools actually are."""
        path = self._put(doc, doc.get("name"))
        args = "plan %s --json" % shlex.quote(path)
        if runs:
            args += " --runs " + shlex.quote(runs)
        status, out, err = self._run(args)
        try:
            return json.loads(out[out.index("{"):out.rindex("}") + 1])
        except (ValueError, IndexError):
            raise RuntimeError("the runner did not answer with a plan: %s"
                               % ((err or out).strip()[:400] or "it said nothing"))

    def launch(self, doc, runs=""):
        """Queue the flow. Returns where it is and what is waiting on what."""
        path = self._put(doc, doc.get("name"))
        args = "submit " + shlex.quote(path)
        if runs:
            args += " --runs " + shlex.quote(runs)
        status, out, err = self._run(args, timeout=600)
        if status != 0:
            raise RuntimeError((err or out).strip()[:600] or "the runner refused the flow")
        lines = [l.strip() for l in (out or "").splitlines() if l.strip()]
        folder = next((l for l in lines if l.startswith("/")), "")
        if not folder:
            raise RuntimeError("the runner queued something but did not say where: %s"
                               % " ".join(lines)[:300])
        self.hub.say("flow %s queued in %s" % (doc.get("name") or "", folder))
        return {"folder": folder, "log": lines}

    def status(self, folder):
        """How far a flow has got, read from the record its own jobs keep."""
        status, out, err = self._run("status %s --json" % shlex.quote(folder))
        try:
            return json.loads(out[out.index("{"):out.rindex("}") + 1])
        except (ValueError, IndexError):
            raise RuntimeError("that flow's record could not be read: %s"
                               % ((err or out).strip()[:300] or "it said nothing"))

    def resume(self, folder):
        """Carry on a flow that stopped. What finished is left alone; the rest is queued again.

        It waits as long as launch rather than as long as stop, because it does the same work:
        a flow of five cards is a dozen sbatch calls down the connection, and a resume cut short
        halfway would leave a person with half a flow in the queue and no way to tell which half.
        """
        status, out, err = self._run("resume %s" % shlex.quote(folder), timeout=600)
        if status != 0:
            raise RuntimeError(said(out, err) or "the flow could not be carried on")
        return {"resumed": (out or "").strip()}

    def stop(self, folder):
        status, out, err = self._run("stop %s" % shlex.quote(folder))
        if status != 0:
            raise RuntimeError(said(out, err) or "the flow could not be stopped")
        return {"stopped": (out or "").strip()}


# --- the page the launcher serves --------------------------------------------------------------
# The launcher is a shell: it signs in, holds one connection, and serves a page. The page was
# always the one built into it, which meant every change to the page - a new view, a reworded
# refusal, a field on a card - needed everybody to download a launcher again. Sharing a tool
# should not mean sharing it repeatedly.
#
# So the page is taken from the lab's install on the cluster when that install's page says it can
# work against this launcher's server, and from the build when it cannot. The two numbers that
# decide it are in __init__.py. A launcher that is too old to serve the newer page keeps its own
# and says so in one line, rather than serving a page whose buttons call routes it does not have.

PAGE_CACHE = os.path.join(os.path.expanduser("~"), ".hope_labs_page")
PAGE_FILES = ("index.html", "app.js", "flow.js", "style.css", "tool.html", "tool.js")


def page_from_cluster(transport, install, provides, say=None):
    """Fetch the install's page into a folder on this computer. Returns (folder, what to say).

    Fails safe in every direction: anything unreadable, anything missing, any version this
    launcher is too old for, and the answer is the page this launcher was built with.
    """
    say = say or (lambda *a: None)
    try:
        import paramiko
        sftp = paramiko.SFTPClient.from_transport(transport)
    except Exception as why:                                    # noqa: BLE001
        return "", "the page on the cluster could not be reached (%s); using this launcher's own" % why
    try:
        needs, version = _page_version(sftp, install)
        if needs is None:
            return "", ""                                       # no install to read; nothing to say
        if needs > provides:
            return "", ("HOPE Labs %s on the cluster needs a newer launcher than this one. "
                        "This launcher's own page is being used; download %s to get the rest."
                        % (version or "there", version or "the current release"))
        where = os.path.join(PAGE_CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", install))
        os.makedirs(where, exist_ok=True)
        got = 0
        for name in PAGE_FILES:
            try:
                sftp.get("%s/hope_labs/web/%s" % (install, name), os.path.join(where, name))
                got += 1
            except IOError:
                continue                                        # a page file this install lacks
        if got < 3:
            return "", ""                                       # not a page; keep the built-in one
        _page_docs(sftp, install, where)
        say("page %s from the cluster" % (version or ""))
        return where, ""
    except Exception as why:                                    # noqa: BLE001
        return "", "the page on the cluster could not be read (%s); using this launcher's own" % why
    finally:
        try:
            sftp.close()
        except Exception:                                       # noqa: BLE001
            pass


def _page_version(sftp, install):
    """(the server API that install's page needs, its version), or (None, "") when there is none."""
    try:
        with sftp.open("%s/hope_labs/__init__.py" % install) as fh:
            text = fh.read().decode("utf-8", "replace")
    except IOError:
        return None, ""
    needs = re.search(r"^PAGE_NEEDS\s*=\s*(\d+)", text, re.M)
    version = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    # An install from before these existed served a page this launcher's server can read, since
    # that is the server it had; treat it as the first contract rather than refusing it.
    return (int(needs.group(1)) if needs else 1), (version.group(1) if version else "")


def _page_docs(sftp, install, where):
    """The documentation beside the page, so it is as current as the page is."""
    for part in ("docs/pages", "docs/img"):
        here = os.path.join(where, *part.split("/"))
        os.makedirs(here, exist_ok=True)
        try:
            names = sftp.listdir("%s/hope_labs/web/%s" % (install, part))
        except IOError:
            continue
        for name in names[:200]:
            try:
                sftp.get("%s/hope_labs/web/%s/%s" % (install, part, name),
                         os.path.join(here, name))
            except IOError:
                continue
