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

shutil.rmtree(work, ignore_errors=True)
if fails:
    print("FAIL %d of %d" % (len(fails), ran))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ok  %d checks: every start line names what is missing" % ran)
