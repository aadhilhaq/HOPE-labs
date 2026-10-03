"""Slurm, as a flow uses it: one small job per card, each waiting on the one before it.

A card's step job is not the work. It is the few minutes that read what the card before it left,
write what this card needs, start the tool, and queue the next card's step job behind the tool it
just started. The work itself is whatever the tool submits, unchanged, under the person's own
account.

Nothing of the launcher is alive while this happens. That is the point of doing it this way
rather than watching from a login node: a flow that has been queued survives the laptop being
closed, the launcher being shut and the connection going away.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

#: Where a step job runs. It reads a few files and calls sbatch, so it wants a short queue and
#: very little of anything else. The partition is a setting because this is the one line that
#: differs between the clusters the lab uses.
STEP_PARTITION = os.environ.get("HOPEFLOW_PARTITION", "short")
STEP_TIME = "00:30:00"
STEP_CPUS = 2
STEP_MEM = "8G"

JOBID = re.compile(r"(\d+)")


def available():
    return shutil.which("sbatch") is not None


def submit(script, cwd, dependency="", name=""):
    """Queue a script and give back its job id.

    `dependency` is a whole Slurm dependency expression, not a bare id, because a card with two
    tracks arriving at it waits on both and the caller is the one that knows.
    """
    cmd = ["sbatch", "--parsable"]
    if dependency:
        cmd.append("--dependency=" + dependency)
    if name:
        cmd.append("--job-name=" + name)
    cmd.append(str(script))
    run = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        raise RuntimeError("sbatch refused %s: %s" % (os.path.basename(str(script)),
                                                      (run.stderr or run.stdout).strip()))
    found = JOBID.search(run.stdout or "")
    if not found:
        raise RuntimeError("sbatch took %s but printed no job id: %s"
                           % (os.path.basename(str(script)), (run.stdout or "").strip()))
    return found.group(1)


def step_script(flow_dir, node_id, python, package_root, account="", partition=""):
    """The job that runs one card: adapters in, tool out, the next card queued behind it.

    It carries the caches into scratch as every job of the lab's does. A step job that writes
    into a home folder would be a small thing each time and a filled quota by the end of a week.
    """
    where = os.path.join(str(flow_dir), "logs")
    lines = [
        "#!/bin/bash",
        "#SBATCH --job-name=flow-%s" % node_id,
        "#SBATCH --partition=%s" % (partition or STEP_PARTITION),
        "#SBATCH --time=%s" % STEP_TIME,
        "#SBATCH --ntasks=1",
        "#SBATCH --cpus-per-task=%d" % STEP_CPUS,
        "#SBATCH --mem=%s" % STEP_MEM,
        "#SBATCH --output=%s/%s-%%j.out" % (where, node_id),
    ]
    if account:
        lines.append("#SBATCH --account=%s" % account)
    lines += [
        "",
        "# Caches into scratch, never a home folder.",
        'export XDG_CACHE_HOME="${SCRATCH:-/tmp}/.cache/hopeflow"',
        'export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"',
        'export CUDA_CACHE_PATH="$XDG_CACHE_HOME/nv"',
        'mkdir -p "$XDG_CACHE_HOME"',
        "",
        "set -u",
        'PYTHONPATH=%s exec %s -m hope_flow.cli step %s %s'
        % (_q(package_root), _q(python), _q(str(flow_dir)), _q(node_id)),
        "",
    ]
    return "\n".join(lines)


def _q(text):
    """A shell word, quoted once and properly."""
    text = str(text)
    if re.match(r"^[A-Za-z0-9_@%+=:,./-]+$", text):
        return text
    return "'" + text.replace("'", "'\\''") + "'"


def states(job_ids):
    """{job id: what Slurm says}, for jobs that may already have left the queue.

    squeue knows the ones still about; sacct knows the ones that have finished. Asking both and
    preferring squeue is what every tool in the lab does, because sacct lags a little behind a
    job that has only just ended.
    """
    out = {}
    ids = [str(j) for j in job_ids if str(j).strip()]
    if not ids:
        return out
    joined = ",".join(ids)
    for cmd, split in (
            (["sacct", "-n", "-X", "-P", "-o", "JobID,State", "-j", joined], "|"),
            (["squeue", "-h", "-o", "%i %T", "-j", joined], " ")):
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if run.returncode != 0:
            continue
        for line in (run.stdout or "").splitlines():
            bits = line.strip().split(split)
            if len(bits) >= 2 and bits[0].strip():
                out[bits[0].strip().split(".")[0]] = bits[1].strip().split()[0]
    return out


def all_done(job_ids):
    """(finished, failed): whether every job has ended, and the ones that did not end well."""
    seen = states(job_ids)
    bad, pending = [], False
    for jid in (str(j) for j in job_ids):
        state = seen.get(jid, "")
        if not state:
            pending = True                      # not in either answer yet: too soon to say
        elif state.startswith(("COMPLETING", "PENDING", "RUNNING", "REQUEUED", "RESIZING",
                               "SUSPENDED", "CONFIGURING")):
            pending = True
        elif not state.startswith("COMPLETED"):
            bad.append((jid, state))
    return (not pending, bad)
