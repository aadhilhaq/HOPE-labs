"""The lines that start each tool, run for real against installs that are wrong on purpose.

By Aadhil Haq

A tool is started on the login node by one shell line from tools.py, and when it stops before it
is ready the launcher reads what it printed and says why (hub.Hub.why). These run those same lines
here in bash, against folders made wrong in one way at a time and a python that fails the way a
missing environment does, and check that the sentence a person would see names the real cause:
a folder that is not there, an activate.sh that is not there, or an environment that is not
where the launcher looks for it.

    python3 tests/test_start_lines.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from hope_labs import hub, tools  # noqa: E402

fails, ran = [], 0


def check(cond, why):
    global ran
    ran += 1
    if not cond:
        fails.append(why)


work = tempfile.mkdtemp(prefix="hl_start_")
fakebin = os.path.join(work, "bin")
os.makedirs(fakebin)
# What a login shell's own python does with a tool it cannot see: says so, and stops.
for name in ("python", "python3"):
    path = os.path.join(fakebin, name)
    with open(path, "w") as fh:
        fh.write('#!/bin/sh\nwhile [ "$1" != "-m" ] && [ $# -gt 0 ]; do shift; done\n'
                 'echo "ModuleNotFoundError: No module named \'${2%%.*}\'" >&2\nexit 1\n')
    os.chmod(path, 0o755)
ENV = dict(os.environ, PATH=fakebin + os.pathsep + os.environ.get("PATH", ""))
for var in ("ADCP_PYTHON", "HOPEMD_PYTHON", "PYTHONPATH"):
    ENV.pop(var, None)


def said(key, install, env=None, port=8123):
    """The sentence the launcher shows when this tool, installed here, fails to start."""
    tool = tools.BY_KEY[key]
    line = tool.command(install=install, runs="", port=port)
    got = subprocess.run(["bash", "-c", line], env=env or ENV, cwd=work,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
    return hub.Hub(None, installs={key: install}).why(tool, got.stdout), got.stdout


def folder(*parts, activate=None):
    path = os.path.join(work, *parts)
    os.makedirs(path, exist_ok=True)
    if activate is not None:
        with open(os.path.join(path, "activate.sh"), "w") as fh:
            fh.write(activate)
    return path


missing = os.path.join(work, "nowhere", "ADCP_docking")

# --- a folder that is not there is named as that, for every tool ---------------
for key in ("adcp", "hopemd", "aptamer", "pipelines", "bindcraft"):
    name = tools.BY_KEY[key].name
    text, out = said(key, os.path.join(work, "nowhere", key))
    check(text.startswith("there is no %s on the cluster" % name),
          "%s, install missing: said %r\n      it printed: %r" % (key, text, out[-300:]))

# --- an install with no activate.sh ---------------------------------------------
for key in ("adcp", "hopemd", "aptamer"):
    where = folder("no_activate", key)
    text, out = said(key, where)
    check("activate.sh is missing" in text and where in text,
          "%s, no activate.sh: said %r\n      it printed: %r" % (key, text, out[-300:]))

# ...but a Python named outright stands in for it, as it always has, and a failure
# after that is reported as what it is
where = folder("named_python", "adcp")
text, out = said("adcp", where, env=dict(ENV, ADCP_PYTHON=os.path.join(fakebin, "python3")))
check("NO-ACTIVATE" not in out and "was not found in its install" in text,
      "adcp with ADCP_PYTHON named: said %r\n      it printed: %r" % (text, out[-300:]))

# ...and with activate.sh present, a module missing is reported as a module missing
where = folder("with_activate", "hopemd", activate="# an environment that does not help\n")
text, out = said("hopemd", where)
check("NO-ACTIVATE" not in out and "was not found in its install" in text,
      "hopemd with an activate.sh: said %r\n      it printed: %r" % (text, out[-300:]))

# --- the monitor: its environment is envs/hope beside the install ----------------
where = folder("scratch_no_env", "HOPE-pipelines")
text, out = said("pipelines", where, port=8900)
check("no environment at envs/hope" in text,
      "pipelines with no envs/hope beside it: said %r\n      it printed: %r" % (text, out[-300:]))

root = os.path.join(work, "scratch_with_env")
where = folder("scratch_with_env", "HOPE-pipelines")
envbin = folder("scratch_with_env", "envs", "hope", "bin")
with open(os.path.join(envbin, "activate"), "w") as fh:
    fh.write('PATH="%s:$PATH"; export PATH\n' % fakebin)
text, out = said("pipelines", where, port=8900)
check("NO-ENV" not in out and "was not found in its install" in text,
      "pipelines with envs/hope beside it: said %r\n      it printed: %r" % (text, out[-300:]))
# and the root the monitor is given is that folder, not the lab's
line = tools.BY_KEY["pipelines"].command(install=where, port=8900)
got = subprocess.run(["bash", "-c", line.replace("exec python", 'echo "ROOT=$HL_ROOT"; exec python')],
                     env=ENV, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
check("ROOT=%s\n" % os.path.realpath(root) in got.stdout,
      "the monitor's root is not the folder holding the install: %r" % got.stdout[-300:])

# --- the tools travel too ----------------------------------------------------
# A tool installed on the cluster must be startable by a launcher built before it existed, or
# every new tool means everybody downloading the programme again. What travels is what a tool is
# and the line that starts it; how it says it is ready stays here, by name.
import copy as _copy                                                       # noqa: E402
import json as _json                                                       # noqa: E402

_doc = tools.catalogue()
_before = {t.key: (t.command(install="/inst", runs="/runs", port=8899),
                   t.command(install="/inst", runs="", port=8899))
           for t in tools.TOOLS if not t.flow_only}
check(_json.loads(_json.dumps(_doc)) == _doc, "a tools catalogue is plain JSON, which is how it travels")
check(tools.adopt(_copy.deepcopy(_doc)), "and a launcher adopts it")
_after = {t.key: (t.command(install="/inst", runs="/runs", port=8899),
                  t.command(install="/inst", runs="", port=8899))
          for t in tools.TOOLS if not t.flow_only}
check(_before == _after,
      "a start line changed in the round trip: %s"
      % [k for k in _before if _before.get(k) != _after.get(k)])

# a tool this launcher has never heard of, naming a reader it does have
_newer = _copy.deepcopy(_doc)
_newer["tools"].append({
    "key": "later", "name": "A Later Tool", "tagline": "installed after this launcher was built",
    "category": "Design", "install": "/scratch/group/sflab/Later", "ready": "url",
    "needs_port": False, "flow_only": False, "runs": ["$SCRATCH/later_runs"],
    "start": {"plain": "cd __HOPELABS_INSTALL__ && exec ./serve --port __HOPELABS_PORT__",
              "with_runs": "cd __HOPELABS_INSTALL__ && exec ./serve --port __HOPELABS_PORT__ "
                           "--runs __HOPELABS_RUNS__"}})
check(tools.adopt(_newer), "a catalogue with a tool this launcher has never seen is adopted")
_one = tools.BY_KEY.get("later")
check(_one is not None and not _one.flow_only, "and it is a tool that can be started")
check(_one.command(install="/scratch/group/sflab/Later", runs="/r", port=9001)
      == "cd /scratch/group/sflab/Later && exec ./serve --port 9001 --runs /r",
      "its start line is filled in: %s" % (_one and _one.command(install="/i", runs="/r", port=9001)))
check(_one.ready is tools.READERS["url"], "and it reads its ready line the way it asked to")

# one naming a reader this launcher does not have is listed, not started
_odd = _copy.deepcopy(_doc)
_odd["tools"][0] = dict(_odd["tools"][0], key="strange", ready="a_reader_from_the_future")
check(tools.adopt(_odd), "a tool naming an unknown reader does not spoil the catalogue")
check(tools.BY_KEY["strange"].flow_only,
      "and that tool is listed without a Launch that could only fail")

_future = _copy.deepcopy(_doc); _future["rules"] = tools.RULES + 5
check(tools.adopt(_future) == "", "a catalogue written for newer rules is left alone")
for _rubbish in ({}, {"tools": []}, "nonsense", None):
    check(tools.adopt(_rubbish) == "", "rubbish is refused: %r" % (_rubbish,))
check(tools.adopt(_doc), "and the built-in catalogue can be adopted back")

shutil.rmtree(work, ignore_errors=True)
if fails:
    print("FAIL %d of %d" % (len(fails), ran))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ok  %d checks: the start lines, and that they travel" % ran)
