"""Starting one card's tool, the way that tool's own page starts it.

Every driver here goes through the tool's own command line or its own submitting function. None
reimplements what a tool does, and none writes a job script for a tool: a run queued by a flow
and the same run queued from the tool's page are meant to be the same run, and the only way to be
sure of that is to go through the same door.

Each tool has a Python of its own, so a driver starts a shell, enters that tool's environment the
way the launcher's start lines do, and reads back what it printed. Importing them into one
process is not open to us: they do not agree on a version of Python, let alone on anything else.

A driver is given the card as it was drawn, what arrived at it, and the flow's folder. It returns
(where the run is, [the job ids the next card must wait for]).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.request

#: Where the lab's copies are, as the launcher's catalogue has them. One setting moves all five.
LAB_ROOT = os.environ.get("HOPEFLOW_LAB_ROOT", "/scratch/group/sflab")
INSTALLS = {
    "pipelines": LAB_ROOT + "/HOPE-pipelines",
    "bindcraft": LAB_ROOT + "/BindCraft2",
    "adcp": LAB_ROOT + "/ADCP_docking",
    "aptamer": LAB_ROOT + "/HOPE-aptamer-pipeline",
    "hopemd": LAB_ROOT + "/HOPE-MD/MD",
    "rfdiffusion": LAB_ROOT + "/ML_programs/RFdiffusion",
    "boltzgen": LAB_ROOT + "/envs/boltzgen",
}

#: The two design tools the lab runs that have no launcher of their own: no page, no submitting
#: script, nothing that already knows how to queue them. Every other driver here goes through a
#: tool's own door, as the docstring says; for these two there is no door, so the flow writes
#: their job itself. That is the exception, and it is written down rather than left to be noticed.
SE3NV = LAB_ROOT + "/envs/SE3nv"                      # RFdiffusion's environment, and ProteinMPNN runs in it too
DL_BINDER_DESIGN = LAB_ROOT + "/ML_programs/dl_binder_design"
BOLTZGEN_CACHE = LAB_ROOT + "/envs/boltzgen_cache"    # the weights, fetched on a login node

#: Where a tool's own run folders go, when the card does not say.
RUNS = {
    "pipelines": os.path.join(os.environ.get("SCRATCH", "/tmp"), "hope", "runs"),
    "bindcraft": LAB_ROOT + "/bindcraft_runs/" + os.environ.get("USER", "unknown"),
    "adcp": os.path.join(os.environ.get("SCRATCH", "/tmp"), "adcp_runs"),
    "aptamer": os.path.join(os.environ.get("SCRATCH", "/tmp"), "hope-aptamer-runs"),
    "hopemd": os.path.join(os.environ.get("SCRATCH", "/tmp"), "hopemd_runs"),
    "rfdiffusion": os.path.join(os.environ.get("SCRATCH", "/tmp"), "rfdiffusion_runs"),
    "boltzgen": os.path.join(os.environ.get("SCRATCH", "/tmp"), "boltzgen_runs"),
}

RCSB = "https://files.rcsb.org/download/%s.pdb"

#: What a Slurm job id looks like coming back from any of them.
JOBID = re.compile(r"\b(\d{4,})\b")


class NotWired(RuntimeError):
    """A card the runner cannot start. Raised with the reason a person can act on."""


def submit(node, flow, carried, flow_dir, record, say=print):
    fn = BY_CARD.get(node.card)
    if fn is None:
        raise NotWired("%s cannot be started by a flow yet" % node.card)
    return fn(node, flow, carried, flow_dir, record, say)


# --- running a tool in its own environment -----------------------------------------------------

def _shell(line, where, say=print, minutes=30):
    """Run one line in a login shell, in a tool's own folder, and give back what it printed.

    The caches are pushed into scratch first. A tool started from a flow must leave a home folder
    exactly as it found it, and several of these write one by default.
    """
    cache = os.path.join(os.environ.get("SCRATCH", "/tmp"), ".cache", "hopeflow")
    env = dict(os.environ, XDG_CACHE_HOME=cache, MPLCONFIGDIR=os.path.join(cache, "matplotlib"),
               CUDA_CACHE_PATH=os.path.join(cache, "nv"))
    os.makedirs(cache, exist_ok=True)
    run = subprocess.run(["bash", "-lc", line], cwd=where, env=env, capture_output=True,
                         text=True, timeout=minutes * 60)
    out = (run.stdout or "") + (run.stderr or "")
    for tail in out.strip().splitlines()[-6:]:
        say("   | " + tail[:200])
    if run.returncode != 0:
        raise NotWired("the tool refused to start (status %d): %s"
                       % (run.returncode, out.strip()[-500:] or "it said nothing"))
    return out


def _unique(root, name):
    """A run folder of this name that does not exist yet.

    Two branches of one flow can derive the same name - the same target, the same engine - and
    every one of these tools refuses a folder that already holds a run. Settling it here means a
    flow does not fail halfway for a reason that has nothing to do with the science.
    """
    where = os.path.join(root, name)
    n = 2
    while os.path.exists(where):
        where = os.path.join(root, "%s_%d" % (name, n))
        n += 1
    return where


def _target(carried):
    got = (carried.get("target") or [None])[0]
    if not got:
        raise NotWired("no target reached this card")
    return got


def _run_root(node, card):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(
        node.settings.get("runs") or RUNS[card])))


# --- the target ---------------------------------------------------------------------------------
# Not a tool: the one card that is the person's own input. Its structure is fetched once, into the
# flow's folder, so every track below it reads the same file rather than each fetching its own and
# hoping the RCSB gave them all the same thing on the same day.

def _target_card(node, flow, carried, flow_dir, record, say=print):
    s = node.settings
    where = os.path.join(flow_dir, "inputs")
    os.makedirs(where, exist_ok=True)
    source = (s.get("source") or "rcsb").strip()

    if source == "file":
        src = os.path.abspath(os.path.expandvars(os.path.expanduser(s.get("path") or "")))
        if not os.path.isfile(src):
            raise NotWired("the target file is not there: %s" % src)
        got = os.path.join(where, "target" + (os.path.splitext(src)[1] or ".pdb"))
        shutil.copy2(src, got)
        say("the target was copied from %s" % src)
    else:
        code = (s.get("pdb_id") or "").strip().upper()
        if not re.match(r"^[0-9A-Z]{4}$", code):
            raise NotWired("%r is not a four-character PDB id" % code)
        got = os.path.join(where, "target.pdb")
        try:
            with urllib.request.urlopen(RCSB % code, timeout=120) as answer, \
                    open(got, "wb") as out:
                shutil.copyfileobj(answer, out)
        except Exception as why:                                # noqa: BLE001
            raise NotWired("the RCSB would not give %s: %s" % (code, why))
        say("%s was fetched into the flow" % code)

    if os.path.getsize(got) < 200:
        raise NotWired("the target structure came back empty")
    record.set(node.id, path=got)
    return where, []


# --- the design pipelines -------------------------------------------------------------------------

def _pipelines(node, flow, carried, flow_dir, record, say=print):
    """The peptide-design pipelines, through their own submitting function.

    Their settings are the web form's field names, and the function takes them as a mapping, so
    this hands over a small JSON document rather than building a command line of thirty flags.
    """
    target = _target(carried)
    install = INSTALLS["pipelines"]
    root = os.path.join(install, "pipelines")
    s = node.settings
    name = "%s_%s" % (flow.name, node.id)
    where = _unique(_run_root(node, "pipelines"), name)

    asked = {"job_name": os.path.basename(where),
             "run_dir": os.path.dirname(where),
             "pipeline": s.get("pipeline") or "dimer loop",
             "receptor": target["path"],
             "chain": target.get("chains") or "A",
             "hotspots": target.get("hotspots") or ""}
    # Only what the card was given: a key left out falls through to the pipeline's own config
    # template, which is where the lab's considered defaults live and where they should stay.
    # A zero is "keep yours" for the sizes, so it is not passed either.
    keep_own = ("library_size", "cpus", "exhaustiveness", "adcp_steps", "max_construct_length")
    for key in ("rounds", "cpus", "mem", "nodes", "partition", "account", "library_size",
                "n_constructs", "min_construct_length", "max_construct_length", "adcp",
                "mmgbsa", "colabfold", "scout", "hopepe", "pose_viewer", "ph", "protein_prep",
                "exhaustiveness", "n_mmgbsa", "adcp_replicas", "adcp_steps", "rerank_engine",
                "anchor_linkers", "linker_sweep", "sweep_families"):
        value = s.get(key)
        if value in (None, ""):
            continue
        if key in keep_own and str(value) in ("0", "0.0"):
            continue
        asked[key] = value

    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helpers", "pipelines.py")
    line = ('if [ -f %(env)s ]; then . %(env)s; fi; '
            'PYTHONPATH=%(install)s python %(helper)s %(root)s'
            % {"env": shlex.quote(os.path.join(install, "..", "envs", "hope", "bin", "activate")),
               "install": shlex.quote(install), "helper": shlex.quote(helper),
               "root": shlex.quote(root)})
    out = _shell(line + " <<'ASKED'\n" + json.dumps(asked) + "\nASKED", install, say)
    got = _last_json(out)
    if got.get("problem"):
        raise NotWired("the design run was refused: %s" % got["problem"])
    jid = str(got.get("jobid") or "")
    if not jid.isdigit():
        raise NotWired("the design run did not queue a job (it said %r)" % jid)
    return got.get("rundir") or where, [jid]


# --- the two design tools with no launcher of their own -------------------------------------
# Everything else here hands a tool its own command line and lets that tool queue itself. These
# two have nothing to hand to, so this writes the job. Both end by writing designs.json, which is
# the one thing the next card reads; the shape of it is documented in adapters.py.

JOB = """#!/bin/bash
#SBATCH --job-name={name}
#SBATCH --partition={partition}
#SBATCH --gres=gpu:{gpu}:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}G
#SBATCH --time={walltime}
#SBATCH --output={out}/slurm_%j.out
{account}set -uo pipefail
umask 002
OUT={out}
# Nothing may reach $HOME: it holds 10 000 files and these write caches by the thousand.
export XDG_CACHE_HOME="$OUT/cache" MPLCONFIGDIR="$OUT/cache/mpl" CUDA_CACHE_PATH="$OUT/cache/nv"
export TMPDIR="$OUT/cache/tmp" HF_HOME={hf_home} TORCH_HOME="$OUT/cache/torch"
mkdir -p "$TMPDIR" "$MPLCONFIGDIR" "$CUDA_CACHE_PATH"
unset PYTHONPATH PYTHONHOME
{body}
status=$?
echo "flow: {name} finished with status $status"
exit $status
"""


def _queue(where, script, say):
    """Write a job script into the run folder, queue it, and give back its id."""
    path = os.path.join(where, "job.sbatch")
    with open(path, "w") as fh:
        fh.write(script)
    done = subprocess.run(["sbatch", "--parsable", path], cwd=where, capture_output=True, text=True)
    out = ((done.stdout or "") + (done.stderr or "")).strip()
    if done.returncode != 0:
        raise NotWired("sbatch refused the job: %s" % (out[-400:] or "it said nothing"))
    found = JOBID.search(done.stdout or "")
    if not found:
        raise NotWired("sbatch queued nothing it could name: %r" % out[-200:])
    say("   | queued job %s" % found.group(1))
    return found.group(1)


def _design_job(node, flow, carried, card, body, say, cpus=8, mem=48, hf_home='"$OUT/cache/hf"'):
    """The parts of a design job that do not differ between the two tools."""
    s = node.settings
    where = _unique(_run_root(node, card), "%s_%s" % (flow.name, node.id))
    os.makedirs(os.path.join(where, "cache"), exist_ok=True)
    gpu = str(s.get("gpu") or "a100")
    if gpu == "auto":
        gpu = "a100"
    script = JOB.format(
        name="%s_%s" % (card, node.id), partition=str(s.get("partition") or "gpu"),
        gpu=gpu, cpus=cpus, mem=mem, walltime=str(s.get("walltime") or "12:00:00"),
        out=where, hf_home=hf_home,
        account=("#SBATCH --account=%s\n" % s["account"]) if s.get("account") else "",
        body=body(where))
    return where, [_queue(where, script, say)]


def _rfdiffusion(node, flow, carried, flow_dir, record, say=print):
    """Binder backbones from RFdiffusion, sequences from ProteinMPNN, in one job.

    Both halves run in RFdiffusion's own environment: ProteinMPNN needs only torch and numpy, and
    SE3nv has them. The environment the lab built for it separately is missing its standard
    library and has never run.
    """
    target = _target(carried)
    s = node.settings
    if not os.path.isdir(DL_BINDER_DESIGN):
        raise NotWired("ProteinMPNN is not unpacked at %s, so a design would have no sequence"
                       % DL_BINDER_DESIGN)
    plan = {
        "target": target["path"],
        "chains": target.get("chains") or "A",
        "hotspots": target.get("hotspots") or "",
        "binder_min": int(target.get("binder_min") or 70),
        "binder_max": int(target.get("binder_max") or 100),
        "designs": int(s.get("designs") or 10),
        "seqs_per_backbone": int(s.get("seqs_per_backbone") or 8),
        "noise_scale": float(s.get("noise_scale") or 0),
        "diffuser_T": int(s.get("diffuser_T") or 0),
        "ckpt": str(s.get("ckpt") or ""),
        "rfdiffusion": INSTALLS["rfdiffusion"],
        "dl_binder_design": DL_BINDER_DESIGN,
        "se3nv_python": os.path.join(SE3NV, "bin", "python"),
    }
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helpers",
                          "rfdiffusion_design.py")

    def body(where):
        with open(os.path.join(where, "plan.json"), "w") as fh:
            json.dump(dict(plan, out=where), fh, indent=1)
        return ('%s %s %s' % (shlex.quote(plan["se3nv_python"]), shlex.quote(helper),
                              shlex.quote(os.path.join(where, "plan.json"))))

    return _design_job(node, flow, carried, "rfdiffusion", body, say)


def _boltzgen(node, flow, carried, flow_dir, record, say=print):
    """Binders generated by BoltzGen, folded and ranked by its own pipeline.

    The weights are 10 GB and live in the group space, fetched on a login node: a compute node has
    no internet, so the cache is pointed at that copy and the run is told not to reach for more.
    """
    target = _target(carried)
    s = node.settings
    if not os.path.isdir(BOLTZGEN_CACHE):
        raise NotWired("BoltzGen's weights are not in %s; they are fetched on a login node"
                       % BOLTZGEN_CACHE)
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helpers",
                          "boltzgen_design.py")
    plan = {
        "target": target["path"],
        "chains": target.get("chains") or "A",
        "hotspots": target.get("hotspots") or "",
        "binder_min": int(target.get("binder_min") or 70),
        "binder_max": int(target.get("binder_max") or 100),
        "designs": int(s.get("designs") or 10),
        "protocol": str(s.get("protocol") or "protein-anything"),
        "cyclic": bool(s.get("cyclic")),
        "sampling_steps": int(s.get("sampling_steps") or 0),
        "fold": s.get("fold") is not False,
        "boltzgen": os.path.join(INSTALLS["boltzgen"], "bin", "boltzgen"),
        "cache": BOLTZGEN_CACHE,
    }

    def body(where):
        with open(os.path.join(where, "plan.json"), "w") as fh:
            json.dump(dict(plan, out=where), fh, indent=1)
        return ("export HF_HUB_OFFLINE=1\n%s %s %s"
                % (shlex.quote(os.path.join(INSTALLS["boltzgen"], "bin", "python")),
                   shlex.quote(helper), shlex.quote(os.path.join(where, "plan.json"))))

    # BoltzGen wants 40 GB of card: upstream reports running out of memory on a modest target at
    # 16 GB, and again in its analysis step at a hundred designs.
    return _design_job(node, flow, carried, "boltzgen", body, say, cpus=8, mem=64,
                       hf_home=shlex.quote(BOLTZGEN_CACHE))


def _last_json(text):
    """The last JSON object printed, so a tool's chatter before it does not matter."""
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    raise NotWired("the tool printed nothing this could read:\n%s" % (text or "")[-400:])


# --- the binder design ---------------------------------------------------------------------------

def _bindcraft(node, flow, carried, flow_dir, record, say=print):
    """The binder design, through its own wrapper, which knows its environment and its cards."""
    target = _target(carried)
    s = node.settings
    where = _unique(_run_root(node, "bindcraft"), "%s_%s" % (flow.name, node.id))
    args = ["--receptor", target["path"], "--chains", target.get("chains") or "A",
            "--out", where,
            "--min-length", str(int(target.get("binder_min") or 70)),
            "--max-length", str(int(target.get("binder_max") or 100)),
            "--designs", str(int(s.get("designs") or 10))]
    if target.get("hotspots"):
        args += ["--hotspots", target["hotspots"]]
    if s.get("coldspots"):
        args += ["--coldspots", str(s["coldspots"])]
    if s.get("forced"):
        args.append("--forced")
    for flag, key in (("--gpu", "gpu"), ("--gpus", "gpus"), ("--walltime", "walltime"),
                      ("--account", "account")):
        if s.get(key) not in (None, ""):
            args += [flag, str(s[key])]
    line = "./sflab/bc2-submit " + " ".join(shlex.quote(a) for a in args)
    _shell(line, INSTALLS["bindcraft"], say)
    # The wrapper writes what it did beside the run, which is steadier than reading its output.
    record_file = os.path.join(where, "submission.json")
    try:
        with open(record_file, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError) as why:
        raise NotWired("the campaign left no submission.json in %s (%s)" % (where, why))
    jid = str(got.get("job_id") or "")
    if not jid.isdigit():
        raise NotWired("the campaign queued no job (its record says job_id=%r)" % got.get("job_id"))
    return where, [jid]


# --- the docking ----------------------------------------------------------------------------------

def _adcp(node, flow, carried, flow_dir, record, say=print):
    """The docking console: a run folder made, then submitted, as its own command line does it.

    It queues three jobs of its own and chains them; the last of them is what the next card waits
    for, and its id is in the run folder once the run has been submitted.
    """
    target = _target(carried)
    peptides = [g for g in carried.get("sequences", []) if g.get("path")]
    if not peptides:
        raise NotWired("no peptides reached the docking")
    s = node.settings
    where = _unique(_run_root(node, "adcp"), "%s_%s" % (flow.name, node.id))

    combined = _one_peptides_file(flow_dir, node.id, peptides)
    args = ["new", where, "-r", target["path"], "-f", combined]
    if target.get("hotspots"):
        args += ["-s", _site(target)]
    for flag, key in (("--poses", "poses"), ("--replicas", "replicas"), ("--steps", "steps"),
                      ("--partition", "partition"), ("--account", "account"),
                      ("--cpus", "cpus"), ("--time", "walltime")):
        value = s.get(key)
        if value in (None, "") or (key == "steps" and str(value) in ("0", "0.0")):
            continue
        args += [flag, str(value)]
    if s.get("mmgbsa", True):
        args.append("--mmgbsa")

    enter = ('if [ -f ./activate.sh ]; then . ./activate.sh; fi; PY="${ADCP_PYTHON:-python3}"; '
             'PYTHONPATH=%s ' % shlex.quote(INSTALLS["adcp"]))
    _shell(enter + '"$PY" -m adcp_dock.cli ' + " ".join(shlex.quote(a) for a in args),
           INSTALLS["adcp"], say)
    out = _shell(enter + '"$PY" -m adcp_dock.cli run ' + shlex.quote(where),
                 INSTALLS["adcp"], say)

    jobs = _adcp_jobs(where) or JOBID.findall(out)
    if not jobs:
        raise NotWired("the docking queued nothing this could find in %s" % where)
    # Its own last job is what everything after it waits for: the one that gathers the results.
    return where, [jobs[-1]]


def _one_peptides_file(flow_dir, nid, carried_sequences):
    """Several tracks of peptides, as the one file the docking takes."""
    if len(carried_sequences) == 1:
        return carried_sequences[0]["path"]
    where = os.path.join(flow_dir, "inputs", "%s_peptides_all.txt" % nid)
    seen = set()
    with open(where, "w", encoding="utf-8") as out:
        for got in carried_sequences:
            with open(got["path"], encoding="utf-8") as fh:
                for line in fh:
                    seq = line.split(":", 1)[-1].strip().upper()
                    if seq and seq not in seen:
                        seen.add(seq)
                        out.write(line if line.endswith("\n") else line + "\n")
    return where


def _site(target):
    """The residues the box should cover, in the form the docking takes: A:41,A:45.

    The flow writes hotspots the way the design tools want them - bare numbers, or a chain letter
    stuck to the front. The docking wants a colon between the two, so this puts one in and gives
    a residue with no chain the target's first.
    """
    chain = (target.get("chains") or "A").split(",")[0].strip() or "A"
    out = []
    for part in re.split(r"[,\s]+", target.get("hotspots") or ""):
        part = part.strip()
        if not part:
            continue
        found = re.match(r"^([A-Za-z]?):?(\d+)(?:-(\d+))?$", part)
        if not found:
            continue
        where, first, last = found.group(1) or chain, int(found.group(2)), found.group(3)
        for n in range(first, int(last) + 1 if last else first + 1):
            out.append("%s:%d" % (where, n))
    return ",".join(out)


def _adcp_jobs(where):
    """The job ids the docking wrote down for this run, oldest first."""
    for name in ("job.json", "jobs.json"):
        path = os.path.join(where, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            continue
        ids = got.get("slurm") or got.get("jobs") or {}
        if isinstance(ids, dict):
            found = [str(v) for k, v in ids.items() if str(v).isdigit()]
            if found:
                return found
    return []


# --- the simulation --------------------------------------------------------------------------------

def _hopemd(node, flow, carried, flow_dir, record, say=print):
    """The simulation, one run per pose or per design, through its own submitting command line."""
    arriving = carried.get("structures") or []
    if not arriving:
        raise NotWired("nothing reached the simulation")
    s = node.settings
    root = _run_root(node, "hopemd")
    os.makedirs(root, exist_ok=True)
    rundirs, jobs = [], []

    top = _top_n(s)
    for got in arriving:
        if got["kind"] == "poses":
            # What arrives is already in the order the tool that made it ranked, so the best of
            # it is the front of it.
            picks = (got["selections"] or [])[:top]
            specs = [(_spec(s, {"kind": got["source_kind"], "path": got["path"]}), picks, "")]
        else:
            specs = [(_spec(s, {"kind": "complex", "path": d["path"]},
                            d["receptor_chains"], d["partner_chains"]),
                      None, "%s_%s" % (flow.name, d["name"]))
                     for d in (got.get("designs") or [])[:top]]
        for spec, picks, name in specs:
            where, ids = _hopemd_one(flow_dir, node.id, spec, picks, name, root, say)
            rundirs.extend(where)
            jobs.extend(ids)
    if not jobs:
        raise NotWired("the simulation queued nothing")
    # Neither the report nor the videos are made by a run on its own: they are asked for
    # afterwards, from the Runs screen, which for twenty runs is twenty rounds of pressing
    # buttons. A flow that ran overnight should leave something to read in the morning, so it
    # queues one small job per run to do it, behind the run it belongs to.
    if s.get("report", True) or s.get("videos"):
        jobs.extend(_finish_runs(rundirs, jobs, s, flow_dir, node.id, say))
    return (rundirs[0] if len(rundirs) == 1 else root), jobs


def _finish_runs(rundirs, after, s, flow_dir, node_id, say=print):
    """Queue one job per finished run to write its report, and its videos when asked for.

    It waits on everything the simulation queued rather than on that run's own jobs: a flow has
    no business picking apart another tool's graph, and a few minutes of a short queue after the
    last run is cheaper than being clever about it.
    """
    want_report = bool(s.get("report", True))
    want_videos = bool(s.get("videos"))
    reps = max(1, int(_number(s.get("replicates"), 3)))
    where = os.path.join(flow_dir, "logs")
    os.makedirs(where, exist_ok=True)
    script = os.path.join(where, "finish-%s.sbatch" % node_id)
    lines = ["#!/bin/bash",
             "#SBATCH --job-name=flow-%s-finish" % node_id,
             "#SBATCH --partition=%s" % (s.get("partition") or "short"),
             "#SBATCH --time=01:00:00", "#SBATCH --ntasks=1", "#SBATCH --cpus-per-task=2",
             "#SBATCH --mem=8G",
             "#SBATCH --output=%s/%s-finish-%%j.out" % (where, node_id)]
    if s.get("account"):
        lines.append("#SBATCH --account=%s" % s["account"])
    lines += ['export XDG_CACHE_HOME="${SCRATCH:-/tmp}/.cache/hopeflow"',
              'export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"',
              'mkdir -p "$XDG_CACHE_HOME"',
              "cd %s || exit 1" % _q(INSTALLS["hopemd"]),
              'if [ -f ./activate.sh ]; then . ./activate.sh; fi',
              'PY="${HOPEMD_PYTHON:-python3}"',
              "export PYTHONPATH=%s" % _q(INSTALLS["hopemd"]),
              ""]
    for rundir in rundirs:
        if want_report:
            # Each on its own line and never fatal: one run whose report will not write must not
            # take the reports of the nineteen beside it with it.
            lines.append('"$PY" -m hopemd.export.report %s || echo "no report for %s"'
                         % (_q(rundir), os.path.basename(rundir)))
        if want_videos:
            for rep_n in range(1, reps + 1):
                lines.append('"$PY" -m hopemd.export.video %s %d || echo "no video %d for %s"'
                             % (_q(rundir), rep_n, rep_n, os.path.basename(rundir)))
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(script, 0o755)
    try:
        from . import queue as q
        jid = q.submit(script, flow_dir,
                       dependency="afterok:" + ":".join(str(j) for j in after),
                       name="flow-%s-finish" % node_id)
    except RuntimeError as why:
        # Not worth failing the simulation for: the runs are queued and the report can be asked
        # for from the page as it always could.
        say("the finishing job was refused (%s); the runs are queued regardless" % why)
        return []
    say("%s will write %s when the runs finish"
        % (jid, " and ".join(x for x in (("reports" if want_report else ""),
                                         ("videos" if want_videos else "")) if x)))
    return [jid]


def _top_n(s):
    """How many of what arrives to simulate. Everything arriving is already ranked."""
    try:
        return max(1, int(s.get("top_n") or 10))
    except (TypeError, ValueError):
        return 10


def _spec(s, source, receptor_chains=None, partner_chains=None):
    """The card's settings as the simulation's own spec.

    The engine belongs to the force field rather than to the compute settings - putting it in the
    wrong place is silently ignored and the run comes out on the default engine - and the number
    of frames is written as the interval between them, which is what the spec holds.
    """
    system = {"source": source}
    if receptor_chains:
        system["receptor_chains"] = receptor_chains
    if partner_chains:
        system["partner_chains"] = partner_chains

    ns = _number(s.get("length_ns"), 100.0)
    protocol = {"length_ns": ns, "replicates": int(_number(s.get("replicates"), 3))}
    frames = _number(s.get("frames"), 0)
    if frames and frames > 0:
        # The spec keeps how often a frame is written, not how many there are; a person thinks in
        # frames. One is the other over the length of the run.
        protocol["save_ps"] = max(0.1, round(ns * 1000.0 / frames, 3))

    for key in ("temperature_K", "pressure_bar", "timestep_fs", "equil_ps", "heat_ps",
                "minimise_steps", "seed"):
        if s.get(key) not in (None, ""):
            protocol[key] = _number(s[key], 0)
    forcefield = {"engine": s.get("engine") or "amber"}
    for key in ("water", "protein"):
        if s.get(key):
            forcefield[key] = s[key]
    compute = {}
    for key in ("walltime", "partition", "account"):
        if s.get(key):
            compute[key] = s[key]

    spec = {"system": system, "forcefield": forcefield, "protocol": protocol,
            "analysis": {"mmgbsa": bool(s.get("mmgbsa", True))}}
    if compute:
        spec["compute"] = compute
    return spec


def _number(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _hopemd_one(flow_dir, nid, spec, picks, name, root, say):
    """One call of the simulation's command line, for one source. Returns (run folders, job ids)."""
    where = os.path.join(flow_dir, "inputs")
    os.makedirs(where, exist_ok=True)
    spec_file = os.path.join(where, "%s_spec_%d.json" % (nid, abs(hash(json.dumps(spec, sort_keys=True))) % 10 ** 6))
    with open(spec_file, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
    args = ["--runs", root, "--quiet"]
    if name:
        args += ["--name", name]
    if picks:
        picks_file = spec_file.replace("_spec_", "_picks_")
        with open(picks_file, "w", encoding="utf-8") as fh:
            json.dump(picks, fh)
        args += ["--selections", picks_file]
    line = ('if [ -f ./activate.sh ]; then . ./activate.sh; fi; PY="${HOPEMD_PYTHON:-python3}"; '
            'PYTHONPATH=%s "$PY" -m hopemd.submit %s %s'
            % (shlex.quote(INSTALLS["hopemd"]), shlex.quote(spec_file),
               " ".join(shlex.quote(a) for a in args)))
    out = _shell(line, INSTALLS["hopemd"], say, minutes=60)
    got = _last_json(_braces(out))
    runs = got.get("runs") or {}
    ids = [str(j) for one in runs.values() for j in one.values() if str(j).isdigit()]
    for why in (got.get("refused") or {}).items():
        say("   refused %s: %s" % why)
    return list(runs), ids


def _braces(text):
    """The last whole {...} in a lump of output, which may run over many lines."""
    start = (text or "").rfind("{\n")
    if start < 0:
        return text or ""
    return " ".join((text[start:]).split())


BY_CARD = {
    "target": _target_card,
    "pipelines": _pipelines,
    "bindcraft": _bindcraft,
    "rfdiffusion": _rfdiffusion,
    "boltzgen": _boltzgen,
    "adcp": _adcp,
    "hopemd": _hopemd,
}
