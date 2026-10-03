#!/usr/bin/env python
"""Design binders with RFdiffusion, give them sequences with ProteinMPNN, and record what came out.

Run by RFdiffusion's own Python (SE3nv, 3.9), inside a GPU job, not by the flow's. Written for
3.9: no match statements, no newer typing.

Unlike every other tool a flow starts, these two have no launcher of their own to go through -
no page, no submitting script, nothing that already knows how to queue them. So this is that
missing piece rather than a second way to do something the lab already had, and it is deliberately
the whole of it: the two steps, and the record the next card reads.

    rfdiffusion_design.py <plan.json>

The plan is what the driver worked out; the record left behind is <out>/designs.json, in the shape
hope_flow/adapters.py documents.
"""
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


def say(*what):
    print(*what)
    sys.stdout.flush()


def run(args, where=None, env=None):
    say("$ " + " ".join(args[:8]) + (" ..." if len(args) > 8 else ""))
    done = subprocess.run(args, cwd=where, env=env)
    if done.returncode != 0:
        raise SystemExit("%s exited %d" % (os.path.basename(args[0]), done.returncode))


def chains_of(path):
    """{chain: [residue numbers]} for the amino-acid residues of a PDB, in file order."""
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


def sequence_of(path, chain):
    """The one-letter sequence of one chain, in file order."""
    out = []
    seen = set()
    with open(path, errors="replace") as fh:
        for line in fh:
            if not line.startswith("ATOM") or line[12:16].strip() != "CA":
                continue
            if (line[21].strip() or "A") != chain:
                continue
            key = line[22:27]
            if key in seen:
                continue
            seen.add(key)
            out.append(AMINO.get(line[17:20].strip(), "X"))
    return "".join(out)


def residues(text, default_chain):
    """"54,56,66-70" or "A54,B12-16" -> ["A54", "A56", ...], the way RFdiffusion wants them.

    RFdiffusion names every residue it is to aim at; it has no range form, so a range is spelled
    out. The chain is carried from the token before it when a token does not name one, which is
    how the other tools' hotspot boxes are written.
    """
    out = []
    for token in (t.strip() for t in (text or "").split(",") if t.strip()):
        found = re.match(r"^([A-Za-z]?)(\d+)(?:-(\d+))?$", token)
        if not found:
            continue
        chain = found.group(1) or default_chain
        low = int(found.group(2))
        high = int(found.group(3) or low)
        for n in range(low, high + 1):
            out.append("%s%d" % (chain, n))
    return out


def contig(target_chains, binder_min, binder_max):
    """The contig map: every target chain as it stands, a chain break, then the binder to design.

    "[A1-150/0 70-100]" is RFdiffusion's own example: keep A1-150, break the chain so the binder
    is not fused to the target, then diffuse a binder whose length is sampled in that range.
    """
    parts = []
    for chain in sorted(target_chains):
        numbers = target_chains[chain]
        if numbers:
            parts.append("%s%d-%d" % (chain, numbers[0], numbers[-1]))
    return "[%s/0 %d-%d]" % ("/0 ".join(parts), binder_min, binder_max)


def main():
    plan = json.load(open(sys.argv[1]))
    out = plan["out"]
    rf_dir = os.path.join(out, "rfdiffusion")
    mpnn_dir = os.path.join(out, "proteinmpnn")
    for d in (rf_dir, mpnn_dir):
        if not os.path.isdir(d):
            os.makedirs(d)

    target = plan["target"]
    wanted = [c.strip() for c in (plan.get("chains") or "A").split(",") if c.strip()]
    present = chains_of(target)
    keep = {c: present[c] for c in wanted if c in present}
    if not keep:
        raise SystemExit("none of the chains %s are in %s (it has %s)"
                         % (",".join(wanted), target, ",".join(sorted(present)) or "none"))

    # ---- RFdiffusion: backbones, with the target kept beside them -------------------------
    hotspots = residues(plan.get("hotspots"), sorted(keep)[0])
    args = [plan["se3nv_python"], os.path.join(plan["rfdiffusion"], "scripts", "run_inference.py"),
            "inference.output_prefix=" + os.path.join(rf_dir, "design"),
            "inference.input_pdb=" + target,
            "contigmap.contigs=" + contig(keep, plan["binder_min"], plan["binder_max"]),
            "inference.num_designs=%d" % plan["designs"]]
    if hotspots:
        args.append("ppi.hotspot_res=[%s]" % ",".join(hotspots))
    if plan.get("ckpt"):
        args.append("inference.ckpt_override_path="
                    + os.path.join(plan["rfdiffusion"], "models", plan["ckpt"]))
    if plan.get("diffuser_T"):
        args.append("diffuser.T=%d" % int(plan["diffuser_T"]))
    # The example lowers both noise scales to 0 for binder design, which is what makes the designs
    # worth folding. A person who asks for noise gets it on both, as RFdiffusion's own flags are.
    noise = float(plan.get("noise_scale") or 0)
    args += ["denoiser.noise_scale_ca=%g" % noise, "denoiser.noise_scale_frame=%g" % noise]
    run(args, where=plan["rfdiffusion"])

    backbones = sorted(f for f in os.listdir(rf_dir) if f.endswith(".pdb"))
    if not backbones:
        raise SystemExit("RFdiffusion wrote no designs into %s" % rf_dir)
    say("rfdiffusion: %d backbone(s)" % len(backbones))

    # ---- ProteinMPNN: a sequence for the binder, with the target fixed --------------------
    # RFdiffusion writes the diffused binder as the LAST chain, after the target it kept. That is
    # the chain to design; the target is what the design is conditioned on and must not change.
    mpnn = os.path.join(plan["dl_binder_design"], "mpnn_fr", "ProteinMPNN")
    designs = []
    for name in backbones:
        path = os.path.join(rf_dir, name)
        here = chains_of(path)
        binder = sorted(here)[-1] if here else ""
        target_chains = [c for c in sorted(here) if c != binder]
        if not binder or not target_chains:
            say("  %s: skipped, it has %d chain(s)" % (name, len(here)))
            continue
        folder = os.path.join(mpnn_dir, os.path.splitext(name)[0])
        if not os.path.isdir(folder):
            os.makedirs(folder)
        run([plan["se3nv_python"], os.path.join(mpnn, "protein_mpnn_run.py"),
             "--pdb_path", path,
             "--pdb_path_chains", binder,
             "--out_folder", folder,
             "--num_seq_per_target", str(plan["seqs_per_backbone"]),
             "--sampling_temp", "0.1",
             "--seed", "37",
             "--batch_size", "1"], where=mpnn)
        # ProteinMPNN writes seqs/<name>.fa: the native sequence first, then its designs, each
        # with its score in the header. The best design is the one with the lowest score.
        fasta = os.path.join(folder, "seqs", os.path.splitext(name)[0] + ".fa")
        best, best_score = "", None
        try:
            with open(fasta, errors="replace") as fh:
                header = ""
                for line in fh:
                    line = line.strip()
                    if line.startswith(">"):
                        header = line
                        continue
                    if not line or "score=" not in header:
                        continue
                    try:
                        score = float(re.search(r"score=([\d.]+)", header).group(1))
                    except (AttributeError, ValueError):
                        continue
                    # The first record is the backbone's own sequence, not a design: it is the
                    # one with sample= absent from its header.
                    if "sample=" not in header:
                        continue
                    if best_score is None or score < best_score:
                        best, best_score = line.split("/")[-1], score
        except OSError:
            say("  %s: ProteinMPNN left no sequences" % name)
            continue
        if not best:
            say("  %s: no designed sequence" % name)
            continue
        designs.append({"name": os.path.splitext(name)[0], "path": path,
                        "binder_chains": [binder], "target_chains": target_chains,
                        "sequence": best, "score": best_score})
        say("  %s: %d residues, score %.3f" % (name, len(best), best_score))

    # Best first, so the next card can take the top few without knowing what the number means.
    designs.sort(key=lambda d: d["score"])
    with open(os.path.join(out, "designs.json"), "w") as fh:
        json.dump({"tool": "rfdiffusion", "designs": designs}, fh, indent=1)
        fh.write("\n")
    say("wrote designs.json: %d design(s)" % len(designs))
    if not designs:
        raise SystemExit("no design came through with a sequence")


if __name__ == "__main__":
    main()
