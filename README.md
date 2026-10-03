# HOPE Labs

One front for the HOPE Lab's tools on Grace. Sign in once, pick a tool, and it opens in a tab of
its own: docking, aptamer design, binder design, peptide design and molecular dynamics, each the
page it already was, reached through one connection and one Duo approval.

| Tool | What it does | Leaves behind |
|---|---|---|
| **ADCP docking** | Docks a peptide into a receptor and ranks the poses | docked poses |
| **HOPE-Aptamer** | Designs aptamers against a target, folds and scores them | aptamer poses |
| **BindCraft2** | Designs protein binders with AlphaFold 2 and ProteinMPNN | designed binders |
| **HOPE-pipelines** | Designs peptides with the lab's four pipelines, set up from one workspace | designed peptides |
| **HOPE-MD** | Molecular dynamics of a complex on five engines | trajectories, binding energies |

The tools are not changed in any way. Each already serves its own page on a login node; the
launcher starts the one you pick over the connection it is holding, forwards a port to it and
opens it in a tab of its own. Nothing is installed on the cluster for this, and nothing about
the tools is installed on your computer.

It opens the lab's own copies under `/scratch/group/sflab`. To use your own, install the tools in
your scratch on Grace and name that folder once:
[docs/install-on-grace.md](docs/install-on-grace.md).

## Using it

**Windows.** Download `HOPE-Labs-windows.zip` from the [releases page](../../releases/latest),
unzip it **whole** (the folder travels together) and run `HOPE-Labs.exe`. It is unsigned, so the
first run shows "Windows protected your PC": choose More info, then Run anyway.

**macOS (Apple silicon).** Download `HOPE-Labs-mac-apple-silicon.zip`, unzip it, then right-click
the app and choose Open the first time.

Pick **Grace (TAMU)**, type your NetID, press **Sign in and open HOPE Labs**. Grace asks for your
password and then a Duo approval, once, however many tools you then open. The page opens by
itself.

## What the page does

**Tools** is the landing page: every tool a block, with what it does, what it takes from another
tool and what it leaves for the next one, over a search box and the categories. **Launch** starts
it on the login node and opens it in a tab of its own, on the tool's own page, as the tool's own
launcher opens it: HOPE-pipelines on its workspace, the others on their front page. The block then
says *running*, and picking it again goes back to the tab that is already open rather than
starting a second copy.

**Results** lists the run folders of all five tools together, newest first, filtered by tool. Each
run carries the step that usually follows it: *Simulate these poses in HOPE-MD* beside a docking
run, *Simulate a design in HOPE-MD* beside a BindCraft2 campaign. Pressing one opens the tool that
takes it; its tab shows the run's folder with a **Copy path** button, and copies it on the way to
the tool, ready to be pasted into the tool's import box.

**Docs**, in the top right corner, opens the built-in documentation in a tab of its own: every
part of the page, a tool's tab, Results, installing the tools in your own scratch, and what each
message means, with pictures of the page as it is. The bar along the bottom of the page carries the
version, the copyright and who does the work; each tool's own page has its own Docs and its own bar. To change the
pictures, `tools/docs_screenshots.py` takes them again from the running page.

**Flows** is the third view: a canvas where the lab's tools are cards, linked socket to socket,
with the target filled in once and the whole chain launched from one button. What may be linked to
what is `hope_flow/cards.py`, which the canvas and the cluster both read, so they cannot disagree.
`hope_flow` is the runner: one small job per card, each waiting on the one before it through a
Slurm dependency, turning what that card left into what the next one needs. A launched flow needs
nothing of this running — close the laptop and it carries on.

**Sign out** closes the pages and the connection. Anything already queued on the cluster carries
on without it: the launcher submits work, it does not hold it.

## Running it from source

```bash
pip install paramiko
python -m hope_labs
```

Python 3.10 or newer, with tkinter. `python -m hope_labs --selftest` checks the parts that need no
display, including that each tool's start line and each of the three handshakes still parse and that
the docs came along, and `--version` prints the build. `tests/test_docs.py` checks the docs, their
pictures and their routes, and `tests/test_start_lines.py` runs every start line against installs
that are wrong on purpose, to check that the launcher names what is missing.

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
handshakes are in use: the URL line that HOPE-MD, BindCraft2 and the docking console print, the
two lines the aptamer pipeline prints, and the monitor's banner. A new tool either matches one of
them or brings a parser of its own. Nothing else in the launcher knows one tool from another.

None of them takes a token on its command line, deliberately: a login node is shared and `ps` shows
every argument to everybody on it, so each tool prints its token instead and the launcher reads it
off the channel it is already holding.

## Credits

The tools are the HOPE Lab's, except BindCraft2, which is by the Pacesa lab; the methods they run,
AlphaFold, ProteinMPNN, ADCP, Amber, OpenMM, GROMACS, NAMD, Desmond and the rest, belong to their
authors, and every run records what it used. Please acknowledge Texas A&M High Performance Research
Computing.

By Aadhil Haq, HOPE Lab (PI Dr. Sandun Fernando), Texas A&M University.
