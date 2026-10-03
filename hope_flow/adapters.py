"""The junctions: what one card left, read as what the next card needs.

This is the whole of what a flow adds. Every card is its tool, untouched; an adapter is the few
seconds between two of them that a person would otherwise spend copying a path, opening a table
and typing a sequence into another page.

An adapter is given the edge and the flow's record, and returns a small dictionary describing
what is being carried:

    {"kind": one of cards.KINDS, "what": a line for the log, "count": how many things,
     "dropped": [(name, why), ...], ... whatever that kind carries ...}

`count` is read by the runner: nothing carried means the track before this one produced nothing,
which ends that track quietly rather than starting a tool with an empty input. `dropped` is what
was deliberately left behind, with the reason, so a pruned branch can be told from a lost one.
"""
from __future__ import annotations

import csv
import json
import os
import re

from .cards import DOCKABLE_MAX_LENGTH

#: What ADCP will take, from adcp_dock/peptide.py: the standard twenty, and five residues at the
#: short end because below that every replica of the search fails. Repeated here because an
#: adapter runs on a compute node where ADCP's own package may not be importable, and refusing a
#: peptide with the reason beats letting the docking refuse it later, once per task.
STANDARD = set("ACDEFGHIKLMNPQRSTVWY")
DOCKABLE_MIN_LENGTH = 5


class NotWired(RuntimeError):
    """A junction that cannot be made, named so a person knows which and why."""


def carry(flow, record, edge, flow_dir):
    src = flow.node(edge.src)
    dst = flow.node(edge.dst)
    fn = BY_JUNCTION.get((src.card, edge.src_port, dst.card))
    if fn is None:
        raise NotWired("nothing yet carries %s from %s to %s"
                       % (edge.src_port, src.card, dst.card))
    return fn(flow, record, edge, flow_dir)


def _rundir(record, nid):
    where = record.card(nid).get("rundir") or ""
    if not where or not os.path.isdir(where):
        raise NotWired("the run folder of %s is not there: %r" % (nid, where))
    return where


def _rows(path, sep="\t"):
    """A table as a list of dicts, whatever it is delimited by."""
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        if sep is None:
            sep = "\t" if sample.count("\t") >= sample.count(",") else ","
        return [dict(r) for r in csv.DictReader(fh, delimiter=sep)]


def _column(row, *names):
    """The first of these columns that this row has, however it was capitalised."""
    lower = {str(k).strip().lower(): v for k, v in row.items() if k}
    for name in names:
        if name.lower() in lower:
            return (lower[name.lower()] or "").strip()
    return ""


def _dockable(name, seq):
    """Why this peptide cannot be docked, or "" when it can.

    The same four refusals ADCP's own check makes, in the same order, so a peptide this lets
    through is one the docking will take rather than one it will refuse a minute later.
    """
    seq = (seq or "").strip().upper()
    if not seq:
        return "no sequence"
    odd = sorted(set(seq) - STANDARD)
    if odd:
        return "the docking has no rotamer for %s" % ", ".join(odd)
    if len(seq) < DOCKABLE_MIN_LENGTH:
        return "%d residues, shorter than the %d the docking needs" % (len(seq), DOCKABLE_MIN_LENGTH)
    if len(seq) > DOCKABLE_MAX_LENGTH:
        return "%d residues, longer than the %d the docking takes" % (len(seq), DOCKABLE_MAX_LENGTH)
    return ""


def _peptides_file(flow_dir, nid, pairs):
    """Write ADCP's peptides file: one "name: SEQUENCE" a line, which it reads as it stands.

    A colon cannot occur in a sequence, so the named form is the one of the several ADCP accepts
    that cannot be misread. Duplicates are dropped here rather than at the docking, which refuses
    a whole run for them because it keys its folders on the sequence.
    """
    where = os.path.join(flow_dir, "inputs", "%s_peptides.txt" % nid)
    os.makedirs(os.path.dirname(where), exist_ok=True)
    seen, kept, dropped = set(), [], []
    for name, seq in pairs:
        seq = seq.strip().upper()
        if seq in seen:
            dropped.append((name, "the same sequence as %s" % seen_name[seq]))
            continue
        seen.add(seq)
        seen_name[seq] = name
        kept.append((re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "peptide", seq))
    with open(where, "w", encoding="utf-8") as fh:
        for name, seq in kept:
            fh.write("%s: %s\n" % (name, seq))
    return where, kept, dropped


seen_name = {}


# --- from the target -------------------------------------------------------------------------
# Every tool needs the receptor and the site, and they are the same for all of them, so this one
# adapter serves every card the target feeds.

def _target_to_anything(flow, record, edge, flow_dir):
    node = flow.node(edge.src)
    s = node.settings
    got = record.card(node.id).get("path") or os.path.join(flow_dir, "inputs", "target.pdb")
    if not os.path.isfile(got):
        raise NotWired("the target structure is not in the flow's folder: %s" % got)
    return {"kind": "target", "count": 1, "path": got,
            "chains": (s.get("chains") or "").strip(),
            "hotspots": (s.get("hotspots") or "").strip(),
            "binder_min": s.get("binder_min"), "binder_max": s.get("binder_max"),
            "what": "the target %s, hotspots %s" % (os.path.basename(got),
                                                    s.get("hotspots") or "none")}


# --- designed peptides into the docking ------------------------------------------------------

def _pipelines_to_adcp(flow, record, edge, flow_dir):
    """The pipelines' ranked constructs, as a peptides file.

    The sequences are already upper-case one-letter standard residues, so the whole conversion is
    reading a column and giving each a name. What needs care is which table: the ranked set is
    final_constructs.tsv, and anything the pipeline's own length cap put aside is in a second
    table beside it, which a reader of the first alone would silently lose.
    """
    where = _rundir(record, edge.src)
    progress = os.path.join(where, ".hope_progress.json")
    if os.path.isfile(progress):
        try:
            with open(progress, encoding="utf-8") as fh:
                p = json.load(fh)
            if p.get("failed_stages"):
                raise NotWired("the design run failed at %s" % ", ".join(p["failed_stages"]))
        except (ValueError, OSError):
            pass                       # the tables on disk are the evidence; this file is a hint

    tables = [os.path.join(where, "final_constructs.tsv"),
              os.path.join(where, "final_constructs.outside_length.tsv"),
              os.path.join(where, "report", "results.tsv")]
    rows, read = [], []
    for table in tables:
        if os.path.isfile(table):
            rows.extend(_rows(table))
            read.append(os.path.basename(table))
        if rows and table.endswith("results.tsv"):
            break                      # the ranked tables are preferred; this one is the fallback
    if not rows:
        raise NotWired("the design run left no table of constructs in %s" % where)

    pairs, dropped = [], []
    for i, row in enumerate(rows, 1):
        seq = _column(row, "sequence", "construct", "peptide")
        name = _column(row, "name", "id", "construct_id", "rank") or "rank%d" % i
        why = _dockable(name, seq)
        if why:
            dropped.append((name, why))
        else:
            pairs.append(("%s_%s" % (flow.name, name), seq))
    path, kept, same = _peptides_file(flow_dir, edge.dst, pairs)
    dropped.extend(same)
    return {"kind": "sequences", "count": len(kept), "path": path, "dropped": dropped,
            "what": "%d peptide(s) from %s%s" % (len(kept), " and ".join(read),
                                                 _said(dropped))}


def _bindcraft_to_adcp(flow, record, edge, flow_dir):
    """Accepted designs short enough to dock.

    The two tools barely overlap: the design tool's own floor is eight residues and its usual
    range is seventy to a hundred, while the docking takes five to thirty. A campaign asked for
    the usual range can produce nothing this junction will pass, which is why the canvas refuses
    the link before anything is queued; this says the same thing again for a flow that reached
    the cluster as a file.
    """
    where = _rundir(record, edge.src)
    # What the campaign was asked for is a prediction; what it designed is a fact, and the fact is
    # on disk by the time this runs. So the lengths are read from the designs rather than from the
    # request: a campaign asked for long binders that happened to pass a short one is not turned
    # away, and one asked for short binders that drifted long is not waved through.
    asked = _asked_lengths(where)
    if asked and asked[1] > DOCKABLE_MAX_LENGTH:
        say = "this campaign asked for binders of up to %d residues and the docking takes %d" \
              % (asked[1], DOCKABLE_MAX_LENGTH)
    else:
        say = ""
    rows, read = _bindcraft_designs(where)
    pairs, dropped = [], []
    for row in rows:
        name = _column(row, "design", "name") or "design"
        seq = _column(row, "binder_sequence", "sequence")
        why = _dockable(name, seq)
        if why:
            dropped.append((name, why))
        else:
            pairs.append((name, seq))
    path, kept, same = _peptides_file(flow_dir, edge.dst, pairs)
    dropped.extend(same)
    return {"kind": "sequences", "count": len(kept), "path": path, "dropped": dropped,
            "what": "%d design(s) from %s%s%s"
                    % (len(kept), read, _said(dropped), ("; " + say) if say and not kept else "")}


def _said(dropped):
    if not dropped:
        return ""
    return "; %d left behind (%s)" % (len(dropped), "; ".join("%s: %s" % d for d in dropped[:3]))


def _asked_lengths(where):
    """[shortest, longest] the campaign was asked for, known before it has designed anything."""
    for name in ("submission.json", "design.json",
                 os.path.join("results", "campaign_metadata.json"),
                 "campaign_metadata.json"):
        path = os.path.join(where, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                got = json.load(fh)
        except (ValueError, OSError):
            continue
        pair = got.get("binder_lengths") or (got.get("settings") or {}).get("binder_lengths")
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            try:
                return [int(pair[0]), int(pair[1])]
            except (TypeError, ValueError):
                pass
    return None


def _campaign(where):
    """Where the campaign's own output sits inside a run folder.

    A run queued through the lab's wrapper keeps the campaign under results/; a campaign started
    on its own writes those folders at the top. Both are met on this cluster, so both are looked
    for rather than one being declared correct.
    """
    for here in (os.path.join(where, "results"), where):
        if os.path.isdir(os.path.join(here, "3_Ranked")) or \
                os.path.isdir(os.path.join(here, "2_Refolded")):
            return here
    return where


def _bindcraft_designs(where):
    """(the accepted designs' rows, which table they came from).

    The ranked table is the campaign's own answer. Before a campaign has ranked anything, the
    refolded table holds the same columns with an outcome beside each, so the accepted ones can
    be taken from it.
    """
    here = _campaign(where)
    ranked = os.path.join(here, "3_Ranked", "!_Ranked.csv")
    if os.path.isfile(ranked):
        return _rows(ranked, sep=","), "the ranked designs"
    refolded = os.path.join(here, "2_Refolded", "!_Refolded.csv")
    if os.path.isfile(refolded):
        rows = [r for r in _rows(refolded, sep=",")
                if _column(r, "outcome").lower() == "accepted"]
        return rows, "the refolded designs that were accepted"
    raise NotWired("the campaign left no table of designs in %s" % where)


# --- structures into the simulation -----------------------------------------------------------

def _adcp_to_hopemd(flow, record, edge, flow_dir):
    """Docked poses, as the simulation's own ADCP source reads them.

    Nothing is copied or rewritten: the simulation imports an ADCP run folder as it stands. What
    this does is choose which poses, and take each peptide's name from the folder it was docked
    in rather than from the table, because the importer matches that folder name exactly and a
    re-cased name quietly matches the wrong files.
    """
    where = _rundir(record, edge.src)
    docking = os.path.join(where, "docking")
    if not os.path.isdir(docking):
        raise NotWired("the docking run has no docking/ folder: %s" % where)
    picks, poses_each = [], max(1, int(flow.node(edge.dst).settings.get("poses_each") or 1))
    for peptide in sorted(os.listdir(docking)):
        folder = os.path.join(docking, peptide)
        ranked = [f for f in os.listdir(folder) if re.match(r"^out_ranked_\d+\.pdb$", f)] \
            if os.path.isdir(folder) else []
        for n in range(1, min(poses_each, len(ranked)) + 1):
            picks.append({"peptide": peptide, "pose": n})
    return {"kind": "poses", "count": len(picks), "source_kind": "adcp", "path": where,
            "selections": picks, "dropped": [],
            "what": "%d pose(s) of %d peptide(s) in %s"
                    % (len(picks), len(set(p["peptide"] for p in picks)), os.path.basename(where))}


def _aptamer_to_hopemd(flow, record, edge, flow_dir):
    """Folded aptamer poses, through the simulation's own HOPE-Aptamer source."""
    where = _rundir(record, edge.src)
    poses = os.path.join(where, "poses")
    if not os.path.isdir(poses):
        raise NotWired("the aptamer run has no poses/ folder: %s" % where)
    many = len([f for f in os.listdir(poses) if f.lower().endswith((".pdb", ".cif"))])
    take = max(1, int(flow.node(edge.dst).settings.get("poses_each") or 1))
    picks = [{"pose": n} for n in range(1, min(take, many) + 1)]
    return {"kind": "poses", "count": len(picks), "source_kind": "hope_aptamer", "path": where,
            "selections": picks, "dropped": [],
            "what": "%d of %d aptamer pose(s)" % (len(picks), many)}


def _bindcraft_to_hopemd(flow, record, edge, flow_dir):
    """Designed complexes: the binder already placed on the target, simulated as they stand.

    Each design is its own structure file, so each becomes its own run. The one thing that must
    not be left to chance is which chain is which: the simulation splits a complex by size, and a
    binder longer than the target it was designed against would be taken for the receptor. Every
    design file states the answer itself, and this reads it from there.
    """
    where = _rundir(record, edge.src)
    rows, read = _bindcraft_designs(where)
    ranked = os.path.join(_campaign(where), "3_Ranked")
    designs, dropped = [], []
    for row in rows:
        name = _column(row, "design", "name")
        if not name:
            continue
        found = [os.path.join(ranked, f) for f in (os.listdir(ranked) if os.path.isdir(ranked) else [])
                 if f.startswith(name) and f.endswith(".cif") and not f.endswith("_monomer.cif")]
        if not found:
            dropped.append((name, "no structure in 3_Ranked"))
            continue
        chains = _bindcraft_chains(found[0])
        if not chains:
            dropped.append((name, "the structure does not say which chain is the binder"))
            continue
        designs.append({"name": name, "path": found[0],
                        "receptor_chains": chains["target"], "partner_chains": chains["binder"]})
    return {"kind": "complexes", "count": len(designs), "source_kind": "complex",
            "designs": designs, "dropped": dropped,
            "what": "%d complex(es) from %s%s" % (len(designs), read, _said(dropped))}


def _bindcraft_chains(path):
    """{"binder": [...], "target": [...]} as the design file itself states them.

    Every design carries a block naming its own chains. Reading it is the difference between a
    split that is right and one that happens to be right because the target was the larger of the
    two.
    """
    want = {"_bindcraft.binder_chains": "binder", "_bindcraft.target_chains": "target"}
    got = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for key, which in want.items():
                    if line.startswith(key):
                        value = line[len(key):].strip().strip("'\"")
                        if value:
                            got[which] = [c for c in re.split(r"[,\s]+", value) if c]
    except OSError:
        return None
    return got if "binder" in got and "target" in got else None


#: What a design tool with no page of its own leaves for the next card. RFdiffusion and BoltzGen
#: are driven from this repository rather than by a tool that already had a run folder of its own,
#: so their drivers write this file and these two adapters are all that is needed to read it. One
#: settled file rather than a scrape of each tool's output: the driver knows what it ran, and a
#: format agreed here cannot drift the way a parsed log does.
#:
#: <rundir>/designs.json
#:   {"tool": "rfdiffusion",
#:    "designs": [{"name": "design_0", "path": "/abs/design_0.pdb",
#:                 "binder_chains": ["B"], "target_chains": ["A"],
#:                 "sequence": "MKT...", "score": 0.87}, ...]}
#:
#: `score` is whatever that tool ranks by, and the driver writes the list best first, so the
#: simulation takes the best few off the top without having to know which number it was.
DESIGNS_FILE = "designs.json"


def _designs(where):
    """[the designs a driver recorded], best first, and a line saying where they came from."""
    path = os.path.join(where or "", DESIGNS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return [], "no %s in %s" % (DESIGNS_FILE, where or "the run")
    designs = [d for d in (got.get("designs") or []) if isinstance(d, dict)]
    return designs, "%s (%s)" % (DESIGNS_FILE, got.get("tool") or "a design run")


def _designs_to_hopemd(flow, record, edge, flow_dir):
    """Designed complexes, simulated as they stand.

    The binder is already placed on the target in all of these, so there is nothing to dock first.
    Which chain is which is taken from the record the driver wrote rather than guessed from size:
    a binder longer than its target would otherwise be taken for the receptor.
    """
    where = _rundir(record, edge.src)
    designs, read = _designs(where)
    kept, dropped = [], []
    for got in designs:
        name = str(got.get("name") or "").strip() or "design"
        path = str(got.get("path") or "")
        if not path or not os.path.isfile(path):
            dropped.append((name, "no structure on disk"))
            continue
        binder = [c for c in (got.get("binder_chains") or []) if c]
        target = [c for c in (got.get("target_chains") or []) if c]
        if not binder or not target:
            dropped.append((name, "the record does not say which chain is the binder"))
            continue
        kept.append({"name": name, "path": path,
                     "receptor_chains": target, "partner_chains": binder})
    return {"kind": "complexes", "count": len(kept), "source_kind": "complex",
            "designs": kept, "dropped": dropped,
            "what": "%d complex(es) from %s%s" % (len(kept), read, _said(dropped))}


def _designs_to_adcp(flow, record, edge, flow_dir):
    """The designed sequences, for those short enough to dock.

    A tool asked for a hundred-residue binder produces nothing this junction can pass, and the
    canvas says so as a caution while the link is drawn. A caution rather than a refusal because
    what the target card asks for is what the tool aims at, not what it produces: the answer is
    only known here, from the designs themselves.
    """
    where = _rundir(record, edge.src)
    designs, read = _designs(where)
    pairs, dropped = [], []
    for got in designs:
        name = str(got.get("name") or "").strip() or "design"
        seq = str(got.get("sequence") or "").strip().upper()
        why = _dockable(name, seq)
        if why:
            dropped.append((name, why))
        else:
            pairs.append((name, seq))
    path, kept, same = _peptides_file(flow_dir, edge.dst, pairs)
    dropped.extend(same)
    return {"kind": "sequences", "count": len(kept), "path": path, "dropped": dropped,
            "what": "%d design(s) from %s%s" % (len(kept), read, _said(dropped))}


#: (the card it leaves, the socket, the card it arrives at) -> the adapter.
BY_JUNCTION = {
    ("target", "target", "pipelines"): _target_to_anything,
    ("target", "target", "bindcraft"): _target_to_anything,
    ("target", "target", "rfdiffusion"): _target_to_anything,
    ("target", "target", "boltzgen"): _target_to_anything,
    ("target", "target", "aptamer"): _target_to_anything,
    ("target", "target", "adcp"): _target_to_anything,
    ("target", "target", "hopemd"): _target_to_anything,
    ("pipelines", "sequences", "adcp"): _pipelines_to_adcp,
    ("bindcraft", "sequences", "adcp"): _bindcraft_to_adcp,
    ("bindcraft", "complexes", "hopemd"): _bindcraft_to_hopemd,
    # Both design tools this repository drives itself leave the same record, so one pair of
    # adapters reads both.
    ("rfdiffusion", "sequences", "adcp"): _designs_to_adcp,
    ("rfdiffusion", "complexes", "hopemd"): _designs_to_hopemd,
    ("boltzgen", "sequences", "adcp"): _designs_to_adcp,
    ("boltzgen", "complexes", "hopemd"): _designs_to_hopemd,
    ("adcp", "poses", "hopemd"): _adcp_to_hopemd,
    ("aptamer", "poses", "hopemd"): _aptamer_to_hopemd,
}
