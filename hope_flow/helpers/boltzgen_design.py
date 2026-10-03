#!/usr/bin/env python
"""Generate binders with BoltzGen, and record what came out.

Run by BoltzGen's own Python (3.12), inside a GPU job, not by the flow's.

Two things about BoltzGen's design spec are easy to get wrong, and both are handled here rather
than left to whoever fills the card in:

  - Hotspots are numbered by POSITION IN THE CHAIN, not by the numbering the structure file uses.
    hPD-L1's own file is numbered from 18, so residue 56 in the file is position 39 to BoltzGen.
    Every other tool in the lab takes the file's own numbering, so the card does too and this
    converts. Getting it wrong does not fail: it designs against a different patch of the surface
    for twelve hours.
  - `total_len` is the length of the WHOLE complex, target included, and it is a resample-until-it
    -fits loop. The binder's own length belongs in its sequence as "70..100", which is what this
    writes; total_len is left out.

The conversion is checked before anything expensive starts: `boltzgen check` writes the spec as a
structure with the binding residues marked, and this reads them back and refuses if they are not
the residues that were asked for.

    boltzgen_design.py <plan.json>

Leaves <out>/designs.json, in the shape hope_flow/adapters.py documents.
"""
import csv
import json
import os
import re
import subprocess
import sys

AMINO = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
    "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
    "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
BINDER_CHAIN = "Zz"          # unlikely to collide with a chain in the target file


def say(*what):
    print(*what)
    sys.stdout.flush()


def run(args, where=None):
    say("$ " + " ".join(os.path.basename(a) if i == 0 else a for i, a in enumerate(args))[:400])
    done = subprocess.run(args, cwd=where)
    if done.returncode != 0:
        raise SystemExit("%s exited %d" % (os.path.basename(args[0]), done.returncode))


def chains_of(path):
    """{chain: [author residue numbers]} for the amino acids of a structure, in file order."""
    found = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            if not line.startswith("ATOM") or line[12:16].strip() != "CA":
                continue
            if line[17:20].strip() not in AMINO:
                continue
            chain = line[21].strip() or "A"
            try:
                number = int(line[22:26])
            except ValueError:
                continue
            got = found.setdefault(chain, [])
            if not got or got[-1] != number:
                got.append(number)
    return found


def wanted(text, default_chain):
    """{chain: [author residue numbers]} from "54,56,66-70" or "A54,B12-16"."""
    out = {}
    for token in (t.strip() for t in (text or "").split(",") if t.strip()):
        found = re.match(r"^([A-Za-z]?)(\d+)(?:-(\d+))?$", token)
        if not found:
            continue
        chain = found.group(1) or default_chain
        low = int(found.group(2))
        high = int(found.group(3) or low)
        out.setdefault(chain, []).extend(range(low, high + 1))
    return out


def positions(author_numbers, asked):
    """The asked-for residues as positions in the chain, 1-based, which is what BoltzGen wants."""
    where = {n: i + 1 for i, n in enumerate(author_numbers)}
    found, missing = [], []
    for n in asked:
        if n in where:
            found.append(where[n])
        else:
            missing.append(n)
    return sorted(set(found)), missing


def spec_yaml(plan, keep, binding):
    """The design specification, written by hand: it is five keys and a list."""
    lines = ["# Written by HOPE Labs for a flow. Residue numbers below are positions in the",
             "# chain, converted from the structure's own numbering.",
             "entities:",
             "  - file:",
             "      path: %s" % plan["target"],
             "      include:"]
    for chain in sorted(keep):
        lines.append("        - chain:")
        lines.append("            id: %s" % chain)
    if binding:
        lines.append("      binding_types:")
        for chain in sorted(binding):
            lines.append("        - chain:")
            lines.append("            id: %s" % chain)
            lines.append('            binding: "%s"' % ",".join(str(p) for p in binding[chain]))
    lines.append("  - protein:")
    lines.append("      id: %s" % BINDER_CHAIN)
    lines.append('      sequence: "%d..%d"' % (plan["binder_min"], plan["binder_max"]))
    if plan.get("cyclic"):
        lines.append("      cyclic: true")
    return "\n".join(lines) + "\n"


def marked(cif):
    """The residues `boltzgen check` marked as binding, as positions.

    It writes the spec as a structure whose B-factor is 80 per binding residue, and 100 more for
    a designed one. Reading them back is how the conversion above is checked without a GPU.
    """
    out = []
    try:
        with open(cif, errors="replace") as fh:
            for line in fh:
                if not line.startswith(("ATOM", "HETATM")):
                    continue
                bits = line.split()
                if len(bits) < 15:
                    continue
                try:
                    b = float(bits[14])
                    seq = int(bits[16]) if len(bits) > 16 else int(bits[8])
                except (ValueError, IndexError):
                    continue
                if 79.0 <= b <= 81.0 and seq not in out:
                    out.append(seq)
    except OSError:
        return []
    return sorted(out)


def main():
    plan = json.load(open(sys.argv[1]))
    out = plan["out"]
    boltzgen = plan["boltzgen"]
    cache = plan["cache"]

    present = chains_of(plan["target"])
    keep = [c.strip() for c in (plan.get("chains") or "A").split(",") if c.strip() and c.strip() in present]
    if not keep:
        raise SystemExit("none of the chains %s are in %s (it has %s)"
                         % (plan.get("chains"), plan["target"], ",".join(sorted(present)) or "none"))

    # The hotspots, converted from the file's numbering to BoltzGen's positions.
    asked = wanted(plan.get("hotspots"), keep[0])
    binding, told = {}, []
    for chain, numbers in asked.items():
        if chain not in present:
            told.append("chain %s is not in the target" % chain)
            continue
        got, missing = positions(present[chain], numbers)
        if missing:
            told.append("chain %s has no residue %s"
                        % (chain, ", ".join(str(m) for m in missing[:6])))
        if got:
            binding[chain] = got
    for line in told:
        say("hotspots: " + line)
    if asked and not binding:
        raise SystemExit("none of the hotspots given are in the target")
    for chain, got in sorted(binding.items()):
        first, last = present[chain][0], present[chain][-1]
        say("hotspots: chain %s %s -> positions %s (the chain is numbered %d to %d)"
            % (chain, ",".join(str(n) for n in sorted(set(asked.get(chain, [])))[:8]),
               ",".join(str(p) for p in got[:8]), first, last))

    # No underscore in the name: BoltzGen takes everything before the first one as the target's
    # name, and every design it writes is named after it.
    stem = re.sub(r"[^A-Za-z0-9]", "", os.path.splitext(os.path.basename(plan["target"]))[0]) or "target"
    spec = os.path.join(out, stem + ".yaml")
    with open(spec, "w") as fh:
        fh.write(spec_yaml(plan, keep, binding))
    say("wrote %s" % spec)

    # ---- check before anything expensive, and prove the conversion ------------------------
    checked = os.path.join(out, "checked")
    run([boltzgen, "check", spec, "--output", checked, "--cache", cache])
    if binding:
        want = sorted(p for got in binding.values() for p in got)
        got = marked(os.path.join(checked, stem + ".cif"))
        if got and got != want:
            raise SystemExit("the hotspots did not survive conversion: asked for positions %s, "
                             "the spec marks %s. Nothing has been queued."
                             % (want[:10], got[:10]))
        say("hotspots: %d residue(s) confirmed in the spec" % len(want))

    # ---- the design run ---------------------------------------------------------------------
    args = [boltzgen, "run", spec, "--protocol", plan["protocol"], "--output", out,
            "--num_designs", str(plan["designs"]), "--cache", cache, "--devices", "1"]
    if plan.get("sampling_steps"):
        args += ["--step_scale", str(plan["sampling_steps"])]
    if not plan.get("fold", True):
        args += ["--steps", "design", "inverse_folding"]
    run(args)

    # ---- what came out ----------------------------------------------------------------------
    ranked = os.path.join(out, "final_ranked_designs")
    rows = []
    for name in ("final_designs_metrics_%d.csv" % 30, "all_designs_metrics.csv"):
        path = os.path.join(ranked, name)
        if os.path.isfile(path):
            with open(path, newline="", errors="replace") as fh:
                rows = list(csv.DictReader(fh))
            say("read %s: %d row(s)" % (name, len(rows)))
            break
    if not rows:
        # The metrics are the ranking; without them there is nothing to hand on in order.
        raise SystemExit("BoltzGen left no metrics CSV in %s" % ranked)

    structures = {}
    for folder, _, files in os.walk(ranked):
        for f in files:
            if f.endswith(".cif") and os.sep + "before_refolding" not in folder:
                structures.setdefault(re.sub(r"^rank\d+_", "", f[:-4]), os.path.join(folder, f))

    designs = []
    for row in rows:
        name = (row.get("design_name") or row.get("name") or row.get("design") or "").strip()
        seq = (row.get("designed_chain_sequence") or row.get("designed_sequence") or "").strip()
        if not name or not seq:
            continue
        path = structures.get(name) or structures.get(re.sub(r"\.cif$", "", name))
        if not path:
            continue
        try:
            rank = int(float(row.get("final_rank") or row.get("secondary_rank") or 1e9))
        except ValueError:
            rank = 10 ** 9
        designs.append({"name": name, "path": path,
                        "binder_chains": [BINDER_CHAIN], "target_chains": keep,
                        "sequence": seq.upper(), "score": rank})
    designs.sort(key=lambda d: d["score"])
    with open(os.path.join(out, "designs.json"), "w") as fh:
        json.dump({"tool": "boltzgen", "designs": designs}, fh, indent=1)
        fh.write("\n")
    say("wrote designs.json: %d design(s)" % len(designs))
    if not designs:
        raise SystemExit("no design came through with both a structure and a sequence")


if __name__ == "__main__":
    main()
