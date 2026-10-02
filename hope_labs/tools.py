"""The five tools: where each lives, how it is started, and how it says it is ready.

Everything that differs between the lab's tools is in this table, so the hub itself knows
nothing about any particular one. Each tool is already a web page served on a login node; the
hub starts it over the shared SSH connection, forwards a local port and shows it.

The three handshakes are the awkward part. HOPE-MD, BindCraft2 and the docking console all
print one line carrying the port they took and the token that gates them. The aptamer pipeline
prints two lines of its own. The pipelines monitor prints neither: it is told which port to use
and prints a banner with the token in it. None of them takes a token on the command line, and
that is deliberate in all five: a login node is shared and `ps` shows every argument to
everybody on it.
"""
from __future__ import annotations

import re
import shlex

# HOPE-MD, BindCraft2 and the docking console: "open  http://127.0.0.1:<port>/?t=<token>"
URL_LINE = re.compile(r"http://127\.0\.0\.1:(\d+)/\?t=([A-Za-z0-9_\-]+)")
# The aptamer pipeline announces itself in two lines.
APTAMER_PORT = re.compile(r"HOPE-APTAMER-LAUNCHER port=(\d+) node=(\S+)")
APTAMER_TOKEN = re.compile(r"HOPE-APTAMER-TOKEN ([A-Za-z0-9_-]{16,})")
# The pipelines monitor says this when it is up, and prints its token in its banner.
MONITOR_READY = "Ctrl-C here stops the server"
MONITOR_TOKEN = re.compile(r"\?t=([A-Za-z0-9_-]{8,})")


#: Where the lab's own copies are. Every default install below sits under it, so one setting
#: moves all five: a person outside the group installs them in their own scratch and names that
#: folder instead. See docs/install-on-grace.md.
LAB_ROOT = "/scratch/group/sflab"


def rebase(install, root):
    """`install` as it would be under `root`, keeping the layout the lab uses.

    Only the lab root is replaced, so a path already pointing somewhere else is left alone and
    a tool named individually keeps whatever it was given.
    """
    root = (root or "").strip().rstrip("/")
    if not root or not install.startswith(LAB_ROOT + "/"):
        return install
    return root + install[len(LAB_ROOT):]


def installs_for(root="", overrides=None):
    """{tool key: where it is}, from one root and any tool named on its own."""
    out = {}
    for tool in TOOLS:
        where = rebase(tool.install, root)
        if where != tool.install:
            out[tool.key] = where
    for key, where in (overrides or {}).items():
        if key in BY_KEY and str(where or "").strip():
            out[key] = str(where).strip()
    return out


def remote_path(path):
    """A path for the far end's shell, with ~ still able to expand."""
    path = (path or "").strip()
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


def _url_ready(text, asked_port):
    """(port, token) once one of the three prints its URL line."""
    found = URL_LINE.search(text)
    return (int(found.group(1)), found.group(2)) if found else None


def _aptamer_ready(text, asked_port):
    port, token = APTAMER_PORT.search(text), APTAMER_TOKEN.search(text)
    if port and token:
        return int(port.group(1)), token.group(1)
    return None


def _monitor_ready(text, asked_port):
    """The monitor is up when it says so; its token comes out of the same banner."""
    if MONITOR_READY not in text:
        return None
    found = MONITOR_TOKEN.search(text)
    return asked_port, (found.group(1) if found else "")


class Tool:
    """One tool: what it is, where it is, and the line that starts it."""

    def __init__(self, key, name, tagline, category, install, start, ready, blurb="",
                 needs_port=False, runs=(), next_steps=(), takes="", gives="", page="/"):
        self.key = key
        self.name = name
        self.tagline = tagline
        self.blurb = blurb
        self.category = category
        self.install = install
        self._start = start
        self.ready = ready
        self.needs_port = needs_port      # True when the tool cannot pick a free port itself
        self.runs = tuple(runs)           # where its run folders live, $USER left to the shell
        self.next_steps = tuple(next_steps)
        self.takes = takes                # what another tool can hand it
        self.gives = gives                # what it leaves for the next tool
        self.page = page                  # the page its tab opens on, as its own launcher opens it

    def command(self, install="", runs="", port=0):
        return self._start(remote_path(install or self.install), runs, port)

    def as_json(self):
        return {"key": self.key, "name": self.name, "tagline": self.tagline, "blurb": self.blurb,
                "category": self.category, "install": self.install,
                "next_steps": [{"to": to, "label": label} for to, label in self.next_steps],
                "takes": self.takes, "gives": self.gives, "page": self.page}


# --- the lines that start each tool ----------------------------------------
# Each sources the install's own activate.sh rather than naming a Python: that file is where the
# installed layout is recorded, so the hub cannot drift away from what the installer did.

def _activate(override):
    """Enter the install's environment through its activate.sh, from inside the install.

    A Python named in `override` stands in for the file. With neither, the tool still starts on
    whatever python3 the login shell has, as it always did, but the line says first that the file
    is missing: a tool that then fails is reported for that, not as a module it could not find.
    """
    return ('if [ -f ./activate.sh ]; then . ./activate.sh; '
            'elif [ -z "${%s:-}" ]; then echo "NO-ACTIVATE $PWD/activate.sh"; fi; ' % override)


def _hopemd(where, runs, port):
    args = "-m hopemd.server --host 127.0.0.1 --port %d" % port
    if runs:
        args += " --runs " + remote_path(runs)
    return ('cd %s || exit 1; %sPY="${HOPEMD_PYTHON:-python3}"; PYTHONPATH=%s exec "$PY" %s'
            % (where, _activate("HOPEMD_PYTHON"), where, args))


def _bindcraft(where, runs, port):
    args = "--host 127.0.0.1 --port %d" % port
    if runs:
        args += " --runs " + remote_path(runs)
    # bc2-serve names the install's own environment, so no module is loaded and no Python named.
    return 'cd %s || exit 1; exec ./sflab/bc2-serve %s' % (where, args)


def _adcp(where, runs, port):
    args = "-m adcp_dock.cli serve --host 127.0.0.1 --port %d" % port
    if runs:
        args += " --runs " + remote_path(runs)
    return ('cd %s || exit 1; %sPY="${ADCP_PYTHON:-python3}"; PYTHONPATH=%s exec "$PY" %s'
            % (where, _activate("ADCP_PYTHON"), where, args))


def _aptamer(where, runs, port):
    # Its own launcher wants `serve port=N`, and it cannot choose a port itself.
    tail = (" runs=" + remote_path(runs)) if runs else ""
    return ("bash -lc '(module load Anaconda3) >/dev/null 2>&1 || true; "
            'if [ ! -d %(w)s ]; then echo "NO-INSTALL %(w)s"; exit 3; fi; '
            'if [ -f %(w)s/activate.sh ]; then . %(w)s/activate.sh; '
            'else echo "NO-ACTIVATE %(w)s/activate.sh"; exit 3; fi; '
            "exec python -u -m hope_aptamer.cli serve port=%(p)d%(t)s'"
            % {"w": where, "p": port, "t": tail})


def _monitor(where, runs, port):
    # The monitor is told its port. Its environment is envs/hope beside the checkout, not an
    # activate.sh inside it: a conda environment, which that pipeline's setup.sh gives a venv
    # style bin/activate. So both the environment and the root it lists runs under are taken from
    # the folder the checkout sits in. For the lab's own copy that is /scratch/group/sflab, as
    # before; for a copy in somebody's scratch it follows them there without a second setting.
    #
    # --token on its own makes the monitor generate one and print it. It is off by default there,
    # and left off anyone else logged into the same login node could reach it over loopback, so
    # the hub always asks for it and reads it back out of the banner.
    args = '-m hope_monitor --host 127.0.0.1 --port %d --token --root "$HL_ROOT"' % port
    if runs:
        args += " --runs " + remote_path(runs)
    return ('cd %s || exit 1; HL_ROOT="$(cd .. && pwd)"; '
            'if [ -f "$HL_ROOT"/envs/hope/bin/activate ]; then . "$HL_ROOT"/envs/hope/bin/activate; '
            'else echo "NO-ENV $HL_ROOT/envs/hope"; fi; '
            'PYTHONPATH=%s exec python %s' % (where, where, args))


TOOLS = (
    Tool("adcp", "ADCP docking", "Dock a peptide into a receptor",
         "Docking", "/scratch/group/sflab/ADCP_docking", _adcp, _url_ready,
         blurb="Prepares a receptor and a peptide, runs ADCP on the queue and ranks the poses it "
               "finds, with a viewer for each one.",
         runs=("$SCRATCH/adcp_runs", "$HOME/adcp_runs"),
         gives="docked poses",
         next_steps=(("hopemd", "Simulate these poses in HOPE-MD"),)),

    Tool("aptamer", "HOPE-Aptamer", "Design and fold an aptamer",
         "Design", "/scratch/group/sflab/HOPE-aptamer-pipeline", _aptamer, _aptamer_ready,
         blurb="Builds aptamer candidates against a target, folds them and scores the binding, "
               "leaving ranked poses with their energies.",
         needs_port=True,
         runs=("$SCRATCH/hope-aptamer-runs",),
         gives="aptamer poses",
         next_steps=(("hopemd", "Simulate a pose in HOPE-MD"),)),

    Tool("bindcraft", "BindCraft2", "Design a protein binder",
         "Design", "/scratch/group/sflab/BindCraft2", _bindcraft, _url_ready,
         blurb="Designs miniprotein binders against a target with AlphaFold 2 and ProteinMPNN, "
               "from a PDB id, a structure or a sequence.",
         runs=("/scratch/group/sflab/bindcraft_runs/$USER",),
         gives="designed binders",
         next_steps=(("hopemd", "Simulate a design in HOPE-MD"),)),

    Tool("pipelines", "HOPE-pipelines", "Design a peptide",
         "Design", "/scratch/group/sflab/HOPE-pipelines", _monitor, _monitor_ready,
         blurb="The lab's four peptide-design pipelines, dimer and trimer loops and the trimer and "
               "tetramer pipelines, set up from one workspace: the target, its hotspots, the "
               "stages, then Submit.",
         needs_port=True,
         # $SCRATCH/hope/runs is where the monitor writes when it is not told otherwise, which
         # is how this launcher starts it, and where my_workspace.sh points the notebooks
         runs=("$SCRATCH/hope/runs", "/scratch/group/sflab/hope_runs"),
         gives="designed peptides",
         # the workspace, where a run is set up: the pipelines' own launcher opens it first too,
         # since someone who has just signed in is setting a run up; it lists the runs as well
         page="/pick",
         next_steps=(("adcp", "Dock a design in ADCP"), ("hopemd", "Simulate a design in HOPE-MD"))),

    Tool("hopemd", "HOPE-MD", "Simulate a complex",
         "Simulation", "/scratch/group/sflab/HOPE-MD/MD", _hopemd, _url_ready,
         blurb="Molecular dynamics of a docked complex on five engines, from import to analysed "
               "trajectory: plots, MM-GBSA binding energies, a report and videos.",
         runs=("/scratch/group/sflab/hopemd_runs", "$SCRATCH/hopemd_runs"),
         takes="poses, designs and complexes",
         gives="trajectories and binding energies",
         next_steps=()),
)

BY_KEY = {tool.key: tool for tool in TOOLS}


def categories():
    """The categories, in the order the tools are listed."""
    seen = []
    for tool in TOOLS:
        if tool.category not in seen:
            seen.append(tool.category)
    return seen
