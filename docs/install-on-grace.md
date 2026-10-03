# Installing the five tools in your own scratch on Grace

HOPE Labs opens five tools that already run on Grace. This page is for a researcher with a
Grace account (TAMU HPRC) who is not in the lab's group allocation, or who wants a copy of
their own. Your personal scratch is `/scratch/user/<NetID>`. Replace `<NetID>` with yours
everywhere below.

Nothing is installed on Grace for HOPE Labs itself. It signs in over SSH, starts a tool on a login
node and forwards a port to it. What you install here is the five tools.

## Before you start

**Ask for access.** Three of the five are not open. `LICENSE` in HOPE-aptamer-pipeline and in
HOPE-pipelines both say the software is not open source and carries no licence to use outside the
HOPE Lab, and HOPE-MD's README says its repository is private while HOPE-MD is in testing. ADCP
docking carries a BSD 3-Clause licence. BindCraft2 is by the Pacesa lab, and the page HOPE Labs
starts is the lab's own cluster side, which its README asks you not to offer to people outside the
group. Write to the lab's principal investigator first.

The clone lines below are each repository's own address, in the form its own documentation
gives it. For a private repository either form wants your own GitHub access: an SSH key on the
login node, or a token for the HTTPS lines.

**Check your file count, not your disk space.** Grace caps the number of files as well as the
bytes.

```bash
showquota
```

Read the File Usage column. HOPE-Aptamer's `GRACE.md` measured personal scratch on Grace at 250,000
files with 35,632 free, against an environment of roughly 60,000 files, and says plainly that it does
not fit there. HOPE-pipelines' own environment is about 67,000 files. So five full environments will
not fit in one personal scratch allowance as those pages measured it. Clear space with `conda clean
-a -y`, take the smaller environment where a tool offers one, or share one between tools as shown
under HOPE-MD.

**Nothing in your home directory.** Home on Grace is 10 GB and 10,000 files. HOPE-pipelines' and
HOPE-MD's installers refuse a prefix under `$HOME`; the other two leave it to you, so always give a
prefix.

**Install from a login node.** Each installer downloads something, and Grace's compute nodes have
no outbound network.

**Use one folder for all five.** HOPE Labs looks for the tools under one root, in the layout the
lab uses:

| Tool key | Folder under your root |
|---|---|
| `adcp` | `ADCP_docking` |
| `aptamer` | `HOPE-aptamer-pipeline` |
| `bindcraft` | `BindCraft2` |
| `pipelines` | `HOPE-pipelines` |
| `hopemd` | `HOPE-MD/MD` |

Give `/scratch/user/<NetID>` to each installer as its prefix and you get exactly that layout.

## ADCP docking

Clone it where it will stay. `install.sh` writes an `activate.sh` beside the checkout and records
that path inside it.

```bash
module load Anaconda3
git clone https://github.com/aadhilhaq/ADCP_docking.git /scratch/user/<NetID>/ADCP_docking
cd /scratch/user/<NetID>/ADCP_docking
./install.sh /scratch/user/<NetID>
```

The prefix is not optional on a cluster. The script puts the conda environment in
`<prefix>/envs/adcp`, its package cache in `<prefix>/conda_shared/pkgs` and ADFRsuite in
`<prefix>/tools/docking`. It says the slow part is 15 to 40 minutes, almost all of it AmberTools,
which is about 60,000 files by itself. ADFRsuite is roughly a 100 MB download from Scripps,
checked against a pinned checksum. `./install.sh --check` reports what it finds and changes
nothing. Then:

```bash
source /scratch/user/<NetID>/ADCP_docking/activate.sh
adcp-dock check
```

Some parts of ADFRsuite are free for academic use only; `THIRD_PARTY_NOTICES.md` lists the terms.

## HOPE-Aptamer

The repository name begins with a hyphen, which is part of the name.

```bash
module load Anaconda3
git clone git@github.com:aadhilhaq/-HOPE-aptamer-pipeline.git \
    /scratch/user/<NetID>/HOPE-aptamer-pipeline
cd /scratch/user/<NetID>/HOPE-aptamer-pipeline
./install.sh /scratch/user/<NetID>
```

The prefix gives you `<prefix>/envs/hope-aptamer` for the environment and `<prefix>/tools/docking`
for Vina and ADFRsuite, and the script writes the `activate.sh` that HOPE Labs sources. It takes
15 to 40 minutes. `GRACE.md` budgets 80,000 files for the full environment and states that it does
not fit in personal scratch on Grace. If `showquota` agrees, use:

```bash
./install.sh --minimal /scratch/user/<NetID>      # no AmberTools: no 3D builds, no MM-GBSA
```

Folding with Boltz is a separate installer, `./install_boltz.sh`, into an environment of its own.
`GRACE.md` also covers a read only deploy key, for an account with no GitHub access of its own.

## BindCraft2

**This one you cannot install from the repository cloned here.** `BindCraft2` in the lab's space is
the desktop launcher only. Its README says the page, the submit tool and the environment live with the
cluster side install, and that `sflab/README.md` inside that install documents them. HOPE Labs starts
`sflab/bc2-serve` there. That cluster side is not in the launcher repository, so this page has no
command that installs it: read `sflab/README.md` in the lab's install at
`/scratch/group/sflab/BindCraft2`, and the upstream project at
<https://github.com/PacesaLab/BindCraft2>. A campaign is queued on a GPU node, so you need an
allocation that can use one.

## HOPE-pipelines

```bash
module load Anaconda3
git clone https://github.com/aadhilhaq/HOPE-pipelines.git /scratch/user/<NetID>/HOPE-pipelines
cd /scratch/user/<NetID>/HOPE-pipelines
./install.sh /scratch/user/<NetID>
```

`install.sh` builds the environment in `<prefix>/envs/hope`, keeps conda's and pip's caches under
the prefix, clones the four pipelines beside the checkout, then runs `setup.sh` and `my_workspace.sh`
for you. It puts the environment at twenty minutes to an hour and about 67,000 files, and `GRACE.md`
at roughly 3 GB with AmberTools. Adding `--minimal` builds from `environment-minimal.yml` instead,
which leaves out MM-GBSA.

Keep the environment and the checkout under the same root: HOPE Labs starts the monitor by sourcing
`<root>/envs/hope/bin/activate` and running the checkout with `PYTHONPATH` set. To run `python3 -m
hope_monitor` yourself, `GRACE.md` notes that `conda env create` brings the dependencies and not the
package, so install it into the environment once:

```bash
/scratch/user/<NetID>/envs/hope/bin/python -m pip install -e \
    /scratch/user/<NetID>/HOPE-pipelines
```

## HOPE-MD

```bash
P=/scratch/user/<NetID>
git clone git@github.com:aadhilhaq/HOPE-MD.git $P/HOPE-MD/MD && bash $P/HOPE-MD/MD/install.sh $P
```

That gives `<prefix>/HOPE-MD/MD` for the checkout and `<prefix>/HOPE-MD/env` for its environment, with
caches in `<prefix>/HOPE-MD/.cache`. The environment is a venv on a base Python that already has
OpenMM, PDBFixer, pdb2pqr and AmberTools. The script looks in `HOPEMD_BASE_PYTHON` first, then the
lab's group environments, which you cannot read from outside the group, and failing that builds a
conda environment in `<prefix>/HOPE-MD/conda`, which its README calls tens of thousands of files. The
HOPE-pipelines environment above passes the same test, so name it and that build is skipped:

```bash
HOPEMD_BASE_PYTHON=/scratch/user/<NetID>/envs/hope/bin/python3 bash $P/HOPE-MD/MD/install.sh $P
```

The script then checks that HOPE-MD imports and audits which of its `module load` lines work here,
which takes a minute or two. The engines are never installed: they are Grace's own modules. Its
README's Requirements table is plain about what that needs, and none of it is yours to grant: the
`amber` group for every run, the `desmond` group for Desmond runs, and HPRC's Schrödinger users list
for Prime MM-GBSA. Each is a mail to help@hprc.tamu.edu after registering with the authors.

## RFdiffusion and BoltzGen

These two are not on the Tools screen and have no page of their own: they are cards on the canvas,
and a flow is how the lab runs them. Both are installed in the group space, and neither needs
anything from you if you work there.

**RFdiffusion with ProteinMPNN.** `ML_programs/RFdiffusion` holds the code and its nine checkpoints,
and `envs/SE3nv` is its environment, a Python 3.9 with torch. `ML_programs/dl_binder_design` is the
ProteinMPNN half, with its own weights under `mpnn_fr/ProteinMPNN`. Both halves run in `SE3nv`:
ProteinMPNN needs only torch and numpy, and that environment has them.

`envs/proteinmpnn_binder_design` is **not used, and does not work.** It has no Python standard
library at all: 78 conda packages and no `lib/python3.11`, so its interpreter cannot start whatever
its permissions say. Rebuild it only if something outside HOPE Labs wants it; the card does not.

**BoltzGen.** `envs/boltzgen` is BoltzGen 0.3.2 on Python 3.12, and `envs/boltzgen_cache` holds its
weights: five checkpoints and `mols.zip`, about 8 GB. It cannot share the Boltz-2 environment beside
it, because `boltz` pins numpy below 2 and `boltzgen` pins 2.0.2: pip installs the second over the
first without saying so, and leaves Boltz-2 broken. To install it again, elsewhere:

```bash
conda create -p <prefix>/envs/boltzgen python=3.12 && <prefix>/envs/boltzgen/bin/pip install boltzgen
HF_HOME=<prefix>/envs/boltzgen_cache <prefix>/envs/boltzgen/bin/boltzgen download all \
    --cache <prefix>/envs/boltzgen_cache
```

Fetch the weights on a **login** node: a compute node has no internet, and a cache missing one
checkpoint fails when the model loads rather than when the job is submitted.

One thing to know before reading a BoltzGen spec by hand: it numbers the residues a binder should
touch by their **position in the chain**, not by the numbering the structure file carries. On the
lab's own hPD-L1, whose file begins at residue 18, residues 54 and 56 are positions 37 and 39. The
card takes the file's numbering, as every other tool here does, and converts; it then runs
`boltzgen check` and reads the marked residues back before queueing anything, because getting this
wrong does not fail. It designs against a different patch of the surface and returns binders for the
wrong site.

## Pointing HOPE Labs at your installs

HOPE Labs reads a small settings file on your own computer, not on Grace. On macOS and Linux it is
`~/.hope_labs.json`; on Windows it is `%USERPROFILE%\.hope_labs.json`.

Two keys matter. `"root"` is one folder holding all five installs, and each tool is looked for under
it with the layout in the table above. `"installs"` names a tool on its own and wins over `"root"`.
Its keys are the tool keys: `adcp`, `aptamer`, `bindcraft`, `pipelines`, `hopemd`.

```json
{
  "root": "/scratch/user/jane.doe",
  "installs": {
    "hopemd": "/scratch/user/jane.doe/HOPE-MD/MD",
    "bindcraft": "/scratch/group/sflab/BindCraft2"
  }
}
```

With neither key set, HOPE Labs uses the lab's group installs under `/scratch/group/sflab`, which is
what a lab member wants. The file is read when you sign in, so sign out and in again after an edit.
The launcher keeps the sign in boxes in the same file and leaves what you wrote by hand alone. To
try a root without editing the file, set `HOPE_LABS_ROOT` in the environment HOPE Labs is started
from; it wins over the file's `"root"`.

Where a tool writes its runs is a separate question from where it is installed. What each repository
documents:

| Tool | Runs folder, as its own documentation gives it |
|---|---|
| ADCP docking | `$SCRATCH/adcp_runs` |
| HOPE-Aptamer | `$SCRATCH/hope-aptamer-runs` |
| BindCraft2 | the lab's `/scratch/group/sflab/bindcraft_runs/<NetID>`; nothing documented for your own copy |
| HOPE-pipelines | `$SCRATCH/hope/runs`, made by `my_workspace.sh` |
| HOPE-MD | `/scratch/user/<NetID>/hopemd_runs` |

## Running HOPE Labs

Download `HOPE-Labs-windows.zip` or the macOS `.zip` from the releases page, or run it from source:

```bash
pip install paramiko
python -m hope_labs
```

Pick **Grace (TAMU)**, type your NetID, and press **Sign in and open HOPE Labs**. The box wants the
NetID alone, without `@tamu.edu`. Grace then asks for your password and one Duo approval, however
many tools you open. If your settings file named any installs, the log lists each tool key and its
path just after you sign in, so you can see the file was read.

Pressing **Launch** starts the tool on the login node over the connection already held, waits for it
to print its own address and token, forwards a local port to it and opens it in a window of its own.
The [README](../README.md) covers the rest of the page.

## If something goes wrong

The launcher says what it found. Its own sentences, with the tool named; the built in docs
(Docs, at the top right of the page) list every one:

* *there is no HOPE-MD on the cluster: /scratch/user/jane.doe/HOPE-MD/MD* means that path does not
  exist. Check that `"root"` plus the layout really spell your folder.
* *ADCP docking is installed at /scratch/user/jane.doe/ADCP_docking but its activate.sh is missing,
  so its environment cannot be entered. Running its install.sh again writes it.* The same sentence
  names HOPE-Aptamer or HOPE-MD when it is theirs.
* *HOPE-pipelines is installed at /scratch/user/jane.doe/HOPE-pipelines but there is no environment
  at envs/hope beside it.* Keep the environment and the checkout under the same root, as its
  `install.sh` does.
* *HOPE-pipelines was not found in its install at ...*, with the last lines the tool printed. The
  package is not importable there; see the `pip install -e` line above.
* *the cluster ran ADCP docking with a Python too old to parse it; its environment did not load.*
  Its `activate.sh` is not naming the install's own Python.
* *the port HOPE-pipelines was given is taken; try again and it will be given another.*
* *permission denied starting BindCraft2:* usually a path you cannot read, such as a group install you
  are not in.
* *HOPE-MD did not report a URL within 120s. What it said:* a cold login node can be slow, so try
  again; otherwise the quoted lines say why.

By Aadhil Haq, HOPE Lab (PI Dr. Sandun Fernando), Texas A&M University.
