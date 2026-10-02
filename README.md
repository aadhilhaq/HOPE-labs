# HOPE Labs

One front for the HOPE Lab's tools on Grace. Sign in once, pick a tool, and it opens in the same
window: docking, aptamer design, binder design, screening and molecular dynamics, each the page it
already was, reached through one connection and one Duo approval.

| Tool | What it does | Leaves behind |
|---|---|---|
| **ADCP docking** | Docks a peptide into a receptor and ranks the poses | docked poses |
| **HOPE-Aptamer** | Designs aptamers against a target, folds and scores them | aptamer poses |
| **BindCraft2** | Designs protein binders with AlphaFold 2 and ProteinMPNN | designed binders |
| **HOPE-pipelines** | The screening pipelines and their monitor | screening hits |
| **HOPE-MD** | Molecular dynamics of a complex on five engines | trajectories, binding energies |

The tools are not changed in any way. Each already serves its own page on a login node; the
launcher starts the one you pick over the connection it is holding, forwards a port to it and
shows it inside the shell. Nothing is installed on the cluster for this, and nothing about the
tools is installed on your computer.

## Using it

**Windows** — download `HOPE-Labs-windows.zip` from the [releases page](../../releases/latest),
unzip it **whole** (the folder travels together) and run `HOPE-Labs.exe`. It is unsigned, so the
first run shows "Windows protected your PC": More info → Run anyway.

**macOS (Apple silicon)** — download the `.zip`, unzip, then right-click the app → Open the first
time.

Pick **Grace (TAMU)**, type your NetID, press **Sign in and open HOPE Labs**. Grace asks for your
password and then a Duo approval — once, however many tools you then open. The page opens by
itself.

## What the page does

**Tools** is the catalogue: every tool as a card, with what it does, what it takes from another
tool and what it leaves for the next one. **Launch** starts it on the login node; the card then
says *running* and **Open** shows it.

**Every tool is one button from every other.** Along the top of any tool there is a row of the
others, so a pose that came out of docking is a click away from being simulated, and the buttons
that follow the lab's own order of work are marked.

**Results** lists the run folders of all five tools together, newest first, filtered by tool. Each
run carries the step that usually follows it — *Simulate these poses in HOPE-MD* beside a docking
run, *Simulate a design in HOPE-MD* beside a BindCraft2 campaign. Pressing one puts the run's
folder on your clipboard and opens the tool that takes it, ready to be pasted into its import box.

**Sign out** closes the pages and the connection. Anything already queued on the cluster carries
on without it: the launcher submits work, it does not hold it.

## Running it from source

```bash
pip install paramiko
python -m hope_labs
```

Python 3.10 or newer, with tkinter. `python -m hope_labs --selftest` checks the parts that need no
display — including that each tool's start line and each of the three handshakes still parse — and
`--version` prints the build.

## Building the executables

A tag starting with `v` builds both and makes a release page:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

PyInstaller does not cross-compile, so the Windows build runs on a Windows runner and the Mac build
on a Mac. `packaging/build_windows.bat` builds it on a Windows machine without a runner.

## How a tool is added

Everything that differs between tools is in [`hope_labs/tools.py`](hope_labs/tools.py): one entry
per tool, giving where it is installed, the line that starts it, and how it says it is ready. Three
handshakes are in use — the URL line that HOPE-MD, BindCraft2 and the docking console print, the
two lines the aptamer pipeline prints, and the monitor's banner — and a new tool either matches one
of them or brings a parser of its own. Nothing else in the launcher knows one tool from another.

None of them takes a token on its command line, deliberately: a login node is shared and `ps` shows
every argument to everybody on it, so each tool prints its token instead and the launcher reads it
off the channel it is already holding.

## Credits

The tools are the HOPE Lab's, except BindCraft2, which is by the Pacesa lab; the methods they run —
AlphaFold, ProteinMPNN, ADCP, Amber, OpenMM, GROMACS, NAMD, Desmond and the rest — belong to their
authors, and every run records what it used. Please acknowledge Texas A&M High Performance Research
Computing.

By Aadhil Haq, HOPE Lab (PI Dr. Sandun Fernando), Texas A&M University.
